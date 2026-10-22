#![cfg_attr(target_os = "windows", windows_subsystem = "windows")]

mod config;
#[cfg(not(target_os = "linux"))]
mod desktop;
mod monitor;
mod notifications;
mod startup;

use std::{fs, path::PathBuf};

use anyhow::{Context, Result, bail};

fn run() -> Result<()> {
    let mut path = config::default_path()?;
    let mut autostart = None;
    let mut args = std::env::args_os().skip(1);
    while let Some(argument) = args.next() {
        match argument.to_str() {
            Some("--headless") => {}
            Some("--autostart") => {
                autostart = Some(
                    args.next()
                        .context("--autostartにはon・off・statusを指定してください。")?,
                );
            }
            Some("--config") => {
                path = PathBuf::from(
                    args.next()
                        .context("--configに設定ファイルのパスを指定してください。")?,
                )
            }
            Some("--help" | "-h") => {
                println!(
                    "Codex Goal Monitor\n\n--headless        トレイを表示せず監視します\n--config <path>   設定JSONのパス\n--autostart <on|off|status> 自動起動を設定・確認して終了します\n--version        バージョンを表示します"
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
    let path = std::path::absolute(path)?;
    let directory = path.parent().context("設定の保存先が不正です。")?;
    let mut builder = fs::DirBuilder::new();
    builder.recursive(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::DirBuilderExt;
        builder.mode(0o700);
    }
    builder.create(directory)?;
    let mut settings = config::Settings::load(&path)?;
    if let Some(action) = autostart {
        match action.to_str() {
            Some("on") => startup::configure(&mut settings, &path, true)?,
            Some("off") => startup::configure(&mut settings, &path, false)?,
            Some("status") => println!(
                "設定: {}\nOSへの登録: {}",
                settings.autostart,
                startup::enabled()?
            ),
            _ => bail!("--autostartにはon・off・statusを指定してください。"),
        }
        return Ok(());
    }
    let lock = fs::OpenOptions::new()
        .read(true)
        .write(true)
        .create(true)
        .truncate(false)
        .open(path.with_extension("lock"))?;
    lock.try_lock()
        .context("同じ設定のCodex Goal Monitorがすでに起動しています。")?;
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
        || std::env::args_os().any(|arg| arg == "--autostart")
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
