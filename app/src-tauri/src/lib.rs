/// Timestamped diagnostics on stderr (watcher arrivals, notifications, window events).
macro_rules! log {
    ($($arg:tt)*) => {
        eprintln!("[showwork {}] {}", chrono::Local::now().format("%H:%M:%S%.3f"), format_args!($($arg)*))
    };
}

pub mod notify_mac;
pub mod state;
pub mod store;
pub mod watch;

use std::collections::BTreeSet;
use std::process::Command;
use std::sync::{Mutex, MutexGuard};

use serde::Serialize;
use tauri::{AppHandle, Emitter, Manager, RunEvent, State, WindowEvent};

use state::{UiState, View};
use store::{ProjectSummary, ReportDetail, ReportMeta, Store};

type Ui = Mutex<UiState>;

/// Report ids already notified in this run, so startup and the watcher never both notify one report.
#[derive(Default)]
struct Notified(Mutex<BTreeSet<String>>);

impl Notified {
    fn claim(&self, report_id: &str) -> bool {
        self.0.lock().unwrap_or_else(|e| e.into_inner()).insert(report_id.to_string())
    }
}

#[derive(Serialize, Clone, Debug)]
#[serde(rename_all = "camelCase")]
struct ReportRef {
    project_id: String,
    report_id: String,
}

#[derive(Serialize)]
struct ViewState {
    view: View,
}

fn lock(ui: &Ui) -> MutexGuard<'_, UiState> {
    ui.lock().unwrap_or_else(|e| e.into_inner())
}

fn err(error: impl ToString) -> String {
    error.to_string()
}

// ---- commands ----

#[tauri::command]
fn list_projects(store: State<Store>, ui: State<Ui>) -> Result<Vec<ProjectSummary>, String> {
    let read = lock(&ui).read.clone();
    store.list_projects(&read).map_err(err)
}

#[tauri::command]
fn list_reports(store: State<Store>, project_id: String) -> Result<Vec<ReportMeta>, String> {
    store.list_reports(&project_id).map_err(err)
}

#[tauri::command]
fn get_report(store: State<Store>, project_id: String, report_id: String) -> Result<ReportDetail, String> {
    store.get_report(&project_id, &report_id).map_err(err)
}

#[tauri::command]
fn submit_choice(store: State<Store>, project_id: String, report_id: String, version: String, choice: String) -> Result<(), String> {
    store.submit_choice(&project_id, &report_id, &version, &choice).map_err(err)
}

#[tauri::command]
fn mark_read(store: State<Store>, ui: State<Ui>, report_id: String) -> Result<(), String> {
    let mut ui = lock(&ui);
    ui.mark_read(&report_id);
    ui.save(&store.root).map_err(err)
}

#[tauri::command]
fn get_state(ui: State<Ui>) -> Result<ViewState, String> {
    Ok(ViewState { view: lock(&ui).view })
}

#[tauri::command]
fn set_view(store: State<Store>, ui: State<Ui>, view: View) -> Result<(), String> {
    let mut ui = lock(&ui);
    ui.view = view;
    ui.save(&store.root).map_err(err)
}

#[tauri::command]
fn delete_report(store: State<Store>, project_id: String, report_id: String) -> Result<(), String> {
    store.delete_report(&project_id, &report_id).map_err(err)
}

#[tauri::command]
fn delete_project(store: State<Store>, project_id: String) -> Result<(), String> {
    store.delete_project(&project_id).map_err(err)
}

/// Reveals the project in Finder: the newest worktree that still exists, else the repository folder.
#[tauri::command]
fn reveal_project(store: State<Store>, project_id: String) -> Result<(), String> {
    let path = store.reveal_path(&project_id).map_err(|_| "This project's folder no longer exists".to_string())?;
    let status = Command::new("open").arg("-R").arg(&path).status().map_err(err)?;
    if status.success() { Ok(()) } else { Err(format!("Could not reveal {}", path.display())) }
}

// ---- window, arrivals, notifications ----

fn show_main(app: &AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.unminimize();
        let _ = window.show();
        let _ = window.set_focus();
    }
}

fn type_label(kind: &str) -> String {
    match kind {
        "adversarial-review" => "Adversarial review".to_string(),
        other => {
            let mut chars = other.chars();
            chars.next().map(|c| c.to_uppercase().chain(chars).collect()).unwrap_or_default()
        }
    }
}

/// Notification click: bring the window forward and ask the frontend to select the report.
fn open_report(app: &AppHandle, target: &ReportRef) {
    show_main(app);
    let result = app.emit("open-report", target);
    log!("emit open-report {target:?}: {result:?}");
}

/// Startup summary text for several unseen reports.
fn summary_body(total: usize, open: usize) -> String {
    match open {
        0 => format!("{total} new reports"),
        1 => format!("{total} new reports, 1 needs your choice"),
        n => format!("{total} new reports, {n} need your choice"),
    }
}

fn send_notification(app: &AppHandle, title: &str, body: &str, target: ReportRef) {
    let handle = app.clone();
    notify_mac::show(title, body, move || open_report(&handle, &target));
}

fn notify_report(app: &AppHandle, project_id: &str, report_id: &str) {
    let store = app.state::<Store>();
    let project = store.list_projects(&BTreeSet::new()).ok().and_then(|all| all.into_iter().find(|p| p.id == project_id));
    let meta = store.list_reports(project_id).ok().and_then(|all| all.into_iter().find(|r| r.id == report_id));
    let (Some(project), Some(meta)) = (project, meta) else {
        log!("cannot notify {project_id}/{report_id}: project or report not readable");
        return;
    };
    let title = format!("{} · {}", project.display_name, type_label(&meta.r#type));
    let body = if meta.open { format!("Needs your choice: {}", meta.title) } else { meta.title.clone() };
    let target = ReportRef { project_id: project_id.to_string(), report_id: report_id.to_string() };
    send_notification(app, &title, &body, target);
}

fn advance_cursor(app: &AppHandle, ui: &mut UiState, newest: Option<&String>) {
    if let Some(newest) = newest.filter(|id| ui.last_seen.as_ref().is_none_or(|seen| *id > seen)) {
        ui.last_seen = Some(newest.clone());
        if let Err(error) = ui.save(&app.state::<Store>().root) {
            log!("saving state failed: {error}");
        }
    }
}

/// Watcher callback: badge refresh for the frontend plus one notification.
fn on_arrival(app: &AppHandle, project_id: String, report_id: String) {
    advance_cursor(app, &mut lock(&app.state::<Ui>()), Some(&report_id));
    let target = ReportRef { project_id: project_id.clone(), report_id: report_id.clone() };
    let result = app.emit("report-arrived", &target);
    log!("emit report-arrived {target:?}: {result:?}");
    if app.state::<Notified>().claim(&report_id) {
        notify_report(app, &project_id, &report_id);
    }
}

/// Reports published while the app was not running: one notification, or one summary for several.
/// `launched` is the state as loaded at launch, so a watcher arrival that already moved the cursor
/// cannot hide older reports from this run's catch-up.
fn notify_unseen_at_startup(app: &AppHandle, launched: &UiState) {
    let ids = app.state::<Store>().all_report_ids();
    let unseen = launched.unseen_since_last_run(&ids);
    advance_cursor(app, &mut lock(&app.state::<Ui>()), ids.iter().map(|(_, r)| r).max());
    let notified = app.state::<Notified>();
    let unseen: Vec<(String, String)> = unseen.into_iter().filter(|(_, r)| notified.claim(r)).collect();
    log!("startup: {} report(s), {} unseen since last run", ids.len(), unseen.len());
    match unseen.as_slice() {
        [] => {}
        [(project_id, report_id)] => notify_report(app, project_id, report_id),
        [.., (project_id, report_id)] => {
            // Open decisions among the unseen reports, oldest first; a click opens the newest one.
            let store = app.state::<Store>();
            let projects: BTreeSet<&String> = unseen.iter().map(|(p, _)| p).collect();
            let open: Vec<ReportRef> = projects
                .into_iter()
                .flat_map(|p| store.list_reports(p).unwrap_or_default())
                .filter(|meta| meta.open && unseen.iter().any(|(_, r)| *r == meta.id))
                .map(|meta| ReportRef { project_id: meta.project_id, report_id: meta.id })
                .collect();
            let newest_open = open.iter().max_by(|a, b| a.report_id.cmp(&b.report_id)).cloned();
            let target = newest_open.unwrap_or(ReportRef { project_id: project_id.clone(), report_id: report_id.clone() });
            send_notification(app, "Showwork", &summary_body(unseen.len(), open.len()), target);
        }
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let root = store::store_root();
    let launched = state::load(&root);
    // Read before building: the launch activation happens before `setup` runs.
    let background = std::env::args().any(|arg| arg == "--background");
    let builder = tauri::Builder::default();
    // A `--background` launch (agent publish with the app closed) must not take focus. With `false`
    // macOS activates the app only when no other app is active; a normal launch keeps the default.
    #[cfg(target_os = "macos")]
    let builder = builder.activate_ignoring_other_apps(!background);
    let app = builder
        .manage(Store { root: root.clone() })
        .manage(Mutex::new(launched.clone()))
        .manage(Notified::default())
        .invoke_handler(tauri::generate_handler![
            list_projects,
            list_reports,
            get_report,
            submit_choice,
            mark_read,
            get_state,
            set_view,
            delete_report,
            delete_project,
            reveal_project
        ])
        .setup(move |app| {
            let handle = app.handle().clone();
            log!("store root {}", root.display());
            match store::ensure_store_dirs(&root) {
                Err(error) => log!("store unavailable, not watching: {error}"),
                Ok(()) => {
                    let on_new = {
                        let handle = handle.clone();
                        move |project_id, report_id| on_arrival(&handle, project_id, report_id)
                    };
                    match watch::start(Store { root: root.clone() }, on_new) {
                        Ok(watcher) => {
                            app.manage(Mutex::new(watcher)); // keep it alive for the app's lifetime
                        }
                        Err(error) => log!("watcher failed to start: {error}"),
                    }
                }
            }
            // After the watcher is running, so nothing published during startup is missed.
            notify_unseen_at_startup(&handle, &launched);
            log!("launched background={background}");
            if !background {
                show_main(&handle);
            }
            Ok(())
        })
        .on_window_event(|window, event| {
            if let WindowEvent::CloseRequested { api, .. } = event {
                api.prevent_close();
                let _ = window.hide();
            }
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application");
    app.run(|_handle, _event| {
        #[cfg(target_os = "macos")]
        if let RunEvent::Reopen { has_visible_windows, .. } = _event {
            log!("reopen (has_visible_windows={has_visible_windows})");
            show_main(_handle);
        }
    });
}

#[cfg(test)]
mod tests {
    #[test]
    fn type_label_matches_frontend_labels() {
        let labels: Vec<String> = ["plan", "review", "verify", "result", "adversarial-review", ""].map(super::type_label).into();
        assert_eq!(labels, ["Plan", "Review", "Verify", "Result", "Adversarial review", ""]);
    }

    #[test]
    fn summary_body_says_when_a_choice_is_needed() {
        assert_eq!(super::summary_body(3, 0), "3 new reports");
        assert_eq!(super::summary_body(3, 1), "3 new reports, 1 needs your choice");
        assert_eq!(super::summary_body(4, 2), "4 new reports, 2 need your choice");
    }
}
