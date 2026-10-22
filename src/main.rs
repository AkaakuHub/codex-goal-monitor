#![cfg_attr(target_os = "windows", windows_subsystem = "windows")]

mod config;
#[cfg(not(target_os = "linux"))]
mod desktop;
mod monitor;
mod notifications;

use std::{fs, path::PathBuf};

use anyhow::{Context, Result, bail};

fn run() -> Result<()> {
    let mut path = config::default_path()?;
    let mut args = std::env::args_os().skip(1);
    while let Some(argument) = args.next() {
        match argument.to_str() {
            Some("--headless") => {}
            Some("--config") => {
                path = PathBuf::from(
                    args.next()
                        .context("--configに設定ファイルのパスを指定してください。")?,
                )
            }
            Some("--help" | "-h") => {
                println!(
                    "Codex Goal Monitor\n\n--headless        トレイを表示せず監視します（Linuxサーバー・WSL用）\n--config <path>   設定JSONのパス\n--version        バージョンを表示します"
                );
                return Ok(());
            }
            Some("--version") => {
                println!("{}", env!("CARGO_PKG_VERSION"));
                return Ok(());
            }
            _ => bail!("不明な引数です。--helpを確認してください。"),
        }
    }
    let directory = path.parent().context("設定の保存先が不正です。")?;
    let mut builder = fs::DirBuilder::new();
    builder.recursive(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::DirBuilderExt;
        builder.mode(0o700);
    }
    builder.create(directory)?;
    let lock = fs::OpenOptions::new()
        .read(true)
        .write(true)
        .create(true)
        .truncate(false)
        .open(path.with_extension("lock"))?;
    lock.try_lock()
        .context("同じ設定のCodex Goal Monitorがすでに起動しています。")?;
    let settings = config::Settings::load(&path)?;
    #[cfg(not(target_os = "linux"))]
    if !without_gui() {
        return desktop::run(settings, path);
    }
    settings.validate()?;
    monitor::headless(settings)
}

#[cfg(not(target_os = "linux"))]
fn without_gui() -> bool {
    std::env::args_os().any(|arg| arg == "--headless")
        || std::env::var_os("SSH_CONNECTION").is_some()
}

fn main() -> std::process::ExitCode {
    match run() {
        Ok(()) => std::process::ExitCode::SUCCESS,
        Err(error) => {
            eprintln!("{error:#}");
            #[cfg(not(target_os = "linux"))]
            if !without_gui() {
                tinyfiledialogs::message_box_ok(
                    "Codex Goal Monitor",
                    &format!("{error:#}"),
                    tinyfiledialogs::MessageBoxIcon::Error,
                );
            }
            std::process::ExitCode::FAILURE
        }
    }
}
