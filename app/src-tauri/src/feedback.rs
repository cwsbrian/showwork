//! Sends a plan's saved feedback to the exact Orca terminal that authored it.

use std::path::{Path, PathBuf};
use std::process::Command;
use std::sync::Mutex;
use std::{fs, io::Write};

use serde::{Deserialize, Serialize};
use serde_json::Value;

use crate::store::{FeedbackReceipt, FeedbackStatus, ReportComment, ReportMeta, Store, StoreError};

static SUBMIT_LOCK: Mutex<()> = Mutex::new(());

#[derive(Serialize, Clone, Debug)]
#[serde(rename_all = "camelCase")]
pub struct DecisionDelivery {
    pub sent: bool,
    pub retryable: bool,
    pub reason: Option<String>,
}

#[derive(Serialize, Clone, Debug)]
#[serde(rename_all = "camelCase")]
pub struct SessionStatus {
    pub linked: bool,
    pub connected: bool,
    pub reason: Option<String>,
}

#[derive(Serialize, Deserialize)]
struct DecisionReceipt {
    version: String,
    choice: String,
    sent_at: String,
}

fn orca_executable() -> PathBuf {
    if let Some(override_path) = std::env::var_os("SHOWWORK_ORCA_CLI") { return PathBuf::from(override_path); }
    if cfg!(target_os = "macos") {
        let installed = Path::new("/Applications/Orca.app/Contents/Resources/bin/orca");
        if installed.is_file() { return installed.to_path_buf(); }
    }
    PathBuf::from(if cfg!(target_os = "linux") { "orca-ide" } else { "orca" })
}

fn run_orca(executable: &Path, args: &[&str]) -> Result<Value, StoreError> {
    let output = Command::new(executable).args(args).output()
        .map_err(|error| StoreError::AgentUnavailable(error.to_string()))?;
    let value: Value = serde_json::from_slice(&output.stdout)
        .map_err(|_| StoreError::AgentUnavailable("Orca returned an unreadable response".into()))?;
    if !output.status.success() || value.get("ok") == Some(&Value::Bool(false)) {
        let reason = value.pointer("/error/message").and_then(Value::as_str)
            .unwrap_or("Orca could not reach the session");
        return Err(StoreError::AgentUnavailable(reason.into()));
    }
    Ok(value)
}

fn verified_terminal(meta: &ReportMeta, executable: &Path) -> Result<String, StoreError> {
    let session = meta.agent_session.as_ref().ok_or(StoreError::NoAgentSession)?;
    if !session.terminal_handle.starts_with("term_") || session.terminal_handle.len() > 80 {
        return Err(StoreError::NoAgentSession);
    }
    let result = run_orca(executable, &["terminal", "show", "--terminal", &session.terminal_handle, "--json"])?;
    let terminal = result.pointer("/result/terminal").ok_or_else(|| StoreError::AgentUnavailable("Terminal details missing".into()))?;
    let same_worktree_path = terminal.get("worktreePath").and_then(Value::as_str).is_some_and(|path| {
        path == meta.worktree || Path::new(path).canonicalize().ok()
            .zip(Path::new(&meta.worktree).canonicalize().ok()).is_some_and(|(a, b)| a == b)
    });
    let same = terminal.get("handle").and_then(Value::as_str) == Some(session.terminal_handle.as_str())
        && terminal.get("incarnationId").and_then(Value::as_str) == Some(session.terminal_incarnation.as_str())
        && terminal.get("worktreeId").and_then(Value::as_str) == Some(session.worktree_id.as_str())
        && same_worktree_path
        && terminal.get("agentIdentity").and_then(Value::as_str) == Some(meta.agent.as_str());
    if !same || terminal.get("connected") != Some(&Value::Bool(true)) || terminal.get("writable") != Some(&Value::Bool(true)) {
        return Err(StoreError::AgentUnavailable("The original terminal has changed or closed".into()));
    }
    Ok(session.terminal_handle.clone())
}

fn send_to_session(meta: &ReportMeta, text: &str, executable: &Path) -> Result<(), StoreError> {
    if text.len() > 64 * 1024 { return Err(StoreError::AgentUnavailable("Message is too long to send at once".into())); }
    let handle = verified_terminal(meta, executable)?;
    let result = run_orca(executable, &["terminal", "send", "--terminal", &handle,
        "--text", text, "--enter", "--wait-submit", "10", "--json"])?;
    let accepted = result.pointer("/result/send/accepted").and_then(Value::as_bool)
        .or_else(|| result.pointer("/result/accepted").and_then(Value::as_bool))
        .or_else(|| result.pointer("/result/receipt/accepted").and_then(Value::as_bool))
        .unwrap_or(false);
    if !accepted { return Err(StoreError::AgentUnavailable("Orca did not accept the message".into())); }
    Ok(())
}

fn safe_text(value: &str) -> String {
    value.chars().map(|ch| if ch == '\n' || ch == '\t' || !ch.is_control() { ch } else { ' ' }).collect()
}

fn message(meta: &ReportMeta, page: &Value, note: Option<&str>, comments: &[ReportComment]) -> String {
    let mut text = format!("Feedback on Showwork plan: {}\nReport ID: {}\n", safe_text(&meta.title), meta.id);
    if let Some(body) = note {
        text.push_str("\nOverall note:\n");
        text.push_str(&safe_text(body));
        text.push('\n');
    }
    if !comments.is_empty() {
        text.push_str("\nInline comments:\n");
        for (index, comment) in comments.iter().enumerate() {
            text.push_str(&format!("\n{}. ", index + 1));
            if let Some(path) = comment.anchor.target.strip_prefix("file-")
                .and_then(|index| index.parse::<usize>().ok())
                .and_then(|index| page.get("files")?.get(index))
                .and_then(|file| file.get("path")).and_then(Value::as_str) {
                text.push_str(&format!("File: {}\n   ", safe_text(path)));
            }
            text.push_str(&format!("Selected text: “{}”\n   Comment: {}\n",
                safe_text(&comment.anchor.quote), safe_text(&comment.body)));
        }
    }
    text.push_str("\nPlease respond to each point in this session and update the plan as needed.");
    text
}

pub fn status(store: &Store, project_id: &str, report_id: &str) -> Result<FeedbackStatus, StoreError> {
    let report = store.get_report(project_id, report_id)?;
    if report.meta.r#type != "plan" || report.meta.mode != "handoff" { return Err(StoreError::NotAPlan); }
    let (snapshot, note, comments) = store.feedback_snapshot(project_id, report_id)?;
    let submitted = store.feedback_receipt(project_id, report_id)?
        .is_some_and(|receipt| receipt.snapshot == snapshot);
    let session = session_status_for_meta(&report.meta, &orca_executable());
    Ok(FeedbackStatus {
        available: session.connected,
        submitted,
        has_feedback: note.is_some() || !comments.is_empty(),
        reason: session.reason,
    })
}

pub fn session_status(store: &Store, project_id: &str, report_id: &str) -> Result<SessionStatus, StoreError> {
    let report = store.get_report(project_id, report_id)?;
    Ok(session_status_for_meta(&report.meta, &orca_executable()))
}

fn session_status_for_meta(meta: &ReportMeta, executable: &Path) -> SessionStatus {
    if meta.agent_session.is_none() {
        return SessionStatus { linked: false, connected: false, reason: Some("This report has no linked agent session.".into()) };
    }
    match verified_terminal(meta, executable) {
        Ok(_) => SessionStatus { linked: true, connected: true, reason: None },
        Err(error) => SessionStatus { linked: true, connected: false, reason: Some(error.to_string()) },
    }
}

pub fn submit(store: &Store, project_id: &str, report_id: &str, version: &str) -> Result<(), StoreError> {
    submit_with_cli(store, project_id, report_id, version, &orca_executable())
}

fn submit_with_cli(store: &Store, project_id: &str, report_id: &str, version: &str, executable: &Path) -> Result<(), StoreError> {
    let _guard = SUBMIT_LOCK.lock().unwrap_or_else(|poisoned| poisoned.into_inner());
    let report = store.get_report(project_id, report_id)?;
    let meta = report.meta;
    let page = report.page;
    if meta.r#type != "plan" || meta.mode != "handoff" { return Err(StoreError::NotAPlan); }
    if meta.version != version { return Err(StoreError::StaleVersion); }
    let (snapshot, note, comments) = store.feedback_snapshot(project_id, report_id)?;
    if note.is_none() && comments.is_empty() { return Err(StoreError::NoFeedback); }
    if store.feedback_receipt(project_id, report_id)?.is_some_and(|receipt| receipt.snapshot == snapshot) {
        return Err(StoreError::AlreadySubmitted);
    }
    let text = message(&meta, &page, note.as_ref().map(|note| note.body.as_str()), &comments);
    send_to_session(&meta, &text, executable)?;
    store.save_feedback_receipt(project_id, report_id, &FeedbackReceipt {
        snapshot, sent_at: chrono::Utc::now().to_rfc3339_opts(chrono::SecondsFormat::Micros, false),
    })
}

pub fn submit_choice(store: &Store, project_id: &str, report_id: &str, version: &str, choice: &str) -> Result<DecisionDelivery, StoreError> {
    submit_choice_with_cli(store, project_id, report_id, version, choice, &orca_executable())
}

fn submit_choice_with_cli(store: &Store, project_id: &str, report_id: &str, version: &str, choice: &str, executable: &Path) -> Result<DecisionDelivery, StoreError> {
    let _guard = SUBMIT_LOCK.lock().unwrap_or_else(|poisoned| poisoned.into_inner());
    store.submit_choice(project_id, report_id, version, choice)?;
    let report = store.get_report(project_id, report_id)?;
    let dir = store.report_dir(project_id, report_id)?;
    let receipt_path = dir.join("decision-delivery.json");
    if let Ok(source) = fs::read_to_string(&receipt_path) {
        if let Ok(receipt) = serde_json::from_str::<DecisionReceipt>(&source) {
            if receipt.version == version && receipt.choice == choice {
                return Ok(DecisionDelivery { sent: true, retryable: false, reason: None });
            }
        }
    }
    let option = report.page.get("options").and_then(Value::as_array)
        .and_then(|options| options.iter().find(|item| item.get("id").and_then(Value::as_str) == Some(choice)))
        .ok_or(StoreError::UnknownChoice)?;
    let question = report.page.get("question").and_then(Value::as_str).unwrap_or("");
    let title = option.get("title").and_then(Value::as_str).unwrap_or(choice);
    let body = option.get("body").and_then(Value::as_str).unwrap_or("");
    let message = format!("Showwork decision for: {}\nReport ID: {}\nQuestion: {}\nSelected option: {}\nDetails: {}\n\nPlease continue this plan using this choice in this session.",
        safe_text(&report.meta.title), report_id, safe_text(question), safe_text(title), safe_text(body));
    if let Err(error) = send_to_session(&report.meta, &message, executable) {
        return Ok(DecisionDelivery { sent: false, retryable: !matches!(error, StoreError::NoAgentSession), reason: Some(error.to_string()) });
    }
    let receipt = DecisionReceipt { version: version.into(), choice: choice.into(), sent_at: chrono::Utc::now().to_rfc3339_opts(chrono::SecondsFormat::Micros, false) };
    let data = serde_json::to_vec(&receipt).map_err(|error| StoreError::Io(error.to_string()))?;
    let temp = dir.join(format!(".decision-delivery-{}-{}.tmp", std::process::id(), chrono::Utc::now().timestamp_nanos_opt().unwrap_or_default()));
    let result = (|| -> std::io::Result<()> {
        let mut file = fs::OpenOptions::new().write(true).create_new(true).open(&temp)?;
        file.write_all(&data)?;
        file.sync_all()?;
        fs::rename(&temp, &receipt_path)
    })();
    if result.is_err() { let _ = fs::remove_file(&temp); }
    result.map_err(StoreError::from)?;
    Ok(DecisionDelivery { sent: true, retryable: false, reason: None })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::store::{AgentSession, CommentAnchor};
    use serde_json::json;
    use std::fs;
    use tempfile::TempDir;

    #[test]
    fn message_names_selected_text_and_note() {
        let meta = ReportMeta {
            id: "r1".into(), project_id: "p1".into(), r#type: "plan".into(), mode: "handoff".into(),
            title: "Login plan".into(), branch: None, commit: None, worktree: "/w".into(),
            agent: "codex".into(), created_at: "now".into(), version: "v1".into(), run: None,
            agent_session: Some(AgentSession { terminal_handle: "term_1".into(), terminal_incarnation: "i1".into(), worktree_id: "w1".into(), thread_id: None }),
            open: false, chosen: false, read: false,
        };
        let comments = vec![ReportComment { id: "c1".into(), version: "v1".into(),
            anchor: CommentAnchor { target: "summary".into(), start: 0, end: 5, quote: "Login".into() },
            body: "Explain the fallback".into(), created_at: "now".into() }];
        let text = message(&meta, &json!({"files": []}), Some("Ship slowly"), &comments);
        assert!(text.contains("Overall note:\nShip slowly"));
        assert!(text.contains("Selected text: “Login”\n   Comment: Explain the fallback"));
        let code_comment = ReportComment { anchor: CommentAnchor { target: "file-0".into(), start: 0, end: 5, quote: "const".into() }, ..comments[0].clone() };
        let text = message(&meta, &json!({"files": [{"path": "src/login.ts"}]}), None, &[code_comment]);
        assert!(text.contains("File: src/login.ts\n   Selected text: “const”"));
    }

    #[cfg(unix)]
    #[test]
    fn submit_sends_saved_feedback_once_to_matching_terminal() {
        use std::os::unix::fs::PermissionsExt;
        let temp = TempDir::new().unwrap();
        let store = Store { root: temp.path().join("store") };
        let dir = store.root.join("projects/p1/reports/r1");
        fs::create_dir_all(&dir).unwrap();
        fs::write(dir.join("meta.json"), json!({
            "id":"r1","project_id":"p1","type":"plan","mode":"handoff","title":"Plan",
            "branch":null,"commit":null,"worktree":"/w","agent":"codex","created_at":"now","version":"v1",
            "agent_session":{"terminal_handle":"term_123","terminal_incarnation":"inc-1","worktree_id":"wt-1","thread_id":"thread-1"}
        }).to_string()).unwrap();
        fs::write(dir.join("page.json"), json!({"mode":"handoff","title":"Plan"}).to_string()).unwrap();
        store.save_plan_note("p1", "r1", "v1", "Overall feedback").unwrap();
        store.add_comment("p1", "r1", "v1", CommentAnchor {
            target: "summary".into(), start: 0, end: 5, quote: "Quote".into(),
        }, "Inline feedback").unwrap();
        let script = temp.path().join("fake-orca");
        let sent = temp.path().join("sent.txt");
        fs::write(&script, format!(r##"#!/bin/sh
if [ "$2" = show ]; then
  printf '%s\n' '{{"ok":true,"result":{{"terminal":{{"handle":"term_123","incarnationId":"inc-1","worktreeId":"wt-1","worktreePath":"/w","agentIdentity":"codex","connected":true,"writable":true}}}}}}'
elif [ "$2" = send ]; then
  while [ "$#" -gt 0 ]; do
    if [ "$1" = --text ]; then shift; printf '%s' "$1" > '{}'; break; fi
    shift
  done
  printf '%s\n' '{{"ok":true,"result":{{"send":{{"accepted":true}}}}}}'
fi
"##, sent.display())).unwrap();
        fs::set_permissions(&script, fs::Permissions::from_mode(0o700)).unwrap();
        assert!(!status(&store, "p1", "r1").unwrap().submitted);
        submit_with_cli(&store, "p1", "r1", "v1", &script).unwrap();
        let message = fs::read_to_string(&sent).unwrap();
        assert!(message.contains("Overall note:\nOverall feedback"));
        assert!(message.contains("Selected text: “Quote”\n   Comment: Inline feedback"));
        assert!(status(&store, "p1", "r1").unwrap().submitted);
        assert_eq!(submit_with_cli(&store, "p1", "r1", "v1", &script).unwrap_err(), StoreError::AlreadySubmitted);
        store.save_plan_note("p1", "r1", "v1", "Updated feedback").unwrap();
        assert!(!status(&store, "p1", "r1").unwrap().submitted);
        fs::write(&script, "#!/bin/sh\nprintf '%s\\n' '{\"ok\":true,\"result\":{\"terminal\":{\"handle\":\"term_123\",\"incarnationId\":\"different\",\"worktreeId\":\"wt-1\",\"worktreePath\":\"/w\",\"agentIdentity\":\"codex\",\"connected\":true,\"writable\":true}}}'\n").unwrap();
        assert!(matches!(submit_with_cli(&store, "p1", "r1", "v1", &script), Err(StoreError::AgentUnavailable(_))));
        assert_eq!(fs::read_to_string(&sent).unwrap(), message);
    }

    #[cfg(unix)]
    #[test]
    fn decision_sends_question_and_choice_once_and_keeps_record_on_delivery_failure() {
        use std::os::unix::fs::PermissionsExt;
        let temp = TempDir::new().unwrap();
        let store = Store { root: temp.path().join("store") };
        let dir = store.root.join("projects/p1/reports/r1");
        fs::create_dir_all(&dir).unwrap();
        fs::write(dir.join("meta.json"), json!({
            "id":"r1","project_id":"p1","type":"plan","mode":"decision","title":"Layout plan",
            "branch":null,"commit":null,"worktree":"/w","agent":"codex","created_at":"now","version":"v1",
            "agent_session":{"terminal_handle":"term_123","terminal_incarnation":"inc-1","worktree_id":"wt-1","thread_id":null}
        }).to_string()).unwrap();
        fs::write(dir.join("page.json"), json!({"mode":"decision","title":"Layout plan","question":"Which layout?",
            "options":[{"id":"a","title":"Grid","body":"Two columns"}]}).to_string()).unwrap();
        let script = temp.path().join("fake-orca");
        let sent = temp.path().join("sent.txt");
        fs::write(&script, format!(r##"#!/bin/sh
if [ "$2" = show ]; then
  printf '%s\n' '{{"ok":true,"result":{{"terminal":{{"handle":"term_123","incarnationId":"inc-1","worktreeId":"wt-1","worktreePath":"/w","agentIdentity":"codex","connected":true,"writable":true}}}}}}'
elif [ "$2" = send ]; then
  while [ "$#" -gt 0 ]; do
    if [ "$1" = --text ]; then shift; printf '%s' "$1" >> '{}'; break; fi
    shift
  done
  printf '%s\n' '{{"ok":true,"result":{{"send":{{"accepted":true}}}}}}'
fi
"##, sent.display())).unwrap();
        fs::set_permissions(&script, fs::Permissions::from_mode(0o700)).unwrap();
        let meta = store.get_report("p1", "r1").unwrap().meta;
        assert!(session_status_for_meta(&meta, &script).connected);
        let first = submit_choice_with_cli(&store, "p1", "r1", "v1", "a", &script).unwrap();
        assert!(first.sent);
        let text = fs::read_to_string(&sent).unwrap();
        assert!(text.contains("Question: Which layout?\nSelected option: Grid\nDetails: Two columns"));
        assert!(submit_choice_with_cli(&store, "p1", "r1", "v1", "a", &script).unwrap().sent);
        assert_eq!(fs::read_to_string(&sent).unwrap(), text);
        assert_eq!(fs::read_to_string(dir.join("events.jsonl")).unwrap().lines().count(), 1);
        fs::remove_file(dir.join("decision-delivery.json")).unwrap();
        fs::write(&script, "#!/bin/sh\nprintf '%s\\n' '{\"ok\":true,\"result\":{\"terminal\":{\"handle\":\"term_123\",\"incarnationId\":\"other\"}}}'\n").unwrap();
        assert!(!session_status_for_meta(&meta, &script).connected);
        let failed = submit_choice_with_cli(&store, "p1", "r1", "v1", "a", &script).unwrap();
        assert!(!failed.sent && failed.retryable);
        assert_eq!(fs::read_to_string(dir.join("events.jsonl")).unwrap().lines().count(), 1);
    }
}
