//! Watches `<root>/projects` and reports each newly visible report exactly once.
//!
//! Reports appear by renaming `reports/.pending-<id>/` to `reports/<id>/`; `Store::all_report_ids`
//! skips dot folders and broken entries, so rescanning on every event only ever surfaces finished reports.

use std::collections::BTreeSet;
use std::sync::{Arc, Mutex};

use notify::{RecommendedWatcher, RecursiveMode, Watcher};

use crate::store::Store;

struct Scanner<F> {
    store: Store,
    known: BTreeSet<(String, String)>,
    on_new: F,
}

impl<F: Fn(String, String)> Scanner<F> {
    fn rescan(&mut self) {
        for ids in self.store.all_report_ids() {
            if self.known.insert(ids.clone()) {
                log!("watcher arrival: project={} report={}", ids.0, ids.1);
                (self.on_new)(ids.0, ids.1);
            }
        }
    }
}

/// Starts watching; `on_new(project_id, report_id)` runs on the watcher thread, once per id not seen before.
/// Reports already present at start are seeded as known and never reported.
pub fn start(store: Store, on_new: impl Fn(String, String) + Send + 'static) -> notify::Result<RecommendedWatcher> {
    let projects = store.root.join("projects");
    let known = store.all_report_ids().into_iter().collect();
    let scanner = Arc::new(Mutex::new(Scanner { store, known, on_new }));
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
        let watcher = start(store, move |p, r| tx.send((p, r)).unwrap()).unwrap();
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
    fn pending_folder_alone_does_not_fire() {
        let (_tmp, store, reports) = setup();
        let (_watcher, rx) = channel_watcher(store);
        write_report(&reports.join(".pending-b"), "b");
        fs::write(reports.join(".pending-b/meta.json"), r#"{"id":"b"}"#).unwrap();
        assert!(rx.recv_timeout(Duration::from_millis(1500)).is_err(), "pending folders never fire");
    }
}
