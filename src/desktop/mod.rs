mod platform;

use std::{path::PathBuf, sync::Arc};

use anyhow::Result;
use tokio::sync::watch;
use tray_icon::{
    Icon, TrayIcon, TrayIconBuilder,
    menu::{CheckMenuItem, Menu, MenuEvent, MenuItem},
};

use crate::{config::Settings, monitor, startup};

pub enum Event {
    Menu(MenuEvent),
    Status(String),
}

type SendEvent = Arc<dyn Fn(Event) + Send + Sync>;

pub fn run(path: PathBuf) -> Result<()> {
    platform::run(path)
}

struct App {
    _tray: TrayIcon,
    status: MenuItem,
    open: MenuItem,
    reload: MenuItem,
    autostart: CheckMenuItem,
    quit: MenuItem,
    path: PathBuf,
    changes: watch::Sender<Option<Settings>>,
}

impl App {
    fn new(path: PathBuf, send: SendEvent) -> Result<Self> {
        let menu = Menu::new();
        let version = MenuItem::new(
            format!("Codex Goal Monitor {}", env!("CARGO_PKG_VERSION")),
            false,
            None,
        );
        let status = MenuItem::new("Codexの起動を待っています。", false, None);
        let open = MenuItem::new("設定ファイルを開く", true, None);
        let reload = MenuItem::new("設定を再読み込み", true, None);
        let autostart = CheckMenuItem::new("ログイン時に自動起動", true, startup::enabled()?, None);
        let quit = MenuItem::new("終了", true, None);
        menu.append_items(&[&version, &status, &open, &reload, &autostart, &quit])?;
        let icon = Icon::from_rgba(
            include_bytes!("../../assets/icons/tray.rgba").to_vec(),
            32,
            32,
        )?;
        let tray = TrayIconBuilder::new()
            .with_tooltip("Codex Goal Monitor")
            .with_menu(Box::new(menu));
        #[cfg(target_os = "windows")]
        let tray = tray.with_icon(icon);
        #[cfg(target_os = "macos")]
        let tray = tray.with_icon_templated(icon);
        let changes = monitor::start(None, Arc::new(move |text| send(Event::Status(text))));
        let app = Self {
            _tray: tray.build()?,
            status,
            open,
            reload,
            autostart,
            quit,
            path,
            changes,
        };
        app.reload();
        Ok(app)
    }

    fn event(&mut self, event: Event) -> bool {
        match event {
            Event::Status(text) => self.status.set_text(text),
            Event::Menu(event) if event.id == self.quit.id() => return true,
            Event::Menu(event) if event.id == self.reload.id() => self.reload(),
            Event::Menu(event) if event.id == self.open.id() => {
                if let Err(error) = platform::open_config(&self.path) {
                    self.status
                        .set_text(format!("設定ファイルを開けません: {error}"));
                }
            }
            Event::Menu(event) if event.id == self.autostart.id() => {
                let enabled = self.autostart.is_checked();
                let result = Settings::load(&self.path).and_then(|mut settings| {
                    startup::configure(&mut settings, &self.path, enabled)
                });
                if let Err(error) = result {
                    self.autostart.set_checked(!enabled);
                    self.status
                        .set_text(format!("自動起動を変更できません: {error}"));
                }
            }
            _ => {}
        }
        false
    }

    fn reload(&self) {
        match Settings::load(&self.path).and_then(|settings| {
            settings.validate()?;
            Ok(settings)
        }) {
            Ok(settings) => {
                self.status.set_text("Codexの起動を待っています。");
                let _ = self.changes.send(Some(settings));
            }
            Err(error) => {
                let _ = self.changes.send(None);
                self.status
                    .set_text(format!("設定ファイルを確認してください: {error}"));
            }
        }
    }
}
