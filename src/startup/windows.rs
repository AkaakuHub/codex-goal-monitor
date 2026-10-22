use std::path::Path;

use anyhow::Result;
use windows_registry::CURRENT_USER;

const KEY: &str = r"Software\Microsoft\Windows\CurrentVersion\Run";
const NAME: &str = "Codex Goal Monitor";

fn missing<T>(result: windows_registry::Result<T>) -> Result<Option<T>> {
    match result {
        Ok(value) => Ok(Some(value)),
        Err(error) => {
            let error = std::io::Error::from(error);
            if error.kind() == std::io::ErrorKind::NotFound {
                Ok(None)
            } else {
                Err(error.into())
            }
        }
    }
}

pub fn enabled() -> Result<bool> {
    let Some(key) = missing(CURRENT_USER.open(KEY))? else {
        return Ok(false);
    };
    Ok(missing(key.get_string(NAME))?.is_some())
}

pub fn set(path: &Path, enabled: bool) -> Result<()> {
    if enabled {
        let executable = std::env::current_exe()?;
        let mut command = format!(
            "\"{}\" --config \"{}\"",
            super::text(&executable)?,
            super::text(path)?
        );
        if std::env::args_os().any(|arg| arg == "--headless")
            || std::env::var_os("SSH_CONNECTION").is_some()
        {
            command.push_str(" --headless");
        }
        CURRENT_USER.create(KEY)?.set_string(NAME, command)?;
    } else if let Some(key) = missing(CURRENT_USER.options().write().open(KEY))? {
        missing(key.remove_value(NAME))?;
    }
    Ok(())
}
