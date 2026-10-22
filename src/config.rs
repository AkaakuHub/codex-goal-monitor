#[cfg(not(target_os = "linux"))]
use std::io::Write;
use std::{
    fs,
    path::{Path, PathBuf},
};

use anyhow::{Context, Result, ensure};
use serde::{Deserialize, Serialize};

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct Settings {
    pub webhook_url: String,
    pub sender_label: String,
}

impl Default for Settings {
    fn default() -> Self {
        Self {
            webhook_url: String::new(),
            sender_label: "Codex".into(),
        }
    }
}

impl Settings {
    pub fn validate(&self) -> Result<()> {
        let path = self
            .webhook_url
            .strip_prefix("https://discord.com/api/webhooks/")
            .or_else(|| {
                self.webhook_url
                    .strip_prefix("https://discordapp.com/api/webhooks/")
            });
        let valid = path
            .and_then(|p| p.split_once('/'))
            .is_some_and(|(id, token)| {
                !id.is_empty()
                    && id.bytes().all(|c| c.is_ascii_digit())
                    && !token.is_empty()
                    && token
                        .bytes()
                        .all(|c| c.is_ascii_alphanumeric() || c == b'_' || c == b'-')
            });
        ensure!(valid, "Discord Webhook URLを正しく入力してください。");
        ensure!(
            !self.sender_label.trim().is_empty() && self.sender_label.chars().count() <= 80,
            "送信元ラベルは1〜80文字で入力してください。"
        );
        Ok(())
    }

    pub fn load(path: &Path) -> Result<Self> {
        match fs::read(path) {
            Ok(data) => serde_json::from_slice(&data).context("設定ファイルを読み込めません。"),
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(Self::default()),
            Err(error) => Err(error).context("設定ファイルを読み込めません。"),
        }
    }

    #[cfg(not(target_os = "linux"))]
    pub fn save(&self, path: &Path) -> Result<()> {
        self.validate()?;
        if path.exists() && Self::load(path)? == *self {
            return Ok(());
        }
        let temporary = path.with_extension("new");
        let mut options = fs::OpenOptions::new();
        options.write(true).create(true).truncate(true);
        #[cfg(unix)]
        {
            use std::os::unix::fs::OpenOptionsExt;
            options.mode(0o600);
        }
        options
            .open(&temporary)?
            .write_all(&serde_json::to_vec_pretty(self)?)?;
        fs::rename(temporary, path).context("設定を保存できません。")
    }
}

pub fn default_path() -> Result<PathBuf> {
    Ok(dirs::config_dir()
        .context("設定の保存先を取得できません。")?
        .join("codex-goal-monitor/settings.json"))
}

pub fn socket_path() -> Result<PathBuf> {
    let home = match std::env::var_os("CODEX_HOME") {
        Some(path) => PathBuf::from(path),
        None => dirs::home_dir()
            .context("ホームディレクトリを取得できません。")?
            .join(".codex"),
    };
    Ok(home.join("app-server-control/app-server-control.sock"))
}
