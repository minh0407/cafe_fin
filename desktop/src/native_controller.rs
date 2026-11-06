//! Production native adapter. Compiled by the desktop binary, not the standalone
//! synthetic-host harness. All methods run under the desktop lifecycle mutex.
use cafe_fin_desktop::{
    control::{
        ControlCommand, ControlPipe, ControlReply, ControlRequest, MaintenanceReply,
        OperationState, ReplyStatus, ReportsReply,
    },
    maintenance_dto::{
        BootSession, DesktopStatus, MaintenanceKind, MaintenancePhase, MaintenanceResult,
        MaintenanceView, RuntimeState, SelectionPurpose,
    },
    native_attach::{attach_existing, ExistingChild},
    native_draft::{DraftSlot, SelectionTicket},
    native_guards::{CloseProof, PickerHandles},
    native_journal::{JournalStore, NativeJournal, StartupDisposition},
    native_paths::check_local_path,
    native_transition::{self, RootSide, TransitionHost, TransitionResult},
};
use serde::Deserialize;
use std::{
    io::Write,
    path::{Path, PathBuf},
    process::{Child, ChildStdin, Command, Stdio},
    time::{Duration, Instant},
};

const STARTUP: Duration = Duration::from_secs(20);
const CONTROL_WAIT: Duration = Duration::from_secs(30);

pub fn fresh_id() -> String {
    let mut bytes: [u8; 16] = rand::random();
    bytes[6] = (bytes[6] & 15) | 64;
    bytes[8] = (bytes[8] & 63) | 128;
    let hex: String = bytes.iter().map(|byte| format!("{byte:02x}")).collect();
    format!(
        "{}-{}-{}-{}-{}",
        &hex[..8],
        &hex[8..12],
        &hex[12..16],
        &hex[16..20],
        &hex[20..]
    )
}
fn fresh_nonce() -> String {
    let bytes: [u8; 32] = rand::random();
    bytes.iter().map(|byte| format!("{byte:02x}")).collect()
}
fn same_path(a: &Path, b: &Path) -> bool {
    a.canonicalize()
        .ok()
        .zip(b.canonicalize().ok())
        .is_some_and(|(a, b)| a == b)
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Handshake {
    protocol_version: u32,
    status: String,
    api_base: String,
    maintenance_protocol: Option<u32>,
    generation: Option<String>,
    runtime_state: Option<RuntimeState>,
    code: Option<String>,
    message: Option<String>,
    state: Option<OperationState>,
}

struct Backend {
    child: Child,
    control: ControlPipe<ChildStdin>,
    session: BootSession,
    generation: String,
    verified: bool,
    pending_close: Option<CloseProof>,
}
impl ExistingChild for Backend {
    fn generation(&self) -> &str {
        &self.generation
    }
    fn verified(&self) -> bool {
        self.verified
    }
    fn check_alive(&mut self) -> Result<(), &'static str> {
        match self.child.try_wait() {
            Ok(None) => Ok(()),
            _ => Err("SIDECAR_NOT_RUNNING"),
        }
    }
    fn check_health(&mut self) -> Result<(), &'static str> {
        #[derive(Deserialize)]
        struct Health {
            status: String,
            protocol_version: u32,
        }
        let client = reqwest::blocking::Client::builder()
            .timeout(Duration::from_secs(1))
            .no_proxy()
            .redirect(reqwest::redirect::Policy::none())
            .build()
            .map_err(|_| "HEALTH_CLIENT_FAILED")?;
        let response = client
            .get(format!("{}/health", self.session.api_base))
            .header("X-App-Session", &self.session.session_token)
            .send()
            .ok()
            .filter(|response| response.status().is_success())
            .and_then(|response| response.json::<Health>().ok());
        if response.is_some_and(|health| health.status == "ok" && health.protocol_version == 1) {
            Ok(())
        } else {
            Err("SIDECAR_HEALTH_FAILED")
        }
    }
    fn session(&self) -> &BootSession {
        &self.session
    }
}
impl Backend {
    fn frame(
        &mut self,
        command: ControlCommand,
        journal: Option<&NativeJournal>,
        token: &str,
    ) -> TransitionResult<ControlReply> {
        self.check_alive()?;
        let request_id = fresh_id();
        let request = ControlRequest {
            maintenance_protocol: 1,
            request_id: &request_id,
            generation: &self.generation,
            command,
            operation_id: journal.map(|journal| journal.operation_id.as_str()),
            origin_generation: journal.map(|journal| journal.origin_generation.as_str()),
            access_token: token,
            kind: if command == ControlCommand::Prepare {
                journal.map(|journal| journal.kind)
            } else {
                None
            },
            destination: if command == ControlCommand::Prepare {
                journal.map(|journal| journal.destination.as_path())
            } else {
                None
            },
            backup_source: if command == ControlCommand::Prepare {
                journal.and_then(|journal| journal.backup_source.as_deref())
            } else {
                None
            },
        };
        self.control.send(&request)?;
        self.receive(CONTROL_WAIT)
    }
    fn receive(&mut self, timeout: Duration) -> TransitionResult<ControlReply> {
        let response = self.control.receive(timeout)?;
        self.session.runtime_state = Some(match &response {
            ControlReply::Maintenance(reply) => reply.runtime_state,
            ControlReply::Reports(reply) | ControlReply::Identity(reply) => reply.runtime_state,
        });
        Ok(response)
    }
    fn close_proof(
        &mut self,
        journal: &NativeJournal,
        token: &str,
    ) -> TransitionResult<CloseProof> {
        if self.pending_close.is_none() {
            let reply = match self.frame(ControlCommand::Close, Some(journal), token)? {
                ControlReply::Maintenance(reply) => reply,
                _ => return Err("CONTROL_RESPONSE_MISMATCH".into()),
            };
            native_transition::core_ok(&reply)?;
            let mut proof = CloseProof::new(
                reply.generation.clone(),
                journal.operation_id.clone(),
                reply.request_id.clone(),
            );
            proof
                .acknowledge(
                    &reply.generation,
                    &reply.operation_id,
                    &reply.request_id,
                    "CLOSED",
                    reply.state == OperationState::Closed
                        && reply.runtime_state == RuntimeState::Closed,
                )
                .map_err(|error| error.code())?;
            self.pending_close = Some(proof);
        }
        self.observe_close()
    }
    fn observe_close(&mut self) -> TransitionResult<CloseProof> {
        let deadline = Instant::now() + STARTUP;
        loop {
            match self.child.try_wait() {
                Ok(Some(status)) => {
                    self.verified = false;
                    let mut proof = self.pending_close.take().ok_or("CLOSE_PROOF_REQUIRED")?;
                    proof.observe_exit(status.code());
                    if !proof.is_clean() {
                        return Err("SHUTDOWN_FAILED".into());
                    }
                    let reader_deadline = Instant::now() + Duration::from_secs(1);
                    loop {
                        match self.control.finish_reader() {
                            Ok(()) => break,
                            Err("CONTROL_READER_PENDING") if Instant::now() < reader_deadline => {
                                std::thread::sleep(Duration::from_millis(5))
                            }
                            Err(code) => {
                                proof.mark_unclean();
                                return Err(code.into());
                            }
                        }
                    }
                    self.session.runtime_state = Some(RuntimeState::Closed);
                    return Ok(proof);
                }
                Ok(None) if Instant::now() < deadline => {
                    std::thread::sleep(Duration::from_millis(25))
                }
                Ok(None) => return Err("CLOSE_EXIT_PENDING".into()),
                Err(_) => return Err("CLOSE_EXIT_UNKNOWN".into()),
            }
        }
    }
    fn ordinary_shutdown(&mut self) {
        let _ = self.control.send_legacy_shutdown();
        let deadline = Instant::now() + Duration::from_secs(8);
        while Instant::now() < deadline {
            if matches!(self.child.try_wait(), Ok(Some(_))) {
                return;
            }
            std::thread::sleep(Duration::from_millis(50));
        }
        // Ordinary app exit only: no journal advance, CLOSED proof or config switch.
        let _ = self.child.kill();
        let _ = self.child.wait();
    }
}

fn command() -> TransitionResult<Command> {
    let beside = std::env::current_exe()
        .map_err(|_| "SIDECAR_MISSING")?
        .parent()
        .ok_or("SIDECAR_MISSING")?
        .join("cafe-fin-sidecar.exe");
    if beside.is_file() {
        return Ok(Command::new(beside));
    }
    #[cfg(debug_assertions)]
    {
        let root = Path::new(env!("CARGO_MANIFEST_DIR"))
            .parent()
            .ok_or("SIDECAR_MISSING")?;
        let packaged = root.join("desktop/binaries/cafe-fin-sidecar-x86_64-pc-windows-msvc.exe");
        if packaged.is_file() {
            return Ok(Command::new(packaged));
        }
        let python = root.join(".venv/Scripts/python.exe");
        if python.is_file() {
            let mut command = Command::new(python);
            command
                .args(["-m", "cafe_fin"])
                .current_dir(root.join("backend"));
            return Ok(command);
        }
    }
    Err("SIDECAR_MISSING".into())
}
fn spawn(
    root: &Path,
    initialize: bool,
    dormant: bool,
    pending: Option<&NativeJournal>,
) -> TransitionResult<Backend> {
    check_local_path(root)?;
    if !root.exists() && !initialize {
        return Err("DATA_ROOT_UNAVAILABLE".into());
    }
    let generation = fresh_id();
    let token = fresh_nonce();
    let mut command = command()?;
    command
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::null());
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        command.creation_flags(0x08000000);
    }
    let mut child = command.spawn().map_err(|_| "SIDECAR_START_FAILED")?;
    let outcome = (|| -> TransitionResult<(ControlPipe<ChildStdin>, BootSession, String)> {
        let mut stdin = child.stdin.take().ok_or("SIDECAR_PIPE_FAILED")?;
        let stdout = child.stdout.take().ok_or("SIDECAR_PIPE_FAILED")?;
        let origin = if cfg!(debug_assertions) {
            "http://127.0.0.1:1420"
        } else {
            "http://tauri.localhost"
        };
        let mut frame=serde_json::to_vec(&serde_json::json!({"protocol_version":1,"maintenance_protocol":1,"generation":generation,
            "activation_mode":if dormant{"dormant"}else{"active"},"session_token":token,"data_root":root,"initialize":initialize,"allowed_origin":origin})).map_err(|_|"BOOT_PROTOCOL_INVALID")?;
        frame.push(b'\n');
        if frame.len() > 262144 {
            return Err("BOOT_PROTOCOL_INVALID".into());
        }
        stdin
            .write_all(&frame)
            .and_then(|_| stdin.flush())
            .map_err(|_| "SIDECAR_PIPE_FAILED")?;
        let mut control = ControlPipe::new(stdin, stdout);
        let raw = control.boot_frame(STARTUP)?;
        let handshake: Handshake =
            serde_json::from_slice(&raw).map_err(|_| "SIDECAR_PROTOCOL_MISMATCH")?;
        if handshake.status == "error" {
            let code = handshake
                .code
                .filter(|code| {
                    !code.is_empty()
                        && code.len() <= 64
                        && code.bytes().all(|byte| {
                            byte.is_ascii_uppercase() || byte.is_ascii_digit() || byte == b'_'
                        })
                })
                .unwrap_or_else(|| "SIDECAR_START_FAILED".into());
            return Err(code);
        }
        if handshake.code.is_some() || handshake.message.is_some() || handshake.state.is_some() {
            return Err("SIDECAR_PROTOCOL_MISMATCH".into());
        }
        let valid = reqwest::Url::parse(&handshake.api_base).is_ok_and(|url| {
            url.scheme() == "http"
                && url.host_str() == Some("127.0.0.1")
                && url.port().is_some()
                && url.path() == "/api/v1"
                && url.username().is_empty()
                && url.password().is_none()
                && url.query().is_none()
                && url.fragment().is_none()
        });
        let expected = if dormant {
            RuntimeState::Dormant
        } else {
            RuntimeState::Active
        };
        if handshake.protocol_version != 1
            || handshake.status != "ready"
            || handshake.maintenance_protocol != Some(1)
            || handshake.generation.as_deref() != Some(generation.as_str())
            || handshake.runtime_state != Some(expected)
            || !valid
        {
            return Err("SIDECAR_PROTOCOL_MISMATCH".into());
        }
        let session = BootSession {
            protocol_version: 1,
            api_base: handshake.api_base,
            session_token: token,
            data_root: root
                .canonicalize()
                .map_err(|_| "DATA_ROOT_UNAVAILABLE")?
                .to_str()
                .ok_or("DATA_ROOT_UNAVAILABLE")?
                .into(),
            maintenance_protocol: Some(1),
            generation: Some(generation.clone()),
            runtime_state: Some(expected),
            pending_transition: pending.map(|journal| journal.summary(true)),
        };
        Ok((control, session, generation))
    })();
    match outcome {
        Ok((control, session, generation)) => {
            let mut backend = Backend {
                child,
                control,
                session,
                generation,
                verified: true,
                pending_close: None,
            };
            let deadline = Instant::now() + STARTUP;
            loop {
                if backend.check_alive().is_err() {
                    backend.ordinary_shutdown();
                    return Err("SIDECAR_START_FAILED".into());
                }
                if backend.check_health().is_ok() {
                    return Ok(backend);
                }
                if Instant::now() >= deadline {
                    backend.ordinary_shutdown();
                    return Err("SIDECAR_HEALTH_FAILED".into());
                }
                std::thread::sleep(Duration::from_millis(50));
            }
        }
        Err(error) => {
            let _ = child.kill();
            let _ = child.wait();
            Err(error)
        }
    }
}

#[derive(Default)]
pub struct NativeController {
    selected_root: Option<PathBuf>,
    backend: Option<Backend>,
    draft: DraftSlot,
    handles: Option<PickerHandles>,
    pub startup_error: Option<String>,
}

impl NativeController {
    fn current(&mut self, store: &JournalStore) -> TransitionResult<&mut Backend> {
        let backend = self.backend.as_mut().ok_or("MAINTENANCE_UNAVAILABLE")?;
        if !backend.verified
            || backend.session.maintenance_protocol != Some(1)
            || backend.control.is_broken()
        {
            return Err("MAINTENANCE_RECOVERY_HELD".into());
        }
        backend.check_alive()?;
        let configured = store.configured_root()?.ok_or("CONFIG_UNAVAILABLE")?;
        if !same_path(&configured, Path::new(&backend.session.data_root)) {
            return Err("CONFIG_JOURNAL_CONFLICT".into());
        }
        Ok(backend)
    }
    fn reset_draft(&mut self) {
        self.draft = DraftSlot::default();
        self.handles = self
            .backend
            .as_ref()
            .map(|backend| PickerHandles::new(backend.generation.clone()));
    }
    fn identity(&mut self, store: &JournalStore, token: &str) -> TransitionResult<ReportsReply> {
        let reply = match self
            .current(store)?
            .frame(ControlCommand::SourceIdentity, None, token)?
        {
            ControlReply::Identity(reply) => reply,
            _ => return Err("CONTROL_RESPONSE_MISMATCH".into()),
        };
        if reply.status == ReplyStatus::Error {
            return Err(reply.code.unwrap_or_else(|| "PERMISSION_DENIED".into()));
        }
        Ok(reply)
    }
    fn view(
        &self,
        journal: &NativeJournal,
        complete: bool,
        can_activate: bool,
    ) -> TransitionResult<MaintenanceView> {
        let backend = self.backend.as_ref().ok_or("MAINTENANCE_RECOVERY_HELD")?;
        Ok(MaintenanceView {
            operation_id: journal.operation_id.clone(),
            kind: journal.kind,
            phase: if complete {
                MaintenancePhase::Active
            } else {
                journal.phase
            },
            recovery_required: !complete,
            generation: backend.generation.clone(),
            runtime_state: backend.session.runtime_state,
            destination_display: Some(
                journal
                    .destination
                    .to_str()
                    .ok_or("NATIVE_PATH_INVALID")?
                    .into(),
            ),
            backup_source_display: journal
                .backup_source
                .as_ref()
                .map(|path| {
                    path.to_str()
                        .map(str::to_owned)
                        .ok_or("NATIVE_PATH_INVALID")
                })
                .transpose()?,
            ready: false,
            can_activate,
        })
    }
    fn update_pending(&mut self, store: &JournalStore) -> TransitionResult<()> {
        let journal = store.load()?;
        if let Some(backend) = &mut self.backend {
            backend.session.pending_transition =
                journal.as_ref().map(|journal| journal.summary(true));
        }
        Ok(())
    }
    pub fn status(&mut self, store: &JournalStore) -> TransitionResult<DesktopStatus> {
        let journal = store.load()?;
        let configured = store.configured_root()?;
        let running = self
            .backend
            .as_mut()
            .is_some_and(|backend| matches!(backend.child.try_wait(), Ok(None)));
        let verified = self.backend.as_ref().filter(|backend| {
            running
                && backend.verified
                && configured
                    .as_ref()
                    .is_some_and(|root| same_path(root, Path::new(&backend.session.data_root)))
        });
        let pending = if let Some(journal) = &journal {
            Some(journal.summary(true))
        } else if let (Some(handles), Some(_)) = (&self.handles, self.draft.operation_id()) {
            Some(self.draft.view(
                store,
                handles,
                verified.and_then(|backend| backend.session.runtime_state),
            )?)
            .map(
                |view| cafe_fin_desktop::maintenance_dto::PendingTransition {
                    operation_id: view.operation_id,
                    kind: view.kind,
                    phase: view.phase,
                    recovery_required: view.recovery_required,
                },
            )
        } else {
            None
        };
        Ok(DesktopStatus {
            data_root: configured
                .or_else(|| self.selected_root.clone())
                .map(|path| path.to_string_lossy().into()),
            running,
            maintenance_protocol: verified.and_then(|backend| backend.session.maintenance_protocol),
            generation: verified.map(|backend| backend.generation.clone()),
            runtime_state: verified.and_then(|backend| backend.session.runtime_state),
            pending_transition: pending,
        })
    }
    pub fn choose_allowed(&self, store: &JournalStore) -> TransitionResult<()> {
        if store.load()?.is_some() || self.backend.is_some() || self.draft.is_busy() {
            return Err("MAINTENANCE_RECOVERY_HELD".into());
        }
        Ok(())
    }
    pub fn choose_root(&mut self, store: &JournalStore, path: PathBuf) -> TransitionResult<String> {
        self.choose_allowed(store)?;
        check_local_path(&path)?;
        let label = path.to_str().ok_or("NATIVE_PATH_INVALID")?.into();
        self.selected_root = Some(path);
        Ok(label)
    }
    pub fn start(
        &mut self,
        store: &JournalStore,
        initialize: bool,
    ) -> TransitionResult<BootSession> {
        let journal = store.load()?;
        if let Some(journal) = &journal {
            let configured = store.configured_root()?.ok_or("CONFIG_UNAVAILABLE")?;
            journal.reconcile_config(&configured)?;
            if let Some(backend) = &self.backend {
                if !same_path(Path::new(&backend.session.data_root), &configured) {
                    return Err("MAINTENANCE_RECOVERY_HELD".into());
                }
            }
        }
        let pending = journal.as_ref().map(|journal| journal.summary(true));
        if let Some(boot) = attach_existing(self.backend.as_mut(), pending.as_ref(), initialize)? {
            return Ok(boot);
        }
        if self.startup_error.is_some() {
            return Err("MAINTENANCE_RECOVERY_HELD".into());
        }
        let root = self
            .selected_root
            .clone()
            .or(store.configured_root()?)
            .ok_or("DATA_ROOT_REQUIRED")?;
        let mut backend = spawn(&root, initialize, false, None)?;
        let saved = store
            .save_initial_root(&root, &backend.generation)
            .and_then(|()| {
                let configured = store.configured_root()?.ok_or("CONFIG_WRITE_FAILED")?;
                if !same_path(&configured, &root) {
                    return Err("CONFIG_WRITE_FAILED");
                }
                Ok(())
            });
        if let Err(error) = saved {
            backend.ordinary_shutdown();
            return Err(error.into());
        }
        self.selected_root = None;
        let session = backend.session.clone();
        self.backend = Some(backend);
        self.reset_draft();
        Ok(session)
    }
    pub fn restart(&mut self, store: &JournalStore) -> TransitionResult<BootSession> {
        if store.load()?.is_some()
            || self.draft.is_busy()
            || self.draft.has_uncertain_effects()
            || self.backend.as_ref().is_some_and(|backend| {
                backend.control.pending_request().is_some() || backend.pending_close.is_some()
            })
        {
            return Err("MAINTENANCE_RECOVERY_HELD".into());
        }
        // Restart always follows durable config, never a first-install picker
        // choice retained from an earlier root/generation.
        store.configured_root()?.ok_or("CONFIG_UNAVAILABLE")?;
        self.selected_root = None;
        if let Some(mut backend) = self.backend.take() {
            backend.ordinary_shutdown();
        }
        self.reset_draft();
        self.start(store, false)
    }
    pub fn begin(
        &mut self,
        store: &JournalStore,
        kind: MaintenanceKind,
    ) -> TransitionResult<MaintenanceView> {
        let backend = self.current(store)?;
        if backend.control.pending_request().is_some()
            || backend.session.runtime_state != Some(RuntimeState::Active)
        {
            return Err("MAINTENANCE_RECOVERY_HELD".into());
        }
        let generation = backend.generation.clone();
        let runtime = backend.session.runtime_state;
        let handles = self.handles.as_mut().ok_or("MAINTENANCE_UNAVAILABLE")?;
        self.draft
            .begin(fresh_id(), generation, kind, store, handles)?;
        Ok(self.draft.view(store, handles, runtime)?)
    }
    pub fn select_begin(
        &mut self,
        store: &JournalStore,
        operation: &str,
        purpose: SelectionPurpose,
    ) -> TransitionResult<SelectionTicket> {
        let backend = self.current(store)?;
        if backend.control.pending_request().is_some() {
            return Err("CONTROL_REQUEST_PENDING".into());
        }
        let generation = backend.generation.clone();
        Ok(self
            .draft
            .start_selection(operation, &generation, purpose, store)?)
    }
    pub fn select_finish(
        &mut self,
        store: &JournalStore,
        ticket: SelectionTicket,
        path: Option<PathBuf>,
    ) -> TransitionResult<Option<MaintenanceView>> {
        let runtime = self.current(store)?.session.runtime_state;
        let handles = self.handles.as_mut().ok_or("MAINTENANCE_UNAVAILABLE")?;
        self.draft.finish_selection(
            ticket,
            path.as_deref(),
            if path.is_some() {
                fresh_nonce()
            } else {
                String::new()
            },
            store,
            handles,
        )?;
        if path.is_none() {
            Ok(None)
        } else {
            Ok(Some(self.draft.view(store, handles, runtime)?))
        }
    }
    pub fn open_reports(&mut self, store: &JournalStore, token: &str) -> TransitionResult<()> {
        if store.load()?.is_some() {
            return Err("MAINTENANCE_REQUIRED".into());
        }
        self.settle_pending(store, None)?;
        let backend = self.current(store)?;
        let generation = backend.generation.clone();
        let reply = match backend.frame(ControlCommand::ReportsAuthorizeOpen, None, token)? {
            ControlReply::Reports(reply) => reply,
            _ => return Err("CONTROL_RESPONSE_MISMATCH".into()),
        };
        if reply.status != ReplyStatus::Ok || reply.allowed != Some(true) {
            return Err(reply.code.unwrap_or_else(|| "PERMISSION_DENIED".into()));
        }
        if !backend.verified || backend.generation != generation {
            return Err("MAINTENANCE_RECOVERY_HELD".into());
        }
        backend.check_alive()?;
        #[cfg(windows)]
        cafe_fin_desktop::native_paths::open_reports(Path::new(&backend.session.data_root))?;
        #[cfg(not(windows))]
        return Err("WINDOWS_REQUIRED".into());
        Ok(())
    }
    pub fn run(
        &mut self,
        store: &JournalStore,
        operation: &str,
        token: &str,
    ) -> TransitionResult<MaintenanceResult> {
        self.settle_pending(store, Some(operation))?;
        let journal = if let Some(journal) = store.load()? {
            if journal.operation_id != operation {
                return Err("MAINTENANCE_CONFLICT".into());
            }
            journal
        } else {
            let backend = self.current(store)?;
            let generation = backend.generation.clone();
            let root = PathBuf::from(&backend.session.data_root);
            let runtime = backend.session.runtime_state;
            let handles = self.handles.as_ref().ok_or("MAINTENANCE_UNAVAILABLE")?;
            let view = self.draft.view(store, handles, runtime)?;
            if view.operation_id != operation || !view.ready {
                return Err("DRAFT_NOT_READY".into());
            }
            let (destination, backup_source) = self.draft.selected_paths(store, handles)?;
            if destination
                .try_exists()
                .map_err(|_| "NATIVE_PATH_UNAVAILABLE")?
            {
                return Err("MAINTENANCE_DESTINATION_EXISTS".into());
            }
            let identity = self.identity(store, token)?;
            if identity.runtime_state != RuntimeState::Active {
                return Err("MAINTENANCE_REQUIRED".into());
            }
            let journal = NativeJournal {
                format: 1,
                operation_id: operation.into(),
                kind: view.kind,
                origin_generation: generation,
                source_root: root,
                destination,
                backup_source,
                source_root_id: identity.root_id.ok_or("CONTROL_RESPONSE_INVALID")?,
                source_fingerprint: identity
                    .source_fingerprint
                    .ok_or("CONTROL_RESPONSE_INVALID")?,
                candidate_root_id: None,
                candidate_fingerprint: None,
                manifest_sha256: None,
                phase: MaintenancePhase::Intent,
            };
            journal.validate()?;
            self.draft.mark_intent_attempted(operation)?;
            store.begin(&journal)?
        };
        let result = {
            let mut host = Host {
                controller: self,
                store,
            };
            native_transition::run(&mut host, store, journal, token)
        };
        self.update_pending(store)?;
        let mut outcome = result?;
        if outcome.completed {
            self.reset_draft();
        }
        let view = self.view(&outcome.journal, outcome.completed, false)?;
        if let Some(boot) = &mut outcome.boot_session {
            boot.pending_transition = Some(outcome.journal.summary(true));
        }
        Ok(MaintenanceResult {
            operation: view,
            boot_session: outcome.boot_session,
        })
    }
    pub fn activate(
        &mut self,
        store: &JournalStore,
        operation: &str,
        token: &str,
    ) -> TransitionResult<MaintenanceResult> {
        self.settle_pending(store, Some(operation))?;
        let journal = store.load()?.ok_or("MAINTENANCE_OPERATION_NOT_FOUND")?;
        if journal.operation_id != operation {
            return Err("MAINTENANCE_CONFLICT".into());
        }
        let result = {
            let mut host = Host {
                controller: self,
                store,
            };
            native_transition::activate(&mut host, store, journal, token)
        };
        self.update_pending(store)?;
        let outcome = result?;
        self.reset_draft();
        Ok(MaintenanceResult {
            operation: self.view(&outcome.journal, true, false)?,
            boot_session: None,
        })
    }
    pub fn operation_status(
        &mut self,
        store: &JournalStore,
        operation: &str,
        token: &str,
    ) -> TransitionResult<MaintenanceResult> {
        self.settle_pending(store, Some(operation))?;
        let pending = store.load()?;
        let saved = match pending {
            Some(journal) => Some(journal),
            None => store.completed(operation)?,
        };
        let Some(mut journal) = saved else {
            let identity = self.identity(store, token)?;
            let handles = self.handles.as_ref().ok_or("MAINTENANCE_UNAVAILABLE")?;
            let view = self
                .draft
                .view(store, handles, Some(identity.runtime_state))?;
            if view.operation_id != operation {
                return Err("MAINTENANCE_CONFLICT".into());
            }
            return Ok(MaintenanceResult {
                operation: view,
                boot_session: None,
            });
        };
        if journal.operation_id != operation {
            return Err("MAINTENANCE_CONFLICT".into());
        }
        if journal.phase == MaintenancePhase::OldClosed {
            let backend = self
                .current(store)
                .map_err(|_| "MAINTENANCE_RECOVERY_HELD")?;
            backend
                .check_health()
                .map_err(|_| "MAINTENANCE_RECOVERY_HELD")?;
        }
        let candidate = self.backend.as_ref().is_some_and(|backend| {
            same_path(Path::new(&backend.session.data_root), &journal.destination)
        });
        let mut host = Host {
            controller: self,
            store,
        };
        host.verify_root(
            &journal,
            token,
            if candidate {
                RootSide::Candidate
            } else {
                RootSide::Source
            },
        )?;
        let reply = host.call(ControlCommand::Status, &journal, token)?;
        if reply.status == ReplyStatus::Error {
            if reply.code.as_deref() == Some("MAINTENANCE_OPERATION_NOT_FOUND")
                && matches!(
                    journal.phase,
                    MaintenancePhase::Intent | MaintenancePhase::Quiesced
                )
            {
                return Ok(MaintenanceResult {
                    operation: host.controller.view(&journal, false, false)?,
                    boot_session: None,
                });
            }
            native_transition::core_ok(&reply)?;
        }
        let complete = if candidate || reply.state == OperationState::Prepared {
            native_transition::finish_from_status(store, &mut journal, &reply, candidate)?
        } else {
            false
        };
        let can_activate = candidate
            && !complete
            && reply.state == OperationState::Dormant
            && reply.runtime_state == RuntimeState::Dormant
            && matches!(
                journal.phase,
                MaintenancePhase::CandidateDormant
                    | MaintenancePhase::ActivationDispatched
                    | MaintenancePhase::Active
            );
        host.controller.update_pending(store)?;
        if complete {
            host.controller.reset_draft();
        }
        Ok(MaintenanceResult {
            operation: host.controller.view(&journal, complete, can_activate)?,
            boot_session: None,
        })
    }
    fn settle_pending(
        &mut self,
        store: &JournalStore,
        operation: Option<&str>,
    ) -> TransitionResult<()> {
        let Some(backend) = &mut self.backend else {
            return Ok(());
        };
        if let Some(request) = backend.control.pending_request() {
            if request
                .operation_id
                .as_deref()
                .is_some_and(|saved| Some(saved) != operation)
            {
                return Err("CONTROL_REQUEST_PENDING".into());
            }
            let reply = backend.receive(Duration::ZERO)?;
            if let ControlReply::Maintenance(reply) = reply {
                native_transition::core_ok(&reply)?;
                let mut journal = store.load()?.ok_or("JOURNAL_MISSING")?;
                if journal.operation_id != reply.operation_id {
                    return Err("JOURNAL_CONFLICT".into());
                }
                match request.command {
                    ControlCommand::Quiesce if journal.phase == MaintenancePhase::Intent => {
                        journal.phase = MaintenancePhase::Quiesced;
                        store.advance(&journal)?;
                    }
                    ControlCommand::Prepare => {
                        let prepared = native_transition::prepared_binding(&journal, &reply)?;
                        store.advance(&prepared)?;
                    }
                    ControlCommand::Close => {
                        let mut proof = CloseProof::new(
                            reply.generation.clone(),
                            reply.operation_id.clone(),
                            reply.request_id.clone(),
                        );
                        proof
                            .acknowledge(
                                &reply.generation,
                                &reply.operation_id,
                                &reply.request_id,
                                "CLOSED",
                                reply.state == OperationState::Closed
                                    && reply.runtime_state == RuntimeState::Closed,
                            )
                            .map_err(|error| error.code())?;
                        backend.pending_close = Some(proof);
                    }
                    // The minimal activation ACK is not the artifact receipt.
                    // Leave ACTIVATION_DISPATCHED until fresh status authenticates
                    // the caller and verifies every saved candidate binding.
                    ControlCommand::Activate => {}
                    _ => {}
                }
            }
            // A late read-only identity/reports authorization never triggers an OS
            // open or grants the new caller permission; its new call reauthenticates.
        }
        if backend.pending_close.is_some() {
            let proof = backend.observe_close()?;
            let mut journal = store.load()?.ok_or("JOURNAL_MISSING")?;
            journal.phase = MaintenancePhase::OldClosed;
            store.record_closed(&journal, &proof)?;
        }
        self.update_pending(store)
    }
    pub fn bootstrap_recovery(&mut self, store: &JournalStore) -> TransitionResult<()> {
        let Some(mut journal) = store.load()? else {
            return Ok(());
        };
        let configured = store.configured_root()?.ok_or("CONFIG_UNAVAILABLE")?;
        let disposition = journal.reconcile_config(&configured)?;
        let (root, dormant) = match disposition {
            StartupDisposition::OnlineBackupSource => (journal.source_root.clone(), false),
            StartupDisposition::SourceDormant => (journal.source_root.clone(), true),
            StartupDisposition::ReconcileConfig => {
                store.switch_candidate(&journal)?;
                journal.phase = MaintenancePhase::ConfigSwitched;
                store.advance(&journal)?;
                (journal.destination.clone(), true)
            }
            StartupDisposition::CandidateDormant => (journal.destination.clone(), true),
        };
        if same_path(&root, &journal.destination) {
            journal.verify_candidate_marker()?;
        }
        self.backend = Some(spawn(&root, false, dormant, Some(&journal))?);
        self.reset_draft();
        if journal.phase == MaintenancePhase::ConfigSwitched {
            journal.phase = MaintenancePhase::CandidateDormant;
            store.advance(&journal)?;
        }
        self.update_pending(store)
    }
    pub fn shutdown(&mut self) {
        if let Some(mut backend) = self.backend.take() {
            backend.ordinary_shutdown();
        }
    }
}

#[cfg(test)]
#[path = "../../tests/desktop/production_controller.rs"]
mod production_tests;

struct Host<'a> {
    controller: &'a mut NativeController,
    store: &'a JournalStore,
}
impl TransitionHost for Host<'_> {
    fn verify_root(
        &mut self,
        journal: &NativeJournal,
        token: &str,
        side: RootSide,
    ) -> TransitionResult<()> {
        let expected = if side == RootSide::Source {
            &journal.source_root
        } else {
            &journal.destination
        };
        if !self
            .controller
            .backend
            .as_ref()
            .is_some_and(|backend| same_path(Path::new(&backend.session.data_root), expected))
        {
            return Err("MAINTENANCE_SOURCE_CONFLICT".into());
        }
        let identity = self.controller.identity(self.store, token)?;
        let (id, fp) = if side == RootSide::Source {
            (
                Some(journal.source_root_id.as_str()),
                Some(journal.source_fingerprint.as_str()),
            )
        } else {
            (
                journal.candidate_root_id.as_deref(),
                journal.candidate_fingerprint.as_deref(),
            )
        };
        if identity.root_id.as_deref() != id || identity.source_fingerprint.as_deref() != fp {
            return Err("MAINTENANCE_SOURCE_CONFLICT".into());
        }
        Ok(())
    }
    fn call(
        &mut self,
        command: ControlCommand,
        journal: &NativeJournal,
        token: &str,
    ) -> TransitionResult<MaintenanceReply> {
        match self
            .controller
            .current(self.store)?
            .frame(command, Some(journal), token)?
        {
            ControlReply::Maintenance(reply) => Ok(reply),
            _ => Err("CONTROL_RESPONSE_MISMATCH".into()),
        }
    }
    fn close_source(
        &mut self,
        journal: &NativeJournal,
        token: &str,
    ) -> TransitionResult<CloseProof> {
        self.controller
            .current(self.store)?
            .close_proof(journal, token)
    }
    fn source_live(&mut self, journal: &NativeJournal) -> TransitionResult<bool> {
        let Some(backend) = &mut self.controller.backend else {
            return Ok(false);
        };
        match backend.child.try_wait() {
            Ok(Some(_)) => Ok(false),
            Ok(None) => {
                if same_path(Path::new(&backend.session.data_root), &journal.source_root) {
                    Ok(true)
                } else if same_path(Path::new(&backend.session.data_root), &journal.destination) {
                    Ok(false)
                } else {
                    Err("MAINTENANCE_SOURCE_CONFLICT".into())
                }
            }
            Err(_) => Err("CLOSE_EXIT_UNKNOWN".into()),
        }
    }
    fn attach_candidate(
        &mut self,
        journal: &NativeJournal,
    ) -> TransitionResult<Option<BootSession>> {
        let Some(backend) = &mut self.controller.backend else {
            return Ok(None);
        };
        if !same_path(Path::new(&backend.session.data_root), &journal.destination) {
            return if matches!(backend.child.try_wait(), Ok(Some(_))) {
                Ok(None)
            } else {
                Err("MAINTENANCE_RECOVERY_HELD".into())
            };
        }
        if matches!(backend.child.try_wait(), Ok(Some(_))) {
            return Ok(None);
        }
        let pending = journal.summary(true);
        Ok(attach_existing(Some(backend), Some(&pending), false)?)
    }
    fn start_candidate(&mut self, journal: &NativeJournal) -> TransitionResult<BootSession> {
        if self
            .controller
            .backend
            .as_mut()
            .is_some_and(|backend| !matches!(backend.child.try_wait(), Ok(Some(_))))
        {
            return Err("MAINTENANCE_RECOVERY_HELD".into());
        }
        self.controller.backend = None;
        let configured = self.store.configured_root()?.ok_or("CONFIG_UNAVAILABLE")?;
        journal.reconcile_config(&configured)?;
        if !same_path(&configured, &journal.destination) {
            return Err("CONFIG_JOURNAL_CONFLICT".into());
        }
        journal.verify_candidate_marker()?;
        let backend = spawn(&journal.destination, false, true, Some(journal))?;
        let session = backend.session.clone();
        self.controller.backend = Some(backend);
        self.controller.reset_draft();
        Ok(session)
    }
}
