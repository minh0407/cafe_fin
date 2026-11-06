#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use cafe_fin_desktop::{
    control::ControlPipe,
    maintenance_dto::{BootSession, DesktopStatus, PendingTransition, RuntimeState},
    native_attach::{attach_existing, ExistingChild},
    native_journal::{JournalStore, NativeJournal},
};
use serde::{Deserialize, Serialize};
use std::{
    fs,
    io::Write,
    path::{Path, PathBuf},
    process::{Child, ChildStdin, Command, Stdio},
    sync::{Arc, Mutex},
    time::{Duration, Instant},
};
use tauri::{Manager, State};
use tauri_plugin_dialog::DialogExt;

const PROTOCOL: u32 = 1;
const STARTUP_DEADLINE: Duration = Duration::from_secs(20);

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Handshake {
    protocol_version: u32,
    api_base: String,
    status: String,
    code: Option<String>,
    message: Option<String>,
    maintenance_protocol: Option<u32>,
    generation: Option<String>,
    runtime_state: Option<RuntimeState>,
}
#[derive(Serialize, Deserialize)]
struct MachineConfig {
    version: u32,
    data_root: String,
}
struct Backend {
    child: Child,
    control: ControlPipe<ChildStdin>,
    session: BootSession,
    generation: String,
    verified: bool,
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
        let client = health_client()?;
        if healthy(&client, &self.session.api_base, &self.session.session_token) {
            Ok(())
        } else {
            Err("SIDECAR_HEALTH_FAILED")
        }
    }
    fn session(&self) -> &BootSession {
        &self.session
    }
}
#[derive(Default)]
struct DesktopState {
    selected_root: Option<PathBuf>,
    backend: Option<Backend>,
}

fn config_path(app: &tauri::AppHandle) -> Result<PathBuf, String> {
    app.path()
        .app_config_dir()
        .map(|path| path.join("machine.json"))
        .map_err(|_| "CONFIG_UNAVAILABLE: Không truy cập được cấu hình máy.".into())
}

fn pending_journal(app: &tauri::AppHandle) -> Result<Option<NativeJournal>, String> {
    let directory = app
        .path()
        .app_config_dir()
        .map_err(|_| "MAINTENANCE_RECOVERY_HELD")?;
    JournalStore::new(&directory)
        .and_then(|store| store.load())
        .map_err(|_| "MAINTENANCE_RECOVERY_HELD: Chưa xác minh được nhật ký chuyển dữ liệu.".into())
}

fn pending_binding(
    app: &tauri::AppHandle,
    journal: &NativeJournal,
    backend: &Backend,
) -> Result<(), String> {
    let configured = configured_root(app)
        .map_err(|_| "MAINTENANCE_RECOVERY_HELD")?
        .ok_or("MAINTENANCE_RECOVERY_HELD")?;
    journal
        .reconcile_config(&configured)
        .map_err(|_| "MAINTENANCE_RECOVERY_HELD")?;
    let actual = Path::new(&backend.session.data_root);
    journal
        .reconcile_config(actual)
        .map_err(|_| "MAINTENANCE_RECOVERY_HELD")?;
    let configured = configured
        .canonicalize()
        .map_err(|_| "MAINTENANCE_RECOVERY_HELD")?;
    let actual = actual
        .canonicalize()
        .map_err(|_| "MAINTENANCE_RECOVERY_HELD")?;
    if actual != configured {
        return Err("MAINTENANCE_RECOVERY_HELD".into());
    }
    Ok(())
}

fn child_generation() -> String {
    let mut bytes: [u8; 16] = rand::random();
    bytes[6] = (bytes[6] & 0x0f) | 0x40;
    bytes[8] = (bytes[8] & 0x3f) | 0x80;
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

fn health_client() -> Result<reqwest::blocking::Client, &'static str> {
    reqwest::blocking::Client::builder()
        .timeout(Duration::from_secs(1))
        .no_proxy()
        .redirect(reqwest::redirect::Policy::none())
        .build()
        .map_err(|_| "HEALTH_CLIENT_FAILED")
}

fn healthy(client: &reqwest::blocking::Client, api_base: &str, token: &str) -> bool {
    #[derive(Deserialize)]
    struct Health {
        status: String,
        protocol_version: u32,
    }
    client
        .get(format!("{api_base}/health"))
        .header("X-App-Session", token)
        .send()
        .ok()
        .filter(|response| response.status().is_success())
        .and_then(|response| response.json::<Health>().ok())
        .is_some_and(|health| health.status == "ok" && health.protocol_version == PROTOCOL)
}
fn configured_root(app: &tauri::AppHandle) -> Result<Option<PathBuf>, String> {
    let path = config_path(app)?;
    if !path.exists() {
        return Ok(None);
    }
    let bytes = fs::read(path).map_err(|_| "CONFIG_UNAVAILABLE: Không đọc được cấu hình máy.")?;
    let config: MachineConfig = serde_json::from_slice(&bytes)
        .map_err(|_| "CONFIG_INVALID: Cấu hình máy không hợp lệ; không tự tạo dữ liệu mới.")?;
    if config.version != 1 {
        return Err("CONFIG_NEWER: Phiên bản cấu hình chưa được hỗ trợ.".into());
    }
    Ok(Some(PathBuf::from(config.data_root)))
}
fn save_root(app: &tauri::AppHandle, root: &Path) -> Result<(), String> {
    let path = config_path(app)?;
    fs::create_dir_all(path.parent().unwrap())
        .map_err(|_| "CONFIG_WRITE_FAILED: Không ghi được cấu hình máy.")?;
    let bytes = serde_json::to_vec(&MachineConfig {
        version: 1,
        data_root: root.to_string_lossy().into(),
    })
    .map_err(|_| "CONFIG_WRITE_FAILED")?;
    let temporary = path.with_extension("json.tmp");
    let mut file = fs::File::create(&temporary).map_err(|_| "CONFIG_WRITE_FAILED")?;
    file.write_all(&bytes)
        .and_then(|_| file.sync_all())
        .map_err(|_| "CONFIG_WRITE_FAILED")?;
    // std::fs::rename uses replacement semantics on Windows; never remove the old config first.
    fs::rename(&temporary, &path)
        .map_err(|_| "CONFIG_WRITE_FAILED: Không hoàn tất ghi cấu hình máy.")?;
    Ok(())
}
fn shutdown(backend: &mut Backend) {
    // Normal legacy exit only; journal-pending restart/cutover never calls this.
    let _ = backend.control.send_legacy_shutdown();
    let deadline = Instant::now() + Duration::from_secs(8);
    while Instant::now() < deadline {
        if backend.child.try_wait().ok().flatten().is_some() {
            return;
        }
        std::thread::sleep(Duration::from_millis(50));
    }
    let _ = backend.child.kill();
    let _ = backend.child.wait();
}
fn sidecar_command() -> Result<Command, String> {
    let beside = std::env::current_exe()
        .map_err(|_| "SIDECAR_MISSING")?
        .parent()
        .unwrap()
        .join("cafe-fin-sidecar.exe");
    if beside.exists() {
        return Ok(Command::new(beside));
    }
    #[cfg(debug_assertions)]
    {
        let root = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .parent()
            .unwrap()
            .to_path_buf();
        let packaged = root.join("desktop/binaries/cafe-fin-sidecar-x86_64-pc-windows-msvc.exe");
        if packaged.exists() {
            return Ok(Command::new(packaged));
        }
        let python = root.join(".venv/Scripts/python.exe");
        if python.exists() {
            let mut command = Command::new(python);
            command
                .args(["-m", "cafe_fin"])
                .current_dir(root.join("backend"));
            return Ok(command);
        }
    }
    Err("SIDECAR_MISSING: Thiếu backend đi kèm chương trình.".into())
}
fn spawn_backend(root: &Path, initialize: bool) -> Result<Backend, String> {
    if !root.exists() && !initialize {
        return Err(
            "DATA_ROOT_UNAVAILABLE: Thư mục đã chọn không có sẵn; không tự tạo dữ liệu rỗng."
                .into(),
        );
    }
    let bytes: [u8; 32] = rand::random();
    let token: String = bytes.iter().map(|byte| format!("{byte:02x}")).collect();
    let mut command = sidecar_command()?;
    command
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::null());
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        command.creation_flags(0x08000000);
    }
    let mut child = command
        .spawn()
        .map_err(|_| "SIDECAR_START_FAILED: Không mở được backend local.")?;
    let mut stdin = child.stdin.take().ok_or("SIDECAR_PIPE_FAILED")?;
    let stdout = child.stdout.take().ok_or("SIDECAR_PIPE_FAILED")?;
    let origin = if cfg!(debug_assertions) {
        "http://127.0.0.1:1420"
    } else {
        "http://tauri.localhost"
    };
    let request = serde_json::json!({ "protocol_version": PROTOCOL, "session_token": token, "data_root": root, "initialize": initialize, "allowed_origin": origin });
    if writeln!(stdin, "{request}")
        .and_then(|_| stdin.flush())
        .is_err()
    {
        let _ = child.kill();
        return Err("SIDECAR_PIPE_FAILED".into());
    }
    let mut control = ControlPipe::new(stdin, stdout);
    let deadline = Instant::now() + STARTUP_DEADLINE;
    let handshake = match control
        .boot_frame(STARTUP_DEADLINE)
        .ok()
        .and_then(|frame| serde_json::from_slice::<Handshake>(&frame).ok())
    {
        Some(value) => value,
        None => {
            let _ = child.kill();
            let _ = child.wait();
            return Err("SIDECAR_START_TIMEOUT: Backend chưa sẵn sàng trong 20 giây.".into());
        }
    };
    if handshake.status == "error" {
        let _ = child.kill();
        let _ = child.wait();
        return Err(format!(
            "{}: {}",
            handshake
                .code
                .unwrap_or_else(|| "SIDECAR_START_FAILED".into()),
            handshake
                .message
                .unwrap_or_else(|| "Không mở được dữ liệu local.".into())
        ));
    }
    let valid_url = reqwest::Url::parse(&handshake.api_base)
        .map(|url| {
            url.scheme() == "http"
                && url.host_str() == Some("127.0.0.1")
                && url.port().is_some()
                && url.path() == "/api/v1"
                && url.query().is_none()
                && url.fragment().is_none()
                && url.username().is_empty()
                && url.password().is_none()
        })
        .unwrap_or(false);
    // Legacy core has not negotiated maintenance yet. Do not advertise support
    // merely because a backend sends unsolicited new handshake fields.
    if handshake.protocol_version != PROTOCOL
        || handshake.status != "ready"
        || !valid_url
        || handshake.maintenance_protocol.is_some()
        || handshake.generation.is_some()
        || handshake.runtime_state.is_some()
    {
        let _ = child.kill();
        let _ = child.wait();
        return Err("SIDECAR_PROTOCOL_MISMATCH: Backend không tương thích.".into());
    }
    let client = match health_client() {
        Ok(client) => client,
        Err(code) => {
            let _ = child.kill();
            let _ = child.wait();
            return Err(code.into());
        }
    };
    loop {
        if healthy(&client, &handshake.api_base, &token) {
            break;
        }
        if Instant::now() >= deadline || child.try_wait().ok().flatten().is_some() {
            let _ = child.kill();
            let _ = child.wait();
            return Err("SIDECAR_HEALTH_FAILED: Không kết nối được backend local.".into());
        }
        std::thread::sleep(Duration::from_millis(100));
    }
    Ok(Backend {
        child,
        control,
        generation: child_generation(),
        verified: true,
        session: BootSession {
            protocol_version: PROTOCOL,
            api_base: handshake.api_base,
            session_token: token,
            data_root: root.to_string_lossy().into(),
            maintenance_protocol: None,
            generation: None,
            runtime_state: Some(RuntimeState::Active),
            pending_transition: None,
        },
    })
}

#[tauri::command]
async fn desktop_status(
    app: tauri::AppHandle,
    state: State<'_, Arc<Mutex<DesktopState>>>,
) -> Result<DesktopStatus, String> {
    let state = Arc::clone(state.inner());
    tauri::async_runtime::spawn_blocking(move || desktop_status_inner(&app, &state))
        .await
        .map_err(|_| "DESKTOP_TASK_FAILED".to_owned())?
}

fn desktop_status_inner(
    app: &tauri::AppHandle,
    state: &Mutex<DesktopState>,
) -> Result<DesktopStatus, String> {
    let mut state = state.lock().map_err(|_| "DESKTOP_STATE_FAILED")?;
    let journal = pending_journal(&app)?;
    let running = state
        .backend
        .as_mut()
        .map(|backend| matches!(backend.child.try_wait(), Ok(None)))
        .unwrap_or(false);
    let root = if journal.is_some() {
        configured_root(&app).map_err(|_| "MAINTENANCE_RECOVERY_HELD")?
    } else {
        state.selected_root.clone().or(configured_root(&app)?)
    };
    let verified = state.backend.as_ref().filter(|backend| {
        running
            && backend.verified
            && journal
                .as_ref()
                .is_none_or(|journal| pending_binding(&app, journal, backend).is_ok())
    });
    Ok(DesktopStatus {
        data_root: root.map(|path| path.to_string_lossy().into()),
        running,
        maintenance_protocol: verified.and_then(|backend| backend.session.maintenance_protocol),
        generation: verified.and_then(|backend| backend.session.generation.clone()),
        runtime_state: verified.and_then(|backend| backend.session.runtime_state),
        pending_transition: journal.as_ref().map(|journal| journal.summary(true)),
    })
}
#[tauri::command]
async fn choose_data_root(
    app: tauri::AppHandle,
    state: State<'_, Arc<Mutex<DesktopState>>>,
) -> Result<Option<String>, String> {
    let state = Arc::clone(state.inner());
    tauri::async_runtime::spawn_blocking(move || choose_data_root_inner(&app, &state))
        .await
        .map_err(|_| "DESKTOP_TASK_FAILED".to_owned())?
}

fn choose_data_root_inner(
    app: &tauri::AppHandle,
    state: &Mutex<DesktopState>,
) -> Result<Option<String>, String> {
    if pending_journal(&app)?.is_some() {
        return Err("MAINTENANCE_RECOVERY_HELD".into());
    }
    if state
        .lock()
        .map_err(|_| "DESKTOP_STATE_FAILED")?
        .backend
        .is_some()
    {
        return Err("BACKEND_RUNNING: Đóng phiên dữ liệu trước khi chọn thư mục khác.".into());
    }
    let selected = app
        .dialog()
        .file()
        .set_title("Chọn thư mục dữ liệu Cafe Fin trên ổ local")
        .blocking_pick_folder();
    let path = selected
        .map(|value| value.into_path().map_err(|_| "DATA_ROOT_INVALID"))
        .transpose()?;
    if let Some(path) = path {
        let mut state = state.lock().map_err(|_| "DESKTOP_STATE_FAILED")?;
        // A dialog result can arrive after another native command changed state.
        if state.backend.is_some() || pending_journal(&app)?.is_some() {
            return Err("MAINTENANCE_RECOVERY_HELD".into());
        }
        state.selected_root = Some(path.clone());
        return Ok(Some(path.to_string_lossy().into()));
    }
    Ok(None)
}
#[tauri::command]
async fn start_backend(
    app: tauri::AppHandle,
    state: State<'_, Arc<Mutex<DesktopState>>>,
    initialize: bool,
) -> Result<BootSession, String> {
    let state = Arc::clone(state.inner());
    tauri::async_runtime::spawn_blocking(move || start_backend_inner(&app, &state, initialize))
        .await
        .map_err(|_| "DESKTOP_TASK_FAILED".to_owned())?
}

fn start_backend_inner(
    app: &tauri::AppHandle,
    state: &Mutex<DesktopState>,
    initialize: bool,
) -> Result<BootSession, String> {
    let mut state = state.lock().map_err(|_| "DESKTOP_STATE_FAILED")?;
    let journal = pending_journal(&app)?;
    if let (Some(journal), Some(backend)) = (&journal, &state.backend) {
        pending_binding(&app, journal, backend)?;
    }
    let pending: Option<PendingTransition> = journal.as_ref().map(|journal| journal.summary(true));
    if let Some(boot) = attach_existing(state.backend.as_mut(), pending.as_ref(), initialize)
        .map_err(str::to_owned)?
    {
        if let Some(journal) = &journal {
            if pending_journal(app)?.as_ref() != Some(journal) {
                return Err("MAINTENANCE_RECOVERY_HELD".into());
            }
            pending_binding(
                app,
                journal,
                state.backend.as_ref().ok_or("MAINTENANCE_RECOVERY_HELD")?,
            )?;
        }
        return Ok(boot);
    }
    // attach_existing returns None only with no child AND no journal. Pending
    // recovery has no hidden spawn/source fallback; explicit controller bootstrap
    // will be added only after the approved dormant protocol is available.
    let root = state
        .selected_root
        .clone()
        .or(configured_root(&app)?)
        .ok_or("DATA_ROOT_REQUIRED: Chọn thư mục dữ liệu trước.")?;
    let mut backend = spawn_backend(&root, initialize)?;
    if let Err(error) = save_root(&app, &root) {
        shutdown(&mut backend);
        return Err(error);
    }
    let session = backend.session.clone();
    state.backend = Some(backend);
    Ok(session)
}
#[tauri::command]
async fn restart_backend(
    app: tauri::AppHandle,
    state: State<'_, Arc<Mutex<DesktopState>>>,
) -> Result<BootSession, String> {
    let state = Arc::clone(state.inner());
    tauri::async_runtime::spawn_blocking(move || restart_backend_inner(&app, &state))
        .await
        .map_err(|_| "DESKTOP_TASK_FAILED".to_owned())?
}

fn restart_backend_inner(
    app: &tauri::AppHandle,
    state: &Mutex<DesktopState>,
) -> Result<BootSession, String> {
    {
        let mut state = state.lock().map_err(|_| "DESKTOP_STATE_FAILED")?;
        if pending_journal(&app)?.is_some() {
            return Err("MAINTENANCE_RECOVERY_HELD".into());
        }
        if let Some(mut backend) = state.backend.take() {
            shutdown(&mut backend);
        }
    }
    start_backend_inner(app, state, false)
}
fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _, _| {
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.set_focus();
            }
        }))
        .plugin(tauri_plugin_dialog::init())
        .manage(Arc::new(Mutex::new(DesktopState::default())))
        .invoke_handler(tauri::generate_handler![
            desktop_status,
            choose_data_root,
            start_backend,
            restart_backend
        ])
        .plugin(
            tauri::plugin::Builder::<tauri::Wry, ()>::new("navigation-policy")
                .on_navigation(|_, url| {
                    let origin = url.origin().ascii_serialization();
                    origin == "http://tauri.localhost"
                        || origin == "tauri://localhost"
                        || (cfg!(debug_assertions) && origin == "http://127.0.0.1:1420")
                })
                .build(),
        )
        .build(tauri::generate_context!())
        .expect("Cafe Fin desktop startup failed")
        .run(|app, event| {
            if let tauri::RunEvent::Exit = event {
                if let Ok(mut state) = app.state::<Arc<Mutex<DesktopState>>>().lock() {
                    if let Some(mut backend) = state.backend.take() {
                        shutdown(&mut backend);
                    }
                }
            }
        });
}
