#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use serde::{Deserialize, Serialize};
use std::{
    fs,
    io::{BufRead, BufReader, Write},
    path::{Path, PathBuf},
    process::{Child, ChildStdin, Command, Stdio},
    sync::{mpsc, Mutex},
    time::{Duration, Instant},
};
use tauri::{Manager, State};
use tauri_plugin_dialog::DialogExt;

const PROTOCOL: u32 = 1;
const STARTUP_DEADLINE: Duration = Duration::from_secs(20);

#[derive(Clone, Serialize)]
struct BootSession {
    protocol_version: u32,
    api_base: String,
    session_token: String,
    data_root: String,
}
#[derive(Serialize)]
struct DesktopStatus {
    data_root: Option<String>,
    running: bool,
}
#[derive(Deserialize)]
struct Handshake {
    protocol_version: u32,
    api_base: String,
    status: String,
    code: Option<String>,
    message: Option<String>,
}
#[derive(Serialize, Deserialize)]
struct MachineConfig {
    version: u32,
    data_root: String,
}
struct Backend {
    child: Child,
    stdin: ChildStdin,
    session: BootSession,
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
    let _ = backend.stdin.write_all(b"{\"command\":\"shutdown\"}\n");
    let _ = backend.stdin.flush();
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
    let (sender, receiver) = mpsc::channel();
    std::thread::spawn(move || {
        let mut reader = BufReader::new(stdout);
        let mut line = String::new();
        let result = reader
            .read_line(&mut line)
            .ok()
            .filter(|size| *size <= 65536)
            .and_then(|_| serde_json::from_str::<Handshake>(&line).ok());
        let _ = sender.send(result);
        // Drain any later stdout without exposing backend output to the renderer or logs.
        let mut sink = std::io::sink();
        let _ = std::io::copy(&mut reader, &mut sink);
    });
    let deadline = Instant::now() + STARTUP_DEADLINE;
    let handshake = match receiver.recv_timeout(STARTUP_DEADLINE).ok().flatten() {
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
    if handshake.protocol_version != PROTOCOL || handshake.status != "ready" || !valid_url {
        let _ = child.kill();
        let _ = child.wait();
        return Err("SIDECAR_PROTOCOL_MISMATCH: Backend không tương thích.".into());
    }
    let client = reqwest::blocking::Client::builder()
        .timeout(Duration::from_secs(1))
        .no_proxy()
        .redirect(reqwest::redirect::Policy::none())
        .build()
        .map_err(|_| "HEALTH_CLIENT_FAILED")?;
    loop {
        let healthy = client
            .get(format!("{}/health", handshake.api_base))
            .header("X-App-Session", &token)
            .send()
            .map(|response| response.status().is_success())
            .unwrap_or(false);
        if healthy {
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
        stdin,
        session: BootSession {
            protocol_version: PROTOCOL,
            api_base: handshake.api_base,
            session_token: token,
            data_root: root.to_string_lossy().into(),
        },
    })
}

#[tauri::command]
fn desktop_status(
    app: tauri::AppHandle,
    state: State<'_, Mutex<DesktopState>>,
) -> Result<DesktopStatus, String> {
    let mut state = state.lock().map_err(|_| "DESKTOP_STATE_FAILED")?;
    let running = state
        .backend
        .as_mut()
        .map(|backend| backend.child.try_wait().ok().flatten().is_none())
        .unwrap_or(false);
    let root = state.selected_root.clone().or(configured_root(&app)?);
    Ok(DesktopStatus {
        data_root: root.map(|path| path.to_string_lossy().into()),
        running,
    })
}
#[tauri::command]
async fn choose_data_root(
    app: tauri::AppHandle,
    state: State<'_, Mutex<DesktopState>>,
) -> Result<Option<String>, String> {
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
        state
            .lock()
            .map_err(|_| "DESKTOP_STATE_FAILED")?
            .selected_root = Some(path.clone());
        return Ok(Some(path.to_string_lossy().into()));
    }
    Ok(None)
}
#[tauri::command]
async fn start_backend(
    app: tauri::AppHandle,
    state: State<'_, Mutex<DesktopState>>,
    initialize: bool,
) -> Result<BootSession, String> {
    let mut state = state.lock().map_err(|_| "DESKTOP_STATE_FAILED")?;
    if let Some(backend) = state.backend.as_mut() {
        if backend.child.try_wait().ok().flatten().is_none() {
            return Ok(backend.session.clone());
        }
    }
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
    state: State<'_, Mutex<DesktopState>>,
) -> Result<BootSession, String> {
    {
        let mut state = state.lock().map_err(|_| "DESKTOP_STATE_FAILED")?;
        if let Some(mut backend) = state.backend.take() {
            shutdown(&mut backend);
        }
    }
    start_backend(app, state, false).await
}
fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _, _| {
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.set_focus();
            }
        }))
        .plugin(tauri_plugin_dialog::init())
        .manage(Mutex::new(DesktopState::default()))
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
                if let Ok(mut state) = app.state::<Mutex<DesktopState>>().lock() {
                    if let Some(mut backend) = state.backend.take() {
                        shutdown(&mut backend);
                    }
                }
            }
        });
}
