export type Values = Record<string, string | null>;
export interface ColumnDefinition {
  id: string; name: string; kind: 'text' | 'date' | 'integer' | 'decimal' | 'money' | 'choice' | 'formula';
  required?: boolean; scale?: number; precision?: number; choices?: string[]; editable?: boolean;
  formula?: string; display?: Record<string, unknown>;
  validation?: { min?: string; max?: string; max_length?: number };
}
export interface Book { id: string; name: string; version: number; schema_revision: number; data_revision: number; columns: ColumnDefinition[]; semantics: Record<string, unknown> }
export interface Issue { code: string; message: string; suggestion?: string; severity?: string; column_id?: string; source_column?: string; cell?: string; source_row?: number; source_sheet?: string; raw_value?: string | null }
export interface LedgerRow { id: string; version: number; logical_row: number; values: Values; issues: Issue[]; deleted_at?: string | null }
export interface StageRow { row_id: string; source_sheet: string; source_row: number; revision: number; raw_values: Values; edited_values: Values; typed_values: Values; issues: Issue[]; duplicate_count: number; decision: 'keep' | 'skip' | null; imported: boolean }
export interface Batch { id: string; book_id: string; file_id: string; state: string; version: number; revision: number; mapping_revision: number; decision_revision: number; validation_token: string | null; profile: Record<string, unknown>; mapping: Record<string, string>; counts: Record<string, number>; job_id?: string; attempt_id?: string; error_code?: string; job?: { state: string; phase: string; counts: Record<string, number>; error_code?: string } }
export interface GridRecord { id: string; version: number; label: string; values: Values; issues: Issue[]; locked?: boolean }
