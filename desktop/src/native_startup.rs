//! Current-user startup is opt-in. Reading status never repairs or creates a value.
//! Renderer commands expose only status()/set_enabled(bool), never the test seams.
use crate::native_lifecycle::STARTUP_ARGUMENT;
use serde::Serialize;
use std::path::Path;

pub const STARTUP_VALUE_NAME: &str = "CafeFin";
pub const MAX_RUN_COMMAND_UTF16: usize = 260;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct RuntimeStatus {
    pub startup_enabled: bool,
    pub startup_supported: bool,
}

/// Raw type/bytes are compared exactly: REG_EXPAND_SZ, malformed UTF16,
/// embedded/trailing NULs and alternate arguments are never treated as owned.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct StartupValue {
    pub value_type: u32,
    pub bytes: Vec<u8>,
}

impl StartupValue {
    pub fn command(command: &str) -> Self {
        Self {
            value_type: 1, // REG_SZ, not REG_EXPAND_SZ.
            bytes: command
                .encode_utf16()
                .chain(std::iter::once(0))
                .flat_map(u16::to_le_bytes)
                .collect(),
        }
    }
}

/// Adapters must compare and replace atomically; a changed/unowned value is a
/// conflict. The production adapter uses a Windows registry transaction.
pub trait StartupStore {
    fn read(&mut self) -> Result<Option<StartupValue>, String>;
    fn compare_exchange(
        &mut self,
        expected: Option<&StartupValue>,
        replacement: Option<&StartupValue>,
    ) -> Result<(), String>;
}

/// Pure Windows command validation for native callers/tests. The OS wrappers
/// additionally verify the current executable exists on a local, non-reparse path.
pub fn startup_command(executable: &Path) -> Result<String, String> {
    let text = executable.to_str().ok_or("STARTUP_PATH_INVALID")?;
    if text.chars().any(|ch| ch.is_control() || ch == '"') {
        return Err("STARTUP_PATH_INVALID".into());
    }
    let local = text.strip_prefix(r"\\?\").unwrap_or(text);
    let bytes = local.as_bytes();
    if bytes.len() < 4
        || !bytes[0].is_ascii_alphabetic()
        || bytes[1] != b':'
        || !matches!(bytes[2], b'\\' | b'/')
        || local[2..].contains([':', '<', '>', '|', '?', '*'])
    {
        return Err("STARTUP_PATH_INVALID".into());
    }
    let components: Vec<&str> = local[3..].split(['\\', '/']).collect();
    if components
        .iter()
        .any(|part| part.is_empty() || *part == "." || *part == ".." || part.ends_with([' ', '.']))
    {
        return Err("STARTUP_PATH_INVALID".into());
    }
    let file = components.last().ok_or("STARTUP_PATH_INVALID")?;
    if file.len() <= 4 || !file.to_ascii_lowercase().ends_with(".exe") {
        return Err("STARTUP_PATH_INVALID".into());
    }
    let command = format!("\"{text}\" {STARTUP_ARGUMENT}");
    if command.encode_utf16().count() > MAX_RUN_COMMAND_UTF16 {
        return Err("STARTUP_COMMAND_TOO_LONG".into());
    }
    Ok(command)
}

fn configured(value: Option<&StartupValue>, owned: &StartupValue) -> Result<bool, String> {
    match value {
        None => Ok(false),
        Some(value) if value == owned => Ok(true),
        Some(_) => Err("STARTUP_CONFLICT".into()),
    }
}

fn public_error(error: String) -> String {
    match error.as_str() {
        "STARTUP_CONFLICT" => "STARTUP_CONFLICT",
        "STARTUP_PATH_INVALID" | "STARTUP_COMMAND_TOO_LONG" => "STARTUP_COMMAND_INVALID",
        _ => "STARTUP_UNAVAILABLE",
    }
    .into()
}

pub fn status_with(
    store: &mut impl StartupStore,
    executable: &Path,
) -> Result<RuntimeStatus, String> {
    let owned = StartupValue::command(&startup_command(executable)?);
    let value = store.read()?;
    Ok(RuntimeStatus {
        startup_enabled: configured(value.as_ref(), &owned)?,
        startup_supported: true,
    })
}

pub fn set_enabled_with(
    store: &mut impl StartupStore,
    executable: &Path,
    enabled: bool,
) -> Result<RuntimeStatus, String> {
    let owned = StartupValue::command(&startup_command(executable)?);
    let before = store.read()?;
    let current = configured(before.as_ref(), &owned)?;
    if current == enabled {
        return Ok(RuntimeStatus {
            startup_enabled: current,
            startup_supported: true,
        });
    }
    store.compare_exchange(before.as_ref(), enabled.then_some(&owned))?;
    let after = store.read()?;
    let actual = configured(after.as_ref(), &owned)?;
    if actual != enabled {
        return Err("STARTUP_READBACK_FAILED".into());
    }
    Ok(RuntimeStatus {
        startup_enabled: actual,
        startup_supported: true,
    })
}

#[cfg(windows)]
mod windows {
    use super::*;
    use std::{borrow::Cow, io, path::PathBuf, sync::Mutex};
    use winreg::{
        enums::{HKEY_CURRENT_USER, KEY_CREATE_SUB_KEY, KEY_QUERY_VALUE, KEY_SET_VALUE, REG_SZ},
        transaction::Transaction,
        RegKey, RegValue,
    };

    const RUN_PARENT: &str = r"Software\Microsoft\Windows\CurrentVersion";
    const RUN_KEY: &str = r"Software\Microsoft\Windows\CurrentVersion\Run";
    static STARTUP_LOCK: Mutex<()> = Mutex::new(());

    fn read_value(key: &RegKey) -> Result<Option<StartupValue>, String> {
        match key.get_raw_value(STARTUP_VALUE_NAME) {
            Ok(raw) => Ok(Some(StartupValue {
                value_type: raw.vtype as u32,
                bytes: raw.bytes.into_owned(),
            })),
            Err(error) if error.kind() == io::ErrorKind::NotFound => Ok(None),
            Err(_) => Err("STARTUP_READ_FAILED".into()),
        }
    }

    fn write_error(error: io::Error) -> String {
        // ERROR_TRANSACTIONAL_CONFLICT: an external writer changed this key.
        if error.raw_os_error() == Some(6800) {
            "STARTUP_CONFLICT".into()
        } else {
            "STARTUP_WRITE_FAILED".into()
        }
    }

    struct CurrentUserRun;

    impl StartupStore for CurrentUserRun {
        fn read(&mut self) -> Result<Option<StartupValue>, String> {
            match RegKey::predef(HKEY_CURRENT_USER).open_subkey_with_flags(RUN_KEY, KEY_QUERY_VALUE)
            {
                Ok(key) => read_value(&key),
                Err(error) if error.kind() == io::ErrorKind::NotFound => Ok(None),
                Err(_) => Err("STARTUP_READ_FAILED".into()),
            }
        }

        fn compare_exchange(
            &mut self,
            expected: Option<&StartupValue>,
            replacement: Option<&StartupValue>,
        ) -> Result<(), String> {
            let transaction = Transaction::new().map_err(write_error)?;
            let hkcu = RegKey::predef(HKEY_CURRENT_USER);
            let key = match hkcu.open_subkey_transacted_with_flags(
                RUN_KEY,
                &transaction,
                KEY_QUERY_VALUE | KEY_SET_VALUE,
            ) {
                Ok(key) => key,
                Err(error) if error.kind() == io::ErrorKind::NotFound => {
                    if expected.is_some() {
                        return Err("STARTUP_CONFLICT".into());
                    }
                    if replacement.is_none() {
                        return Ok(());
                    }
                    // Create only Run, under an existing fixed Windows parent. Never
                    // recreate other registry paths, policies, tasks or services.
                    let parent = hkcu
                        .open_subkey_with_flags(RUN_PARENT, KEY_CREATE_SUB_KEY)
                        .map_err(write_error)?;
                    parent
                        .create_subkey_transacted_with_flags(
                            "Run",
                            &transaction,
                            KEY_QUERY_VALUE | KEY_SET_VALUE,
                        )
                        .map_err(write_error)?
                        .0
                }
                Err(error) => return Err(write_error(error)),
            };
            if read_value(&key)?.as_ref() != expected {
                return Err("STARTUP_CONFLICT".into());
            }
            match replacement {
                Some(value) => {
                    if value.value_type != 1 {
                        return Err("STARTUP_CONFLICT".into());
                    }
                    key.set_raw_value(
                        STARTUP_VALUE_NAME,
                        &RegValue {
                            bytes: Cow::Borrowed(&value.bytes),
                            vtype: REG_SZ,
                        },
                    )
                    .map_err(write_error)?;
                }
                None => key.delete_value(STARTUP_VALUE_NAME).map_err(write_error)?,
            }
            drop(key);
            transaction.commit().map_err(write_error)
        }
    }

    fn current_executable() -> Result<PathBuf, String> {
        let path = std::env::current_exe().map_err(|_| "STARTUP_PATH_INVALID")?;
        startup_command(&path)?;
        crate::native_paths::check_local_path(&path).map_err(|_| "STARTUP_PATH_INVALID")?;
        if !path.is_file() {
            return Err("STARTUP_PATH_INVALID".into());
        }
        Ok(path)
    }

    pub(super) fn status() -> Result<RuntimeStatus, String> {
        let _guard = STARTUP_LOCK.lock().map_err(|_| "STARTUP_STATE_FAILED")?;
        status_with(&mut CurrentUserRun, &current_executable()?)
    }

    pub(super) fn set_enabled(enabled: bool) -> Result<RuntimeStatus, String> {
        let _guard = STARTUP_LOCK.lock().map_err(|_| "STARTUP_STATE_FAILED")?;
        set_enabled_with(&mut CurrentUserRun, &current_executable()?, enabled)
    }
}

pub fn status() -> Result<RuntimeStatus, String> {
    #[cfg(windows)]
    {
        windows::status().map_err(public_error)
    }
    #[cfg(not(windows))]
    {
        Ok(RuntimeStatus {
            startup_enabled: false,
            startup_supported: false,
        })
    }
}

/// The only production mutation entrypoint; invoke after an explicit UI choice.
pub fn set_enabled(enabled: bool) -> Result<RuntimeStatus, String> {
    #[cfg(windows)]
    {
        windows::set_enabled(enabled).map_err(public_error)
    }
    #[cfg(not(windows))]
    {
        let _ = enabled;
        Err(public_error("STARTUP_UNSUPPORTED".into()))
    }
}

#[cfg(test)]
mod tests {
    use super::public_error;

    #[test]
    fn only_safe_stable_errors_reach_the_renderer() {
        for code in ["STARTUP_PATH_INVALID", "STARTUP_COMMAND_TOO_LONG"] {
            assert_eq!(public_error(code.into()), "STARTUP_COMMAND_INVALID");
        }
        assert_eq!(public_error("STARTUP_CONFLICT".into()), "STARTUP_CONFLICT");
        for code in [
            "STARTUP_READ_FAILED",
            "STARTUP_WRITE_FAILED",
            "STARTUP_READBACK_FAILED",
            "STARTUP_STATE_FAILED",
            "STARTUP_UNSUPPORTED",
        ] {
            assert_eq!(public_error(code.into()), "STARTUP_UNAVAILABLE");
        }
    }
}
