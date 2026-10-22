use std::{
    fs,
    path::{Path, PathBuf},
};

use anyhow::{Context, Result};
use plist::{Dictionary, Value};

fn file() -> Result<PathBuf> {
    Ok(dirs::home_dir()
        .context("ホームディレクトリを取得できません。")?
        .join("Library/LaunchAgents/org.akaakuhub.codex-goal-monitor.plist"))
}

pub fn enabled() -> Result<bool> {
    Ok(file()?.exists())
}

pub fn set(path: &Path, enabled: bool) -> Result<()> {
    let file = file()?;
    if !enabled {
        if file.exists() {
            fs::remove_file(file)?;
        }
        return Ok(());
    }
    fs::create_dir_all(file.parent().context("LaunchAgentの保存先が不正です。")?)?;
    let mut args = vec![
        Value::String(super::text(&std::env::current_exe()?)?.into()),
        Value::String("--config".into()),
        Value::String(super::text(path)?.into()),
    ];
    if std::env::args_os().any(|arg| arg == "--headless")
        || std::env::var_os("SSH_CONNECTION").is_some()
    {
        args.push(Value::String("--headless".into()));
    }
    let mut agent = Dictionary::new();
    agent.insert(
        "Label".into(),
        Value::String("org.akaakuhub.codex-goal-monitor".into()),
    );
    agent.insert("ProgramArguments".into(), Value::Array(args));
    agent.insert("RunAtLoad".into(), Value::Boolean(true));
    agent.insert(
        "AssociatedBundleIdentifiers".into(),
        Value::Array(vec![Value::String(
            "org.akaakuhub.codex-goal-monitor".into(),
        )]),
    );
    if let Some(home) = std::env::var_os("CODEX_HOME") {
        let mut environment = Dictionary::new();
        environment.insert(
            "CODEX_HOME".into(),
            Value::String(super::text(Path::new(&home))?.into()),
        );
        agent.insert(
            "EnvironmentVariables".into(),
            Value::Dictionary(environment),
        );
    }
    let temporary = file.with_extension("new");
    Value::Dictionary(agent).to_file_xml(&temporary)?;
    fs::rename(temporary, file)?;
    Ok(())
}
