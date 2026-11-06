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
export interface User {
  id: string;
  username: string;
  role: "admin" | "operator";
  permissions: string[];
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
}
export interface DesktopStatus {
  data_root: string | null;
  running: boolean;
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
export type JobState =
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
