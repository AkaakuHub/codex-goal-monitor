use super::Settings;

#[test]
fn notifications_are_optional() {
    assert!(Settings::default().validate().is_ok());
    assert!(
        Settings {
            sender_label: String::new(),
            ..Settings::default()
        }
        .validate()
        .is_ok()
    );
}

#[test]
fn configured_notifications_require_a_valid_webhook_and_sender_label() {
    let mut settings = Settings {
        webhook_url: "https://discord.com/api/webhooks/123/token".into(),
        ..Settings::default()
    };
    assert!(settings.validate().is_ok());

    settings.sender_label.clear();
    assert!(settings.validate().is_err());

    settings.sender_label = "Codex".into();
    settings.webhook_url = "invalid".into();
    assert!(settings.validate().is_err());
}
