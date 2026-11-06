//! Actual Rust codec <-> production Python entrypoint, loopback HTTP and core.
//! Run explicitly on permitted CI, never to work around host AppControl.
use cafe_fin_native_checks::{
    control::{
        ControlCommand, ControlPipe, ControlReply, ControlRequest, MaintenanceReply,
        OperationState, ReplyStatus,
    },
    maintenance_dto::{MaintenanceKind, MaintenancePhase, RuntimeState},
    native_guards::CloseProof,
    native_journal::NativeJournal,
    native_paths::check_local_path,
    native_transition::{candidate_binding, prepared_binding},
};
use serde_json::{json, Value};
use std::{
    fs,
    io::{Read, Write},
    net::TcpStream,
    path::{Path, PathBuf},
    process::{Child, ChildStdin, Command, Stdio},
    time::{Duration, Instant},
};

const GEN: &str = "00000000-0000-4000-8000-000000000002";
const TARGET_GEN: &str = "00000000-0000-4000-8000-000000000005";
const OP: &str = "00000000-0000-4000-8000-000000000001";
const APP: &str = "synthetic-rust-python-app-session-0123456789";
const PASSWORD: &str = "synthetic-rust-python-password";

fn sanitized_boot_code(boot: &Value) -> &str {
    boot.get("code")
        .and_then(Value::as_str)
        .filter(|code| {
            !code.is_empty()
                && code.len() <= 64
                && code
                    .bytes()
                    .all(|byte| byte.is_ascii_uppercase() || byte.is_ascii_digit() || byte == b'_')
        })
        .unwrap_or("BOOT_CODE_UNAVAILABLE")
}

struct Fixture {
    root: PathBuf,
    temp: PathBuf,
}
impl Fixture {
    fn new() -> Self {
        let temp = std::env::temp_dir().canonicalize().unwrap();
        let stamp = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let root = temp.join(format!("cafe-fin-wire-test-{}-{stamp}", std::process::id()));
        fs::create_dir(&root).unwrap();
        Self { root, temp }
    }
}
impl Drop for Fixture {
    fn drop(&mut self) {
        if let Ok(root) = self.root.canonicalize() {
            if root.starts_with(&self.temp)
                && root != self.temp
                && root
                    .file_name()
                    .unwrap()
                    .to_string_lossy()
                    .starts_with("cafe-fin-wire-test-")
                && check_local_path(&root).is_ok()
            {
                let _ = fs::remove_dir_all(root);
            }
        }
    }
}

struct Peer {
    child: Child,
    pipe: ControlPipe<ChildStdin>,
    generation: &'static str,
    base: String,
    seq: u64,
}
impl Peer {
    fn start(python: &Path, root: &Path, generation: &'static str, dormant: bool) -> Self {
        let repo = Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../..")
            .canonicalize()
            .unwrap();
        let mut child = Command::new(python)
            .args(["-m", "cafe_fin"])
            .current_dir(repo.join("backend"))
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::null())
            .spawn()
            .expect("production Python child must start");
        let mut stdin = child.stdin.take().unwrap();
        let stdout = child.stdout.take().unwrap();
        serde_json::to_writer(&mut stdin, &json!({"protocol_version":1,"maintenance_protocol":1,"generation":generation,
            "activation_mode":if dormant{"dormant"}else{"active"},"session_token":APP,"data_root":root,"initialize":!dormant,"allowed_origin":"http://tauri.localhost"})).unwrap();
        stdin.write_all(b"\n").unwrap();
        stdin.flush().unwrap();
        let mut pipe = ControlPipe::new(stdin, stdout);
        let raw = pipe
            .boot_frame(Duration::from_secs(30))
            .expect("production boot frame");
        let boot: Value = serde_json::from_slice(&raw).unwrap();
        assert!(
            boot["status"] == "ready",
            "production boot failed ({})",
            sanitized_boot_code(&boot)
        );
        assert_eq!(boot["generation"], generation);
        assert_eq!(boot["maintenance_protocol"], 1);
        assert_eq!(
            boot["runtime_state"],
            if dormant { "DORMANT" } else { "ACTIVE" }
        );
        Self {
            child,
            pipe,
            generation,
            base: boot["api_base"].as_str().unwrap().into(),
            seq: 0,
        }
    }
    fn login(&self, setup: bool) -> String {
        let address = self
            .base
            .strip_prefix("http://127.0.0.1:")
            .unwrap()
            .split('/')
            .next()
            .unwrap();
        let mut stream =
            TcpStream::connect(format!("127.0.0.1:{address}")).expect("loopback auth connection");
        stream
            .set_read_timeout(Some(Duration::from_secs(10)))
            .unwrap();
        stream
            .set_write_timeout(Some(Duration::from_secs(10)))
            .unwrap();
        let body =
            serde_json::to_vec(&json!({"username":"interop-admin","password":PASSWORD})).unwrap();
        let action = if setup { "setup" } else { "login" };
        write!(stream,"POST /api/v1/auth/{action} HTTP/1.0\r\nHost: 127.0.0.1:{address}\r\nX-App-Session: {APP}\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",body.len()).unwrap();
        stream.write_all(&body).unwrap();
        stream.flush().unwrap();
        let mut response = Vec::new();
        stream
            .take(65537)
            .read_to_end(&mut response)
            .expect("bounded auth response");
        assert!(response.len() <= 65536);
        let split = response
            .windows(4)
            .position(|bytes| bytes == b"\r\n\r\n")
            .expect("HTTP headers");
        let header = std::str::from_utf8(&response[..split]).unwrap();
        assert!(
            header.starts_with("HTTP/1.1 200 ") || header.starts_with("HTTP/1.0 200 "),
            "auth request must succeed"
        );
        let value: Value = serde_json::from_slice(&response[split + 4..]).expect("auth JSON");
        value["access_token"].as_str().expect("auth token").into()
    }
    fn call(
        &mut self,
        command: ControlCommand,
        token: &str,
        destination: Option<&Path>,
    ) -> ControlReply {
        self.seq += 1;
        let request_id = format!("00000000-0000-4000-8000-{:012x}", 100 + self.seq);
        let plain = matches!(
            command,
            ControlCommand::SourceIdentity | ControlCommand::ReportsAuthorizeOpen
        );
        self.pipe
            .send(&ControlRequest {
                maintenance_protocol: 1,
                request_id: &request_id,
                generation: self.generation,
                command,
                operation_id: if plain { None } else { Some(OP) },
                origin_generation: if plain { None } else { Some(GEN) },
                access_token: token,
                kind: destination.map(|_| MaintenanceKind::Move),
                destination,
                backup_source: None,
            })
            .expect("Rust encoder must accept actual request");
        self.pipe
            .receive(Duration::from_secs(30))
            .expect("Rust decoder must accept production response")
    }
    fn maintenance(
        &mut self,
        command: ControlCommand,
        token: &str,
        destination: Option<&Path>,
    ) -> MaintenanceReply {
        match self.call(command, token, destination) {
            ControlReply::Maintenance(reply) => reply,
            _ => panic!("operation reply expected"),
        }
    }
    fn closed(&mut self, token: &str) {
        let reply = self.maintenance(ControlCommand::Close, token, None);
        assert_eq!(reply.status, ReplyStatus::Ok);
        assert_eq!(reply.state, OperationState::Closed);
        assert_eq!(reply.runtime_state, RuntimeState::Closed);
        let mut proof = CloseProof::new(
            reply.generation.clone(),
            OP.into(),
            reply.request_id.clone(),
        );
        proof
            .acknowledge(&reply.generation, OP, &reply.request_id, "CLOSED", true)
            .unwrap();
        let deadline = Instant::now() + Duration::from_secs(20);
        loop {
            if let Some(status) = self.child.try_wait().unwrap() {
                proof.observe_exit(status.code());
                break;
            }
            assert!(Instant::now() < deadline, "observed clean exit required");
            std::thread::sleep(Duration::from_millis(20));
        }
        assert!(proof.is_clean());
    }
}
impl Drop for Peer {
    fn drop(&mut self) {
        // Cleanup is not closure evidence and never advances a native journal.
        if !matches!(self.child.try_wait(), Ok(Some(_))) {
            let _ = self.pipe.send_legacy_shutdown();
            let _ = self.child.kill();
            let _ = self.child.wait();
        }
    }
}

#[test]
#[ignore = "Requires permitted native execution and CAFE_FIN_TEST_PYTHON with locked dependencies"]
fn production_python_move_frames_roundtrip_through_rust_codec() {
    let python = PathBuf::from(
        std::env::var_os("CAFE_FIN_TEST_PYTHON")
            .expect("set CAFE_FIN_TEST_PYTHON explicitly on permitted CI"),
    );
    assert!(
        python.is_absolute() && python.is_file(),
        "explicit Python executable required"
    );
    let fixture = Fixture::new();
    let source = fixture.root.join("Nguồn dữ liệu");
    let target = fixture.root.join(format!("CafeFinData-{OP}"));
    let mut peer = Peer::start(&python, &source, GEN, false);
    let token = peer.login(true);
    let identity = match peer.call(ControlCommand::SourceIdentity, &token, None) {
        ControlReply::Identity(reply) => reply,
        _ => panic!("identity reply expected"),
    };
    assert_eq!(identity.status, ReplyStatus::Ok);
    let journal = NativeJournal {
        format: 1,
        operation_id: OP.into(),
        kind: MaintenanceKind::Move,
        origin_generation: GEN.into(),
        source_root: source.canonicalize().unwrap(),
        destination: target.clone(),
        backup_source: None,
        source_root_id: identity.root_id.unwrap(),
        source_fingerprint: identity.source_fingerprint.unwrap(),
        candidate_root_id: None,
        candidate_fingerprint: None,
        manifest_sha256: None,
        phase: MaintenancePhase::Intent,
    };
    assert_eq!(
        peer.maintenance(ControlCommand::Quiesce, &token, None)
            .runtime_state,
        RuntimeState::Quiesced
    );
    let prepared = peer.maintenance(ControlCommand::Prepare, &token, Some(&target));
    let journal = prepared_binding(&journal, &prepared).expect("actual prepared receipt binding");
    assert_eq!(prepared.runtime_state, RuntimeState::Quiesced);
    prepared_binding(
        &journal,
        &peer.maintenance(ControlCommand::Status, &token, None),
    )
    .unwrap();
    peer.closed(&token);
    let mut candidate = Peer::start(&python, &target, TARGET_GEN, true);
    let fresh = candidate.login(false);
    let denied = candidate.maintenance(ControlCommand::Activate, &token, None);
    assert_eq!(denied.status, ReplyStatus::Error);
    assert_eq!(denied.runtime_state, RuntimeState::Dormant);
    let dormant = candidate.maintenance(ControlCommand::Status, &fresh, None);
    candidate_binding(&journal, &dormant).unwrap();
    assert_eq!(dormant.runtime_state, RuntimeState::Dormant);
    let active = candidate.maintenance(ControlCommand::Activate, &fresh, None);
    assert_eq!(active.status, ReplyStatus::Ok);
    assert_eq!(active.state, OperationState::Active);
    assert!(active.kind.is_none());
    assert!(active.manifest_sha256.is_none());
    let status = candidate.maintenance(ControlCommand::Status, &fresh, None);
    candidate_binding(&journal, &status).unwrap();
    assert_eq!(status.runtime_state, RuntimeState::Active);
    candidate.closed(&fresh);
    assert!(source.is_dir());
    assert!(target.is_dir());
}
