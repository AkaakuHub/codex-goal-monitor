mod platform;

use std::{path::PathBuf, sync::Arc};

use anyhow::Result;
use tokio::sync::watch;
use tray_icon::{
    NativeIcon, TrayIcon, TrayIconBuilder,
    menu::{CheckMenuItem, Menu, MenuEvent, MenuItem},
};

use crate::{config::Settings, monitor, startup};

pub enum Event {
    Menu(MenuEvent),
    Status(String),
}
type SendEvent = Arc<dyn Fn(Event) + Send + Sync>;

pub fn run(settings: Settings, path: PathBuf) -> Result<()> {
    platform::run(settings, path)
}

struct App {
    _tray: TrayIcon,
    status: MenuItem,
    configure: MenuItem,
    autostart: CheckMenuItem,
    quit: MenuItem,
    settings: Settings,
    path: PathBuf,
    changes: watch::Sender<Option<Settings>>,
}

impl App {
    fn new(mut settings: Settings, path: PathBuf, send: SendEvent) -> Result<Self> {
        let menu = Menu::new();
        let status = MenuItem::new("Codexの起動を待っています。", false, None);
        let configure = MenuItem::new("設定…", true, None);
        settings.autostart = startup::enabled()?;
        let autostart = CheckMenuItem::new("ログイン時に自動起動", true, settings.autostart, None);
        let quit = MenuItem::new("終了", true, None);
        menu.append_items(&[&status, &configure, &autostart, &quit])?;
        let tray = TrayIconBuilder::new()
            .with_tooltip("Codex Goal Monitor")
            .with_native_icon(NativeIcon::Info)
            .with_menu(Box::new(menu))
            .build()?;
        let configured = if settings.webhook_url.is_empty() {
            None
        } else {
            settings.validate()?;
            Some(settings.clone())
        };
        let changes = monitor::start(configured, Arc::new(move |text| send(Event::Status(text))));
        let mut app = Self {
            _tray: tray,
            status,
            configure,
            autostart,
            quit,
            settings,
            path,
            changes,
        };
        if app.settings.webhook_url.is_empty() {
            app.configure();
        }
        Ok(app)
    }

    fn event(&mut self, event: Event) -> bool {
        match event {
            Event::Status(text) => self.status.set_text(text),
            Event::Menu(event) if event.id == self.quit.id() => {
                let _ = self.changes.send(None);
                return true;
            }
            Event::Menu(event) if event.id == self.configure.id() => self.configure(),
            Event::Menu(event) if event.id == self.autostart.id() => {
                if let Err(error) =
                    startup::configure(&mut self.settings, &self.path, self.autostart.is_checked())
                {
                    self.autostart.set_checked(self.settings.autostart);
                    tinyfiledialogs::message_box_ok(
                        "自動起動を変更できません",
                        &format!("{error:#}"),
                        tinyfiledialogs::MessageBoxIcon::Error,
                    );
                }
            }
            _ => {}
        }
        false
    }

    fn configure(&mut self) {
        let Some(url) = tinyfiledialogs::password_box(
            "Codex Goal Monitor",
            "Discord Webhook URLを入力してください。\n空欄の場合は現在の値を保持します。",
        ) else {
            return;
        };
        let Some(label) = tinyfiledialogs::input_box(
            "Codex Goal Monitor",
            "送信元ラベル",
            &self.settings.sender_label,
        ) else {
            return;
        };
        let settings = Settings {
            webhook_url: if url.trim().is_empty() {
                self.settings.webhook_url.clone()
            } else {
                url.trim().into()
            },
            sender_label: label.trim().into(),
            autostart: self.settings.autostart,
        };
        match settings.save(&self.path) {
            Ok(()) => {
                self.settings = settings.clone();
                let _ = self.changes.send(Some(settings));
            }
            Err(error) => tinyfiledialogs::message_box_ok(
                "設定を保存できません",
                &error.to_string(),
                tinyfiledialogs::MessageBoxIcon::Error,
            ),
        }
    }
}
