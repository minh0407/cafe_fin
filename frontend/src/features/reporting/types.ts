import type { Page } from "../../shared/types";

export type ReportState = "PREVIEW" | "SAVED";
export type DeliveryState =
  | "WAITING"
  | "SENDING"
  | "SENT"
  | "FAILED"
  | "UNKNOWN"
  | "UNCONFIGURED";
export interface InventoryLine {
  product_id: string;
  warehouse_id: string;
  opening_kg: string;
  received_kg: string;
  issued_kg: string;
  closing_kg: string;
}
export interface Book {
  book_id: string;
  has_valid_money_mapping: boolean;
  metrics: {
    key: string;
    meaning?: string | null;
    amount_vnd: string;
    mapping_revision: number;
  }[];
  validation_flags: string[];
}
export interface Snapshot {
  generation?: {
    kind: string;
    created_late: boolean;
    scheduled_due_at: string;
  };
  notice: string;
  cutoff: string;
  source_sha256: string;
  consistency: string;
  period: {
    date_range_contract?: "inclusive_business_dates_v1";
    timestamp_range_contract?: "half_open_utc";
    from_on: string;
    through_on: string;
    from: string;
    to: string;
    timezone: string;
  };
  sources: {
    inventory: {
      items: InventoryLine[];
      movement_breakdown?: MovementLine[] | null;
    };
    books: Book[];
  };
  warnings: string[];
}
export interface MovementLine {
  product_id: string;
  warehouse_id: string;
  purchased_kg: string;
  sold_kg: string;
  production_input_kg: string;
  production_output_kg: string;
  transfer_in_kg: string;
  transfer_out_kg: string;
  adjustment_in_kg: string;
  adjustment_out_kg: string;
}
export interface Report {
  id: string;
  version: number;
  from_on: string;
  through_on: string;
  state: ReportState;
  sha256: string;
  reason: string;
  created_at: string;
  saved_at: string | null;
}
export interface ExportFile {
  id: string;
  report_id: string;
  format: "pdf" | "xlsx" | "txt";
  file_id: string;
  sha256: string;
  size: number;
  local_export?: {
    state: "COPYING" | "PENDING" | "READY" | "FAILED" | "CONFLICT";
    relative_key: string;
    error_code: string | null;
    verified_at: string | null;
    attempts: number;
  } | null;
}
export interface ReportDetail extends Report {
  snapshot: Snapshot;
  short_message: string;
  exports: ExportFile[];
}
export interface Delivery {
  id: string;
  report_id: string;
  destination: string;
  oa_id: string;
  state: DeliveryState;
  phase: string;
  version: number;
  attempts: number;
  message_id: string | null;
  file_message_id: string | null;
  error_code: string | null;
  created_at: string;
}
export interface Attempt {
  id: string;
  phase: string;
  outcome: string;
  code: string | null;
  message_id: string | null;
  created_at: string;
}
export interface Settings {
  version: number;
  oa_id: string;
  group_id: string;
  enabled: boolean;
  timezone: string;
  send_at: string | null;
  attachments_enabled: boolean;
  auto_generate_daily?: boolean;
  daily_book_ids?: string[];
  daily_export_formats?: ("pdf" | "xlsx" | "txt")[];
  scheduled_actor_id?: string | null;
  schedule_actor_status?: "ACTIVE" | "BLOCKED";
  credential_store_available?: boolean;
  credential_configured?: boolean;
  sender_status?: string;
  scheduler_limit?: string;
  scheduler_mode?: "APP_RUNTIME" | "MANUAL";
  scheduler_status?: {
    registered: boolean;
    state: string;
    running: boolean;
    active: boolean;
    error_code: string | null;
    last_error_code: string | null;
    task_error_code: string | null;
    runs: number;
    failures: number;
  };
}
export interface DailyRun {
  id: string;
  business_on: string;
  state: string;
  phase: string;
  policy: string;
  report_id: string | null;
  outbox_id: string | null;
  attempts: number;
  error_code: string | null;
  config_version: number;
  updated_at: string;
}
export type ReportPage = Page<Report>;
export type DeliveryPage = Page<Delivery>;
