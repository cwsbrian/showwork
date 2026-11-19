//! macOS notifications with a click callback (via `mac_notification_sys`).

#[cfg(target_os = "macos")]
use std::sync::Mutex;

#[cfg(target_os = "macos")]
static LATEST: Mutex<u64> = Mutex::new(0);

/// Shows a notification. A background thread waits for the user's response and runs
/// `on_click` only when the notification itself is clicked.
#[cfg(target_os = "macos")]
pub fn show(title: &str, body: &str, on_click: impl FnOnce() + Send + 'static) {
    use mac_notification_sys::{set_application, Notification, NotificationResponse};
    use std::sync::Once;

    static APPLICATION: Once = Once::new();
    APPLICATION.call_once(|| {
        let result = set_application("dev.showwork.app");
        log!("notification set_application(dev.showwork.app): {result:?}");
    });

    // The notification library polls the whole delivered list twice a second for each
    // pending click. Keep only the newest notification so those polls cannot pile up.
    let generation = {
        let mut latest = LATEST.lock().unwrap_or_else(|error| error.into_inner());
        *latest = latest.wrapping_add(1);
        clear_delivered();
        *latest
    };

    let (title, body) = (title.to_string(), body.to_string());
    std::thread::spawn(move || {
        if *LATEST.lock().unwrap_or_else(|error| error.into_inner()) != generation {
            return;
        }
        log!("notification sending: title={title:?} body={body:?}");
        let response = Notification::new()
            .title(&title)
            .message(&body)
            .wait_for_click(true)
            .send();
        log!("notification response: {response:?}");
        if let Ok(NotificationResponse::Click) = response {
            log!("notification clicked: running callback");
            on_click();
        }
    });
}

#[cfg(target_os = "macos")]
#[allow(deprecated)]
fn clear_delivered() {
    objc2_foundation::NSUserNotificationCenter::defaultUserNotificationCenter()
        .removeAllDeliveredNotifications();
}

#[cfg(not(target_os = "macos"))]
pub fn show(title: &str, body: &str, _on_click: impl FnOnce() + Send + 'static) {
    log!("notifications unsupported on this platform: {title}: {body}");
}
