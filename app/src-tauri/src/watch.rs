//! Watches `<root>/projects` and reports each newly visible report exactly once.
//!
//! Reports appear by renaming `reports/.pending-<id>/` to `reports/<id>/`; `Store::all_report_ids`
//! skips dot folders and broken entries, so rescanning on every event only ever surfaces finished reports.

use std::collections::BTreeSet;
use std::sync::{Arc, Mutex};

use notify::{RecommendedWatcher, RecursiveMode, Watcher};

use crate::store::Store;

struct Scanner<F, G> {
    store: Store,
    known: BTreeSet<(String, String)>,
    on_new: F,
    running: BTreeSet<(String, String, String, u64)>,
    sessions: BTreeSet<(String, String, Option<String>)>,
    on_running: G,
}

impl<F: Fn(String, String), G: Fn()> Scanner<F, G> {
    fn rescan(&mut self) {
        for ids in self.store.all_report_ids() {
            if self.known.insert(ids.clone()) {
                log!("watcher arrival: project={} report={}", ids.0, ids.1);
                (self.on_new)(ids.0, ids.1);
            }
        }
        // After arrivals, so a published report shows up before its working item goes away.
        let running = self.store.all_running();
        let sessions = self.store.all_sessions();
        if running != self.running || sessions != self.sessions {
            log!("watcher: {} working item(s)", running.len());
            self.running = running;
            self.sessions = sessions;
            (self.on_running)();
        }
    }
}

/// Starts watching; `on_new(project_id, report_id)` runs on the watcher thread, once per id not seen before.
/// Reports already present at start are seeded as known and never reported. `on_running` runs when the
/// set of working items (`running/*.json`) or session records changes.
pub fn start(
    store: Store,
    on_new: impl Fn(String, String) + Send + 'static,
    on_running: impl Fn() + Send + 'static,
) -> notify::Result<RecommendedWatcher> {
    let projects = store.root.join("projects");
    let known = store.all_report_ids().into_iter().collect();
    let running = store.all_running();
    let sessions = store.all_sessions();
    let scanner = Arc::new(Mutex::new(Scanner { store, known, on_new, running, sessions, on_running }));
    let on_event = Arc::clone(&scanner);
    let mut watcher = notify::recommended_watcher(move |event: notify::Result<notify::Event>| {
        if let Err(error) = event {
            log!("watcher error: {error}"); // still rescan: an overflow can hide events
        }
        on_event.lock().unwrap_or_else(|e| e.into_inner()).rescan();
    })?;
    watcher.watch(&projects, RecursiveMode::Recursive)?;
    // Catch reports that appeared between seeding and the event stream starting.
    scanner.lock().unwrap_or_else(|e| e.into_inner()).rescan();
    log!("watching {}", projects.display());
    Ok(watcher)
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    use std::fs;
    use std::path::Path;
    use std::sync::mpsc;
    use std::time::Duration;
    use tempfile::TempDir;

    fn write_report(dir: &Path, id: &str) {
        fs::create_dir_all(dir.join("assets")).unwrap();
        let meta = json!({"id": id, "project_id": "p1", "type": "result", "mode": "handoff", "title": "T",
            "branch": "main", "commit": null, "worktree": "/w", "agent": "claude",
            "created_at": "2026-11-05T00:00:00Z", "version": "v1"});
        fs::write(dir.join("meta.json"), meta.to_string()).unwrap();
        fs::write(dir.join("page.json"), r#"{"mode":"handoff","title":"T"}"#).unwrap();
    }

    fn setup() -> (TempDir, Store, std::path::PathBuf) {
        let tmp = TempDir::new().unwrap();
        let root = tmp.path().canonicalize().unwrap();
        let reports = root.join("projects/p1/reports");
        fs::create_dir_all(&reports).unwrap();
        fs::write(root.join("projects/p1/project.json"), r#"{"id":"p1","name":"alpha"}"#).unwrap();
        write_report(&reports.join("old"), "old"); // seeded: must never fire
        (tmp, Store { root }, reports)
    }

    fn channel_watcher(store: Store) -> (RecommendedWatcher, mpsc::Receiver<(String, String)>) {
        let (tx, rx) = mpsc::channel();
        let watcher = start(store, move |p, r| tx.send((p, r)).unwrap(), || {}).unwrap();
        std::thread::sleep(Duration::from_millis(300)); // let the event stream settle
        (watcher, rx)
    }

    #[test]
    fn new_report_fires_exactly_once() {
        let (_tmp, store, reports) = setup();
        let (_watcher, rx) = channel_watcher(store);
        write_report(&reports.join(".pending-a"), "a");
        fs::rename(reports.join(".pending-a"), reports.join("a")).unwrap();
        let got = rx.recv_timeout(Duration::from_secs(3)).expect("arrival within 3 s");
        assert_eq!(got, ("p1".to_string(), "a".to_string()));
        fs::write(reports.join("a/meta.json"), fs::read_to_string(reports.join("a/meta.json")).unwrap()).unwrap();
        fs::write(reports.join("a/events.jsonl"), "{}\n").unwrap();
        assert!(rx.recv_timeout(Duration::from_millis(1500)).is_err(), "rewrites must not fire again");
    }

    #[test]
    fn working_items_fire_when_they_appear_and_go() {
        let (_tmp, store, reports) = setup();
        let running = reports.parent().unwrap().join("running");
        let (tx, rx) = mpsc::channel();
        let _watcher = start(store, |_, _| {}, move || tx.send(()).unwrap()).unwrap();
        std::thread::sleep(Duration::from_millis(300));
        fs::create_dir_all(&running).unwrap();
        let run = json!({"id": "r1", "project_id": "p1", "type": "review", "worktree": "/w", "agent": "claude", "started_at": "t"});
        fs::write(running.join("r1.json"), run.to_string()).unwrap();
        rx.recv_timeout(Duration::from_secs(3)).expect("appear fires");
        while rx.recv_timeout(Duration::from_millis(500)).is_ok() {}
        let mut updated = run;
        updated["revision"] = json!(1);
        updated["draft_text"] = json!("Finding: confirmed");
        fs::write(running.join(".pending-r1"), updated.to_string()).unwrap();
        fs::rename(running.join(".pending-r1"), running.join("r1.json")).unwrap();
        rx.recv_timeout(Duration::from_secs(3)).expect("draft update fires");
        while rx.recv_timeout(Duration::from_millis(500)).is_ok() {}
        fs::remove_file(running.join("r1.json")).unwrap();
        rx.recv_timeout(Duration::from_secs(3)).expect("removal fires");
        let sessions = reports.parent().unwrap().join("sessions");
        fs::create_dir_all(&sessions).unwrap();
        let session = json!({"id":"s1","project_id":"p1","run":"r1","kind":"browser","title":null,
            "url":"about:blank","width":800,"height":600,"port":1234,"ws":"ws://127.0.0.1:1234/x",
            "pid":1,"started_at":"now","ended_at":null});
        fs::write(sessions.join("s1.json"), session.to_string()).unwrap();
        rx.recv_timeout(Duration::from_secs(3)).expect("session appears");
        let mut ended = session;
        ended["ended_at"] = json!("later");
        fs::write(sessions.join("s1.json"), ended.to_string()).unwrap();
        rx.recv_timeout(Duration::from_secs(3)).expect("session ends");
    }

    #[test]
    fn ios_sessions_fire_when_created_and_ended() {
        let (_tmp, store, reports) = setup();
        let sessions = reports.parent().unwrap().join("sessions");
        fs::create_dir_all(&sessions).unwrap();
        let (tx, rx) = mpsc::channel();
        let _watcher = start(store, |_, _| {}, move || { let _ = tx.send(()); }).unwrap();
        std::thread::sleep(Duration::from_millis(300));
        let mut record = json!({"id":"ios1","project_id":"p1","run":"r1","kind":"ios-simulator",
            "title":"Phone","width":600,"height":1200,"pid":std::process::id(),
            "started_at":"now","ended_at":null,"udid":"device-1",
            "points_width":402,"points_height":874,"port":1234,"token":"secret"});
        let path = sessions.join("ios1.json");
        fs::write(&path, record.to_string()).unwrap();
        rx.recv_timeout(Duration::from_secs(3)).expect("iOS session appears");
        while rx.recv_timeout(Duration::from_millis(500)).is_ok() {}
        record["ended_at"] = json!("later");
        let pending = sessions.join(".pending-ios1");
        fs::write(&pending, record.to_string()).unwrap();
        fs::rename(&pending, &path).unwrap();
        rx.recv_timeout(Duration::from_secs(3)).expect("iOS session ends");
    }

    #[test]
    fn pending_folder_alone_does_not_fire() {
        let (_tmp, store, reports) = setup();
        let (_watcher, rx) = channel_watcher(store);
        write_report(&reports.join(".pending-b"), "b");
        fs::write(reports.join(".pending-b/meta.json"), r#"{"id":"b"}"#).unwrap();
        assert!(rx.recv_timeout(Duration::from_millis(1500)).is_err(), "pending folders never fire");
    }
}
