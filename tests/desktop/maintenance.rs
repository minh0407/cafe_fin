use cafe_fin_native_checks::{
    control::{ControlCommand, ControlPipe, ControlReply, ControlRequest},
    maintenance_dto::{MaintenanceKind, MaintenancePhase, PendingTransition},
    native_guards::CloseProof,
    native_journal::{JournalStore, NativeJournal, StartupDisposition},
    native_paths::{check_local_path, derive_destination, reports_directory},
};
use std::{
    fs,
    path::{Path, PathBuf},
    process::{Child, ChildStdin, Command, Stdio},
    sync::atomic::{AtomicU64, Ordering},
    time::Duration,
};

const OP: &str = "00000000-0000-4000-8000-000000000001";
const GENERATION: &str = "00000000-0000-4000-8000-000000000002";
const ROOT: &str = "00000000-0000-4000-8000-000000000003";
const REQUEST: &str = "00000000-0000-4000-8000-000000000004";
const TOKEN: &str = "synthetic-memory-token";
static SEQUENCE: AtomicU64 = AtomicU64::new(0);

struct Fixture {
    path: PathBuf,
    temp_root: PathBuf,
}
impl Fixture {
    fn new() -> Self {
        let temp_root = std::env::temp_dir().canonicalize().unwrap();
        let stamp = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let path = temp_root.join(format!(
            "cafe-fin-native-test-{}-{stamp}-{}",
            std::process::id(),
            SEQUENCE.fetch_add(1, Ordering::Relaxed)
        ));
        fs::create_dir(&path).unwrap();
        Self { path, temp_root }
    }
    fn directory(&self, name: &str) -> PathBuf {
        let path = self.path.join(name);
        fs::create_dir_all(&path).unwrap();
        path
    }
    fn intent(&self, kind: MaintenanceKind) -> NativeJournal {
        let source = self.directory("Nguồn dữ liệu");
        let parent = self.directory("Đích mới");
        let destination = derive_destination(&parent, OP, kind == MaintenanceKind::Backup).unwrap();
        NativeJournal {
            format: 1,
            operation_id: OP.into(),
            kind,
            origin_generation: GENERATION.into(),
            source_root: source,
            destination,
            backup_source: if kind == MaintenanceKind::Restore {
                Some(self.directory("Bản sao lưu"))
            } else {
                None
            },
            source_root_id: ROOT.into(),
            source_fingerprint: "opaque:source-fingerprint".into(),
            candidate_root_id: None,
            candidate_fingerprint: None,
            manifest_sha256: None,
            phase: MaintenancePhase::Intent,
        }
    }
}
impl Drop for Fixture {
    fn drop(&mut self) {
        // Delete only this test's verified absolute synthetic directory, never its
        // parent or arbitrary input from a journal/renderer.
        if let Ok(canonical) = self.path.canonicalize() {
            if canonical.starts_with(&self.temp_root)
                && canonical != self.temp_root
                && self
                    .path
                    .file_name()
                    .unwrap()
                    .to_string_lossy()
                    .starts_with("cafe-fin-native-test-")
                && check_local_path(&self.path).is_ok()
            {
                let _ = fs::remove_dir_all(&self.path);
            }
        }
    }
}

fn request(command: ControlCommand) -> ControlRequest<'static> {
    ControlRequest {
        maintenance_protocol: 1,
        request_id: REQUEST,
        generation: GENERATION,
        command,
        operation_id: Some(OP),
        origin_generation: Some(GENERATION),
        access_token: TOKEN,
        kind: None,
        destination: None,
        backup_source: None,
    }
}
fn peer(mode: &str) -> (Child, ControlPipe<ChildStdin>) {
    let mut child = Command::new(env!("CARGO_BIN_EXE_control-peer"))
        .arg(mode)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .spawn()
        .unwrap();
    let mut pipe = ControlPipe::new(child.stdin.take().unwrap(), child.stdout.take().unwrap());
    assert_eq!(
        pipe.boot_frame(Duration::from_secs(5)).unwrap(),
        b"{\"fixture_boot\":true}\n"
    );
    (child, pipe)
}

#[test]
fn public_summary_excludes_private_paths_fingerprints_credentials_and_receipts() {
    let value = serde_json::to_value(PendingTransition {
        operation_id: OP.into(),
        kind: MaintenanceKind::Restore,
        phase: MaintenancePhase::CandidateDormant,
        recovery_required: true,
    })
    .unwrap();
    let keys: Vec<_> = value
        .as_object()
        .unwrap()
        .keys()
        .map(String::as_str)
        .collect();
    assert_eq!(keys, ["kind", "operation_id", "phase", "recovery_required"]);
    assert_eq!(value["phase"], "CANDIDATE_DORMANT");
}

#[test]
fn private_path_fields_allowed_only_for_prepare_and_restore_source_required() {
    let fixture = Fixture::new();
    let mut req = request(ControlCommand::Status);
    req.destination = Some(&fixture.path);
    assert_eq!(req.encode().err(), Some("CONTROL_REQUEST_INVALID"));
    req.command = ControlCommand::Prepare;
    req.kind = Some(MaintenanceKind::Restore);
    assert_eq!(req.encode().err(), Some("CONTROL_REQUEST_INVALID"));
    req.backup_source = Some(&fixture.path);
    let value: serde_json::Value = serde_json::from_slice(&req.encode().unwrap()).unwrap();
    assert_eq!(value["command"], "maintenance.prepare");
    req.kind = Some(MaintenanceKind::Move);
    assert_eq!(req.encode().err(), Some("CONTROL_REQUEST_INVALID"));
}

#[test]
fn reports_request_has_no_operation_or_native_path_capability() {
    let mut req = request(ControlCommand::ReportsAuthorizeOpen);
    assert_eq!(req.encode().err(), Some("CONTROL_REQUEST_INVALID"));
    req.operation_id = None;
    req.origin_generation = None;
    let value: serde_json::Value = serde_json::from_slice(&req.encode().unwrap()).unwrap();
    assert!(value.get("operation_id").is_none());
    assert!(value.get("origin_generation").is_none());
    assert!(value.get("destination").is_none());
    let (mut child, mut pipe) = peer("");
    pipe.send(&req).unwrap();
    match pipe.receive(Duration::from_secs(5)).unwrap() {
        ControlReply::Reports(reply) => {
            assert!(reply.allowed);
            assert_eq!(reply.root_id.as_deref(), Some(ROOT));
        }
        _ => panic!("wrong reply kind"),
    }
    assert!(child.wait().unwrap().success());
}

#[test]
fn invalid_id_and_large_or_control_containing_token_are_rejected_before_write() {
    let mut req = request(ControlCommand::Status);
    req.request_id = "not-a-native-id";
    assert_eq!(req.encode().err(), Some("CONTROL_REQUEST_INVALID"));
    req.request_id = REQUEST;
    req.access_token = "secret\nframe";
    assert_eq!(req.encode().err(), Some("CONTROL_REQUEST_INVALID"));
    let huge = "x".repeat(4097);
    req.access_token = &huge;
    assert_eq!(req.encode().err(), Some("CONTROL_REQUEST_INVALID"));
}

#[test]
fn boot_is_consumed_once_and_lost_ack_keeps_same_pending_request() {
    let (mut child, mut pipe) = peer("delayed");
    assert_eq!(
        pipe.boot_frame(Duration::ZERO).err(),
        Some("CONTROL_STATE_INVALID")
    );
    let req = request(ControlCommand::Status);
    pipe.send(&req).unwrap();
    assert_eq!(
        pipe.receive(Duration::ZERO).err(),
        Some("CONTROL_ACK_PENDING")
    );
    assert_eq!(pipe.send(&req).err(), Some("CONTROL_REQUEST_PENDING"));
    assert!(matches!(
        pipe.receive(Duration::from_secs(5)).unwrap(),
        ControlReply::Maintenance(_)
    ));
    assert!(child.wait().unwrap().success());
}

#[test]
fn wrong_generation_operation_request_or_extra_field_poison_the_stream() {
    for mode in [
        "wrong-generation",
        "wrong-operation",
        "wrong-request",
        "extra-field",
        "oversized",
    ] {
        let (mut child, mut pipe) = peer(mode);
        let req = request(ControlCommand::Status);
        pipe.send(&req).unwrap();
        let code = pipe.receive(Duration::from_secs(5)).err().unwrap();
        assert!(matches!(
            code,
            "CONTROL_RESPONSE_INVALID"
                | "CONTROL_RESPONSE_MISMATCH"
                | "CONTROL_PIPE_FAILED"
                | "CONTROL_FRAME_TOO_LARGE"
        ));
        assert_eq!(pipe.send(&req).err(), Some("CONTROL_PIPE_FAILED"));
        let _ = child.wait().unwrap();
    }
}

#[test]
fn prepare_requires_matching_kind_and_state() {
    let fixture = Fixture::new();
    for mode in ["wrong-kind", "wrong-state"] {
        let (mut child, mut pipe) = peer(mode);
        let mut req = request(ControlCommand::Prepare);
        req.kind = Some(MaintenanceKind::Move);
        req.destination = Some(&fixture.path);
        pipe.send(&req).unwrap();
        assert_eq!(
            pipe.receive(Duration::from_secs(5)).err(),
            Some("CONTROL_RESPONSE_MISMATCH")
        );
        assert!(child.wait().unwrap().success());
    }
}

#[test]
fn actual_child_close_ack_plus_zero_exit_differs_from_nonzero_exit() {
    for mode in ["", "nonzero"] {
        let (mut child, mut pipe) = peer(mode);
        pipe.send(&request(ControlCommand::Close)).unwrap();
        let mut proof = CloseProof::new(GENERATION.into(), OP.into(), REQUEST.into());
        match pipe.receive(Duration::from_secs(5)).unwrap() {
            ControlReply::Maintenance(reply) => proof
                .acknowledge(
                    &reply.generation,
                    &reply.operation_id,
                    &reply.request_id,
                    "CLOSED",
                    true,
                )
                .unwrap(),
            _ => panic!("wrong response"),
        }
        assert!(!proof.is_clean());
        proof.observe_exit(child.wait().unwrap().code());
        assert_eq!(proof.is_clean(), mode.is_empty());
    }
}

#[test]
fn journal_real_file_write_readback_replay_and_immutable_destination() {
    let fixture = Fixture::new();
    let store = JournalStore::new(&fixture.directory("config")).unwrap();
    let mut journal = fixture.intent(MaintenanceKind::Move);
    store.begin(&journal).unwrap();
    assert!(store.load().unwrap().unwrap() == journal);
    let mut changed = journal.clone();
    changed.destination = fixture.path.join(format!("CafeFinData-{OP}"));
    assert_eq!(store.begin(&changed).err(), Some("MAINTENANCE_PENDING"));
    journal.phase = MaintenancePhase::Quiesced;
    store.advance(&journal).unwrap();
    store.advance(&journal).unwrap();
    assert_eq!(
        store.load().unwrap().unwrap().phase,
        MaintenancePhase::Quiesced
    );
    let bytes = fs::read(fixture.path.join("config/maintenance.json")).unwrap();
    assert!(!String::from_utf8(bytes).unwrap().contains(TOKEN));
    assert!(fixture.path.join("Nguồn dữ liệu").is_dir());
}

fn prepared(journal: &mut NativeJournal, store: &JournalStore) {
    journal.phase = MaintenancePhase::Quiesced;
    store.advance(journal).unwrap();
    journal.phase = MaintenancePhase::Prepared;
    journal.candidate_root_id = Some(ROOT.into()); // copied UUID is lineage, not physical identity
    journal.candidate_fingerprint = Some("opaque:candidate-fingerprint".into());
    journal.manifest_sha256 = Some("ab".repeat(32));
    fs::create_dir(&journal.destination).unwrap();
    store.advance(journal).unwrap();
}

#[test]
fn close_proof_required_before_config_phase_and_post_activation_never_source() {
    let fixture = Fixture::new();
    let store = JournalStore::new(&fixture.directory("config")).unwrap();
    let mut journal = fixture.intent(MaintenanceKind::Restore);
    store.begin(&journal).unwrap();
    prepared(&mut journal, &store);
    journal.phase = MaintenancePhase::ConfigSwitched;
    assert_eq!(store.advance(&journal).err(), Some("JOURNAL_CONFLICT"));
    journal.phase = MaintenancePhase::OldClosed;
    assert_eq!(store.advance(&journal).err(), Some("CLOSE_PROOF_REQUIRED"));
    let mut proof = CloseProof::new(GENERATION.into(), OP.into(), REQUEST.into());
    proof
        .acknowledge(GENERATION, OP, REQUEST, "CLOSED", true)
        .unwrap();
    assert_eq!(
        store.record_closed(&journal, &proof).err(),
        Some("CLOSE_PROOF_REQUIRED")
    );
    proof.observe_exit(Some(0));
    store.record_closed(&journal, &proof).unwrap();
    assert_eq!(
        journal.reconcile_config(&journal.source_root).unwrap(),
        StartupDisposition::ReconcileConfig
    );
    assert_eq!(
        journal.reconcile_config(&journal.destination).unwrap(),
        StartupDisposition::ReconcileConfig
    );
    for phase in [
        MaintenancePhase::ConfigSwitched,
        MaintenancePhase::CandidateDormant,
        MaintenancePhase::ActivationDispatched,
        MaintenancePhase::Active,
    ] {
        journal.phase = phase;
        store.advance(&journal).unwrap();
        assert_eq!(
            journal.reconcile_config(&journal.destination).unwrap(),
            StartupDisposition::CandidateDormant
        );
        assert_eq!(
            journal.reconcile_config(&journal.source_root).err(),
            Some("CONFIG_JOURNAL_CONFLICT")
        );
    }
}

#[test]
fn prepared_digest_cannot_be_rebound_or_cleared_on_retry() {
    let fixture = Fixture::new();
    let store = JournalStore::new(&fixture.directory("config")).unwrap();
    let mut journal = fixture.intent(MaintenanceKind::Move);
    store.begin(&journal).unwrap();
    prepared(&mut journal, &store);
    journal.manifest_sha256 = Some("cd".repeat(32));
    assert_eq!(store.advance(&journal).err(), Some("JOURNAL_CONFLICT"));
    journal.manifest_sha256 = None;
    assert_eq!(
        store.advance(&journal).err(),
        Some("JOURNAL_RECEIPT_REQUIRED")
    );
}

#[test]
fn corrupt_newer_extra_field_or_oversized_journal_never_falls_back() {
    let fixture = Fixture::new();
    let config = fixture.directory("config");
    let store = JournalStore::new(&config).unwrap();
    let journal = fixture.intent(MaintenanceKind::Move);
    for mutation in ["format", "access_token"] {
        let mut value = serde_json::to_value(&journal).unwrap();
        if mutation == "format" {
            value[mutation] = 2.into();
        } else {
            value[mutation] = TOKEN.into();
        }
        fs::write(
            config.join("maintenance.json"),
            serde_json::to_vec(&value).unwrap(),
        )
        .unwrap();
        assert_eq!(store.load().err(), Some("JOURNAL_INVALID"));
    }
    fs::write(config.join("maintenance.json"), vec![b'x'; 393217]).unwrap();
    assert_eq!(store.load().err(), Some("JOURNAL_TOO_LARGE"));
}

#[test]
fn backup_is_online_and_cannot_gain_transition_or_activation_phase() {
    let fixture = Fixture::new();
    let store = JournalStore::new(&fixture.directory("config")).unwrap();
    let mut journal = fixture.intent(MaintenanceKind::Backup);
    // The product's own backups directory is a valid backup parent: core copies
    // only referenced immutable files, not prior backup directories recursively.
    journal.destination = derive_destination(&journal.source_root, OP, true).unwrap();
    store.begin(&journal).unwrap();
    assert_eq!(
        journal.reconcile_config(&journal.source_root).unwrap(),
        StartupDisposition::OnlineBackupSource
    );
    journal.phase = MaintenancePhase::Quiesced;
    assert_eq!(store.advance(&journal).err(), Some("JOURNAL_PHASE_INVALID"));
    journal.phase = MaintenancePhase::Prepared;
    journal.manifest_sha256 = Some("ab".repeat(32));
    store.advance(&journal).unwrap();
    journal.phase = MaintenancePhase::Active;
    assert_eq!(store.advance(&journal).err(), Some("JOURNAL_PHASE_INVALID"));
}

#[test]
fn native_destination_is_stable_new_child_with_no_directory_creation() {
    let fixture = Fixture::new();
    let first = derive_destination(&fixture.path, OP, false).unwrap();
    assert_eq!(first, derive_destination(&fixture.path, OP, false).unwrap());
    assert_eq!(
        first.file_name().unwrap(),
        format!("CafeFinData-{OP}").as_str()
    );
    assert!(!first.exists());
    assert_eq!(
        derive_destination(&fixture.path, "../escape", false).err(),
        Some("OPERATION_ID_INVALID")
    );
    fs::create_dir(&first).unwrap();
    assert_eq!(
        derive_destination(&fixture.path, OP, false).err(),
        Some("DESTINATION_EXISTS")
    );
}

fn directory_link(source: &Path, target: &Path) {
    #[cfg(windows)]
    std::os::windows::fs::symlink_dir(source, target).unwrap();
    #[cfg(unix)]
    std::os::unix::fs::symlink(source, target).unwrap();
}

#[test]
fn reports_reparse_substitution_after_selection_is_refused() {
    let fixture = Fixture::new();
    let root = fixture.directory("root");
    fs::create_dir(root.join("reports")).unwrap();
    assert!(reports_directory(&root).is_ok());
    fs::remove_dir(root.join("reports")).unwrap();
    let other = fixture.directory("other");
    directory_link(&other, &root.join("reports"));
    assert_eq!(
        reports_directory(&root).err(),
        Some("NATIVE_REPARSE_REFUSED")
    );
    // Remove the synthetic link itself before fixture cleanup, never its target.
    #[cfg(windows)]
    fs::remove_dir(root.join("reports")).unwrap();
    #[cfg(unix)]
    fs::remove_file(root.join("reports")).unwrap();
    assert!(other.is_dir());
}
