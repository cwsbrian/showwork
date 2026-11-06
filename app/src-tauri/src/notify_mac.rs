//! macOS notifications with a click callback (via `mac_notification_sys`).

/// Shows a notification. A background thread waits for the user's response and runs
/// `on_click` only when the notification itself is clicked.
#[cfg(target_os = "macos")]
pub fn show(title: &str, body: &str, on_click: impl FnOnce() + Send + 'static) {
    use mac_notification_sys::{Notification, NotificationResponse, set_application};
    use std::sync::Once;

    static APPLICATION: Once = Once::new();
    APPLICATION.call_once(|| {
        let result = set_application("dev.showwork.app");
        log!("notification set_application(dev.showwork.app): {result:?}");
    });

    let (title, body) = (title.to_string(), body.to_string());
    std::thread::spawn(move || {
        log!("notification sending: title={title:?} body={body:?}");
        let response = Notification::new().title(&title).message(&body).wait_for_click(true).send();
        log!("notification response: {response:?}");
        if let Ok(NotificationResponse::Click) = response {
            log!("notification clicked: running callback");
            on_click();
        }
    });
}

#[cfg(not(target_os = "macos"))]
pub fn show(title: &str, body: &str, _on_click: impl FnOnce() + Send + 'static) {
    log!("notifications unsupported on this platform: {title}: {body}");
}
