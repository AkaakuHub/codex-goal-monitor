#[cfg(target_os = "linux")]
mod linux;
#[cfg(target_os = "macos")]
mod macos;
#[cfg(target_os = "windows")]
mod windows;

#[cfg(target_os = "linux")]
use linux as platform;
#[cfg(target_os = "macos")]
use macos as platform;
#[cfg(target_os = "windows")]
use windows as platform;

use std::path::Path;

use anyhow::{Context, Result};

use crate::config::Settings;

pub use platform::enabled;

pub fn configure(settings: &mut Settings, path: &Path, enabled: bool) -> Result<()> {
    let mut updated = settings.clone();
    updated.autostart = enabled;
    let previous = platform::enabled()?;
    platform::set(path, enabled).context("自動起動の登録を変更できません。")?;
    if let Err(error) = updated.save(path) {
        platform::set(path, previous)
            .context("設定保存に失敗し、自動起動の登録も元に戻せませんでした。")?;
        return Err(error);
    }
    *settings = updated;
    Ok(())
}

fn text(path: &Path) -> Result<&str> {
    path.to_str().context("パスをUnicodeとして読み取れません。")
}
