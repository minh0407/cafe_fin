export interface Contact {
  kind: string;
  value: string;
  label: string | null;
}
export interface BankAccount {
  bank_name: string;
  account_number: string;
  account_holder: string | null;
  branch: string | null;
}
export interface Party {
  type: string;
  roles?: string[];
  name: string;
  address: string | null;
  tax_code: string | null;
  contacts: Contact[];
  bank_details: BankAccount[];
  representative: {
    name: string;
    title: string | null;
    authorization_reference?: string | null;
  } | null;
}
export interface WeightLine {
  description: string | null;
  gross_kg: string | null;
  tare_kg: string | null;
  net_kg: string | null;
  quantity_source: string | null;
  note: string | null;
  product_id: string | null;
}
export interface ContractLine extends WeightLine {
  description: string;
  quantity_kg: string;
  unit_price: string;
  source: {
    type: "weighing";
    id: string;
    version: number;
    line_index: number;
    code: string;
    occurred_on: string;
  } | null;
  source_snapshot: WeightLine | null;
}
export interface ContractData {
  kind: "purchase" | "sale";
  number: string;
  occurred_on: string;
  place: string;
  template_id: string;
  company: Party;
  counterparty: Party;
  lines: ContractLine[];
  tax: {
    mode: "unspecified" | "none" | "exclusive" | "inclusive";
    rate: string | null;
  };
  terms: {
    delivery: string;
    packaging: string;
    quality: string;
    deadline: string;
    responsibilities: string;
    additional: string;
  };
  payment: {
    method: "cash" | "bank" | "mixed" | "other";
    description: string;
    receiving_account: BankAccount | null;
    due_on: string | null;
    deposit_amount: string | null;
    recorded_paid_amount: string | null;
    schedule: { due_on: string; amount: string; note: string }[];
  };
  source_refs: { type: string; id: string; version: number }[];
}
export interface ContractDTO {
  id: string;
  version: number;
  data: ContractData;
  totals?: Record<string, unknown>;
  updated_at?: string;
  deleted_at?: string | null;
}
export interface ContractListItem {
  id: string;
  version: number;
  number?: string;
  kind?: ContractData["kind"];
  occurred_on?: string;
  counterparty_name?: string;
  party_name?: string;
  deleted_at?: string | null;
  data?: ContractData;
  updated_at?: string;
}
export interface ContractTemplate {
  id: string;
  title?: string;
  name?: string;
  kind: ContractData["kind"];
  version?: number;
  body?: string;
  sha256?: string;
}
export interface Preview {
  document: {
    title: string;
    subtitle?: string;
    fields: [string, string][] | Record<string, unknown>;
    paragraphs: string[];
    column_headers: string[];
    rows: (string[] | Record<string, unknown>)[];
  };
  totals: Record<string, unknown>;
}
export type ExportFormat = "docx" | "pdf";
export interface ExportVersion {
  id: string;
  contract_id: string;
  contract_version: number;
  sequence?: number;
  template_id?: string;
  template_version?: number;
  template_sha256?: string;
  snapshot_sha256: string;
  created_at?: string;
  data?: ContractData;
  snapshot?: { data?: ContractData; document?: Preview["document"]; totals?: Record<string, unknown> };
  document?: Preview["document"];
  totals?: Record<string, unknown>;
  files: Partial<Record<ExportFormat, {
    status: string;
    file_id?: string | null;
    sha256?: string | null;
    error_code?: string | null;
    error_message?: string | null;
  }>>;
}
export interface Attachment {
  id: string;
  file_id: string;
  original_name?: string;
  sha256?: string;
  version_id: string | null;
  note: string;
  status: "uploaded" | "user_recorded_signed";
  created_at?: string;
}
export interface Weighing {
  id: string;
  version: number;
  code: string;
  occurred_on: string;
  party_id: string | null;
  lines: WeightLine[];
}

export const emptyParty = (): Party => ({
  type: "company", name: "", address: null, tax_code: null,
  contacts: [], bank_details: [], representative: null,
});
export const emptyAccount = (): BankAccount => ({
  bank_name: "", account_number: "", account_holder: null, branch: null,
});
export const emptyLine = (): ContractLine => ({
  description: "", quantity_kg: "", unit_price: "", gross_kg: null,
  tare_kg: null, net_kg: null, quantity_source: null, note: null,
  product_id: null, source: null, source_snapshot: null,
});
export const defaultTemplateIds = {
  purchase: "be33fbce-4a0d-50eb-b203-895a24102ce1",
  sale: "9be1e97b-8278-55d3-aaba-13f663349ab2",
} as const;
export function newContract(): ContractData {
  // Calendar date follows the computer's business timezone, never UTC truncation.
  const now = new Date();
  const date = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
  return {
    kind: "purchase", number: "", occurred_on: date, place: "",
    template_id: defaultTemplateIds.purchase, company: emptyParty(), counterparty: emptyParty(),
    lines: [emptyLine()], tax: { mode: "unspecified", rate: null },
    terms: { delivery: "", packaging: "", quality: "", deadline: "", responsibilities: "", additional: "" },
    payment: { method: "cash", description: "", receiving_account: null, due_on: null,
      deposit_amount: null, recorded_paid_amount: null, schedule: [] },
    source_refs: [],
  };
}

/** Presentation only: decimal text is grouped without converting money/kg to Number. */
export function decimalText(value: unknown): string {
  if (value === null || value === undefined) return "Chưa nhập";
  const raw = String(value);
  if (!/^-?\d+(\.\d+)?$/.test(raw)) return raw;
  const [integer, fraction] = raw.split(".");
  return integer.replace(/\B(?=(\d{3})+(?!\d))/g, ".") + (fraction ? `,${fraction}` : "");
}
