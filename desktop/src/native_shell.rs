//! Native-only tray actions. No renderer-controlled executable, path or exit flag.
use crate::{native_controller::NativeController, Shared};
use cafe_fin_desktop::{native_lifecycle::Lifecycle, native_paths::check_local_path};
use std::{
    fs::OpenOptions,
    io::{Read, Write},
    path::PathBuf,
    sync::Mutex,
};
use tauri::{
    menu::{Menu, MenuItem},
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
    Manager,
};
use tauri_plugin_dialog::{DialogExt, MessageDialogButtons, MessageDialogKind};

pub struct Shell(pub Mutex<Lifecycle>);

pub fn show(app: &tauri::AppHandle) {
    let handle = app.clone();
    let _ = app.run_on_main_thread(move || {
        if let Ok(mut lifecycle) = handle.state::<Shell>().0.lock() {
            lifecycle.reveal();
        }
        if let Some(window) = handle.get_webview_window("main") {
            let _ = window.show();
            let _ = window.unminimize();
            let _ = window.set_focus();
        }
    });
}

fn marker(app: &tauri::AppHandle) -> Option<PathBuf> {
    let path = app.path().app_config_dir().ok()?.join("tray-notice-v1");
    check_local_path(&path).ok()?;
    Some(path)
}

fn notice_seen(app: &tauri::AppHandle) -> bool {
    let Some(path) = marker(app) else {
        return false;
    };
    let Ok(file) = std::fs::File::open(path) else {
        return false;
    };
    let mut contents = Vec::new();
    file.take(3).read_to_end(&mut contents).is_ok() && contents == b"1\n"
}

fn record_notice(app: &tauri::AppHandle) {
    // A best-effort UX marker only. Never touch machine.json or the journal;
    // missing/unknown markers repeat the explanation instead of hiding silently.
    let Some(path) = marker(app) else {
        return;
    };
    let Some(parent) = path.parent() else {
        return;
    };
    if std::fs::create_dir_all(parent).is_err() || check_local_path(&path).is_err() {
        return;
    }
    if let Ok(mut file) = OpenOptions::new().write(true).create_new(true).open(path) {
        let _ = file.write_all(b"1\n").and_then(|()| file.sync_all());
    }
}

pub fn close_to_tray(window: &tauri::Window) {
    let app = window.app_handle();
    let tray_ready = app
        .state::<Shell>()
        .0
        .lock()
        .is_ok_and(|state| state.tray_ready);
    if !tray_ready {
        request_exit(app);
        return;
    }
    if notice_seen(app) {
        if app
            .state::<Shell>()
            .0
            .lock()
            .is_ok_and(|state| state.can_hide())
        {
            let _ = window.hide();
        }
        return;
    }
    let epoch = app
        .state::<Shell>()
        .0
        .lock()
        .ok()
        .and_then(|mut state| state.begin_notice());
    let Some(epoch) = epoch else {
        return;
    };
    let handle = app.clone();
    app.dialog().message("Đóng cửa sổ chỉ thu Cafe Fin về khay hệ thống. Bản nháp và phiên hiện tại vẫn được giữ; lịch nền tiếp tục khi máy còn thức. Chọn Mở Cafe Fin để quay lại, hoặc Thoát để dừng ứng dụng. Khi máy ngủ/tắt, lịch nền không chạy.")
        .title("Cafe Fin vẫn chạy trong khay").kind(MessageDialogKind::Info)
        .buttons(MessageDialogButtons::Ok).show(move |acknowledged| {
            if acknowledged { record_notice(&handle); }
            let apply = handle.clone();
            let _ = handle.run_on_main_thread(move || {
                // Recheck at application time, on the same thread as manual Open.
                // A queued callback cannot hide a window that the user restored.
                let hide = apply.state::<Shell>().0.lock().is_ok_and(|mut state| state.complete_notice(epoch, acknowledged));
                if hide { if let Some(window) = apply.get_webview_window("main") { let _ = window.hide(); } }
            });
        });
}

pub fn request_exit(app: &tauri::AppHandle) {
    let accepted = app
        .state::<Shell>()
        .0
        .lock()
        .is_ok_and(|mut state| state.begin_exit());
    if !accepted {
        return;
    }
    show(app);
    let handle = app.clone();
    app.dialog().message("Thoát Cafe Fin và dừng lịch nền? Bản nháp chưa lưu sẽ mất. Hãy chọn Hủy để quay lại lưu bản nháp. Dữ liệu đã lưu vẫn được giữ; lịch nền chỉ tiếp tục khi mở ứng dụng lại.")
        .title("Thoát Cafe Fin?").kind(MessageDialogKind::Warning)
        .buttons(MessageDialogButtons::OkCancelCustom("Thoát".into(), "Hủy".into()))
        .show(move |confirmed| {
            let commit = handle.state::<Shell>().0.lock().is_ok_and(|mut state| state.confirm_exit(confirmed));
            if !commit { return; }
            // Stop admission before waiting for the controller mutex. An earlier
            // operation completes first; queued commands recheck inside its lock.
            tauri::async_runtime::spawn_blocking(move || {
                let result = handle.state::<Shared>().lock()
                    .map_err(|_| "DESKTOP_STATE_FAILED".to_owned())
                    .and_then(|mut controller: std::sync::MutexGuard<'_, NativeController>| controller.shutdown_for_exit());
                match result {
                    Ok(()) => handle.exit(0),
                    Err(_) => {
                        if let Ok(mut state) = handle.state::<Shell>().0.lock() { state.exit_failed(); }
                        show(&handle);
                        handle.dialog().message("Chưa xác nhận được dịch vụ dừng sạch, hoặc hộp chọn thư mục vẫn đang mở. Cafe Fin vẫn mở để bạn kiểm tra trạng thái và thử Thoát lại; ứng dụng không buộc dừng dịch vụ.")
                            .title("Chưa thể thoát Cafe Fin").kind(MessageDialogKind::Error).show(|_| {});
                    }
                }
            });
        });
}

pub fn background_ready(app: &tauri::AppHandle) -> Result<(), String> {
    let handle = app.clone();
    app.run_on_main_thread(move || {
        // Do not apply an old status snapshot after a maintenance operation has
        // started. Never block the UI on a busy controller; remain visible.
        let shared = handle.state::<Shared>();
        let Ok(mut controller) = shared.try_lock() else {
            return;
        };
        let Ok(store) = crate::journal_store(&handle) else {
            return;
        };
        let Ok(status) = controller.status(&store) else {
            return;
        };
        let exists = status
            .data_root
            .as_ref()
            .is_some_and(|root| std::path::Path::new(root).is_dir());
        let hide = handle
            .state::<Shell>()
            .0
            .lock()
            .is_ok_and(|mut state| state.take_startup_hide(&status, exists));
        if hide {
            if let Some(window) = handle.get_webview_window("main") {
                let _ = window.hide();
            }
        }
    })
    .map_err(|_| "DESKTOP_WINDOW_UNAVAILABLE".to_owned())
}

pub fn setup(app: &tauri::AppHandle) {
    let result = (|| -> tauri::Result<()> {
        let open = MenuItem::with_id(app, "runtime-open", "Mở Cafe Fin", true, None::<&str>)?;
        let exit = MenuItem::with_id(app, "runtime-exit", "Thoát", true, None::<&str>)?;
        let menu = Menu::with_items(app, &[&open, &exit])?;
        let icon = app
            .default_window_icon()
            .cloned()
            .ok_or_else(|| tauri::Error::AssetNotFound("app icon".into()))?;
        TrayIconBuilder::with_id("cafe-fin-runtime")
            .icon(icon)
            .tooltip("Cafe Fin — dữ liệu local")
            .menu(&menu)
            .show_menu_on_left_click(false)
            .on_menu_event(|app, event| match event.id.as_ref() {
                "runtime-open" => show(app),
                "runtime-exit" => request_exit(app),
                _ => {}
            })
            .on_tray_icon_event(|tray, event| {
                if matches!(
                    event,
                    TrayIconEvent::Click {
                        button: MouseButton::Left,
                        button_state: MouseButtonState::Up,
                        ..
                    }
                ) {
                    show(tray.app_handle());
                }
            })
            .build(app)?;
        Ok(())
    })();
    if let Ok(mut state) = app.state::<Shell>().0.lock() {
        state.tray_ready = result.is_ok();
    }
    if result.is_err() {
        show(app);
        app.dialog().message("Chưa tạo được biểu tượng khay hệ thống. Cafe Fin vẫn mở; đóng cửa sổ sẽ hỏi xác nhận Thoát.")
            .title("Khay hệ thống chưa sẵn sàng").kind(MessageDialogKind::Warning).show(|_| {});
    }
}
