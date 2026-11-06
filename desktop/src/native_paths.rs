//! Native paths are selected by the OS dialog, never accepted from renderer input.
use std::{
    fs, io,
    path::{Component, Path, PathBuf},
};

pub fn valid_uuid(value: &str) -> bool {
    value.len() == 36
        && value.bytes().enumerate().all(|(index, byte)| {
            if [8, 13, 18, 23].contains(&index) {
                byte == b'-'
            } else {
                byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte)
            }
        })
}

pub fn valid_digest(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
}

/// Validate without dereferencing a link, including all existing ancestors.
/// Recheck immediately before each filesystem/OS operation; dialog selection
/// does not prove that the directory has remained unchanged afterwards.
pub fn check_local_path(path: &Path) -> Result<(), &'static str> {
    let text = path.to_str().ok_or("NATIVE_PATH_INVALID")?;
    if !path.is_absolute()
        || text.contains('\0')
        || text.encode_utf16().count() > 32_767
        || text.len() > 98_304
    {
        return Err("NATIVE_PATH_INVALID");
    }
    #[cfg(windows)]
    {
        use std::path::Prefix;
        let drive = match path.components().next() {
            Some(Component::Prefix(prefix)) => match prefix.kind() {
                Prefix::Disk(drive) | Prefix::VerbatimDisk(drive) => drive,
                _ => return Err("NATIVE_PATH_NOT_LOCAL"),
            },
            _ => return Err("NATIVE_PATH_NOT_LOCAL"),
        };
        let root = [drive as u16, b':' as u16, b'\\' as u16, 0];
        #[link(name = "kernel32")]
        extern "system" {
            fn GetDriveTypeW(root: *const u16) -> u32;
        }
        // Fixed, removable and RAM disks are local; network/missing/unknown fail.
        if !matches!(unsafe { GetDriveTypeW(root.as_ptr()) }, 2 | 3 | 6) {
            return Err("NATIVE_PATH_NOT_LOCAL");
        }
    }
    for component in path.components() {
        if matches!(component, Component::ParentDir | Component::CurDir) {
            return Err("NATIVE_PATH_INVALID");
        }
        #[cfg(windows)]
        if let Component::Normal(name) = component {
            let name = name.to_str().ok_or("NATIVE_PATH_INVALID")?;
            if name.contains(':') || name.ends_with([' ', '.']) {
                return Err("NATIVE_PATH_INVALID");
            }
        }
    }
    for ancestor in path.ancestors() {
        match fs::symlink_metadata(ancestor) {
            Ok(metadata) => {
                #[cfg(windows)]
                {
                    use std::os::windows::fs::MetadataExt;
                    if metadata.file_attributes() & 0x400 != 0 {
                        return Err("NATIVE_REPARSE_REFUSED");
                    }
                }
                if metadata.file_type().is_symlink() {
                    return Err("NATIVE_REPARSE_REFUSED");
                }
            }
            Err(error) if error.kind() == io::ErrorKind::NotFound => {}
            Err(_) => return Err("NATIVE_PATH_UNAVAILABLE"),
        }
    }
    Ok(())
}

pub fn derive_destination(
    parent: &Path,
    operation_id: &str,
    backup: bool,
) -> Result<PathBuf, &'static str> {
    if !valid_uuid(operation_id) {
        return Err("OPERATION_ID_INVALID");
    }
    check_local_path(parent)?;
    if !parent.is_dir() {
        return Err("NATIVE_PARENT_UNAVAILABLE");
    }
    let parent = parent
        .canonicalize()
        .map_err(|_| "NATIVE_PARENT_UNAVAILABLE")?;
    let prefix = if backup {
        "CafeFinBackup-"
    } else {
        "CafeFinData-"
    };
    let destination = parent.join(format!("{prefix}{operation_id}"));
    check_local_path(&destination)?;
    // Existing destinations are reconciled by core only AFTER immutable intent;
    // selecting a new operation must not adopt an unrelated directory.
    if destination
        .try_exists()
        .map_err(|_| "NATIVE_PATH_UNAVAILABLE")?
    {
        return Err("DESTINATION_EXISTS");
    }
    Ok(destination)
}

pub fn reports_directory(root: &Path) -> Result<PathBuf, &'static str> {
    check_local_path(root)?;
    let canonical_root = root.canonicalize().map_err(|_| "REPORTS_UNAVAILABLE")?;
    let reports = canonical_root.join("reports");
    check_local_path(&reports)?;
    if !reports.is_dir() {
        return Err("REPORTS_UNAVAILABLE");
    }
    let reports = reports.canonicalize().map_err(|_| "REPORTS_UNAVAILABLE")?;
    if reports.parent() != Some(canonical_root.as_path()) {
        return Err("NATIVE_REPARSE_REFUSED");
    }
    Ok(reports)
}

/// Call only after current reporting.read authorization and generation recheck.
/// No shell command or generic renderer-supplied path is accepted.
#[cfg(windows)]
pub fn open_reports(root: &Path) -> Result<(), &'static str> {
    use std::{ffi::c_void, os::windows::ffi::OsStrExt};
    #[link(name = "shell32")]
    extern "system" {
        fn ShellExecuteW(
            window: *mut c_void,
            verb: *const u16,
            file: *const u16,
            parameters: *const u16,
            directory: *const u16,
            show: i32,
        ) -> isize;
    }
    #[link(name = "ole32")]
    extern "system" {
        fn CoInitializeEx(reserved: *mut c_void, flags: u32) -> i32;
        fn CoUninitialize();
    }
    let reports = reports_directory(root)?;
    let file: Vec<u16> = reports.as_os_str().encode_wide().chain(Some(0)).collect();
    let verb: Vec<u16> = "open\0".encode_utf16().collect();
    // Shell extensions may require STA. Balance both S_OK and S_FALSE; a thread
    // already initialized in an incompatible apartment fails closed.
    let initialized = unsafe { CoInitializeEx(std::ptr::null_mut(), 0x2 | 0x4) };
    if !matches!(initialized, 0 | 1) {
        return Err("REPORTS_OPEN_FAILED");
    }
    let result = unsafe {
        ShellExecuteW(
            std::ptr::null_mut(),
            verb.as_ptr(),
            file.as_ptr(),
            std::ptr::null(),
            std::ptr::null(),
            1,
        )
    };
    unsafe {
        CoUninitialize();
    }
    if result <= 32 {
        Err("REPORTS_OPEN_FAILED")
    } else {
        Ok(())
    }
}
