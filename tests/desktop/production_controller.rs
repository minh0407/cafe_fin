//! Headless production-adapter probes. These use the normal frozen-sidecar
//! resolver, actual controller/store, private pipe and loopback auth. No Tauri
//! window, substituted spawn, mock server, OS Explorer action or external send.
use super::*;
use serde_json::{json, Value};
use std::{fs, io::Read};

const PASSWORD: &str = "synthetic-production-adapter-password";

struct Fixture {
    root: PathBuf,
    temp: PathBuf,
    controller: NativeController,
    store: JournalStore,
}
impl Fixture {
    fn new() -> Self {
        let expected = Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("binaries/cafe-fin-sidecar-x86_64-pc-windows-msvc.exe");
        let resolved =
            command().expect("normal production resolver must find matching frozen sidecar");
        assert_eq!(
            Path::new(resolved.get_program()).canonicalize().unwrap(),
            expected.canonicalize().unwrap(),
            "probe requires the genuine worktree frozen sidecar; no Python fallback"
        );
        let temp = std::env::temp_dir().canonicalize().unwrap();
        let root = temp.join(format!(
            "cafe-fin-controller-test-{}-{}",
            std::process::id(),
            fresh_id()
        ));
        fs::create_dir(&root).unwrap();
        let store = JournalStore::new(&root.join("config")).unwrap();
        Self {
            root,
            temp,
            controller: NativeController::default(),
            store,
        }
    }
    fn directory(&self, name: &str) -> PathBuf {
        let path = self.root.join(name);
        fs::create_dir(&path).unwrap();
        path
    }
    fn initial(&mut self) -> (BootSession, String, String) {
        self.controller
            .choose_root(&self.store, self.root.join("Nguồn đầu tiên"))
            .unwrap();
        let boot = self.controller.start(&self.store, true).unwrap();
        assert!(
            self.controller.selected_root.is_none(),
            "initial choice must be consumed after durable config readback"
        );
        let admin = login(&boot, true, "adapter-admin");
        request(
            &boot,
            &admin,
            "POST",
            "/users",
            Some(
                json!({"username":"adapter-operator","password":PASSWORD,"role":"operator","request_key":fresh_id()}),
            ),
        );
        let operator = login(&boot, false, "adapter-operator");
        (boot, admin, operator)
    }
    fn select(
        &mut self,
        operation: &str,
        purpose: SelectionPurpose,
        path: PathBuf,
    ) -> MaintenanceView {
        let ticket = self
            .controller
            .select_begin(&self.store, operation, purpose)
            .unwrap();
        self.controller
            .select_finish(&self.store, ticket, Some(path))
            .unwrap()
            .unwrap()
    }
    fn draft(
        &mut self,
        kind: MaintenanceKind,
        parent: PathBuf,
        backup: Option<PathBuf>,
    ) -> MaintenanceView {
        let view = self.controller.begin(&self.store, kind).unwrap();
        if let Some(backup) = backup {
            self.select(&view.operation_id, SelectionPurpose::BackupSource, backup);
        }
        self.select(&view.operation_id, SelectionPurpose::Destination, parent)
    }
}
impl Drop for Fixture {
    fn drop(&mut self) {
        self.controller.shutdown(); // Product cleanup; never accepted as transition proof.
        if let Ok(root) = self.root.canonicalize() {
            if root.starts_with(&self.temp)
                && root != self.temp
                && root
                    .file_name()
                    .unwrap()
                    .to_string_lossy()
                    .starts_with("cafe-fin-controller-test-")
                && check_local_path(&root).is_ok()
            {
                let _ = fs::remove_dir_all(root);
            }
        }
    }
}

fn http(
    boot: &BootSession,
    token: Option<&str>,
    method: &str,
    path: &str,
    body: Option<Value>,
) -> Value {
    let client = reqwest::blocking::Client::builder()
        .timeout(Duration::from_secs(10))
        .no_proxy()
        .redirect(reqwest::redirect::Policy::none())
        .build()
        .unwrap();
    let mut request = client
        .request(method.parse().unwrap(), format!("{}{path}", boot.api_base))
        .header("X-App-Session", &boot.session_token);
    if let Some(token) = token {
        request = request.bearer_auth(token);
    }
    if let Some(body) = body {
        request = request.json(&body);
    }
    let response = request
        .send()
        .expect("actual loopback request must finish within deadline");
    assert!(
        response.status().is_success(),
        "synthetic loopback request must succeed"
    );
    let mut bytes = Vec::new();
    response.take(65537).read_to_end(&mut bytes).unwrap();
    assert!(bytes.len() <= 65536, "bounded synthetic response required");
    serde_json::from_slice(&bytes).expect("actual loopback JSON")
}
fn request(
    boot: &BootSession,
    token: &str,
    method: &str,
    path: &str,
    body: Option<Value>,
) -> Value {
    http(boot, Some(token), method, path, body)
}
fn login(boot: &BootSession, setup: bool, username: &str) -> String {
    let result = http(
        boot,
        None,
        "POST",
        if setup { "/auth/setup" } else { "/auth/login" },
        Some(json!({"username":username,"password":PASSWORD})),
    );
    result["access_token"]
        .as_str()
        .expect("synthetic auth token")
        .into()
}
fn assert_root(boot: &BootSession, expected: &Path, store: &JournalStore) {
    assert_eq!(
        Path::new(&boot.data_root).canonicalize().unwrap(),
        expected.canonicalize().unwrap()
    );
    assert_eq!(
        store
            .configured_root()
            .unwrap()
            .unwrap()
            .canonicalize()
            .unwrap(),
        expected.canonicalize().unwrap()
    );
}

#[test]
#[ignore = "Permitted Windows runner only; first build the matching genuine frozen sidecar"]
fn frozen_controller_backup_move_restore_and_restart_keep_configured_target() {
    let mut fixture = Fixture::new();
    let (source, source_admin, source_operator) = fixture.initial();
    let source_root = PathBuf::from(&source.data_root);
    let backup_parent = fixture.directory("Bản sao độc lập");
    let backup = fixture.draft(MaintenanceKind::Backup, backup_parent, None);
    assert!(fixture
        .controller
        .operation_status(&fixture.store, &backup.operation_id, &source_operator)
        .is_err());
    assert!(fixture
        .controller
        .run(&fixture.store, &backup.operation_id, &source_operator)
        .is_err());
    assert!(
        fixture.store.load().unwrap().is_none(),
        "Operator must not create native INTENT"
    );
    let backed_up = fixture
        .controller
        .run(&fixture.store, &backup.operation_id, &source_admin)
        .unwrap();
    assert!(backed_up.boot_session.is_none());
    assert_eq!(
        backed_up.operation.runtime_state,
        Some(RuntimeState::Active)
    );
    assert!(!backed_up.operation.recovery_required);
    assert!(fixture.store.load().unwrap().is_none());
    let backup_path = PathBuf::from(backed_up.operation.destination_display.unwrap());
    assert!(backup_path.join("backup-manifest.json").is_file());
    assert_eq!(
        fixture.controller.backend.as_ref().unwrap().generation,
        source.generation.as_deref().unwrap()
    );

    let move_parent = fixture.directory("Đích chuyển dữ liệu");
    let moving = fixture.draft(MaintenanceKind::Move, move_parent, None);
    let moved = fixture
        .controller
        .run(&fixture.store, &moving.operation_id, &source_admin)
        .unwrap();
    let target = moved
        .boot_session
        .expect("new dormant child must establish a fresh session boundary");
    assert_ne!(target.generation, source.generation);
    assert_eq!(target.runtime_state, Some(RuntimeState::Dormant));
    let moved_root = PathBuf::from(&target.data_root);
    assert_root(&target, &moved_root, &fixture.store);
    assert_ne!(moved_root, source_root);
    assert!(source_root.is_dir());
    assert!(
        fixture
            .controller
            .operation_status(&fixture.store, &moving.operation_id, &source_admin)
            .is_err(),
        "source token cannot authorize target status"
    );
    assert!(
        fixture
            .controller
            .activate(&fixture.store, &moving.operation_id, &source_admin)
            .is_err(),
        "source token cannot activate target"
    );
    let target_admin = login(&target, false, "adapter-admin");
    let target_operator = login(&target, false, "adapter-operator");
    assert!(fixture
        .controller
        .operation_status(&fixture.store, &moving.operation_id, &target_operator)
        .is_err());
    let held = fixture
        .controller
        .operation_status(&fixture.store, &moving.operation_id, &target_admin)
        .unwrap();
    assert!(held.boot_session.is_none());
    assert!(held.operation.can_activate);
    let activated = fixture
        .controller
        .activate(&fixture.store, &moving.operation_id, &target_admin)
        .unwrap();
    assert!(activated.boot_session.is_none());
    assert!(!activated.operation.recovery_required);
    assert_eq!(
        activated.operation.runtime_state,
        Some(RuntimeState::Active)
    );
    assert!(fixture.store.load().unwrap().is_none());
    let restarted = fixture.controller.restart(&fixture.store).unwrap();
    assert_root(&restarted, &moved_root, &fixture.store);
    assert_ne!(restarted.generation, target.generation);
    assert_eq!(restarted.runtime_state, Some(RuntimeState::Active));
    assert!(source_root.is_dir());

    let restarted_admin = login(&restarted, false, "adapter-admin");
    let restore_parent = fixture.directory("Đích khôi phục dữ liệu");
    let restoring = fixture.draft(
        MaintenanceKind::Restore,
        restore_parent,
        Some(backup_path.clone()),
    );
    let restored = fixture
        .controller
        .run(&fixture.store, &restoring.operation_id, &restarted_admin)
        .unwrap()
        .boot_session
        .unwrap();
    assert_eq!(restored.runtime_state, Some(RuntimeState::Dormant));
    let restored_root = PathBuf::from(&restored.data_root);
    assert_root(&restored, &restored_root, &fixture.store);
    assert!(fixture
        .controller
        .activate(&fixture.store, &restoring.operation_id, &restarted_admin)
        .is_err());
    let restored_admin = login(&restored, false, "adapter-admin");
    let restored_operator = login(&restored, false, "adapter-operator");
    assert!(fixture
        .controller
        .operation_status(&fixture.store, &restoring.operation_id, &restored_operator)
        .is_err());
    fixture
        .controller
        .activate(&fixture.store, &restoring.operation_id, &restored_admin)
        .unwrap();
    let settings = request(
        &restored,
        &restored_admin,
        "GET",
        "/reporting/settings",
        None,
    );
    assert_eq!(settings["enabled"], false);
    assert_eq!(settings["auto_generate_daily"], false);
    assert_eq!(settings["restore_review_required"], true);
    assert_eq!(settings["sender_status"], "RESTORE_SUSPENDED");
    let final_boot = fixture.controller.restart(&fixture.store).unwrap();
    assert_root(&final_boot, &restored_root, &fixture.store);
    assert_ne!(final_boot.generation, restored.generation);
    let final_admin = login(&final_boot, false, "adapter-admin");
    let settings = request(
        &final_boot,
        &final_admin,
        "GET",
        "/reporting/settings",
        None,
    );
    assert_eq!(settings["restore_review_required"], true);
    assert_eq!(settings["enabled"], false);
    assert!(source_root.is_dir());
    assert!(moved_root.is_dir());
    assert!(backup_path.is_dir());
}

#[test]
#[ignore = "Permitted Windows runner only; first build the matching genuine frozen sidecar"]
fn frozen_controller_old_closed_dead_source_never_returns_authenticated_view() {
    let mut fixture = Fixture::new();
    let (source, admin, operator) = fixture.initial();
    let parent = fixture.directory("Đích chưa chuyển config");
    let draft = fixture.draft(MaintenanceKind::Move, parent, None);
    let identity = fixture.controller.identity(&fixture.store, &admin).unwrap();
    let (destination, backup_source) = fixture
        .controller
        .draft
        .selected_paths(&fixture.store, fixture.controller.handles.as_ref().unwrap())
        .unwrap();
    let mut journal = NativeJournal {
        format: 1,
        operation_id: draft.operation_id.clone(),
        kind: MaintenanceKind::Move,
        origin_generation: source.generation.clone().unwrap(),
        source_root: PathBuf::from(&source.data_root),
        destination,
        backup_source,
        source_root_id: identity.root_id.unwrap(),
        source_fingerprint: identity.source_fingerprint.unwrap(),
        candidate_root_id: None,
        candidate_fingerprint: None,
        manifest_sha256: None,
        phase: MaintenancePhase::Intent,
    };
    fixture
        .controller
        .draft
        .mark_intent_attempted(&journal.operation_id)
        .unwrap();
    fixture.store.begin(&journal).unwrap();
    {
        // Deliberately stop the real adapter at the durable OLD_CLOSED boundary.
        // Every child, authorization, copy and CLOSED/exit proof below is real;
        // only the subsequent config-switch step is withheld for this fault case.
        let mut host = Host {
            controller: &mut fixture.controller,
            store: &fixture.store,
        };
        host.verify_root(&journal, &admin, RootSide::Source)
            .unwrap();
        let quiesced = host
            .call(ControlCommand::Quiesce, &journal, &admin)
            .unwrap();
        native_transition::core_ok(&quiesced).unwrap();
        journal.phase = MaintenancePhase::Quiesced;
        fixture.store.advance(&journal).unwrap();
        let prepared = host
            .call(ControlCommand::Prepare, &journal, &admin)
            .unwrap();
        journal = native_transition::prepared_binding(&journal, &prepared).unwrap();
        fixture.store.advance(&journal).unwrap();
        let proof = host.close_source(&journal, &admin).unwrap();
        journal.phase = MaintenancePhase::OldClosed;
        fixture.store.record_closed(&journal, &proof).unwrap();
    }
    fixture.controller.update_pending(&fixture.store).unwrap();
    let dead_pid = fixture.controller.backend.as_ref().unwrap().child.id();
    for token in ["invalid-synthetic-token", operator.as_str(), admin.as_str()] {
        assert_eq!(
            fixture
                .controller
                .operation_status(&fixture.store, &journal.operation_id, token)
                .err()
                .as_deref(),
            Some("MAINTENANCE_RECOVERY_HELD")
        );
        assert_eq!(
            fixture.controller.backend.as_ref().unwrap().child.id(),
            dead_pid,
            "status must not spawn a replacement"
        );
        assert!(!fixture.controller.status(&fixture.store).unwrap().running);
        assert_eq!(
            fixture.store.load().unwrap().unwrap().phase,
            MaintenancePhase::OldClosed
        );
        assert_eq!(
            fixture.store.configured_root().unwrap().unwrap(),
            journal.source_root
        );
    }
    fixture.controller.backend = None; // Also cover no child, not just a dead handle.
    assert_eq!(
        fixture
            .controller
            .operation_status(
                &fixture.store,
                &journal.operation_id,
                "invalid-synthetic-token"
            )
            .err()
            .as_deref(),
        Some("MAINTENANCE_RECOVERY_HELD")
    );
    let bounded = fixture.controller.status(&fixture.store).unwrap();
    assert!(!bounded.running);
    assert!(bounded.generation.is_none());
    assert_eq!(
        bounded.pending_transition.unwrap().phase,
        MaintenancePhase::OldClosed
    );
    assert!(journal.source_root.is_dir());
    assert!(journal.destination.is_dir());
}
