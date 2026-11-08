use cafe_fin_native_checks::{
    maintenance_dto::{DesktopStatus, RuntimeState},
    native_lifecycle::Lifecycle,
};

fn active() -> DesktopStatus {
    DesktopStatus {
        data_root: Some("synthetic-root".into()),
        running: true,
        maintenance_protocol: Some(1),
        generation: Some("synthetic-generation".into()),
        runtime_state: Some(RuntimeState::Active),
        pending_transition: None,
    }
}

#[test]
fn startup_only_hides_after_verified_active_root_and_tray() {
    let mut lifecycle = Lifecycle::new(true);
    let mut status = active();
    assert!(!lifecycle.take_startup_hide(&status, true));
    lifecycle.tray_ready = true;
    assert!(!lifecycle.take_startup_hide(&status, false));
    status.running = false;
    assert!(!lifecycle.take_startup_hide(&status, true));
    status.running = true;
    status.runtime_state = Some(RuntimeState::Dormant);
    assert!(!lifecycle.take_startup_hide(&status, true));
    status.runtime_state = Some(RuntimeState::Active);
    status.generation = None;
    assert!(!lifecycle.take_startup_hide(&status, true));
    status.generation = Some("synthetic-generation".into());
    assert!(lifecycle.take_startup_hide(&status, true));
    assert!(!lifecycle.take_startup_hide(&status, true));
}

#[test]
fn normal_launch_and_manual_restore_never_hide_from_delayed_health() {
    let mut normal = Lifecycle::new(false);
    normal.tray_ready = true;
    assert!(!normal.take_startup_hide(&active(), true));
    let mut startup = Lifecycle::new(true);
    startup.tray_ready = true;
    startup.reveal();
    assert!(!startup.take_startup_hide(&active(), true));
}

#[test]
fn exit_is_confirmed_once_and_failure_reopens_admission() {
    let mut lifecycle = Lifecycle::new(true);
    lifecycle.tray_ready = true;
    assert!(!lifecycle.confirm_exit(true));
    assert!(lifecycle.begin_exit());
    assert!(!lifecycle.begin_exit());
    assert!(lifecycle.allows_work());
    assert!(!lifecycle.take_startup_hide(&active(), true));
    assert!(!lifecycle.confirm_exit(false));
    assert!(lifecycle.allows_work());
    assert!(lifecycle.begin_exit());
    assert!(lifecycle.confirm_exit(true));
    assert!(!lifecycle.allows_work());
    assert!(!lifecycle.begin_exit());
    lifecycle.exit_failed();
    assert!(lifecycle.allows_work());
    assert!(lifecycle.begin_exit());
}

#[test]
fn maintenance_pending_keeps_recovery_visible() {
    use cafe_fin_native_checks::maintenance_dto::{
        MaintenanceKind, MaintenancePhase, PendingTransition,
    };
    let mut lifecycle = Lifecycle::new(true);
    lifecycle.tray_ready = true;
    let mut status = active();
    status.pending_transition = Some(PendingTransition {
        operation_id: "held".into(),
        kind: MaintenanceKind::Move,
        phase: MaintenancePhase::OldClosed,
        recovery_required: true,
    });
    assert!(!lifecycle.take_startup_hide(&status, true));
}

#[test]
fn manual_open_during_first_notice_cancels_delayed_hide() {
    let mut lifecycle = Lifecycle::new(false);
    let epoch = lifecycle.begin_notice().unwrap();
    assert!(lifecycle.begin_notice().is_none());
    assert!(!lifecycle.begin_exit());
    lifecycle.reveal();
    assert!(!lifecycle.complete_notice(epoch, true));
    let epoch = lifecycle.begin_notice().unwrap();
    assert!(lifecycle.complete_notice(epoch, true));
    assert!(lifecycle.begin_exit());
}

#[test]
fn failed_or_cancelled_first_notice_keeps_window_visible_and_releases_latch() {
    let mut lifecycle = Lifecycle::new(false);
    let epoch = lifecycle.begin_notice().unwrap();
    assert!(!lifecycle.complete_notice(epoch, false));
    assert!(lifecycle.can_hide());
    assert!(lifecycle.begin_notice().is_some());
}
