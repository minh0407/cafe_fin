fn main() {
    let attributes =
        tauri_build::Attributes::new().app_manifest(tauri_build::AppManifest::new().commands(&[
            "desktop_status",
            "choose_data_root",
            "start_backend",
            "restart_backend",
            "maintenance_begin",
            "maintenance_select",
            "maintenance_run",
            "maintenance_status",
            "maintenance_activate",
            "open_reports",
            "desktop_runtime_status",
            "set_desktop_startup",
            "desktop_background_ready",
        ]));
    tauri_build::try_build(attributes).expect("Tauri build configuration failed");
}
