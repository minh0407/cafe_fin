//! Window visibility does not own the backend. Only confirmed Exit stops it.
//! Kept independent of Tauri so ordering/failure policy can be tested headlessly.
use crate::maintenance_dto::{DesktopStatus, RuntimeState};

pub const STARTUP_ARGUMENT: &str = "--startup-v1";

#[derive(Default)]
pub struct Lifecycle {
    startup_hide_pending: bool,
    pub tray_ready: bool,
    pub notice_open: bool,
    visibility_epoch: u64,
    exit_prompt: bool,
    exiting: bool,
}

impl Lifecycle {
    pub fn new(startup: bool) -> Self {
        Self {
            startup_hide_pending: startup,
            ..Self::default()
        }
    }

    /// A manual launch/restore always wins over a delayed startup health reply.
    pub fn reveal(&mut self) {
        self.startup_hide_pending = false;
        self.visibility_epoch = self.visibility_epoch.wrapping_add(1);
    }

    pub fn begin_notice(&mut self) -> Option<u64> {
        if self.notice_open || self.exit_prompt || self.exiting {
            return None;
        }
        self.notice_open = true;
        Some(self.visibility_epoch)
    }

    pub fn complete_notice(&mut self, epoch: u64, acknowledged: bool) -> bool {
        let hide =
            acknowledged && self.notice_open && epoch == self.visibility_epoch && !self.exiting;
        self.notice_open = false;
        hide
    }

    pub fn take_startup_hide(&mut self, status: &DesktopStatus, root_exists: bool) -> bool {
        if !self.startup_hide_pending
            || !self.tray_ready
            || self.exit_prompt
            || self.exiting
            || self.notice_open
        {
            return false;
        }
        if !root_exists
            || !status.running
            || status.generation.is_none()
            || status.maintenance_protocol != Some(1)
            || status.runtime_state != Some(RuntimeState::Active)
            || status.pending_transition.is_some()
        {
            return false;
        }
        self.startup_hide_pending = false;
        true
    }

    pub fn begin_exit(&mut self) -> bool {
        self.reveal();
        if self.exit_prompt || self.exiting || self.notice_open {
            return false;
        }
        self.exit_prompt = true;
        true
    }

    pub fn confirm_exit(&mut self, confirmed: bool) -> bool {
        if !self.exit_prompt {
            return false;
        }
        self.exit_prompt = false;
        self.exiting = confirmed;
        confirmed
    }

    pub fn exit_failed(&mut self) {
        self.exiting = false;
    }
    pub fn allows_work(&self) -> bool {
        !self.exiting
    }
    pub fn can_hide(&self) -> bool {
        !self.exiting && !self.exit_prompt && !self.notice_open
    }
}
