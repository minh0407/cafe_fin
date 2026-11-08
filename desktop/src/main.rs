#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod native_controller;
mod native_shell;

use cafe_fin_desktop::{
    maintenance_dto::{
        BootSession, DesktopStatus, MaintenanceKind, MaintenanceResult, MaintenanceView,
        SelectionPurpose,
    },
    native_draft::SelectionTicket,
    native_journal::JournalStore,
    native_lifecycle::{Lifecycle, STARTUP_ARGUMENT},
    native_startup::{self, RuntimeStatus},
};
use native_controller::NativeController;
use std::sync::{Arc, Mutex};
use tauri::{Manager, State};
use tauri_plugin_dialog::DialogExt;

type Shared = Arc<Mutex<NativeController>>;

/// Completion is not new work: its native-issued ticket must settle even after
/// Exit closes admission. Otherwise a racing dialog result can strand DRAFT_BUSY.
async fn settle_selection(
    app: tauri::AppHandle,
    state: &State<'_, Shared>,
    ticket: SelectionTicket,
    path: Option<std::path::PathBuf>,
) -> Result<Option<MaintenanceView>, String> {
    let shared = Arc::clone(state.inner());
    tauri::async_runtime::spawn_blocking(move || {
        let mut controller = shared.lock().map_err(|_| "DESKTOP_STATE_FAILED")?;
        match journal_store(&app) {
            Ok(store) => controller.select_finish(&store, ticket, path),
            Err(code) => {
                controller.cancel_selection(ticket)?;
                Err(code)
            }
        }
    })
    .await
    .map_err(|_| "DESKTOP_TASK_FAILED".to_owned())?
}

fn journal_store(app: &tauri::AppHandle) -> Result<JournalStore, String> {
    let directory = app
        .path()
        .app_config_dir()
        .map_err(|_| "CONFIG_UNAVAILABLE")?;
    JournalStore::new(&directory).map_err(str::to_owned)
}

async fn native<T, F>(
    app: tauri::AppHandle,
    state: &State<'_, Shared>,
    work: F,
) -> Result<T, String>
where
    T: Send + 'static,
    F: FnOnce(&mut NativeController, &JournalStore) -> Result<T, String> + Send + 'static,
{
    let shared = Arc::clone(state.inner());
    tauri::async_runtime::spawn_blocking(move || {
        let store = journal_store(&app)?;
        let mut controller = shared.lock().map_err(|_| "DESKTOP_STATE_FAILED")?;
        if !app
            .state::<native_shell::Shell>()
            .0
            .lock()
            .map_err(|_| "DESKTOP_STATE_FAILED")?
            .allows_work()
        {
            return Err("DESKTOP_EXIT_PENDING".into());
        }
        work(&mut controller, &store)
    })
    .await
    .map_err(|_| "DESKTOP_TASK_FAILED".to_owned())?
}

#[tauri::command]
async fn desktop_runtime_status(
    app: tauri::AppHandle,
    state: State<'_, Shared>,
) -> Result<RuntimeStatus, String> {
    native(app, &state, |_, _| native_startup::status()).await
}

#[tauri::command]
async fn set_desktop_startup(
    app: tauri::AppHandle,
    state: State<'_, Shared>,
    enabled: bool,
) -> Result<RuntimeStatus, String> {
    native(app, &state, move |_, _| {
        native_startup::set_enabled(enabled)
    })
    .await
}

#[tauri::command]
async fn desktop_background_ready(app: tauri::AppHandle) -> Result<(), String> {
    native_shell::background_ready(&app)
}

#[tauri::command]
async fn desktop_status(
    app: tauri::AppHandle,
    state: State<'_, Shared>,
) -> Result<DesktopStatus, String> {
    native(app, &state, |controller, store| controller.status(store)).await
}

#[tauri::command]
async fn choose_data_root(
    app: tauri::AppHandle,
    state: State<'_, Shared>,
) -> Result<Option<String>, String> {
    native(app.clone(), &state, |controller, store| {
        controller.choose_allowed(store)
    })
    .await?;
    let picker_app = app.clone();
    let path = tauri::async_runtime::spawn_blocking(move || {
        picker_app
            .dialog()
            .file()
            .set_title("Chọn thư mục dữ liệu Cafe Fin trên ổ local")
            .blocking_pick_folder()
            .map(|value| {
                value
                    .into_path()
                    .map_err(|_| "DATA_ROOT_INVALID".to_owned())
            })
            .transpose()
    })
    .await
    .map_err(|_| "DESKTOP_TASK_FAILED")??;
    match path {
        Some(path) => {
            native(app, &state, move |controller, store| {
                controller.choose_root(store, path).map(Some)
            })
            .await
        }
        None => Ok(None),
    }
}

#[tauri::command]
async fn start_backend(
    app: tauri::AppHandle,
    state: State<'_, Shared>,
    initialize: bool,
) -> Result<BootSession, String> {
    native(app, &state, move |controller, store| {
        controller.start(store, initialize)
    })
    .await
}

#[tauri::command]
async fn restart_backend(
    app: tauri::AppHandle,
    state: State<'_, Shared>,
) -> Result<BootSession, String> {
    native(app, &state, |controller, store| controller.restart(store)).await
}

#[tauri::command]
async fn maintenance_begin(
    app: tauri::AppHandle,
    state: State<'_, Shared>,
    kind: MaintenanceKind,
) -> Result<MaintenanceView, String> {
    native(app, &state, move |controller, store| {
        controller.begin(store, kind)
    })
    .await
}

#[tauri::command]
async fn maintenance_select(
    app: tauri::AppHandle,
    state: State<'_, Shared>,
    operation_id: String,
    purpose: SelectionPurpose,
) -> Result<Option<MaintenanceView>, String> {
    let ticket = native(app.clone(), &state, move |controller, store| {
        controller.select_begin(store, &operation_id, purpose)
    })
    .await?;
    let picker_app = app.clone();
    let selection = tauri::async_runtime::spawn_blocking(move || {
        picker_app
            .dialog()
            .file()
            .set_title(match purpose {
                SelectionPurpose::Destination => "Chọn thư mục cha để tạo bản sao Cafe Fin mới",
                SelectionPurpose::BackupSource => "Chọn thư mục sao lưu Cafe Fin",
            })
            .blocking_pick_folder()
            .map(|value| {
                value
                    .into_path()
                    .map_err(|_| "NATIVE_PATH_INVALID".to_owned())
            })
            .transpose()
    })
    .await
    .map_err(|_| "DESKTOP_TASK_FAILED".to_owned());
    // Finish even on picker failure so the correlated ticket is settled. No lock
    // is held while the OS dialog runs, and completion rechecks all bindings.
    match selection {
        Ok(Ok(path)) => settle_selection(app, &state, ticket, path).await,
        failure => {
            settle_selection(app, &state, ticket, None).await?;
            Err(match failure {
                Ok(Err(code)) | Err(code) => code,
                _ => "NATIVE_PICKER_FAILED".into(),
            })
        }
    }
}

#[tauri::command]
async fn maintenance_run(
    app: tauri::AppHandle,
    state: State<'_, Shared>,
    operation_id: String,
    user_token: String,
) -> Result<MaintenanceResult, String> {
    native(app, &state, move |controller, store| {
        controller.run(store, &operation_id, &user_token)
    })
    .await
}

#[tauri::command]
async fn maintenance_status(
    app: tauri::AppHandle,
    state: State<'_, Shared>,
    operation_id: String,
    user_token: String,
) -> Result<MaintenanceResult, String> {
    native(app, &state, move |controller, store| {
        controller.operation_status(store, &operation_id, &user_token)
    })
    .await
}

#[tauri::command]
async fn maintenance_activate(
    app: tauri::AppHandle,
    state: State<'_, Shared>,
    operation_id: String,
    user_token: String,
) -> Result<MaintenanceResult, String> {
    native(app, &state, move |controller, store| {
        controller.activate(store, &operation_id, &user_token)
    })
    .await
}

#[tauri::command]
async fn open_reports(
    app: tauri::AppHandle,
    state: State<'_, Shared>,
    user_token: String,
) -> Result<(), String> {
    native(app, &state, move |controller, store| {
        controller.open_reports(store, &user_token)
    })
    .await
}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, args, _| {
            // A duplicate Windows-startup invocation must not pull an existing
            // session forward. A manual shortcut restores without spawning again.
            if !args.iter().skip(1).any(|arg| arg == STARTUP_ARGUMENT) {
                native_shell::show(app);
            }
        }))
        .plugin(tauri_plugin_dialog::init())
        .manage(Shared::default())
        .manage(native_shell::Shell(Mutex::new(Lifecycle::new(
            std::env::args_os()
                .skip(1)
                .any(|arg| arg == STARTUP_ARGUMENT),
        ))))
        .setup(|app| {
            // Cold recovery is a controller-owned startup action. Ordinary
            // start_backend(false) remains attach-only whenever a journal exists.
            let shared = app.state::<Shared>();
            let mut controller = shared.lock().map_err(|_| "DESKTOP_STATE_FAILED")?;
            let recovery =
                journal_store(app.handle()).and_then(|store| controller.bootstrap_recovery(&store));
            if let Err(code) = recovery {
                controller.startup_error = Some(code);
            }
            drop(controller);
            native_shell::setup(app.handle());
            Ok(())
        })
        .on_window_event(|window, event| {
            if window.label() == "main" {
                if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                    api.prevent_close();
                    native_shell::close_to_tray(window);
                }
            }
        })
        .invoke_handler(tauri::generate_handler![
            desktop_status,
            choose_data_root,
            start_backend,
            restart_backend,
            maintenance_begin,
            maintenance_select,
            maintenance_run,
            maintenance_status,
            maintenance_activate,
            open_reports,
            desktop_runtime_status,
            set_desktop_startup,
            desktop_background_ready
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
                if let Ok(mut controller) = app.state::<Shared>().lock() {
                    controller.shutdown();
                }
            }
        });
}
