import { Alert, Button, Form, Input, Space, Typography } from "antd";
import type { NamePath } from "antd/es/form/interface";
import { ApiError, messageOf } from "../../shared/api";

export const kgRules = [{ pattern: /^(?:0|[1-9]\d*)(?:\.\d{1,3})?$/, message: "Nhập kg bằng dấu chấm, tối đa 3 chữ số thập phân." }];
export const moneyRules = [{ pattern: /^-?(?:0|[1-9]\d*)(?:\.\d{1,2})?$/, message: "Nhập số tiền bằng dấu chấm, tối đa 2 chữ số thập phân." }];
export const required = [{ required: true, message: "Cần nhập thông tin này." }];

export function todayVN(): string {
  const parts = new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Ho_Chi_Minh", year: "numeric", month: "2-digit", day: "2-digit" }).formatToParts(new Date());
  return ["year", "month", "day"].map((kind) => parts.find((part) => part.type === kind)?.value).join("-");
}

/** Text-only formatting keeps all decimal digits, including totals beyond int64. */
export function decimal(value: string | null | undefined): string {
  if (value === null || value === undefined || value === "") return "—";
  const match = /^(-?)(\d+)(?:\.(\d+))?$/.exec(value);
  if (!match) return value;
  return `${match[1]}${match[2].replace(/\B(?=(\d{3})+(?!\d))/g, ".")}${match[3] ? `,${match[3]}` : ""}`;
}

export function fieldPath(field: string): NamePath {
  return field.replace(/^body\./, "").replace(/\[(\d+)\]/g, ".$1").split(".").map((part) => /^\d+$/.test(part) ? Number(part) : part);
}

export function ErrorNotice({ error }: { error: unknown }) {
  if (!error) return null;
  return <Alert type="error" showIcon title={messageOf(error)} description={error instanceof ApiError && error.fields.length > 0 ? <ul>{error.fields.map((field, i) => <li key={`${field.field}-${i}`}>{field.field}: {field.message}</li>)}</ul> : undefined} />;
}

export function DecimalInput({ label, name, money = false, requiredValue = false }: { label: string; name: NamePath; money?: boolean; requiredValue?: boolean }) {
  return <Form.Item label={label} name={name} rules={[...(requiredValue ? required : []), ...(money ? moneyRules : kgRules)]}><Input inputMode="decimal" placeholder={money ? "Ví dụ 120000.50" : "Ví dụ 1250.125"} autoComplete="off" /></Form.Item>;
}

export function Coverage({ cutoff }: { cutoff?: string }) {
  return <Typography.Paragraph type="secondary">Chỉ phản ánh dữ liệu đã nhập. Ngày nghiệp vụ theo giờ Việt Nam (UTC+07:00).{cutoff ? ` Dữ liệu ghi nhận đến ${new Date(cutoff).toLocaleString("vi-VN", { timeZone: "Asia/Ho_Chi_Minh" })}.` : ""}</Typography.Paragraph>;
}

export function EditorFooter({ busy, onCancel, onSave }: { busy: boolean; onCancel: () => void; onSave: () => void }) {
  return <Space><Button disabled={busy} onClick={onCancel}>Đóng</Button><Button type="primary" aria-label="Lưu dữ liệu" disabled={busy} aria-busy={busy} loading={busy} onClick={onSave}>Lưu dữ liệu</Button></Space>;
}
