use std::{fs, path::Path, process::Command};

use anyhow::{Context, Result, ensure};

const UNIT: &str = "codex-goal-monitor.service";

pub fn enabled() -> Result<bool> {
    let output = Command::new("systemctl")
        .args(["--user", "is-enabled", UNIT])
        .output()?;
    match std::str::from_utf8(&output.stdout)?.trim() {
        "enabled" | "enabled-runtime" => Ok(true),
        "disabled" | "not-found" => Ok(false),
        _ => anyhow::bail!(
            "自動起動の状態を取得できません。{}",
            String::from_utf8_lossy(&output.stderr)
        ),
    }
}

pub fn set(path: &Path, enabled: bool) -> Result<()> {
    if !enabled && !self::enabled()? {
        return Ok(());
    }
    if enabled {
        let directory = dirs::config_dir()
            .context("サービス定義の保存先を取得できません。")?
            .join("systemd/user");
        fs::create_dir_all(&directory)?;
        let executable = std::env::current_exe()?;
        let command = format!(
            "{} --headless --config {}",
            quote(super::text(&executable)?),
            quote(super::text(path)?)
        )
        .replace('$', "$$");
        let mut unit = include_str!("../../deploy/codex-goal-monitor.service").replace(
            "ExecStart=%h/.local/opt/codex-goal-monitor/codex-goal-monitor --headless",
            &format!("ExecStart={command}"),
        );
        if let Some(home) = std::env::var_os("CODEX_HOME") {
            unit.push_str(&format!(
                "\n[Service]\nEnvironment={}\n",
                quote(&format!("CODEX_HOME={}", super::text(Path::new(&home))?))
            ));
        }
        fs::write(directory.join(UNIT), unit)?;
        systemctl(&["daemon-reload"])?;
    }
    systemctl(&[if enabled { "enable" } else { "disable" }, UNIT])
}

fn systemctl(args: &[&str]) -> Result<()> {
    let output = Command::new("systemctl")
        .arg("--user")
        .args(args)
        .output()?;
    ensure!(
        output.status.success(),
        "systemctl: {}",
        String::from_utf8_lossy(&output.stderr)
    );
    Ok(())
}

fn quote(value: &str) -> String {
    format!(
        "\"{}\"",
        value
            .replace('\\', "\\\\")
            .replace('"', "\\\"")
            .replace('\n', "\\n")
            .replace('\r', "\\r")
            .replace('%', "%%")
    )
}
