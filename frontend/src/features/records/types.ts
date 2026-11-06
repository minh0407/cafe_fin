export type Resource = "parties" | "products" | "products/units" | "products/warehouses" | "weighings" | "entries";
export type EntryType = "receipt" | "issue" | "production" | "transfer" | "opening" | "adjustment";
export interface Entity {
  id: string;
  version: number;
  code: string;
  name?: string;
  active: boolean;
  created_at: string;
  updated_at: string;
  created_by: string;
  updated_by: string;
  deleted_at: string | null;
  note?: string | null;
}
export interface Contact { kind: string; value: string; label?: string | null }
export interface BankAccount { bank_name: string; account_number: string; account_holder?: string | null; branch?: string | null }
export interface Party extends Entity { name: string; type: string; roles: string[]; address?: string | null; tax_code?: string | null; contacts: Contact[]; bank_details: BankAccount[]; representative?: { name: string; title?: string | null; authorization_reference?: string | null } | null }
export interface Product extends Entity { name: string; unit_id?: string | null }
export interface WeighingLine { product_id?: string | null; description?: string | null; quantity_source: "gross_tare" | "direct_net"; gross_kg?: string | null; tare_kg?: string | null; net_kg?: string | null; note?: string | null }
export interface Weighing extends Entity { occurred_on: string; occurred_at?: string | null; physical_actor?: string | null; party_id?: string | null; vehicle_plate?: string | null; lines: WeighingLine[] }
export interface EntryLine { product_id: string; warehouse_id: string; quantity_kg: string; direction: "in" | "out"; note?: string | null }
export interface Entry extends Entity { occurred_on: string; occurred_at?: string | null; physical_actor?: string | null; entry_type: EntryType; status: "draft" | "posted" | "cancelled"; party_id?: string | null; weighing_id?: string | null; commercial_amount_vnd?: string | null; lines: EntryLine[] }
export interface InventoryLine { product_id: string; warehouse_id: string; opening_kg: string; received_kg: string; issued_kg: string; closing_kg: string }
export interface InventoryMovementLine {
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
export interface InventorySummary {
  coverage: "entered_records_only";
  cutoff: string;
  from_on: string;
  through_on: string;
  items: InventoryLine[];
  validation_flags: string[];
  breakdown_version: 1 | null;
  movement_breakdown: InventoryMovementLine[] | null;
  // Retained HTTP extension; canonical classification is movement_breakdown.
  breakdown: { product_id: string; warehouse_id: string; entry_type: EntryType; in_kg: string; out_kg: string }[];
}
export interface Receivables { coverage: "entered_records_only"; cutoff: string; as_of: string; items: { party_id: string; amount_vnd: string }[]; validation_flags: string[] }
export interface StockMovement { id: string; entry_id: string; version: number; occurred_on: string; entry_type: EntryType; product_id: string; warehouse_id: string; delta_kg: string }
export type RecordEntity = Party | Product | Weighing | Entry;
export const entryLabels: Record<EntryType, string> = { receipt: "Nhập hàng", issue: "Xuất hàng", production: "Sản xuất", transfer: "Chuyển vị trí", opening: "Tồn đầu có căn cứ", adjustment: "Điều chỉnh" };
