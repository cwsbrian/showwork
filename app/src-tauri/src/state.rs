//! App-owned UI state in `<root>/state.json`: chosen view, read report ids and the arrival cursor.

use std::collections::BTreeSet;
use std::fs;
use std::io;
use std::io::Write;
use std::path::Path;

use serde::{Deserialize, Serialize};

#[derive(Serialize, Deserialize, Default, Clone, Copy, Debug, PartialEq)]
#[serde(rename_all = "lowercase")]
pub enum View {
    #[default]
    List,
    Flow,
}

#[derive(Serialize, Deserialize, Default, Clone, Debug, PartialEq)]
#[serde(default)]
pub struct UiState {
    pub view: View,
    pub read: BTreeSet<String>,
    /// Largest report id seen by any earlier run (ids sort chronologically).
    pub last_seen: Option<String>,
}

const FILE: &str = "state.json";

/// Reads `<root>/state.json`; a missing or unreadable file gives the default state.
pub fn load(root: &Path) -> UiState {
    fs::read_to_string(root.join(FILE)).ok().and_then(|text| serde_json::from_str(&text).ok()).unwrap_or_default()
}

impl UiState {
    /// Writes `<root>/state.json` atomically (temp file + rename), creating the root (0700) if missing.
    pub fn save(&self, root: &Path) -> io::Result<()> {
        let mut dirs = fs::DirBuilder::new();
        dirs.recursive(true);
        #[cfg(unix)]
        {
            use std::os::unix::fs::DirBuilderExt;
            dirs.mode(0o700);
        }
        dirs.create(root)?;
        let tmp = root.join(format!(".{FILE}.{}.tmp", std::process::id()));
        let mut options = fs::OpenOptions::new();
        options.write(true).create(true).truncate(true);
        #[cfg(unix)]
        {
            use std::os::unix::fs::OpenOptionsExt;
            options.mode(0o600);
        }
        let result = (|| {
            let mut file = options.open(&tmp)?;
            file.write_all(&serde_json::to_vec_pretty(self).map_err(io::Error::other)?)?;
            file.sync_all()?;
            fs::rename(&tmp, root.join(FILE))
        })();
        if result.is_err() {
            let _ = fs::remove_file(&tmp);
        }
        result
    }

    pub fn mark_read(&mut self, id: &str) {
        self.read.insert(id.to_string());
    }

    /// `(project_id, report_id)` pairs newer than `last_seen`, oldest first; everything when there is no cursor.
    pub fn unseen_since_last_run(&self, ids: &[(String, String)]) -> Vec<(String, String)> {
        let mut unseen: Vec<(String, String)> =
            ids.iter().filter(|(_, id)| self.last_seen.as_ref().is_none_or(|seen| id > seen)).cloned().collect();
        unseen.sort_by(|a, b| a.1.cmp(&b.1));
        unseen
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    fn pair(p: &str, r: &str) -> (String, String) {
        (p.to_string(), r.to_string())
    }

    #[test]
    fn default_when_missing_or_invalid() {
        let tmp = TempDir::new().unwrap();
        assert_eq!(load(&tmp.path().join("missing")), UiState::default());
        assert_eq!(load(tmp.path()), UiState::default());
        fs::write(tmp.path().join("state.json"), "{not json").unwrap();
        assert_eq!(load(tmp.path()), UiState::default());
        fs::write(tmp.path().join("state.json"), r#"{"view":"sideways"}"#).unwrap();
        assert_eq!(load(tmp.path()), UiState::default());
        assert_eq!(UiState::default().view, View::List);
    }

    #[test]
    fn roundtrip_keeps_view_read_and_cursor() {
        let tmp = TempDir::new().unwrap();
        let root = tmp.path().join("not-yet").join("Showwork"); // save creates the root
        let mut state = UiState { view: View::Flow, ..UiState::default() };
        state.mark_read("r-02");
        state.mark_read("r-01");
        state.mark_read("r-02");
        state.last_seen = Some("r-02".into());
        state.save(&root).unwrap();
        assert_eq!(load(&root), state);
        assert_eq!(load(&root).read.len(), 2);
        let text = fs::read_to_string(root.join("state.json")).unwrap();
        assert!(text.contains("\"flow\""), "{text}");
        let leftovers: Vec<_> = fs::read_dir(&root).unwrap().flatten().map(|e| e.file_name()).collect();
        assert_eq!(leftovers, vec![std::ffi::OsString::from("state.json")], "no temp files left behind");
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            assert_eq!(fs::metadata(&root).unwrap().permissions().mode() & 0o777, 0o700);
        }
    }

    #[test]
    fn unseen_returns_only_ids_after_cursor() {
        let ids = vec![pair("p1", "r-01"), pair("p2", "r-03"), pair("p1", "r-02"), pair("p2", "r-04")];
        let fresh = UiState::default();
        assert_eq!(fresh.unseen_since_last_run(&ids).len(), 4, "no cursor yet means everything is unseen");
        let state = UiState { last_seen: Some("r-02".into()), ..UiState::default() };
        assert_eq!(state.unseen_since_last_run(&ids), vec![pair("p2", "r-03"), pair("p2", "r-04")]);
        let state = UiState { last_seen: Some("r-04".into()), ..UiState::default() };
        assert!(state.unseen_since_last_run(&ids).is_empty());
    }
}
