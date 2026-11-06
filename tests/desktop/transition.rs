//! Synthetic host, real native journal/config files. These tests prove native
//! wiring order and failure fences, not core copy, GUI or clean-client acceptance.
use cafe_fin_native_checks::{
    control::{ControlCommand, MaintenanceReply},
    maintenance_dto::{BootSession, MaintenanceKind, MaintenancePhase, RuntimeState},
    native_guards::CloseProof,
    native_journal::{JournalStore, NativeJournal},
    native_paths::check_local_path,
    native_transition::{self, RootSide, TransitionHost, TransitionResult},
};
use std::{
    fs,
    path::PathBuf,
    sync::atomic::{AtomicU64, Ordering},
};

const OP: &str = "00000000-0000-4000-8000-000000000001";
const GEN: &str = "00000000-0000-4000-8000-000000000002";
const ROOT: &str = "00000000-0000-4000-8000-000000000003";
const REQ: &str = "00000000-0000-4000-8000-000000000004";
const TARGET_GEN: &str = "00000000-0000-4000-8000-000000000005";
static SEQ: AtomicU64 = AtomicU64::new(0);

struct Fixture {
    root: PathBuf,
    temp: PathBuf,
    config: PathBuf,
}
impl Fixture {
    fn new() -> Self {
        let temp = std::env::temp_dir().canonicalize().unwrap();
        let stamp = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let root = temp.join(format!(
            "cafe-fin-transition-test-{}-{stamp}-{}",
            std::process::id(),
            SEQ.fetch_add(1, Ordering::Relaxed)
        ));
        fs::create_dir(&root).unwrap();
        let config = root.join("config");
        fs::create_dir(&config).unwrap();
        Self { root, temp, config }
    }
    fn journal(&self) -> (JournalStore, NativeJournal) {
        let source = self.root.join("Nguồn dữ liệu");
        fs::create_dir(&source).unwrap();
        let store = JournalStore::new(&self.config).unwrap();
        store.save_initial_root(&source, GEN).unwrap();
        let journal = NativeJournal {
            format: 1,
            operation_id: OP.into(),
            kind: MaintenanceKind::Move,
            origin_generation: GEN.into(),
            source_root: source.canonicalize().unwrap(),
            destination: self.root.join(format!("CafeFinData-{OP}")),
            backup_source: None,
            source_root_id: ROOT.into(),
            source_fingerprint: "11".repeat(32),
            candidate_root_id: None,
            candidate_fingerprint: None,
            manifest_sha256: None,
            phase: MaintenancePhase::Intent,
        };
        store.begin(&journal).unwrap();
        (store, journal)
    }
}
impl Drop for Fixture {
    fn drop(&mut self) {
        if let Ok(path) = self.root.canonicalize() {
            if path.starts_with(&self.temp)
                && path != self.temp
                && path
                    .file_name()
                    .unwrap()
                    .to_string_lossy()
                    .starts_with("cafe-fin-transition-test-")
                && check_local_path(&path).is_ok()
            {
                let _ = fs::remove_dir_all(&path);
            }
        }
    }
}

struct Host {
    config: PathBuf,
    source_alive: bool,
    candidate: Option<BootSession>,
    events: Vec<&'static str>,
    close_failure: Option<&'static str>,
    fail_start: bool,
    fail_activation: bool,
    replay: bool,
    activated: bool,
    source_dormant: bool,
    changed_hash: bool,
    changed_activation_hash: bool,
}
impl Host {
    fn new(fixture: &Fixture) -> Self {
        Self {
            config: fixture.config.clone(),
            source_alive: true,
            candidate: None,
            events: vec![],
            close_failure: None,
            fail_start: false,
            fail_activation: false,
            replay: false,
            activated: false,
            source_dormant: false,
            changed_hash: false,
            changed_activation_hash: false,
        }
    }
    fn status_reply(
        &self,
        journal: &NativeJournal,
        state: &str,
        runtime: &str,
    ) -> MaintenanceReply {
        serde_json::from_value(serde_json::json!({"maintenance_protocol":1,"request_id":REQ,"generation":if self.candidate.is_some(){TARGET_GEN}else{GEN},
            "operation_id":OP,"status":"ok","state":state,"runtime_state":runtime,"kind":"move",
            "source_root_id":ROOT,"candidate_root_id":ROOT,"source_fingerprint":"11".repeat(32),"candidate_fingerprint":"22".repeat(32),
            "manifest_sha256":if self.changed_hash {"cd".repeat(32)} else {journal.manifest_sha256.clone().unwrap_or_else(||"ab".repeat(32))}})).unwrap()
    }
}
impl TransitionHost for Host {
    fn verify_root(
        &mut self,
        _: &NativeJournal,
        token: &str,
        side: RootSide,
    ) -> TransitionResult<()> {
        match side {
            RootSide::Source if token == "synthetic-source-admin" => {
                self.events.push("fresh-source-auth")
            }
            RootSide::Candidate if token == "synthetic-target-admin" => {
                self.events.push("fresh-target-auth")
            }
            _ => return Err("PERMISSION_DENIED".into()),
        }
        Ok(())
    }
    fn call(
        &mut self,
        command: ControlCommand,
        journal: &NativeJournal,
        _: &str,
    ) -> TransitionResult<MaintenanceReply> {
        let saved = JournalStore::new(&self.config)?
            .load()?
            .ok_or("JOURNAL_MISSING")?;
        match command {
            ControlCommand::Quiesce => {
                assert_eq!(saved.phase, MaintenancePhase::Intent);
                self.events.push("quiesce-after-intent");
                Ok(self.status_reply(journal, "QUIESCED", "QUIESCED"))
            }
            ControlCommand::Prepare => {
                assert_eq!(saved.phase, MaintenancePhase::Quiesced);
                self.events.push("prepare-after-quiesce");
                fs::create_dir(&journal.destination).unwrap();
                Ok(self.status_reply(journal, "PREPARED", "QUIESCED"))
            }
            ControlCommand::Status => {
                self.events.push("status");
                if self.candidate.is_some() {
                    Ok(self.status_reply(
                        journal,
                        if self.replay {
                            "REPLAY_REQUIRED"
                        } else if self.activated {
                            "ACTIVE"
                        } else {
                            "DORMANT"
                        },
                        if self.activated { "ACTIVE" } else { "DORMANT" },
                    ))
                } else {
                    Ok(self.status_reply(
                        journal,
                        "PREPARED",
                        if self.source_dormant {
                            "DORMANT"
                        } else {
                            "QUIESCED"
                        },
                    ))
                }
            }
            ControlCommand::Activate => {
                assert!(matches!(
                    saved.phase,
                    MaintenancePhase::ActivationDispatched | MaintenancePhase::Active
                ));
                self.events.push("activate-after-durable-dispatch");
                if self.fail_activation {
                    self.replay = true;
                    return Err("ACTIVATION_REPLAY_REQUIRED".into());
                }
                self.activated = true;
                self.changed_hash = self.changed_activation_hash;
                Ok(self.status_reply(journal, "ACTIVE", "ACTIVE"))
            }
            _ => Err("UNEXPECTED_FIXTURE_COMMAND".into()),
        }
    }
    fn close_source(&mut self, journal: &NativeJournal, _: &str) -> TransitionResult<CloseProof> {
        self.events.push("close");
        let mut proof = CloseProof::new(GEN.into(), journal.operation_id.clone(), REQ.into());
        if self.close_failure != Some("missing-ack") {
            proof.acknowledge(GEN, OP, REQ, "CLOSED", true).unwrap();
        }
        proof.observe_exit(if self.close_failure == Some("nonzero") {
            Some(86)
        } else {
            Some(0)
        });
        self.source_alive = false;
        Ok(proof)
    }
    fn source_live(&mut self, _: &NativeJournal) -> TransitionResult<bool> {
        Ok(self.source_alive)
    }
    fn attach_candidate(&mut self, _: &NativeJournal) -> TransitionResult<Option<BootSession>> {
        Ok(self.candidate.clone())
    }
    fn start_candidate(&mut self, journal: &NativeJournal) -> TransitionResult<BootSession> {
        let store = JournalStore::new(&self.config)?;
        assert!(matches!(
            store.load()?.unwrap().phase,
            MaintenancePhase::ConfigSwitched
                | MaintenancePhase::CandidateDormant
                | MaintenancePhase::ActivationDispatched
                | MaintenancePhase::Active
        ));
        assert_eq!(
            store.configured_root()?.unwrap().canonicalize().unwrap(),
            journal.destination.canonicalize().unwrap()
        );
        assert!(!self.source_alive);
        self.events.push("candidate-after-config-and-closed");
        if self.fail_start {
            return Err("CANDIDATE_START_FAILED".into());
        }
        let boot = BootSession {
            protocol_version: 1,
            api_base: "http://127.0.0.1:48888/api/v1".into(),
            session_token: "synthetic-target-app-session-only".into(),
            data_root: journal.destination.to_str().unwrap().into(),
            maintenance_protocol: Some(1),
            generation: Some(TARGET_GEN.into()),
            runtime_state: Some(RuntimeState::Dormant),
            pending_transition: Some(journal.summary(true)),
        };
        self.candidate = Some(boot.clone());
        Ok(boot)
    }
}

#[test]
fn move_gates_then_explicit_fresh_target_activation_without_new_boot_boundary() {
    let fixture = Fixture::new();
    let (store, journal) = fixture.journal();
    let mut host = Host::new(&fixture);
    let moved =
        native_transition::run(&mut host, &store, journal, "synthetic-source-admin").unwrap();
    assert!(!moved.completed);
    assert_eq!(moved.journal.phase, MaintenancePhase::CandidateDormant);
    assert_eq!(
        moved.boot_session.unwrap().generation.as_deref(),
        Some(TARGET_GEN)
    );
    assert!(!host.events.contains(&"activate-after-durable-dispatch"));
    let done =
        native_transition::activate(&mut host, &store, moved.journal, "synthetic-target-admin")
            .unwrap();
    assert!(done.completed);
    assert!(done.boot_session.is_none());
    assert!(store.load().unwrap().is_none());
    assert!(store.completed(OP).unwrap().is_some());
    assert!(done.journal.source_root.is_dir());
}

#[test]
fn missing_ack_or_nonzero_exit_retains_source_config_and_prepared_journal() {
    for failure in ["missing-ack", "nonzero"] {
        let fixture = Fixture::new();
        let (store, journal) = fixture.journal();
        let source = journal.source_root.clone();
        let mut host = Host::new(&fixture);
        host.close_failure = Some(failure);
        assert_eq!(
            native_transition::run(&mut host, &store, journal, "synthetic-source-admin")
                .err()
                .as_deref(),
            Some("CLOSE_PROOF_REQUIRED")
        );
        assert_eq!(
            store.load().unwrap().unwrap().phase,
            MaintenancePhase::Prepared
        );
        assert_eq!(store.configured_root().unwrap().unwrap(), source);
        assert!(source.is_dir());
        assert!(!host.events.contains(&"candidate-after-config-and-closed"));
    }
}

#[test]
fn candidate_failure_never_falls_back_and_same_candidate_can_retry_dormant() {
    let fixture = Fixture::new();
    let (store, journal) = fixture.journal();
    let target = journal.destination.clone();
    let mut host = Host::new(&fixture);
    host.fail_start = true;
    assert_eq!(
        native_transition::run(&mut host, &store, journal, "synthetic-source-admin")
            .err()
            .as_deref(),
        Some("CANDIDATE_START_FAILED")
    );
    let held = store.load().unwrap().unwrap();
    assert_eq!(held.phase, MaintenancePhase::ConfigSwitched);
    assert_eq!(
        store.configured_root().unwrap().unwrap(),
        target.canonicalize().unwrap()
    );
    host.fail_start = false;
    let resumed =
        native_transition::run(&mut host, &store, held, "synthetic-source-admin").unwrap();
    assert_eq!(resumed.journal.phase, MaintenancePhase::CandidateDormant);
    assert!(resumed.journal.source_root.is_dir());
    assert_eq!(
        host.events
            .iter()
            .filter(|event| **event == "close")
            .count(),
        1
    );
}

#[test]
fn source_token_cannot_activate_target_and_partial_activation_is_not_replayed() {
    let fixture = Fixture::new();
    let (store, journal) = fixture.journal();
    let mut host = Host::new(&fixture);
    let moved =
        native_transition::run(&mut host, &store, journal, "synthetic-source-admin").unwrap();
    assert_eq!(
        native_transition::activate(
            &mut host,
            &store,
            moved.journal.clone(),
            "synthetic-source-admin"
        )
        .err()
        .as_deref(),
        Some("PERMISSION_DENIED")
    );
    assert_eq!(
        store.load().unwrap().unwrap().phase,
        MaintenancePhase::CandidateDormant
    );
    host.fail_activation = true;
    assert_eq!(
        native_transition::activate(&mut host, &store, moved.journal, "synthetic-target-admin")
            .err()
            .as_deref(),
        Some("ACTIVATION_REPLAY_REQUIRED")
    );
    let held = store.load().unwrap().unwrap();
    assert_eq!(held.phase, MaintenancePhase::ActivationDispatched);
    assert_eq!(
        native_transition::activate(&mut host, &store, held, "synthetic-target-admin")
            .err()
            .as_deref(),
        Some("ACTIVATION_REPLAY_REQUIRED")
    );
    assert_eq!(
        host.events
            .iter()
            .filter(|event| **event == "activate-after-durable-dispatch")
            .count(),
        1
    );
    assert!(store.load().unwrap().unwrap().source_root.is_dir());
}

#[test]
fn dormant_source_prepared_recovery_closes_with_fresh_auth_before_cutover() {
    let fixture = Fixture::new();
    let (store, journal) = fixture.journal();
    let mut host = Host::new(&fixture);
    host.close_failure = Some("missing-ack");
    let _ = native_transition::run(&mut host, &store, journal, "synthetic-source-admin");
    let held = store.load().unwrap().unwrap();
    host.close_failure = None;
    host.source_alive = true;
    host.source_dormant = true;
    let resumed =
        native_transition::run(&mut host, &store, held, "synthetic-source-admin").unwrap();
    assert_eq!(resumed.journal.phase, MaintenancePhase::CandidateDormant);
    assert!(host.events.contains(&"fresh-source-auth"));
}

#[test]
fn changed_activation_receipt_never_archives_or_clears_pending() {
    let fixture = Fixture::new();
    let (store, journal) = fixture.journal();
    let mut host = Host::new(&fixture);
    let moved =
        native_transition::run(&mut host, &store, journal, "synthetic-source-admin").unwrap();
    host.changed_activation_hash = true;
    assert_eq!(
        native_transition::activate(&mut host, &store, moved.journal, "synthetic-target-admin")
            .err()
            .as_deref(),
        Some("ACTIVATION_BINDING_INVALID")
    );
    assert_eq!(
        store.load().unwrap().unwrap().phase,
        MaintenancePhase::ActivationDispatched
    );
    assert!(store.completed(OP).unwrap().is_none());
}

#[test]
fn fresh_active_status_completes_lost_ack_without_new_boot_or_activation() {
    let fixture = Fixture::new();
    let (store, journal) = fixture.journal();
    let mut host = Host::new(&fixture);
    let moved =
        native_transition::run(&mut host, &store, journal, "synthetic-source-admin").unwrap();
    let mut saved = moved.journal;
    saved.phase = MaintenancePhase::ActivationDispatched;
    store.advance(&saved).unwrap();
    host.activated = true;
    let reply = host
        .call(ControlCommand::Status, &saved, "synthetic-target-admin")
        .unwrap();
    assert!(native_transition::finish_from_status(&store, &mut saved, &reply, true).unwrap());
    assert!(store.load().unwrap().is_none());
    assert_eq!(
        store.completed(OP).unwrap().unwrap().phase,
        MaintenancePhase::Active
    );
    assert!(!host.events.contains(&"activate-after-durable-dispatch"));
    assert!(native_transition::finish_from_status(&store, &mut saved, &reply, true).unwrap());
    assert!(saved.source_root.is_dir());
}
