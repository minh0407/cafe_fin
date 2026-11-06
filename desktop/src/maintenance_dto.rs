//! Renderer output DTOs. Private paths, receipts and access tokens are not DTOs.
use serde::{Deserialize, Serialize};

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum MaintenanceKind {
    Backup,
    Move,
    Restore,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum SelectionPurpose {
    Destination,
    BackupSource,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum MaintenancePhase {
    Selecting,
    Intent,
    Quiesced,
    Prepared,
    OldClosed,
    ConfigSwitched,
    CandidateDormant,
    ActivationDispatched,
    Active,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum RuntimeState {
    Active,
    Quiescing,
    Quiesced,
    Preparing,
    Prepared,
    Closing,
    Closed,
    Dormant,
    Activating,
    FailedHeld,
}

#[derive(Clone, Serialize)]
pub struct PendingTransition {
    pub operation_id: String,
    pub kind: MaintenanceKind,
    pub phase: MaintenancePhase,
    pub recovery_required: bool,
}

// Deliberately no Debug: BootSession holds the app-session secret.
#[derive(Clone, Serialize)]
pub struct BootSession {
    pub protocol_version: u32,
    pub api_base: String,
    pub session_token: String,
    pub data_root: String,
    pub maintenance_protocol: Option<u32>,
    pub generation: Option<String>,
    pub runtime_state: Option<RuntimeState>,
    pub pending_transition: Option<PendingTransition>,
}

#[derive(Serialize)]
pub struct DesktopStatus {
    pub data_root: Option<String>,
    pub running: bool,
    pub maintenance_protocol: Option<u32>,
    pub generation: Option<String>,
    pub runtime_state: Option<RuntimeState>,
    pub pending_transition: Option<PendingTransition>,
}

#[derive(Clone, Serialize)]
pub struct MaintenanceView {
    pub operation_id: String,
    pub kind: MaintenanceKind,
    pub phase: MaintenancePhase,
    pub recovery_required: bool,
    pub generation: String,
    pub runtime_state: Option<RuntimeState>,
    // Presentation only. Renderer must not submit these strings as authority.
    pub destination_display: Option<String>,
    pub backup_source_display: Option<String>,
    pub ready: bool,
    pub can_activate: bool,
}

#[derive(Serialize)]
pub struct MaintenanceResult {
    pub operation: MaintenanceView,
    pub boot_session: Option<BootSession>,
}
