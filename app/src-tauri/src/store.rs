//! Reads (and minimally writes) the Showwork report store that the Python companion creates.
//!
//! Layout (snake_case on disk): `<root>/projects/<project_id>/project.json`,
//! `.../reports/<report_id>/{meta.json,page.json,events.jsonl,assets/}`.

use std::collections::{BTreeMap, BTreeSet};
use std::fmt;
use std::fs;
use std::io;
use std::io::Write;
use std::path::{Path, PathBuf};

use serde::{Deserialize, Serialize};

/// Store root, same rules as the Python `store_root`, but without creating directories.
pub fn store_root() -> PathBuf {
    let home = || std::env::var_os("HOME").map(PathBuf::from).unwrap_or_default();
    if let Some(custom) = std::env::var_os("SHOWWORK_STORE").filter(|v| !v.is_empty()) {
        let custom = PathBuf::from(custom);
        if let Ok(rest) = custom.strip_prefix("~") {
            return home().join(rest);
        }
        return custom;
    }
    if cfg!(target_os = "macos") {
        return home().join("Library").join("Application Support").join("Showwork");
    }
    match std::env::var_os("XDG_DATA_HOME").filter(|v| !v.is_empty()) {
        Some(xdg) => PathBuf::from(xdg).join("showwork"),
        None => home().join(".local").join("share").join("showwork"),
    }
}

/// Creates `<root>` and `<root>/projects` (mode 0700) if missing, so the app works before any publish,
/// and refuses existing ones that are not private to this user.
pub fn ensure_store_dirs(root: &Path) -> io::Result<()> {
    let mut builder = fs::DirBuilder::new();
    builder.recursive(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::DirBuilderExt;
        builder.mode(0o700);
    }
    for dir in [root.to_path_buf(), root.join("projects")] {
        builder.create(&dir)?;
        check_private_dir(&dir)?;
    }
    Ok(())
}

/// Removes `dir` and everything in it with `remove` (`fs::remove_dir_all`, which unlinks symlinks
/// instead of following them). A publish can write `closed.json` into an older report folder while it
/// is being deleted, which fails the removal with "directory not empty" (or "not found" for a file
/// that vanished again), so those are retried a few times; a folder that is already gone counts as removed.
fn remove_tree(dir: &Path, mut remove: impl FnMut(&Path) -> io::Result<()>) -> io::Result<()> {
    const ATTEMPTS: u32 = 5;
    let mut attempt = 0;
    loop {
        attempt += 1;
        let error = match remove(dir) {
            Ok(()) => return Ok(()),
            Err(error) => error,
        };
        if fs::symlink_metadata(dir).is_err_and(|e| e.kind() == io::ErrorKind::NotFound) {
            return Ok(());
        }
        let race = matches!(error.kind(), io::ErrorKind::DirectoryNotEmpty | io::ErrorKind::NotFound);
        if !race || attempt == ATTEMPTS {
            return Err(error);
        }
        std::thread::sleep(std::time::Duration::from_millis(10 * u64::from(attempt)));
    }
}

/// Same rule as the Python `ensure_private_dir`: a real directory, owned by us, no group/other bits.
fn check_private_dir(dir: &Path) -> io::Result<()> {
    let info = fs::symlink_metadata(dir)?;
    let mut safe = info.is_dir();
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        safe = safe && info.uid() == unsafe { libc::getuid() } && info.mode() & 0o077 == 0;
    }
    if safe {
        Ok(())
    } else {
        Err(io::Error::new(io::ErrorKind::PermissionDenied, format!("Unsafe store directory: {}", dir.display())))
    }
}

#[derive(Debug, Clone, PartialEq)]
pub enum StoreError {
    BadId,
    NotFound,
    NotADecision,
    Closed,
    StaleVersion,
    UnknownChoice,
    Io(String),
}

impl fmt::Display for StoreError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            StoreError::BadId => write!(f, "Invalid id"),
            StoreError::NotFound => write!(f, "Not found"),
            StoreError::NotADecision => write!(f, "This report is not a decision"),
            StoreError::Closed => write!(f, "This decision is closed"),
            StoreError::StaleVersion => write!(f, "This report was updated; reload it"),
            StoreError::UnknownChoice => write!(f, "Unknown choice"),
            StoreError::Io(message) => write!(f, "Store error: {message}"),
        }
    }
}

impl std::error::Error for StoreError {}

impl From<io::Error> for StoreError {
    fn from(error: io::Error) -> Self {
        if error.kind() == io::ErrorKind::NotFound {
            StoreError::NotFound
        } else {
            StoreError::Io(error.to_string())
        }
    }
}

#[derive(Serialize, Clone, Debug)]
#[serde(rename_all = "camelCase")]
pub struct ProjectSummary {
    pub id: String,
    pub name: String,
    pub display_name: String,
    pub remote: Option<String>,
    pub last_activity: Option<String>,
    pub unread: usize,
}

#[derive(Serialize, Clone, Debug)]
#[serde(rename_all = "camelCase")]
pub struct ReportMeta {
    pub id: String,
    pub project_id: String,
    pub r#type: String,
    pub mode: String,
    pub title: String,
    pub branch: Option<String>,
    pub commit: Option<String>,
    pub worktree: String,
    pub agent: String,
    pub created_at: String,
    pub version: String,
    pub open: bool,
    pub chosen: bool,
}

#[derive(Serialize, Debug)]
#[serde(rename_all = "camelCase")]
pub struct ReportDetail {
    pub meta: ReportMeta,
    pub page: serde_json::Value,
    pub dir: String,
}

#[derive(Deserialize)]
struct RawMeta {
    id: String,
    project_id: String,
    r#type: String,
    mode: String,
    title: String,
    #[serde(default)]
    branch: Option<String>,
    #[serde(default)]
    commit: Option<String>,
    worktree: String,
    agent: String,
    created_at: String,
    version: String,
}

#[derive(Deserialize)]
struct RawProject {
    id: String,
    name: String,
    #[serde(default)]
    common_dir: Option<String>,
    #[serde(default)]
    remote: Option<String>,
}

fn valid_id(id: &str) -> bool {
    !id.is_empty() && id.bytes().all(|b| b.is_ascii_alphanumeric() || b == b'-')
}

fn check_id(id: &str) -> Result<(), StoreError> {
    if valid_id(id) { Ok(()) } else { Err(StoreError::BadId) }
}

/// `owner/repo` from a git remote URL (https, ssh://, scp-style).
fn owner_repo(remote: &str) -> Option<String> {
    let trimmed = remote.trim().trim_end_matches('/');
    let trimmed = trimmed.strip_suffix(".git").unwrap_or(trimmed);
    let parts: Vec<&str> = trimmed.split(|c| c == '/' || c == ':').filter(|p| !p.is_empty()).collect();
    if parts.len() >= 2 {
        Some(format!("{}/{}", parts[parts.len() - 2], parts[parts.len() - 1]))
    } else {
        None
    }
}

/// Name of the folder that contains the repository, derived from `common_dir`.
fn parent_folder(common_dir: &str) -> Option<String> {
    let path = Path::new(common_dir);
    let repo = if path.file_name().is_some_and(|n| n == ".git") { path.parent()? } else { path };
    repo.parent()?.file_name().map(|n| n.to_string_lossy().into_owned())
}

pub struct Store {
    pub root: PathBuf,
}

impl Store {
    fn projects_dir(&self) -> PathBuf {
        self.root.join("projects")
    }

    fn project_dir(&self, project_id: &str) -> Result<PathBuf, StoreError> {
        check_id(project_id)?;
        Ok(self.projects_dir().join(project_id))
    }

    fn report_dir(&self, project_id: &str, report_id: &str) -> Result<PathBuf, StoreError> {
        check_id(report_id)?;
        Ok(self.project_dir(project_id)?.join("reports").join(report_id))
    }

    /// Valid project folder names (sorted); missing store means none.
    fn project_ids(&self) -> Vec<String> {
        let mut ids = Vec::new();
        if let Ok(entries) = fs::read_dir(self.projects_dir()) {
            for entry in entries.flatten() {
                let name = entry.file_name().to_string_lossy().into_owned();
                if valid_id(&name) && entry.path().is_dir() {
                    ids.push(name);
                }
            }
        }
        ids.sort();
        ids
    }

    /// Reports of a project, oldest first, skipping pending, stray and broken folders.
    fn raw_reports(&self, project_id: &str) -> Vec<RawMeta> {
        let mut metas = Vec::new();
        let Ok(entries) = fs::read_dir(self.projects_dir().join(project_id).join("reports")) else {
            return metas;
        };
        for entry in entries.flatten() {
            let name = entry.file_name().to_string_lossy().into_owned();
            if name.starts_with('.') || !valid_id(&name) || !entry.path().is_dir() {
                continue;
            }
            let Ok(text) = fs::read_to_string(entry.path().join("meta.json")) else { continue };
            if let Ok(meta) = serde_json::from_str::<RawMeta>(&text) {
                if meta.id == name {
                    metas.push(meta);
                }
            }
        }
        metas.sort_by(|a, b| a.id.cmp(&b.id));
        metas
    }

    fn has_choice(&self, project_id: &str, meta: &RawMeta) -> bool {
        let path = self.projects_dir().join(project_id).join("reports").join(&meta.id).join("events.jsonl");
        let Ok(text) = fs::read_to_string(path) else { return false };
        text.lines()
            .filter_map(|line| serde_json::from_str::<serde_json::Value>(line).ok())
            .any(|event| event.get("version").and_then(|v| v.as_str()) == Some(meta.version.as_str()))
    }

    /// `closed.json` in the report folder: Python writes it when a newer same-worktree report is
    /// published, so a decision stays closed even after that newer report is deleted.
    fn closed_marker(&self, project_id: &str, meta: &RawMeta) -> bool {
        self.projects_dir().join(project_id).join("reports").join(&meta.id).join("closed.json").exists()
    }

    /// Newest first, with `open` and `chosen` filled in.
    fn reports_with_state(&self, project_id: &str) -> Vec<ReportMeta> {
        let raws = self.raw_reports(project_id);
        let mut latest: BTreeMap<String, String> = BTreeMap::new();
        for raw in &raws {
            latest.insert(raw.worktree.clone(), raw.id.clone()); // oldest first, so the last wins
        }
        let mut reports: Vec<ReportMeta> = raws
            .iter()
            .map(|raw| ReportMeta {
                open: raw.mode == "decision" && latest.get(&raw.worktree) == Some(&raw.id) && !self.closed_marker(project_id, raw),
                chosen: self.has_choice(project_id, raw),
                id: raw.id.clone(),
                project_id: raw.project_id.clone(),
                r#type: raw.r#type.clone(),
                mode: raw.mode.clone(),
                title: raw.title.clone(),
                branch: raw.branch.clone(),
                commit: raw.commit.clone(),
                worktree: raw.worktree.clone(),
                agent: raw.agent.clone(),
                created_at: raw.created_at.clone(),
                version: raw.version.clone(),
            })
            .collect();
        reports.reverse();
        reports
    }

    pub fn list_projects(&self, read: &BTreeSet<String>) -> Result<Vec<ProjectSummary>, StoreError> {
        let mut projects: Vec<(RawProject, Vec<RawMeta>)> = Vec::new();
        for id in self.project_ids() {
            let Ok(text) = fs::read_to_string(self.projects_dir().join(&id).join("project.json")) else { continue };
            let Ok(project) = serde_json::from_str::<RawProject>(&text) else { continue };
            if project.id != id {
                continue;
            }
            let reports = self.raw_reports(&id);
            projects.push((project, reports));
        }
        let mut name_counts: BTreeMap<&str, usize> = BTreeMap::new();
        for (project, _) in &projects {
            *name_counts.entry(project.name.as_str()).or_default() += 1;
        }
        let mut summaries: Vec<(String, ProjectSummary)> = projects
            .iter()
            .map(|(project, reports)| {
                let shared = name_counts.get(project.name.as_str()).copied().unwrap_or(0) > 1;
                let qualifier = if !shared {
                    None
                } else if let Some(remote) = project.remote.as_deref().filter(|r| !r.is_empty()) {
                    owner_repo(remote)
                } else {
                    project.common_dir.as_deref().and_then(parent_folder)
                };
                let newest = reports.last();
                (
                    newest.map(|r| r.id.clone()).unwrap_or_default(),
                    ProjectSummary {
                        id: project.id.clone(),
                        name: project.name.clone(),
                        display_name: match qualifier {
                            Some(q) => format!("{} ({})", project.name, q),
                            None => project.name.clone(),
                        },
                        remote: project.remote.clone().filter(|r| !r.is_empty()),
                        last_activity: newest.map(|r| r.created_at.clone()),
                        unread: reports.iter().filter(|r| !read.contains(&r.id)).count(),
                    },
                )
            })
            .collect();
        summaries.sort_by(|a, b| b.0.cmp(&a.0).then_with(|| a.1.id.cmp(&b.1.id)));
        Ok(summaries.into_iter().map(|(_, s)| s).collect())
    }

    pub fn list_reports(&self, project_id: &str) -> Result<Vec<ReportMeta>, StoreError> {
        check_id(project_id)?;
        Ok(self.reports_with_state(project_id))
    }

    fn find_meta(&self, project_id: &str, report_id: &str) -> Result<ReportMeta, StoreError> {
        check_id(project_id)?;
        check_id(report_id)?;
        self.reports_with_state(project_id).into_iter().find(|m| m.id == report_id).ok_or(StoreError::NotFound)
    }

    pub fn get_report(&self, project_id: &str, report_id: &str) -> Result<ReportDetail, StoreError> {
        let dir = self.report_dir(project_id, report_id)?;
        let meta = self.find_meta(project_id, report_id)?;
        let text = fs::read_to_string(dir.join("page.json")).map_err(|e| StoreError::Io(e.to_string()))?;
        let page = serde_json::from_str(&text).map_err(|e| StoreError::Io(e.to_string()))?;
        Ok(ReportDetail { meta, page, dir: dir.to_string_lossy().into_owned() })
    }

    pub fn submit_choice(&self, project_id: &str, report_id: &str, version: &str, choice: &str) -> Result<(), StoreError> {
        let dir = self.report_dir(project_id, report_id)?;
        let meta = self.find_meta(project_id, report_id)?;
        if meta.mode != "decision" {
            return Err(StoreError::NotADecision);
        }
        if !meta.open {
            return Err(StoreError::Closed);
        }
        if meta.version != version {
            return Err(StoreError::StaleVersion);
        }
        let text = fs::read_to_string(dir.join("page.json")).map_err(|e| StoreError::Io(e.to_string()))?;
        let page: serde_json::Value = serde_json::from_str(&text).map_err(|e| StoreError::Io(e.to_string()))?;
        let known = page
            .get("options")
            .and_then(|o| o.as_array())
            .is_some_and(|options| options.iter().any(|o| o.get("id").and_then(|v| v.as_str()) == Some(choice)));
        if !known {
            return Err(StoreError::UnknownChoice);
        }
        let event = serde_json::json!({
            "version": meta.version,
            "title": meta.title,
            "choice": choice,
            "time": chrono::Utc::now().to_rfc3339_opts(chrono::SecondsFormat::Micros, false),
        });
        let mut file = fs::OpenOptions::new().create(true).append(true).open(dir.join("events.jsonl"))?;
        file.write_all(format!("{event}\n").as_bytes())?;
        Ok(())
    }

    pub fn delete_report(&self, project_id: &str, report_id: &str) -> Result<(), StoreError> {
        let dir = self.report_dir(project_id, report_id)?;
        if !dir.is_dir() {
            return Err(StoreError::NotFound);
        }
        Ok(remove_tree(&dir, |d| fs::remove_dir_all(d))?)
    }

    pub fn delete_project(&self, project_id: &str) -> Result<(), StoreError> {
        let dir = self.project_dir(project_id)?;
        if !dir.is_dir() {
            return Err(StoreError::NotFound);
        }
        Ok(remove_tree(&dir, |d| fs::remove_dir_all(d))?)
    }

    /// Folder to show in Finder: the newest report's worktree that still exists, else the
    /// repository folder from `project.json` (`common_dir`, minus a trailing `.git`).
    pub fn reveal_path(&self, project_id: &str) -> Result<PathBuf, StoreError> {
        let reports = self.list_reports(project_id)?;
        if let Some(found) = reports.iter().map(|r| PathBuf::from(&r.worktree)).find(|p| p.is_absolute() && p.exists()) {
            return Ok(found);
        }
        let text = fs::read_to_string(self.project_dir(project_id)?.join("project.json"))?;
        let project: RawProject = serde_json::from_str(&text).map_err(|e| StoreError::Io(e.to_string()))?;
        let common = PathBuf::from(project.common_dir.unwrap_or_default());
        let repo = if common.file_name().is_some_and(|n| n == ".git") { common.parent().map(Path::to_path_buf) } else { Some(common) };
        repo.filter(|p| p.is_absolute() && p.exists()).ok_or(StoreError::NotFound)
    }

    /// `(project_id, report_id)` for every valid report, for the watcher and startup.
    pub fn all_report_ids(&self) -> Vec<(String, String)> {
        let mut ids = Vec::new();
        for project in self.project_ids() {
            for meta in self.raw_reports(&project) {
                ids.push((project.clone(), meta.id));
            }
        }
        ids
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    use tempfile::TempDir;

    fn store() -> (TempDir, Store) {
        let dir = TempDir::new().unwrap();
        let store = Store { root: dir.path().to_path_buf() };
        (dir, store)
    }

    fn add_project(s: &Store, id: &str, name: &str, common_dir: &str, remote: Option<&str>) {
        let dir = s.root.join("projects").join(id);
        fs::create_dir_all(dir.join("reports")).unwrap();
        let project = json!({"id": id, "name": name, "common_dir": common_dir, "remote": remote});
        fs::write(dir.join("project.json"), project.to_string()).unwrap();
    }

    fn add_report(s: &Store, project: &str, id: &str, mode: &str, worktree: &str, version: &str) {
        let dir = s.root.join("projects").join(project).join("reports").join(id);
        fs::create_dir_all(&dir).unwrap();
        let meta = json!({"id": id, "project_id": project, "type": "plan", "mode": mode, "title": format!("T {id}"),
            "branch": "main", "commit": null, "worktree": worktree, "agent": "claude",
            "created_at": format!("created-{id}"), "version": version});
        fs::write(dir.join("meta.json"), meta.to_string()).unwrap();
        let mut page = json!({"mode": mode, "title": "T", "version": version, "published_at": "x"});
        if mode == "decision" {
            page["options"] = json!([{"id": "a"}, {"id": "b"}]);
        }
        fs::write(dir.join("page.json"), page.to_string()).unwrap();
    }

    #[test]
    fn ensure_store_dirs_creates_private_dirs() {
        let tmp = TempDir::new().unwrap();
        let root = tmp.path().join("nested").join("Showwork");
        ensure_store_dirs(&root).unwrap();
        ensure_store_dirs(&root).unwrap(); // idempotent
        assert!(root.join("projects").is_dir());
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            assert_eq!(fs::metadata(&root).unwrap().permissions().mode() & 0o777, 0o700);
            assert_eq!(fs::metadata(root.join("projects")).unwrap().permissions().mode() & 0o777, 0o700);
        }
        let store = Store { root };
        assert!(store.list_projects(&BTreeSet::new()).unwrap().is_empty());
    }

    #[cfg(unix)]
    #[test]
    fn ensure_store_dirs_rejects_shared_existing_dirs() {
        use std::os::unix::fs::PermissionsExt;
        let tmp = TempDir::new().unwrap();
        let root = tmp.path().join("Showwork");
        fs::create_dir_all(root.join("projects")).unwrap();
        fs::set_permissions(&root, fs::Permissions::from_mode(0o755)).unwrap();
        let err = ensure_store_dirs(&root).unwrap_err();
        assert_eq!(err.kind(), io::ErrorKind::PermissionDenied);
        fs::set_permissions(&root, fs::Permissions::from_mode(0o700)).unwrap();
        fs::set_permissions(root.join("projects"), fs::Permissions::from_mode(0o750)).unwrap();
        assert_eq!(ensure_store_dirs(&root).unwrap_err().kind(), io::ErrorKind::PermissionDenied);
    }

    #[test]
    fn missing_store_lists_nothing() {
        let tmp = TempDir::new().unwrap();
        let store = Store { root: tmp.path().join("nope") };
        assert!(store.list_projects(&BTreeSet::new()).unwrap().is_empty());
        assert!(store.list_reports("abc").unwrap().is_empty());
        assert!(store.all_report_ids().is_empty());
    }

    #[test]
    fn lists_projects_newest_first_with_unread_counts() {
        let (_t, s) = store();
        add_project(&s, "p1", "alpha", "/x/alpha/.git", None);
        add_project(&s, "p2", "beta", "/x/beta/.git", None);
        add_project(&s, "p3", "empty", "/x/empty/.git", None);
        add_report(&s, "p1", "20260101-000001-000000-aaaa", "handoff", "/w1", "v1");
        add_report(&s, "p1", "20260101-000003-000000-aaaa", "handoff", "/w1", "v2");
        add_report(&s, "p2", "20260101-000002-000000-aaaa", "handoff", "/w2", "v3");
        let read: BTreeSet<String> = ["20260101-000001-000000-aaaa".to_string()].into();
        let projects = s.list_projects(&read).unwrap();
        let names: Vec<_> = projects.iter().map(|p| (p.id.as_str(), p.unread)).collect();
        assert_eq!(names, vec![("p1", 1), ("p2", 1), ("p3", 0)]);
        assert_eq!(projects[0].last_activity.as_deref(), Some("created-20260101-000003-000000-aaaa"));
        assert!(projects[2].last_activity.is_none());
    }

    #[test]
    fn display_name_disambiguates_same_named_repos() {
        let (_t, s) = store();
        add_project(&s, "p1", "app", "/a/app/.git", Some("git@github.com:acme/app.git"));
        add_project(&s, "p2", "app", "/b/app/.git", Some("https://github.com/other/app"));
        add_project(&s, "p3", "app", "/work/app/.git", None);
        add_project(&s, "p4", "solo", "/a/solo/.git", Some("git@github.com:acme/solo.git"));
        let projects = s.list_projects(&BTreeSet::new()).unwrap();
        let by_id = |id: &str| projects.iter().find(|p| p.id == id).unwrap().display_name.clone();
        assert_eq!(by_id("p1"), "app (acme/app)");
        assert_eq!(by_id("p2"), "app (other/app)");
        assert_eq!(by_id("p3"), "app (work)");
        assert_eq!(by_id("p4"), "solo");
    }

    #[test]
    fn lists_reports_newest_first_and_flags_open_decision() {
        let (_t, s) = store();
        add_project(&s, "p1", "alpha", "/x/alpha/.git", None);
        add_report(&s, "p1", "r-01", "decision", "/w1", "v1");
        add_report(&s, "p1", "r-02", "decision", "/w2", "v2");
        add_report(&s, "p1", "r-03", "handoff", "/w1", "v3");
        add_report(&s, "p1", "r-04", "decision", "/w1", "v4");
        fs::write(
            s.root.join("projects/p1/reports/r-04/events.jsonl"),
            "{\"version\":\"old\",\"choice\":\"a\"}\n{\"version\":\"v4\",\"choice\":\"a\"}\n",
        )
        .unwrap();
        let reports = s.list_reports("p1").unwrap();
        let view: Vec<_> = reports.iter().map(|r| (r.id.as_str(), r.open, r.chosen)).collect();
        assert_eq!(view, vec![("r-04", true, true), ("r-03", false, false), ("r-02", true, false), ("r-01", false, false)]);
    }

    #[test]
    fn skips_pending_and_broken_reports() {
        let (_t, s) = store();
        add_project(&s, "p1", "alpha", "/x/alpha/.git", None);
        add_report(&s, "p1", "r-01", "handoff", "/w", "v1");
        add_report(&s, "p1", ".pending-x", "handoff", "/w", "v0");
        let reports = s.root.join("projects/p1/reports");
        fs::create_dir_all(reports.join("r-bad")).unwrap();
        fs::write(reports.join("r-bad/meta.json"), "{nope").unwrap();
        fs::write(reports.join("stray.txt"), "x").unwrap();
        add_report(&s, "p1", "r-02", "handoff", "/w", "v2");
        fs::write(reports.join("r-02/page.json"), "{broken").unwrap();
        let ids: Vec<_> = s.list_reports("p1").unwrap().into_iter().map(|r| r.id).collect();
        assert_eq!(ids, vec!["r-02", "r-01"]);
        assert!(matches!(s.get_report("p1", "r-02"), Err(StoreError::Io(_))));
        assert!(s.get_report("p1", "r-01").is_ok());
        assert_eq!(s.get_report("p1", "r-bad").unwrap_err(), StoreError::NotFound);
        assert_eq!(s.all_report_ids().len(), 2);
    }

    #[test]
    fn rejects_path_like_ids() {
        let (_t, s) = store();
        for bad in ["../x", "a/b", ""] {
            assert_eq!(s.list_reports(bad).unwrap_err(), StoreError::BadId);
            assert_eq!(s.get_report(bad, "r").unwrap_err(), StoreError::BadId);
            assert_eq!(s.get_report("p", bad).unwrap_err(), StoreError::BadId);
            assert_eq!(s.submit_choice(bad, "r", "v", "a").unwrap_err(), StoreError::BadId);
            assert_eq!(s.submit_choice("p", bad, "v", "a").unwrap_err(), StoreError::BadId);
            assert_eq!(s.delete_report(bad, "r").unwrap_err(), StoreError::BadId);
            assert_eq!(s.delete_report("p", bad).unwrap_err(), StoreError::BadId);
            assert_eq!(s.delete_project(bad).unwrap_err(), StoreError::BadId);
        }
    }

    fn decision_store() -> (TempDir, Store) {
        let (t, s) = store();
        add_project(&s, "p1", "alpha", "/x/alpha/.git", None);
        add_report(&s, "p1", "r-01", "decision", "/w", "v1");
        (t, s)
    }

    #[test]
    fn submit_rejects_closed_decision() {
        let (_t, s) = decision_store();
        add_report(&s, "p1", "r-02", "handoff", "/w", "v2");
        assert_eq!(s.submit_choice("p1", "r-01", "v1", "a").unwrap_err(), StoreError::Closed);
        assert_eq!(s.submit_choice("p1", "r-02", "v2", "a").unwrap_err(), StoreError::NotADecision);
        assert_eq!(s.submit_choice("p1", "r-09", "v2", "a").unwrap_err(), StoreError::NotFound);
    }

    #[test]
    fn closed_marker_keeps_decision_closed_after_newer_report_is_deleted() {
        let (_t, s) = decision_store();
        add_report(&s, "p1", "r-02", "handoff", "/w", "v2");
        let marker = json!({"by": "r-02", "time": "2026-01-01T00:00:00+00:00"});
        fs::write(s.root.join("projects/p1/reports/r-01/closed.json"), marker.to_string()).unwrap();
        s.delete_report("p1", "r-02").unwrap();
        assert!(!s.list_reports("p1").unwrap()[0].open, "marker wins even when r-01 is the newest again");
        assert!(!s.get_report("p1", "r-01").unwrap().meta.open);
        assert_eq!(s.submit_choice("p1", "r-01", "v1", "a").unwrap_err(), StoreError::Closed);
        assert!(!s.root.join("projects/p1/reports/r-01/events.jsonl").exists());
    }

    #[test]
    fn submit_rejects_stale_version() {
        let (_t, s) = decision_store();
        assert_eq!(s.submit_choice("p1", "r-01", "old", "a").unwrap_err(), StoreError::StaleVersion);
    }

    #[test]
    fn submit_rejects_unknown_choice() {
        let (_t, s) = decision_store();
        assert_eq!(s.submit_choice("p1", "r-01", "v1", "zzz").unwrap_err(), StoreError::UnknownChoice);
    }

    #[test]
    fn submit_appends_event_line() {
        let (_t, s) = decision_store();
        s.submit_choice("p1", "r-01", "v1", "b").unwrap();
        let text = fs::read_to_string(s.root.join("projects/p1/reports/r-01/events.jsonl")).unwrap();
        let event: serde_json::Value = serde_json::from_str(text.trim()).unwrap();
        assert_eq!(event["version"], "v1");
        assert_eq!(event["title"], "T r-01");
        assert_eq!(event["choice"], "b");
        let time = event["time"].as_str().unwrap();
        assert!(chrono::DateTime::parse_from_rfc3339(time).is_ok(), "{time}");
        assert!(s.list_reports("p1").unwrap()[0].chosen);
    }

    #[test]
    fn reveal_path_falls_back_to_existing_worktree_then_repo() {
        let (t, s) = store();
        let repo = t.path().join("repo");
        let old_tree = t.path().join("tree-old");
        fs::create_dir_all(repo.join(".git")).unwrap();
        fs::create_dir_all(&old_tree).unwrap();
        let gone = t.path().join("tree-gone");
        add_project(&s, "p1", "repo", repo.join(".git").to_str().unwrap(), None);
        assert_eq!(s.reveal_path("p1").unwrap(), repo, "no reports: the repository folder");
        add_report(&s, "p1", "r-01", "handoff", old_tree.to_str().unwrap(), "v1");
        add_report(&s, "p1", "r-02", "handoff", gone.to_str().unwrap(), "v2");
        assert_eq!(s.reveal_path("p1").unwrap(), old_tree, "newest worktree is gone: the newest existing one");
        fs::remove_dir(&old_tree).unwrap();
        assert_eq!(s.reveal_path("p1").unwrap(), repo, "no worktree left: the repository folder");
        fs::remove_dir_all(&repo).unwrap();
        assert_eq!(s.reveal_path("p1").unwrap_err(), StoreError::NotFound);
        assert_eq!(s.reveal_path("../x").unwrap_err(), StoreError::BadId);
    }

    #[test]
    fn remove_tree_retries_when_a_file_appears_mid_delete() {
        let t = TempDir::new().unwrap();
        let dir = t.path().join("r-01");
        fs::create_dir_all(dir.join("assets")).unwrap();
        fs::write(dir.join("meta.json"), "{}").unwrap();
        let mut calls = 0;
        remove_tree(&dir, |d| {
            calls += 1;
            if calls == 1 {
                // A real "directory not empty": everything removed, then a publish writes its marker.
                fs::remove_dir_all(d.join("assets"))?;
                fs::remove_file(d.join("meta.json"))?;
                fs::write(d.join("closed.json"), "{}")?;
                fs::remove_dir(d)
            } else {
                fs::remove_dir_all(d)
            }
        })
        .unwrap();
        assert_eq!(calls, 2);
        assert!(!dir.exists());
    }

    #[test]
    fn remove_tree_treats_already_gone_as_success_and_gives_up_eventually() {
        let t = TempDir::new().unwrap();
        let dir = t.path().join("r-01");
        fs::create_dir_all(&dir).unwrap();
        // Another deleter finished first: the folder is gone and the error is "not found".
        remove_tree(&dir, |d| {
            fs::remove_dir_all(d)?;
            fs::remove_dir(d)
        })
        .unwrap();

        fs::create_dir_all(&dir).unwrap();
        let mut calls = 0;
        let not_empty = remove_tree(&dir, |_| {
            calls += 1;
            Err(io::Error::from(io::ErrorKind::DirectoryNotEmpty))
        });
        assert_eq!(not_empty.unwrap_err().kind(), io::ErrorKind::DirectoryNotEmpty);
        assert_eq!(calls, 5, "a writer that never stops is not retried forever");

        let mut calls = 0;
        let denied = remove_tree(&dir, |_| {
            calls += 1;
            Err(io::Error::from(io::ErrorKind::PermissionDenied))
        });
        assert_eq!(denied.unwrap_err().kind(), io::ErrorKind::PermissionDenied);
        assert_eq!(calls, 1, "other errors are not retried");
    }

    #[cfg(unix)]
    #[test]
    fn delete_report_unlinks_a_symlinked_folder_without_following_it() {
        let (t, s) = decision_store();
        let outside = t.path().join("outside");
        fs::create_dir_all(&outside).unwrap();
        fs::write(outside.join("keep.txt"), "keep").unwrap();
        let link = s.report_dir("p1", "r-09").unwrap();
        std::os::unix::fs::symlink(&outside, &link).unwrap();
        s.delete_report("p1", "r-09").unwrap();
        assert!(fs::symlink_metadata(&link).is_err(), "the link itself is removed");
        assert!(outside.join("keep.txt").exists(), "the link target is untouched");
    }

    #[test]
    fn delete_report_removes_folder() {
        let (_t, s) = decision_store();
        s.delete_report("p1", "r-01").unwrap();
        assert!(s.list_reports("p1").unwrap().is_empty());
        assert_eq!(s.delete_report("p1", "r-01").unwrap_err(), StoreError::NotFound);
        s.delete_project("p1").unwrap();
        assert!(s.list_projects(&BTreeSet::new()).unwrap().is_empty());
    }
}
