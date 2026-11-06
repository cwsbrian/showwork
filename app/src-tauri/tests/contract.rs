//! Python writes, Rust reads: runs the real companion against a temp store.

use std::collections::BTreeSet;
use std::path::PathBuf;
use std::process::Command;

use app_lib::store::Store;

fn companion() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../skills/showwork/scripts/companion.py")
}

fn python(store: &std::path::Path, args: &[&str]) -> String {
    let out = Command::new("python3")
        .arg(companion())
        .args(args)
        .env("SHOWWORK_STORE", store)
        .env("SHOWWORK_NO_APP", "1")
        .output()
        .expect("python3 runs");
    assert!(out.status.success(), "{}", String::from_utf8_lossy(&out.stderr));
    String::from_utf8(out.stdout).unwrap()
}

fn git_repo(tmp: &std::path::Path) -> PathBuf {
    let repo = tmp.join("repo");
    std::fs::create_dir(&repo).unwrap();
    for args in [vec!["init", "-q"], vec!["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "i"]] {
        assert!(Command::new("git").arg("-C").arg(&repo).args(&args).status().unwrap().success());
    }
    repo
}

#[test]
fn rust_reads_what_python_publishes_and_python_sees_the_choice() {
    let tmp = tempfile::TempDir::new().unwrap();
    let repo = git_repo(tmp.path());
    let page = serde_json::json!({
        "mode": "decision", "title": "Pick one", "summary": "Which?", "question": "Which one?",
        "options": [
            {"id": "a", "title": "A", "body": "first", "html": "<p>A</p>"},
            {"id": "b", "title": "B", "body": "second", "html": "<p>B</p>"}
        ]
    });
    let file = tmp.path().join("page.json");
    std::fs::write(&file, page.to_string()).unwrap();
    let store_dir = tmp.path().join("store");

    python(&store_dir, &["publish", "--project", repo.to_str().unwrap(), "--file", file.to_str().unwrap(), "--type", "plan", "--agent", "claude"]);

    let store = Store { root: store_dir.clone() };
    let projects = store.list_projects(&BTreeSet::new()).unwrap();
    assert_eq!(projects.len(), 1);
    assert_eq!(projects[0].name, "repo");
    assert_eq!(projects[0].unread, 1);
    let reports = store.list_reports(&projects[0].id).unwrap();
    assert_eq!(reports.len(), 1);
    let r = &reports[0];
    assert_eq!((r.r#type.as_str(), r.mode.as_str(), r.agent.as_str(), r.open), ("plan", "decision", "claude", true));

    let detail = store.get_report(&projects[0].id, &r.id).unwrap();
    assert_eq!(detail.page["options"][1]["id"], "b");
    store.submit_choice(&projects[0].id, &r.id, &r.version, "b").unwrap();

    let events = python(&store_dir, &["events", "--project", repo.to_str().unwrap()]);
    let events: serde_json::Value = serde_json::from_str(&events).unwrap();
    assert_eq!(events["events"][0]["choice"], "b");
    assert_eq!(events["report"], r.id.as_str());
}

#[test]
fn decision_closed_by_a_newer_report_stays_closed_after_rust_deletes_it() {
    let tmp = tempfile::TempDir::new().unwrap();
    let repo = git_repo(tmp.path());
    let store_dir = tmp.path().join("store");
    let decision = serde_json::json!({"mode": "decision", "title": "Pick", "summary": "s", "question": "Which?",
        "options": [{"id": "a", "title": "A", "body": "a", "html": "<p>A</p>"}, {"id": "b", "title": "B", "body": "b", "html": "<p>B</p>"}]});
    let handoff = serde_json::json!({"mode": "handoff", "title": "Done", "summary": "s",
        "sections": [{"kind": "explanation", "title": "Flow", "body": "b", "html": "<p>x</p>"}],
        "checks": [{"text": "c", "status": "unverified", "evidence": "e"}]});
    for (name, page, kind) in [("d.json", &decision, "plan"), ("h.json", &handoff, "result")] {
        let file = tmp.path().join(name);
        std::fs::write(&file, page.to_string()).unwrap();
        python(&store_dir, &["publish", "--project", repo.to_str().unwrap(), "--file", file.to_str().unwrap(), "--type", kind, "--agent", "claude"]);
    }
    let store = Store { root: store_dir.clone() };
    let project = store.list_projects(&BTreeSet::new()).unwrap().remove(0).id;
    let reports = store.list_reports(&project).unwrap();
    let (newer, older) = (&reports[0], &reports[1]);
    assert_eq!((newer.mode.as_str(), older.mode.as_str(), older.open), ("handoff", "decision", false));

    store.delete_report(&project, &newer.id).unwrap();
    let left = store.list_reports(&project).unwrap();
    assert_eq!((left.len(), left[0].open), (1, false), "the closed.json marker keeps it closed");
    assert_eq!(store.submit_choice(&project, &older.id, &older.version, "a").unwrap_err(), app_lib::store::StoreError::Closed);
    let events = python(&store_dir, &["events", "--project", repo.to_str().unwrap(), "--report", &older.id]);
    let events: serde_json::Value = serde_json::from_str(&events).unwrap();
    assert_eq!((events["open"].as_bool(), events["events"].as_array().map(Vec::len)), (Some(false), Some(0)));
}
