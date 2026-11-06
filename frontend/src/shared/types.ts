export type DecimalString = string;
export interface FieldError {
  field: string;
  code: string;
  message: string;
}
export interface ErrorEnvelope {
  error: {
    code: string;
    message: string;
    field_errors: FieldError[];
    details?: Record<string, unknown>;
  };
  request_id: string;
}
export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}
export type FileCategory = "workbooks" | "documents" | "imports" | "reports";
export interface FileDTO {
  id: string;
  sha256: string;
  size: number;
  category: FileCategory;
  original_name: string;
  media_type: string;
  created_at: string;
}
export interface User {
  id: string;
  username: string;
  role: "admin" | "operator";
  permissions: string[];
  version: number;
}
export interface AuthResponse {
  access_token: string;
  user: User;
}
export interface BootSession {
  protocol_version: 1;
  api_base: string;
  session_token: string;
  data_root: string;
  maintenance_protocol?: 1 | null;
  generation?: string | null;
  runtime_state?: RuntimeState | null;
  pending_transition?: PendingTransition | null;
}
export interface DesktopStatus {
  data_root: string | null;
  running: boolean;
  maintenance_protocol?: 1 | null;
  generation?: string | null;
  runtime_state?: RuntimeState | null;
  pending_transition?: PendingTransition | null;
}
export type MaintenanceKind = "backup" | "move" | "restore";
export type RuntimeState = "ACTIVE" | "QUIESCING" | "QUIESCED" | "PREPARING"
  | "PREPARED" | "CLOSING" | "CLOSED" | "DORMANT" | "ACTIVATING" | "FAILED_HELD";
export type MaintenancePhase = "SELECTING" | "INTENT" | "QUIESCED" | "PREPARED"
  | "OLD_CLOSED" | "CONFIG_SWITCHED" | "CANDIDATE_DORMANT" | "ACTIVATION_DISPATCHED" | "ACTIVE";
export interface PendingTransition {
  operation_id: string;
  kind: MaintenanceKind;
  phase: MaintenancePhase;
  recovery_required: boolean;
}
export interface MaintenanceView extends PendingTransition {
  generation: string;
  runtime_state: RuntimeState | null;
  destination_display: string | null;
  backup_source_display: string | null;
  ready: boolean;
  can_activate: boolean;
}
export interface MaintenanceResult {
  operation: MaintenanceView;
  boot_session: BootSession | null;
}

export function maintenanceHeld(boot: BootSession | null): boolean {
  const pending = boot?.pending_transition;
  return !!boot && (
    (!!boot.runtime_state && boot.runtime_state !== "ACTIVE") ||
    !!pending?.recovery_required ||
    (!!pending && !["SELECTING", "ACTIVE"].includes(pending.phase))
  );
}
export interface Health {
  status: "ok";
  protocol_version: 1;
  setup_required: boolean;
}
export interface SourceIssue {
  sheet: string;
  row: number;
  column: string;
  cell: string;
  code: string;
  message: string;
}
export interface GridRow {
  id: string;
  source_sheet: string;
  source_row: number;
  code: string;
  description: string;
  occurred_on: string;
  amount: DecimalString;
  formula: string;
  issues: SourceIssue[];
}
export interface ImportCounts {
  source_rows: number;
  validated: number;
  valid: number;
  invalid: number;
  potential_duplicates: number;
  conflicts: number;
  excluded: number;
  staged_committed_rows: number;
  published_rows: number;
  pending: number;
}
export type ImportJobState =
  | "UPLOADED"
  | "PARSING"
  | "READY_FOR_MAPPING"
  | "VALIDATING"
  | "READY_FOR_CONFIRM"
  | "COMMITTING"
  | "PARTIALLY_COMMITTED"
  | "COMPLETED"
  | "CANCELLED"
  | "FAILED"
  | "RECOVERABLE";

// Core execution state is distinct from an accounting import's domain state/phase.
export type JobState =
  | "WAITING"
  | "RUNNING"
  | "COMPLETED"
  | "FAILED"
  | "CANCELLED"
  | "RECOVERABLE";

export interface JobDTO {
  id: string;
  kind: string;
  actor: string;
  state: JobState;
  phase: string;
  attempts: number;
  generation: number;
  counts: Record<string, number>;
  checkpoint: Record<string, unknown>;
  cancel_requested: boolean;
  error_code: string | null;
  created_at: string;
  updated_at: string;
}
