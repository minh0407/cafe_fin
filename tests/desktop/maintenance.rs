use cafe_fin_native_checks::{
    control::{ControlCommand, ControlPipe, ControlReply, ControlRequest, OperationState},
    maintenance_dto::{
        BootSession, MaintenanceKind, MaintenancePhase, PendingTransition, RuntimeState,
        SelectionPurpose,
    },
    native_attach::{attach_existing, ExistingChild},
    native_draft::DraftSlot,
    native_guards::{CloseProof, PickerHandles, PickerPurpose},
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
            source_fingerprint: "11".repeat(32),
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
            assert_eq!(reply.allowed, Some(true));
            assert_eq!(reply.root_id.as_deref(), Some(ROOT));
        }
        _ => panic!("wrong reply kind"),
    }
    assert!(child.wait().unwrap().success());
}

#[test]
fn source_identity_has_no_operation_path_or_allowed_field_and_report_errors_omit_allowed() {
    let mut req = request(ControlCommand::SourceIdentity);
    assert_eq!(req.encode().err(), Some("CONTROL_REQUEST_INVALID"));
    req.operation_id = None;
    req.origin_generation = None;
    let (mut child, mut pipe) = peer("");
    pipe.send(&req).unwrap();
    match pipe.receive(Duration::from_secs(5)).unwrap() {
        ControlReply::Identity(reply) => {
            assert_eq!(reply.root_id.as_deref(), Some(ROOT));
            assert_eq!(
                reply.source_fingerprint.as_deref(),
                Some("1111111111111111111111111111111111111111111111111111111111111111")
            );
            assert!(reply.allowed.is_none());
        }
        _ => panic!("wrong reply purpose"),
    }
    assert!(child.wait().unwrap().success());
    req.command = ControlCommand::ReportsAuthorizeOpen;
    let (mut child, mut pipe) = peer("reports-denied");
    pipe.send(&req).unwrap();
    match pipe.receive(Duration::from_secs(5)).unwrap() {
        ControlReply::Reports(reply) => {
            assert!(reply.allowed.is_none());
            assert_eq!(reply.code.as_deref(), Some("PERMISSION_DENIED"));
        }
        _ => panic!("wrong reply purpose"),
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
    let huge = "x".repeat(129);
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
        assert!(matches!(
            pipe.receive(Duration::from_secs(5)).err(),
            Some("CONTROL_RESPONSE_INVALID" | "CONTROL_RESPONSE_MISMATCH")
        ));
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
    journal.candidate_fingerprint = Some("22".repeat(32));
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
    // Approved phase 2 controller requires an independent root for every kind.
    let mut nested = journal.clone();
    nested.destination = derive_destination(&journal.source_root, OP, true).unwrap();
    assert_eq!(store.begin(&nested).err(), Some("JOURNAL_PATH_CONFLICT"));
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

struct AttachChild {
    generation: String,
    verified: bool,
    alive_checks: usize,
    fail_health: bool,
    die_after_health: bool,
    race_generation: bool,
    boot: BootSession,
}
impl AttachChild {
    fn target(root: &Path) -> Self {
        Self {
            generation: GENERATION.into(),
            verified: true,
            alive_checks: 0,
            fail_health: false,
            die_after_health: false,
            race_generation: false,
            boot: BootSession {
                protocol_version: 1,
                api_base: "http://127.0.0.1:48888/api/v1".into(),
                session_token: "synthetic-target-app-session".into(),
                data_root: root.to_str().unwrap().into(),
                maintenance_protocol: Some(1),
                generation: Some(GENERATION.into()),
                runtime_state: Some(RuntimeState::Dormant),
                pending_transition: None,
            },
        }
    }
}
impl ExistingChild for AttachChild {
    fn generation(&self) -> &str {
        &self.generation
    }
    fn verified(&self) -> bool {
        self.verified
    }
    fn check_alive(&mut self) -> Result<(), &'static str> {
        self.alive_checks += 1;
        if self.die_after_health && self.alive_checks == 2 {
            Err("CHILD_EXITED")
        } else {
            Ok(())
        }
    }
    fn check_health(&mut self) -> Result<(), &'static str> {
        if self.race_generation {
            self.generation = "00000000-0000-4000-8000-000000000099".into();
        }
        if self.fail_health {
            Err("HEALTH_FAILED")
        } else {
            Ok(())
        }
    }
    fn session(&self) -> &BootSession {
        &self.boot
    }
}

#[test]
fn lost_run_ack_attaches_current_target_and_overlays_current_pending_binding() {
    let fixture = Fixture::new();
    let store = JournalStore::new(&fixture.directory("attach-config")).unwrap();
    let mut journal = fixture.intent(MaintenanceKind::Move);
    store.begin(&journal).unwrap();
    prepared(&mut journal, &store);
    // Source/current UUID may match after copy; physical target remains distinct.
    assert_eq!(
        journal.source_root_id,
        journal.candidate_root_id.clone().unwrap()
    );
    let mut child = AttachChild::target(&journal.destination);
    let pending = journal.summary(true);
    let boot = attach_existing(Some(&mut child), Some(&pending), false)
        .unwrap()
        .unwrap();
    assert_eq!(boot.data_root, journal.destination.to_str().unwrap());
    assert_ne!(boot.data_root, journal.source_root.to_str().unwrap());
    assert_eq!(boot.session_token, "synthetic-target-app-session");
    assert_eq!(boot.runtime_state, Some(RuntimeState::Dormant));
    assert_eq!(boot.pending_transition.unwrap().operation_id, OP);
    assert_eq!(child.alive_checks, 2);
    // A second lost ACK produces the same app session; renderer still clears its
    // stale source actor before authenticating against this target database.
    let repeated = attach_existing(Some(&mut child), Some(&pending), false)
        .unwrap()
        .unwrap();
    assert_eq!(repeated.generation.as_deref(), Some(GENERATION));
    assert_eq!(repeated.session_token, "synthetic-target-app-session");
}

#[test]
fn pending_attach_has_no_spawn_initialize_or_old_root_fallback_branch() {
    let pending = PendingTransition {
        operation_id: OP.into(),
        kind: MaintenanceKind::Restore,
        phase: MaintenancePhase::CandidateDormant,
        recovery_required: true,
    };
    assert_eq!(
        attach_existing::<AttachChild>(None, Some(&pending), false).err(),
        Some("MAINTENANCE_RECOVERY_HELD")
    );
    let mut child = AttachChild::target(Path::new("unused-synthetic-path"));
    assert_eq!(
        attach_existing(Some(&mut child), Some(&pending), true).err(),
        Some("MAINTENANCE_RECOVERY_HELD")
    );
    child.verified = false;
    assert_eq!(
        attach_existing(Some(&mut child), Some(&pending), false).err(),
        Some("MAINTENANCE_RECOVERY_HELD")
    );
    assert_eq!(child.alive_checks, 0);
}

#[test]
fn attach_rejects_generation_race_stale_boot_health_failure_and_exit_after_probe() {
    let pending = PendingTransition {
        operation_id: OP.into(),
        kind: MaintenanceKind::Move,
        phase: MaintenancePhase::CandidateDormant,
        recovery_required: true,
    };
    for mode in [
        "generation-race",
        "stale-boot",
        "health-failed",
        "died",
        "unnegotiated",
    ] {
        let mut child = AttachChild::target(Path::new("unused-synthetic-path"));
        match mode {
            "generation-race" => child.race_generation = true,
            "stale-boot" => child.boot.generation = Some(REQUEST.into()),
            "health-failed" => child.fail_health = true,
            "died" => child.die_after_health = true,
            "unnegotiated" => child.boot.maintenance_protocol = None,
            _ => unreachable!(),
        }
        assert_eq!(
            attach_existing(Some(&mut child), Some(&pending), false).err(),
            Some("MAINTENANCE_RECOVERY_HELD")
        );
    }
}

#[test]
fn lost_initial_start_ack_can_attach_legacy_verified_child_without_reinitializing() {
    let mut child = AttachChild::target(Path::new("unused-synthetic-path"));
    child.boot.maintenance_protocol = None;
    child.boot.generation = None;
    child.boot.runtime_state = Some(RuntimeState::Active);
    let boot = attach_existing(Some(&mut child), None, false)
        .unwrap()
        .unwrap();
    assert_eq!(boot.session_token, "synthetic-target-app-session");
    assert!(boot.pending_transition.is_none());
    assert!(attach_existing::<AttachChild>(None, None, false)
        .unwrap()
        .is_none());
    assert_eq!(
        attach_existing(Some(&mut child), None, true).err(),
        Some("ATTACH_INITIALIZE_DENIED")
    );
}

#[test]
fn operation_outcome_does_not_replace_actual_runtime_admission() {
    for (mode, expected_operation, expected_runtime) in [
        (
            "prepared-held",
            OperationState::Prepared,
            RuntimeState::Quiesced,
        ),
        (
            "replay-required",
            OperationState::ReplayRequired,
            RuntimeState::Dormant,
        ),
        (
            "failed-held",
            OperationState::FailedHeld,
            RuntimeState::Quiesced,
        ),
    ] {
        let (mut child, mut pipe) = peer(mode);
        pipe.send(&request(ControlCommand::Status)).unwrap();
        match pipe.receive(Duration::from_secs(5)).unwrap() {
            ControlReply::Maintenance(reply) => {
                assert_eq!(reply.state, expected_operation);
                assert_eq!(reply.runtime_state, expected_runtime);
            }
            _ => panic!("wrong response"),
        }
        assert!(child.wait().unwrap().success());
    }
    assert!(serde_json::from_str::<RuntimeState>("\"REPLAY_REQUIRED\"").is_err());
    assert!(serde_json::from_str::<RuntimeState>("\"CLOSE_AUTHORIZED\"").is_err());
}

#[test]
fn close_authorization_or_undrained_runtime_plus_exit_zero_is_not_closed() {
    for mode in ["close-authorized", "close-not-drained"] {
        let (mut child, mut pipe) = peer(mode);
        pipe.send(&request(ControlCommand::Close)).unwrap();
        assert!(matches!(
            pipe.receive(Duration::from_secs(5)).err(),
            Some("CONTROL_RESPONSE_INVALID" | "CONTROL_RESPONSE_MISMATCH")
        ));
        let mut proof = CloseProof::new(GENERATION.into(), OP.into(), REQUEST.into());
        proof.observe_exit(child.wait().unwrap().code());
        assert!(!proof.is_clean());
    }
}

#[test]
fn wire_requires_real_runtime_state_and_checks_optional_activation_binding() {
    for mode in [
        "missing-runtime",
        "bad-runtime-state",
        "wrong-origin",
        "wrong-activation",
        "wrong-format",
    ] {
        let (mut child, mut pipe) = peer(mode);
        pipe.send(&request(ControlCommand::Status)).unwrap();
        let code = pipe.receive(Duration::from_secs(5)).err().unwrap();
        assert!(matches!(
            code,
            "CONTROL_RESPONSE_INVALID" | "CONTROL_RESPONSE_MISMATCH"
        ));
        assert!(child.wait().unwrap().success());
    }
}

#[test]
fn cancelled_draft_can_be_replaced_but_busy_dialog_cannot() {
    let fixture = Fixture::new();
    let store = JournalStore::new(&fixture.directory("config")).unwrap();
    let mut handles = PickerHandles::new(GENERATION.into());
    let mut slot = DraftSlot::default();
    slot.begin(
        OP.into(),
        GENERATION.into(),
        MaintenanceKind::Backup,
        &store,
        &mut handles,
    )
    .unwrap();
    let ticket = slot
        .start_selection(OP, GENERATION, SelectionPurpose::Destination, &store)
        .unwrap();
    assert_eq!(
        slot.begin(
            REQUEST.into(),
            GENERATION.into(),
            MaintenanceKind::Move,
            &store,
            &mut handles
        )
        .err(),
        Some("DRAFT_BUSY")
    );
    slot.finish_selection(ticket, None, String::new(), &store, &mut handles)
        .unwrap();
    assert!(!slot.view(&store, &handles, None).unwrap().ready);
    slot.begin(
        REQUEST.into(),
        GENERATION.into(),
        MaintenanceKind::Move,
        &store,
        &mut handles,
    )
    .unwrap();
    let view = slot.view(&store, &handles, None).unwrap();
    assert_eq!(view.operation_id, REQUEST);
    assert_eq!(view.kind, MaintenanceKind::Move);
    assert_eq!(view.phase, MaintenancePhase::Selecting);
    assert!(!view.recovery_required);
    assert_eq!(
        slot.view(&store, &PickerHandles::new(ROOT.into()), None)
            .err(),
        Some("DRAFT_GENERATION_STALE")
    );
    assert!(store.load().unwrap().is_none());
}

#[test]
fn replacing_restore_draft_revokes_both_purposes_and_stale_dialog_cannot_change_new_draft() {
    let fixture = Fixture::new();
    let store = JournalStore::new(&fixture.directory("config")).unwrap();
    let parent = fixture.directory("Parent");
    let source = fixture.directory("Backup");
    let mut handles = PickerHandles::new(GENERATION.into());
    let mut slot = DraftSlot::default();
    slot.begin(
        OP.into(),
        GENERATION.into(),
        MaintenanceKind::Restore,
        &store,
        &mut handles,
    )
    .unwrap();
    for (purpose, path, nonce) in [
        (
            SelectionPurpose::Destination,
            &parent,
            format!("{:064x}", 1),
        ),
        (
            SelectionPurpose::BackupSource,
            &source,
            format!("{:064x}", 2),
        ),
    ] {
        let ticket = slot
            .start_selection(OP, GENERATION, purpose, &store)
            .unwrap();
        slot.finish_selection(ticket, Some(path), nonce, &store, &mut handles)
            .unwrap();
    }
    assert!(slot.view(&store, &handles, None).unwrap().ready);
    let late = slot
        .start_selection(OP, GENERATION, SelectionPurpose::Destination, &store)
        .unwrap();
    slot.finish_selection(late.clone(), None, String::new(), &store, &mut handles)
        .unwrap();
    slot.begin(
        REQUEST.into(),
        GENERATION.into(),
        MaintenanceKind::Move,
        &store,
        &mut handles,
    )
    .unwrap();
    for (nonce, purpose) in [
        (1, PickerPurpose::RestoreDestination),
        (2, PickerPurpose::RestoreSource),
    ] {
        assert!(handles
            .resolve(&format!("{nonce:064x}"), GENERATION, OP, purpose)
            .is_err());
    }
    let current = slot
        .start_selection(REQUEST, GENERATION, SelectionPurpose::Destination, &store)
        .unwrap();
    assert_eq!(
        slot.finish_selection(
            late,
            Some(&parent),
            format!("{:064x}", 3),
            &store,
            &mut handles
        )
        .err(),
        Some("PICKER_RESULT_STALE")
    );
    slot.finish_selection(
        current,
        Some(&parent),
        format!("{:064x}", 4),
        &store,
        &mut handles,
    )
    .unwrap();
    assert_eq!(
        slot.view(&store, &handles, None).unwrap().operation_id,
        REQUEST
    );
}

#[test]
fn hundred_folder_reselections_preserve_source_and_invalid_reselect_preserves_last_destination() {
    let fixture = Fixture::new();
    let store = JournalStore::new(&fixture.directory("config")).unwrap();
    let parent = fixture.directory("Parent");
    let source = fixture.directory("Backup");
    let mut handles = PickerHandles::new(GENERATION.into());
    let mut slot = DraftSlot::default();
    slot.begin(
        OP.into(),
        GENERATION.into(),
        MaintenanceKind::Restore,
        &store,
        &mut handles,
    )
    .unwrap();
    let ticket = slot
        .start_selection(OP, GENERATION, SelectionPurpose::BackupSource, &store)
        .unwrap();
    slot.finish_selection(
        ticket,
        Some(&source),
        format!("{:064x}", 1),
        &store,
        &mut handles,
    )
    .unwrap();
    for nonce in 2..102 {
        let ticket = slot
            .start_selection(OP, GENERATION, SelectionPurpose::Destination, &store)
            .unwrap();
        slot.finish_selection(
            ticket,
            Some(&parent),
            format!("{nonce:064x}"),
            &store,
            &mut handles,
        )
        .unwrap();
    }
    let before = slot.view(&store, &handles, None).unwrap();
    let ticket = slot
        .start_selection(OP, GENERATION, SelectionPurpose::Destination, &store)
        .unwrap();
    assert!(slot
        .finish_selection(
            ticket,
            Some(Path::new("relative")),
            format!("{:064x}", 102),
            &store,
            &mut handles
        )
        .is_err());
    let after = slot.view(&store, &handles, None).unwrap();
    assert_eq!(after.destination_display, before.destination_display);
    assert_eq!(after.backup_source_display, before.backup_source_display);
    assert!(after.ready);
    assert!(handles
        .resolve(
            &format!("{:064x}", 1),
            GENERATION,
            OP,
            PickerPurpose::RestoreSource
        )
        .is_ok());
}

#[test]
fn persistent_corrupt_uncertain_intent_attempt_or_dispatch_cannot_be_discarded_as_draft() {
    for latch in [
        "uncertain",
        "intent-attempt",
        "dispatch",
        "persistent",
        "corrupt",
    ] {
        let fixture = Fixture::new();
        let config = fixture.directory("config");
        let store = JournalStore::new(&config).unwrap();
        let mut handles = PickerHandles::new(GENERATION.into());
        let mut slot = DraftSlot::default();
        slot.begin(
            OP.into(),
            GENERATION.into(),
            MaintenanceKind::Backup,
            &store,
            &mut handles,
        )
        .unwrap();
        match latch {
            "uncertain" => slot.mark_uncertain(OP).unwrap(),
            "intent-attempt" => slot.mark_intent_attempted(OP).unwrap(),
            "dispatch" => slot.mark_dispatched(OP).unwrap(),
            "persistent" => {
                store
                    .begin(&fixture.intent(MaintenanceKind::Backup))
                    .unwrap();
            }
            "corrupt" => fs::write(config.join("maintenance.json"), b"not a journal").unwrap(),
            _ => unreachable!(),
        }
        let code = slot
            .begin(
                REQUEST.into(),
                GENERATION.into(),
                MaintenanceKind::Move,
                &store,
                &mut handles,
            )
            .err()
            .unwrap();
        assert!(matches!(
            code,
            "MAINTENANCE_PENDING" | "MAINTENANCE_RECOVERY_HELD"
        ));
        assert_eq!(slot.operation_id(), Some(OP));
        if matches!(latch, "persistent" | "corrupt") {
            assert!(slot.view(&store, &handles, None).is_err());
        } else {
            assert!(slot.view(&store, &handles, None).unwrap().recovery_required);
            assert!(slot.has_uncertain_effects());
        }
    }
}

#[test]
fn picker_cancel_settles_matching_ticket_without_touching_selected_handles_or_corrupt_journal() {
    let fixture = Fixture::new();
    let config = fixture.directory("cancel-config");
    let store = JournalStore::new(&config).unwrap();
    let parent = fixture.directory("cancel-parent");
    let mut handles = PickerHandles::new(GENERATION.into());
    let mut slot = DraftSlot::default();
    slot.begin(
        OP.into(),
        GENERATION.into(),
        MaintenanceKind::Backup,
        &store,
        &mut handles,
    )
    .unwrap();
    let selected = slot
        .start_selection(OP, GENERATION, SelectionPurpose::Destination, &store)
        .unwrap();
    let nonce = format!("{:064x}", 1);
    slot.finish_selection(selected, Some(&parent), nonce.clone(), &store, &mut handles)
        .unwrap();
    let previous = handles
        .resolve(&nonce, GENERATION, OP, PickerPurpose::BackupDestination)
        .unwrap()
        .to_path_buf();
    let ticket = slot
        .start_selection(OP, GENERATION, SelectionPurpose::Destination, &store)
        .unwrap();
    let journal = config.join("maintenance.json");
    fs::write(&journal, b"synthetic-corrupt-journal").unwrap();
    assert!(slot.is_busy());
    slot.cancel_selection(&ticket).unwrap();
    assert!(!slot.is_busy());
    assert_eq!(slot.operation_id(), Some(OP));
    assert_eq!(
        handles
            .resolve(&nonce, GENERATION, OP, PickerPurpose::BackupDestination)
            .unwrap(),
        previous
    );
    assert_eq!(fs::read(&journal).unwrap(), b"synthetic-corrupt-journal");
    assert!(store.load().is_err());
    assert_eq!(slot.cancel_selection(&ticket), Err("PICKER_RESULT_STALE"));
}

#[test]
fn picker_cancel_stale_sequence_never_clears_a_new_selection_for_the_same_operation() {
    let fixture = Fixture::new();
    let store = JournalStore::new(&fixture.directory("cancel-config")).unwrap();
    let mut handles = PickerHandles::new(GENERATION.into());
    let mut slot = DraftSlot::default();
    slot.begin(
        OP.into(),
        GENERATION.into(),
        MaintenanceKind::Backup,
        &store,
        &mut handles,
    )
    .unwrap();
    let old = slot
        .start_selection(OP, GENERATION, SelectionPurpose::Destination, &store)
        .unwrap();
    slot.cancel_selection(&old).unwrap();
    let current = slot
        .start_selection(OP, GENERATION, SelectionPurpose::Destination, &store)
        .unwrap();
    assert_eq!(slot.cancel_selection(&old), Err("PICKER_RESULT_STALE"));
    assert!(slot.is_busy());
    assert_eq!(
        slot.finish_selection(old, None, String::new(), &store, &mut handles),
        Err("PICKER_RESULT_STALE")
    );
    assert!(slot.is_busy());
    slot.cancel_selection(&current).unwrap();
    assert!(!slot.is_busy());
    assert_eq!(slot.operation_id(), Some(OP));
    assert!(store.load().unwrap().is_none());
}

#[test]
fn picker_cancel_from_replaced_draft_never_clears_the_current_operation() {
    let fixture = Fixture::new();
    let store = JournalStore::new(&fixture.directory("cancel-config")).unwrap();
    let mut handles = PickerHandles::new(GENERATION.into());
    let mut slot = DraftSlot::default();
    slot.begin(
        OP.into(),
        GENERATION.into(),
        MaintenanceKind::Backup,
        &store,
        &mut handles,
    )
    .unwrap();
    let old = slot
        .start_selection(OP, GENERATION, SelectionPurpose::Destination, &store)
        .unwrap();
    slot.cancel_selection(&old).unwrap();
    slot.begin(
        REQUEST.into(),
        GENERATION.into(),
        MaintenanceKind::Move,
        &store,
        &mut handles,
    )
    .unwrap();
    let current = slot
        .start_selection(REQUEST, GENERATION, SelectionPurpose::Destination, &store)
        .unwrap();
    assert_eq!(slot.cancel_selection(&old), Err("PICKER_RESULT_STALE"));
    assert!(slot.is_busy());
    assert_eq!(slot.operation_id(), Some(REQUEST));
    assert_eq!(
        slot.view(&store, &handles, None).unwrap().operation_id,
        REQUEST
    );
    slot.cancel_selection(&current).unwrap();
    assert!(!slot.is_busy());
}
