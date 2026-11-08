//! Pure adapter tests: these never call Windows startup status/set or mutate HKCU.
use cafe_fin_native_checks::{
    native_lifecycle::STARTUP_ARGUMENT,
    native_startup::{self, RuntimeStatus, StartupStore, StartupValue},
};
use std::path::Path;

const EXE: &str = r"C:\Program Files\Cafe Fin\Café Fin.exe";

#[derive(Default)]
struct MockStore {
    value: Option<StartupValue>,
    reads: usize,
    writes: usize,
    fail_read_at: Option<usize>,
    write_error: bool,
    ignore_write: bool,
    concurrent_value: Option<StartupValue>,
}

impl StartupStore for MockStore {
    fn read(&mut self) -> Result<Option<StartupValue>, String> {
        self.reads += 1;
        if self.fail_read_at == Some(self.reads) {
            return Err("STARTUP_READ_FAILED".into());
        }
        Ok(self.value.clone())
    }

    fn compare_exchange(
        &mut self,
        expected: Option<&StartupValue>,
        replacement: Option<&StartupValue>,
    ) -> Result<(), String> {
        if let Some(value) = self.concurrent_value.take() {
            self.value = Some(value);
        }
        if self.value.as_ref() != expected {
            return Err("STARTUP_CONFLICT".into());
        }
        if self.write_error {
            return Err("STARTUP_WRITE_FAILED".into());
        }
        self.writes += 1;
        if !self.ignore_write {
            self.value = replacement.cloned();
        }
        Ok(())
    }
}

fn command() -> String {
    native_startup::startup_command(Path::new(EXE)).unwrap()
}

fn enabled() -> RuntimeStatus {
    RuntimeStatus {
        startup_enabled: true,
        startup_supported: true,
    }
}

#[test]
fn missing_is_default_off_and_status_does_not_mutate_or_repair() {
    let mut store = MockStore::default();
    assert_eq!(
        native_startup::status_with(&mut store, Path::new(EXE)).unwrap(),
        RuntimeStatus {
            startup_enabled: false,
            startup_supported: true
        }
    );
    assert_eq!(store.writes, 0);
    assert!(store.value.is_none());
    native_startup::set_enabled_with(&mut store, Path::new(EXE), false).unwrap();
    assert_eq!(store.writes, 0);
}

#[test]
fn explicit_enable_disable_are_idempotent_and_relaunch_only_reads_saved_value() {
    let mut store = MockStore::default();
    assert_eq!(
        native_startup::set_enabled_with(&mut store, Path::new(EXE), true).unwrap(),
        enabled()
    );
    assert_eq!(store.value, Some(StartupValue::command(&command())));
    assert_eq!(store.writes, 1);
    native_startup::set_enabled_with(&mut store, Path::new(EXE), true).unwrap();
    assert_eq!(store.writes, 1);
    let mut relaunched = MockStore {
        value: store.value.clone(),
        ..MockStore::default()
    };
    assert_eq!(
        native_startup::status_with(&mut relaunched, Path::new(EXE)).unwrap(),
        enabled()
    );
    assert_eq!(relaunched.writes, 0);
    let result = native_startup::set_enabled_with(&mut relaunched, Path::new(EXE), false).unwrap();
    assert!(!result.startup_enabled);
    assert_eq!(relaunched.writes, 1);
    assert!(relaunched.value.is_none());
    native_startup::set_enabled_with(&mut relaunched, Path::new(EXE), false).unwrap();
    assert_eq!(relaunched.writes, 1);
}

#[test]
fn foreign_type_malformed_encoding_or_command_is_conflict_never_overwritten_or_deleted() {
    let exact = StartupValue::command(&command());
    let mut cases = vec![
        StartupValue {
            value_type: 2,
            bytes: exact.bytes.clone(),
        },
        StartupValue {
            value_type: 4,
            bytes: vec![1, 0, 0, 0],
        },
        StartupValue {
            value_type: 1,
            bytes: vec![0, 0xD8, 0, 0],
        },
        StartupValue {
            value_type: 1,
            bytes: vec![0x41],
        },
        StartupValue::command(r#""C:\Other\CafeFin.exe" --startup-v1"#),
        StartupValue::command(&format!("\"{EXE}\" --startup-v0")),
        StartupValue::command(&format!("\"{EXE}\" --startup-v2")),
        StartupValue::command(&format!("\"{EXE}\" --startup-v1 --extra")),
        StartupValue::command(&format!("{EXE} --startup-v1")),
    ];
    let mut no_terminator = exact.clone();
    no_terminator.bytes.truncate(no_terminator.bytes.len() - 2);
    cases.push(no_terminator);
    let mut extra_terminator = exact;
    extra_terminator.bytes.extend([0, 0]);
    cases.push(extra_terminator);
    for value in cases {
        let mut store = MockStore {
            value: Some(value.clone()),
            ..MockStore::default()
        };
        assert_eq!(
            native_startup::status_with(&mut store, Path::new(EXE)).unwrap_err(),
            "STARTUP_CONFLICT"
        );
        for setting in [true, false] {
            assert_eq!(
                native_startup::set_enabled_with(&mut store, Path::new(EXE), setting).unwrap_err(),
                "STARTUP_CONFLICT"
            );
            assert_eq!(store.value.as_ref(), Some(&value));
            assert_eq!(store.writes, 0);
        }
    }
}

#[test]
fn command_is_quoted_fixed_version_and_unicode_is_counted_as_utf16() {
    assert_eq!(STARTUP_ARGUMENT, "--startup-v1");
    assert_eq!(command(), format!("\"{EXE}\" --startup-v1"));
    let overhead = native_startup::startup_command(Path::new(r"C:\a.exe"))
        .unwrap()
        .encode_utf16()
        .count();
    let padding = 260 - overhead;
    let boundary = format!(r"C:\{}a.exe", "a".repeat(padding));
    assert_eq!(
        native_startup::startup_command(Path::new(&boundary))
            .unwrap()
            .encode_utf16()
            .count(),
        260
    );
    let too_long = format!(r"C:\{}a.exe", "a".repeat(padding + 1));
    assert_eq!(
        native_startup::startup_command(Path::new(&too_long)).unwrap_err(),
        "STARTUP_COMMAND_TOO_LONG"
    );
    let unicode_too_long = format!(r"C:\{}a.exe", "😀".repeat(padding / 2 + 1));
    assert_eq!(
        native_startup::startup_command(Path::new(&unicode_too_long)).unwrap_err(),
        "STARTUP_COMMAND_TOO_LONG"
    );
}

#[test]
fn invalid_paths_are_rejected_before_registry_read_or_write() {
    for invalid in [
        r"CafeFin.exe",
        r"C:CafeFin.exe",
        r"\CafeFin.exe",
        r"\\server\share\CafeFin.exe",
        r"C:\folder\..\CafeFin.exe",
        r"C:\folder\.\CafeFin.exe",
        r"C:\CafeFin.exe:stream",
        r"C:\CafeFin.cmd",
        r"C:\folder.\CafeFin.exe",
        r"C:\folder \CafeFin.exe",
        "C:\\bad\"name.exe",
        "C:\\bad\0name.exe",
        "C:\\bad\nname.exe",
        "C:\\bad\rname.exe",
        "C:\\bad\tname.exe",
    ] {
        let mut store = MockStore::default();
        assert_eq!(
            native_startup::set_enabled_with(&mut store, Path::new(invalid), true).unwrap_err(),
            "STARTUP_PATH_INVALID"
        );
        assert_eq!((store.reads, store.writes), (0, 0));
    }
}

#[test]
fn read_write_and_readback_errors_are_not_reported_as_success() {
    let mut read_failure = MockStore {
        fail_read_at: Some(1),
        ..MockStore::default()
    };
    assert_eq!(
        native_startup::set_enabled_with(&mut read_failure, Path::new(EXE), true).unwrap_err(),
        "STARTUP_READ_FAILED"
    );
    assert_eq!(read_failure.writes, 0);
    let mut write_failure = MockStore {
        write_error: true,
        ..MockStore::default()
    };
    assert_eq!(
        native_startup::set_enabled_with(&mut write_failure, Path::new(EXE), true).unwrap_err(),
        "STARTUP_WRITE_FAILED"
    );
    assert!(write_failure.value.is_none());
    let mut readback_failure = MockStore {
        fail_read_at: Some(2),
        ..MockStore::default()
    };
    assert_eq!(
        native_startup::set_enabled_with(&mut readback_failure, Path::new(EXE), true).unwrap_err(),
        "STARTUP_READ_FAILED"
    );
    let mut not_applied = MockStore {
        ignore_write: true,
        ..MockStore::default()
    };
    assert_eq!(
        native_startup::set_enabled_with(&mut not_applied, Path::new(EXE), true).unwrap_err(),
        "STARTUP_READBACK_FAILED"
    );
}

#[test]
fn concurrent_foreign_value_is_not_overwritten() {
    let foreign = StartupValue::command(r#""C:\Another\CafeFin.exe" --startup-v1"#);
    for enabled in [true, false] {
        let mut store = MockStore {
            value: (!enabled).then(|| StartupValue::command(&command())),
            concurrent_value: Some(foreign.clone()),
            ..MockStore::default()
        };
        assert_eq!(
            native_startup::set_enabled_with(&mut store, Path::new(EXE), enabled).unwrap_err(),
            "STARTUP_CONFLICT"
        );
        assert_eq!(store.value, Some(foreign.clone()));
        assert_eq!(store.writes, 0);
    }
}

#[test]
fn runtime_status_has_only_the_declared_renderer_fields() {
    assert_eq!(
        serde_json::to_value(enabled()).unwrap(),
        serde_json::json!({"startup_enabled":true,"startup_supported":true})
    );
}

#[cfg(not(windows))]
#[test]
fn unsupported_platform_does_not_pretend_to_enable_startup() {
    assert_eq!(
        native_startup::status().unwrap(),
        RuntimeStatus {
            startup_enabled: false,
            startup_supported: false
        }
    );
    assert_eq!(
        native_startup::set_enabled(true).unwrap_err(),
        "STARTUP_UNAVAILABLE"
    );
}
