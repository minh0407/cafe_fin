//! Private native journal, never a renderer DTO and never permission evidence.
//! File flush + replacement/readback is not a hardware power-loss guarantee.
use crate::{
    maintenance_dto::{MaintenanceKind, MaintenancePhase, PendingTransition},
    native_guards::{CloseProof, TransitionPhase},
    native_paths::{check_local_path, valid_digest, valid_uuid},
};
use serde::{Deserialize, Serialize};
use std::{
    fs::{self, OpenOptions},
    io::{Read, Write},
    path::{Path, PathBuf},
    sync::atomic::{AtomicU64, Ordering},
};

const JOURNAL_LIMIT: usize = 393_216;
static TEMP_SEQUENCE: AtomicU64 = AtomicU64::new(0);

// No Debug: journal contains private physical paths, not diagnostics.
#[derive(Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct NativeJournal {
    pub format: u32,
    pub operation_id: String,
    pub kind: MaintenanceKind,
    pub origin_generation: String,
    pub source_root: PathBuf,
    pub destination: PathBuf,
    pub backup_source: Option<PathBuf>,
    pub source_root_id: String,
    pub source_fingerprint: String,
    pub candidate_root_id: Option<String>,
    pub candidate_fingerprint: Option<String>,
    pub manifest_sha256: Option<String>,
    pub phase: MaintenancePhase,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum StartupDisposition {
    // Backup never switches roots or stops normal admission. Resolve its binding
    // against config before normal source boot, then reconcile receipt after login.
    OnlineBackupSource,
    SourceDormant,
    ReconcileConfig,
    CandidateDormant,
}

impl NativeJournal {
    pub fn validate(&self) -> Result<(), &'static str> {
        if self.format != 1
            || !valid_uuid(&self.operation_id)
            || !valid_uuid(&self.origin_generation)
            || !valid_uuid(&self.source_root_id)
            || !opaque_fingerprint(&self.source_fingerprint)
        {
            return Err("JOURNAL_INVALID");
        }
        if self.backup_source.is_some() != (self.kind == MaintenanceKind::Restore)
            || self.phase == MaintenancePhase::Selecting
        {
            return Err("JOURNAL_INVALID");
        }
        for path in [
            Some(&self.source_root),
            Some(&self.destination),
            self.backup_source.as_ref(),
        ]
        .into_iter()
        .flatten()
        {
            check_local_path(path)?;
        }
        if self.destination.starts_with(&self.source_root)
            || self.source_root.starts_with(&self.destination)
            || self.backup_source.as_ref().is_some_and(|source| {
                self.destination.starts_with(source) || source.starts_with(&self.destination)
            })
        {
            return Err("JOURNAL_PATH_CONFLICT");
        }
        let expected = if self.kind == MaintenanceKind::Backup {
            "CafeFinBackup-"
        } else {
            "CafeFinData-"
        };
        if self.destination.file_name().and_then(|name| name.to_str())
            != Some(format!("{expected}{}", self.operation_id).as_str())
        {
            return Err("JOURNAL_DESTINATION_INVALID");
        }
        if self
            .candidate_root_id
            .as_ref()
            .is_some_and(|id| !valid_uuid(id))
            || self
                .candidate_fingerprint
                .as_ref()
                .is_some_and(|value| !opaque_fingerprint(value))
            || self
                .manifest_sha256
                .as_ref()
                .is_some_and(|value| !valid_digest(value))
        {
            return Err("JOURNAL_INVALID");
        }
        let prepared = !matches!(
            self.phase,
            MaintenancePhase::Intent | MaintenancePhase::Quiesced
        );
        if prepared
            && (self.manifest_sha256.is_none()
                || (self.kind != MaintenanceKind::Backup
                    && (self.candidate_root_id.is_none() || self.candidate_fingerprint.is_none())))
        {
            return Err("JOURNAL_RECEIPT_REQUIRED");
        }
        if self.kind == MaintenanceKind::Backup
            && !matches!(
                self.phase,
                MaintenancePhase::Intent | MaintenancePhase::Prepared
            )
        {
            return Err("JOURNAL_PHASE_INVALID");
        }
        Ok(())
    }

    pub fn summary(&self, recovery_required: bool) -> PendingTransition {
        PendingTransition {
            operation_id: self.operation_id.clone(),
            kind: self.kind,
            phase: self.phase,
            recovery_required,
        }
    }

    pub fn startup_disposition(&self) -> StartupDisposition {
        if self.kind == MaintenanceKind::Backup {
            return StartupDisposition::OnlineBackupSource;
        }
        match self.phase {
            MaintenancePhase::Intent | MaintenancePhase::Quiesced | MaintenancePhase::Prepared => {
                StartupDisposition::SourceDormant
            }
            MaintenancePhase::OldClosed => StartupDisposition::ReconcileConfig,
            _ => StartupDisposition::CandidateDormant,
        }
    }

    pub fn reconcile_config(
        &self,
        configured_root: &Path,
    ) -> Result<StartupDisposition, &'static str> {
        self.validate()?;
        check_local_path(configured_root)?;
        let configured = configured_root
            .canonicalize()
            .map_err(|_| "CONFIG_ROOT_UNAVAILABLE")?;
        let same_as = |path: &Path| path.canonicalize().is_ok_and(|path| path == configured);
        let disposition = self.startup_disposition();
        let matches = match disposition {
            StartupDisposition::OnlineBackupSource | StartupDisposition::SourceDormant => {
                same_as(&self.source_root)
            }
            StartupDisposition::ReconcileConfig => {
                same_as(&self.source_root) || same_as(&self.destination)
            }
            StartupDisposition::CandidateDormant => same_as(&self.destination),
        };
        if !matches {
            return Err("CONFIG_JOURNAL_CONFLICT");
        }
        Ok(disposition)
    }

    fn same_intent(&self, next: &Self) -> bool {
        self.format == next.format
            && self.operation_id == next.operation_id
            && self.kind == next.kind
            && self.origin_generation == next.origin_generation
            && self.source_root == next.source_root
            && self.destination == next.destination
            && self.backup_source == next.backup_source
            && self.source_root_id == next.source_root_id
            && self.source_fingerprint == next.source_fingerprint
    }

    fn can_follow(&self, next: &Self) -> bool {
        if !self.same_intent(next) {
            return false;
        }
        for (old, new) in [
            (&self.candidate_root_id, &next.candidate_root_id),
            (&self.candidate_fingerprint, &next.candidate_fingerprint),
            (&self.manifest_sha256, &next.manifest_sha256),
        ] {
            if old.is_some() && old != new {
                return false;
            }
        }
        if self.phase == next.phase {
            // Metadata is published atomically WITH phase advancement, not patched
            // into a prior receipt later. Exact replay only at the same phase.
            return self == next;
        }
        if self.kind == MaintenanceKind::Backup {
            return self.phase == MaintenancePhase::Intent
                && next.phase == MaintenancePhase::Prepared;
        }
        match (transition_phase(self.phase), transition_phase(next.phase)) {
            (Some(old), Some(new)) => old.advance(new).is_ok(),
            _ => false,
        }
    }
}

// Fingerprints are opaque core values, not a native hash of a path spelling.
fn opaque_fingerprint(value: &str) -> bool {
    !value.is_empty() && value.len() <= 256 && !value.chars().any(char::is_control)
}

fn transition_phase(phase: MaintenancePhase) -> Option<TransitionPhase> {
    use MaintenancePhase::*;
    Some(match phase {
        Selecting => return None,
        Intent => TransitionPhase::Intent,
        Quiesced => TransitionPhase::Quiesced,
        Prepared => TransitionPhase::Prepared,
        OldClosed => TransitionPhase::OldClosed,
        ConfigSwitched => TransitionPhase::ConfigSwitched,
        CandidateDormant => TransitionPhase::CandidateDormant,
        ActivationDispatched => TransitionPhase::ActivationDispatched,
        Active => TransitionPhase::Active,
    })
}

pub struct JournalStore {
    path: PathBuf,
}

impl JournalStore {
    /// app_config is native-owned. Calling this does not select a data root.
    pub fn new(app_config: &Path) -> Result<Self, &'static str> {
        check_local_path(app_config)?;
        fs::create_dir_all(app_config).map_err(|_| "JOURNAL_DIRECTORY_FAILED")?;
        check_local_path(app_config)?;
        Ok(Self {
            path: app_config.join("maintenance.json"),
        })
    }

    pub fn load(&self) -> Result<Option<NativeJournal>, &'static str> {
        check_local_path(&self.path)?;
        if !self.path.try_exists().map_err(|_| "JOURNAL_READ_FAILED")? {
            return Ok(None);
        }
        let bytes = read_bounded(&self.path)?;
        let journal: NativeJournal =
            serde_json::from_slice(&bytes).map_err(|_| "JOURNAL_INVALID")?;
        journal.validate()?;
        Ok(Some(journal))
    }

    pub fn begin(&self, intent: &NativeJournal) -> Result<NativeJournal, &'static str> {
        intent.validate()?;
        if intent.phase != MaintenancePhase::Intent {
            return Err("JOURNAL_PHASE_INVALID");
        }
        if let Some(existing) = self.load()? {
            return if existing.same_intent(intent) {
                Ok(existing)
            } else {
                Err("MAINTENANCE_PENDING")
            };
        }
        self.write(intent, false)?;
        Ok(intent.clone())
    }

    /// Serial controller only. Caller persists phase BEFORE the corresponding
    /// irreversible operation; no config/IPC/activation action is performed here.
    pub fn advance(&self, next: &NativeJournal) -> Result<(), &'static str> {
        if next.phase == MaintenancePhase::OldClosed {
            return Err("CLOSE_PROOF_REQUIRED");
        }
        self.advance_inner(next)
    }

    pub fn record_closed(
        &self,
        next: &NativeJournal,
        proof: &CloseProof,
    ) -> Result<(), &'static str> {
        if next.phase != MaintenancePhase::OldClosed
            || !proof.is_clean()
            || !proof.matches_operation(&next.operation_id)
        {
            return Err("CLOSE_PROOF_REQUIRED");
        }
        self.advance_inner(next)
    }

    fn advance_inner(&self, next: &NativeJournal) -> Result<(), &'static str> {
        next.validate()?;
        let existing = self.load()?.ok_or("JOURNAL_MISSING")?;
        if !existing.can_follow(next) {
            return Err("JOURNAL_CONFLICT");
        }
        if existing == *next {
            return Ok(());
        }
        self.write(next, true)
    }

    fn write(&self, journal: &NativeJournal, replace: bool) -> Result<(), &'static str> {
        let bytes = serde_json::to_vec(journal).map_err(|_| "JOURNAL_INVALID")?;
        if bytes.len() > JOURNAL_LIMIT {
            return Err("JOURNAL_TOO_LARGE");
        }
        check_local_path(&self.path)?;
        let sequence = TEMP_SEQUENCE.fetch_add(1, Ordering::Relaxed);
        let temporary = self.path.with_file_name(format!(
            "maintenance.{}.{}.{sequence}.tmp",
            journal.operation_id,
            std::process::id()
        ));
        let mut options = OpenOptions::new();
        options.write(true).create_new(true);
        #[cfg(windows)]
        {
            use std::os::windows::fs::OpenOptionsExt;
            options.custom_flags(0x80000000 | 0x00200000);
        }
        let mut file = options
            .open(&temporary)
            .map_err(|_| "JOURNAL_WRITE_FAILED")?;
        // A failed temp/write is retained as diagnostic evidence, never adopted.
        file.write_all(&bytes)
            .and_then(|_| file.sync_all())
            .map_err(|_| "JOURNAL_WRITE_FAILED")?;
        drop(file);
        check_local_path(&self.path)?;
        check_local_path(&temporary)?;
        replace_file(&temporary, &self.path, replace)?;
        if read_bounded(&self.path)? != bytes {
            return Err("JOURNAL_READBACK_FAILED");
        }
        Ok(())
    }
}

fn read_bounded(path: &Path) -> Result<Vec<u8>, &'static str> {
    let mut options = OpenOptions::new();
    options.read(true);
    #[cfg(windows)]
    {
        use std::os::windows::fs::OpenOptionsExt;
        options.custom_flags(0x00200000);
    }
    let file = options.open(path).map_err(|_| "JOURNAL_READ_FAILED")?;
    let metadata = file.metadata().map_err(|_| "JOURNAL_READ_FAILED")?;
    if !metadata.is_file() {
        return Err("JOURNAL_INVALID");
    }
    #[cfg(windows)]
    {
        use std::os::windows::fs::MetadataExt;
        if metadata.file_attributes() & 0x400 != 0 {
            return Err("NATIVE_REPARSE_REFUSED");
        }
    }
    let mut bytes = Vec::new();
    file.take((JOURNAL_LIMIT + 1) as u64)
        .read_to_end(&mut bytes)
        .map_err(|_| "JOURNAL_READ_FAILED")?;
    if bytes.len() > JOURNAL_LIMIT {
        return Err("JOURNAL_TOO_LARGE");
    }
    check_local_path(path)?;
    Ok(bytes)
}

#[cfg(windows)]
fn replace_file(source: &Path, target: &Path, replace: bool) -> Result<(), &'static str> {
    use std::os::windows::ffi::OsStrExt;
    #[link(name = "kernel32")]
    extern "system" {
        fn MoveFileExW(source: *const u16, target: *const u16, flags: u32) -> i32;
    }
    let source: Vec<u16> = source.as_os_str().encode_wide().chain(Some(0)).collect();
    let target: Vec<u16> = target.as_os_str().encode_wide().chain(Some(0)).collect();
    let flags = 0x8 | u32::from(replace); // WRITE_THROUGH, optionally REPLACE_EXISTING, never COPY_ALLOWED.
    if unsafe { MoveFileExW(source.as_ptr(), target.as_ptr(), flags) } == 0 {
        Err("JOURNAL_REPLACE_FAILED")
    } else {
        Ok(())
    }
}

#[cfg(not(windows))]
fn replace_file(source: &Path, target: &Path, replace: bool) -> Result<(), &'static str> {
    // Non-Windows is supported only for source-level checks, not release proof.
    if !replace && target.try_exists().map_err(|_| "JOURNAL_READ_FAILED")? {
        return Err("JOURNAL_REPLACE_FAILED");
    }
    fs::rename(source, target).map_err(|_| "JOURNAL_REPLACE_FAILED")?;
    fs::File::open(target.parent().ok_or("JOURNAL_INVALID")?)
        .and_then(|directory| directory.sync_all())
        .map_err(|_| "JOURNAL_WRITE_FAILED")
}
