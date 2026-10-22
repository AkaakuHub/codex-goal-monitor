use std::{
    sync::mpsc::{self, SyncSender},
    time::Duration,
};

use serde_json::json;

use crate::{config::Settings, monitor::Status};

pub struct Notification {
    pub settings: Settings,
    pub thread: String,
    pub title: &'static str,
    pub detail: &'static str,
}

pub fn start(status: Status) -> SyncSender<Notification> {
    let (sender, receiver) = mpsc::sync_channel::<Notification>(100);
    std::thread::spawn(move || {
        let config = ureq::Agent::config_builder()
            .http_status_as_error(false)
            .timeout_global(Some(Duration::from_secs(10)))
            .build();
        let agent = ureq::Agent::new_with_config(config);
        for notification in receiver {
            let settings = notification.settings;
            let payload = json!({
                "content": format!("{}\nSource: {}\nThread: {}\n{}", notification.title, settings.sender_label, notification.thread, notification.detail),
                "username": settings.sender_label,
                "allowed_mentions": {"parse": []}
            });
            for attempt in 0..5 {
                let mut delay = Duration::from_secs(5);
                match agent.post(&settings.webhook_url).send_json(&payload) {
                    Ok(response) if response.status().is_success() => break,
                    Ok(mut response) if response.status().as_u16() == 429 => {
                        if let Ok(body) = response.body_mut().read_json::<serde_json::Value>()
                            && let Some(seconds) = body["retry_after"]
                                .as_f64()
                                .filter(|n| n.is_finite() && *n >= 0.0)
                        {
                            delay = Duration::from_secs_f64(seconds.clamp(1.0, 86400.0));
                        }
                    }
                    Ok(response) if response.status().is_client_error() => {
                        status("Discord通知に失敗しました。Webhook URLを確認してください。".into());
                        break;
                    }
                    _ => {}
                }
                if attempt == 4 {
                    status("Discord通知に失敗しました。接続を確認してください。".into());
                } else {
                    std::thread::sleep(delay);
                }
            }
        }
    });
    sender
}

#[cfg(test)]
mod tests;
