mod client;
mod policy;
mod session;

use std::sync::Arc;

use anyhow::{Context, Result};
use notify::{RecursiveMode, Watcher};
use tokio::sync::{mpsc, watch};

use crate::{
    config::{Settings, socket_path},
    notifications,
};

pub type Status = Arc<dyn Fn(String) + Send + Sync>;

pub fn headless(settings: Settings) -> Result<()> {
    let (_sender, receiver) = watch::channel(Some(settings));
    tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()?
        .block_on(run(receiver, Arc::new(|text| eprintln!("{text}"))))
}

#[cfg(not(target_os = "linux"))]
pub fn start(settings: Option<Settings>, status: Status) -> watch::Sender<Option<Settings>> {
    let (sender, receiver) = watch::channel(settings);
    std::thread::spawn(move || {
        let result = tokio::runtime::Builder::new_current_thread()
            .enable_all()
            .build()
            .map_err(anyhow::Error::from)
            .and_then(|runtime| runtime.block_on(run(receiver, status.clone())));
        if let Err(error) = result {
            status(error.to_string());
        }
    });
    sender
}

async fn run(mut settings: watch::Receiver<Option<Settings>>, status: Status) -> Result<()> {
    let path = socket_path()?;
    let (events, mut changes) = mpsc::channel(1);
    let mut watcher = notify::recommended_watcher(move |event: notify::Result<notify::Event>| {
        if event.is_ok() {
            let _ = events.try_send(());
        }
    })?;
    let notifications = notifications::start(status.clone());
    loop {
        let mut directory = path
            .parent()
            .context("Codexの接続先が不正です。")?
            .to_path_buf();
        while !directory.is_dir() {
            if !directory.pop() {
                break;
            }
        }
        let mut directories = vec![directory];
        if let Ok(resolved) = path.canonicalize()
            && let Some(parent) = resolved.parent()
            && !directories.iter().any(|directory| directory == parent)
        {
            directories.push(parent.to_path_buf());
        }
        for directory in &directories {
            watcher.watch(directory, RecursiveMode::NonRecursive)?;
        }
        let configured = settings.borrow_and_update().clone();
        if let Some(configured) = configured {
            if path.exists() {
                match client::Client::connect(&path).await {
                    Ok(client) => {
                        status("監視中です。".into());
                        let mut session =
                            session::Session::new(client, configured, notifications.clone());
                        tokio::select! {
                            result = session.run() => {
                                if result.is_err() { status("Codexとの接続が切れました。".into()); }
                            }
                            changed = settings.changed() => {
                                if changed.is_err() { return Ok(()); }
                                for directory in &directories { watcher.unwatch(directory)?; }
                                continue;
                            }
                        }
                    }
                    Err(_) => status(
                        "Codexに接続できません。CLIのバージョンと起動状態を確認してください。"
                            .into(),
                    ),
                }
            } else {
                status("Codexの起動を待っています。".into());
            }
        } else {
            status("設定からDiscord Webhook URLを入力してください。".into());
        }
        tokio::select! {
            changed = settings.changed() => { if changed.is_err() { break; } }
            event = changes.recv() => { if event.is_none() { break; } }
        }
        for directory in &directories {
            watcher.unwatch(directory)?;
        }
    }
    Ok(())
}
