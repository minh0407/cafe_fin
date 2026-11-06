import { useRef, useState } from "react";
import { Alert, Form, Modal, Typography } from "antd";
import { api, ApiError } from "../../shared/api";
import { useSession } from "../../shared/session";
import { EditorFooter, ErrorNotice, fieldPath, todayVN } from "./helpers";
import { RecordFields } from "./RecordFields";
import type { RecordEntity, Resource } from "./types";

const dataFields: Record<Resource, string[]> = {
  parties: ["code", "name", "type", "roles", "address", "tax_code", "contacts", "bank_details", "representative", "note", "active"],
  products: ["code", "name", "unit_id", "note", "active"],
  "products/units": ["code", "name", "note", "active"],
  "products/warehouses": ["code", "name", "note", "active"],
  weighings: ["code", "occurred_on", "occurred_at", "physical_actor", "party_id", "vehicle_plate", "note", "lines"],
  entries: ["code", "occurred_on", "occurred_at", "physical_actor", "entry_type", "status", "party_id", "weighing_id", "note", "commercial_amount_vnd", "lines"],
};

export function payloadFor(resource: Resource, values: Record<string, unknown>): Record<string, unknown> {
  const payload = Object.fromEntries(dataFields[resource].filter((field) => values[field] !== undefined).map((field) => [field, values[field]]));
  for (const field of ["party_id", "weighing_id", "unit_id", "commercial_amount_vnd", "occurred_at"]) if (payload[field] === "") payload[field] = null;
  if (resource === "parties") {
    const rep = payload.representative as Record<string, unknown> | null | undefined;
    if (rep && !rep.name && !rep.title && !rep.authorization_reference) payload.representative = null;
    payload.roles ??= [];
    payload.contacts ??= [];
    payload.bank_details ??= [];
  }
  if (resource === "weighings") payload.lines = (payload.lines as Record<string, unknown>[] ?? []).map((line) => ({ ...line, gross_kg: line.quantity_source === "gross_tare" ? line.gross_kg || null : null, tare_kg: line.quantity_source === "gross_tare" ? line.tare_kg || null : null, net_kg: line.quantity_source === "direct_net" ? line.net_kg || null : null }));
  if (resource === "entries") payload.lines = (payload.lines as Record<string, unknown>[] ?? []).map((line) => ({ ...line, product_id: line.product_id || null, warehouse_id: line.warehouse_id || null, quantity_kg: line.quantity_kg === "" || line.quantity_kg === undefined ? null : line.quantity_kg }));
  return payload;
}

export function RecordEditor({ resource, initial, title, onClose, onSaved }: { resource: Resource; initial?: Partial<RecordEntity>; title: string; onClose: () => void; onSaved: (value: RecordEntity) => void }) {
  const [form] = Form.useForm();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>();
  const generation = useRef(useSession.getState().generation).current;
  const attempt = useRef<{ fingerprint: string; key: string } | null>(null);
  const defaults = { active: true, type: "organization", roles: [], contacts: [], bank_details: [], occurred_on: todayVN(), entry_type: "receipt", status: "draft", lines: resource === "weighings" ? [{ quantity_source: "direct_net" }] : [{ direction: "in" }], ...initial };

  async function save(values: Record<string, unknown>) {
    if (busy || useSession.getState().generation !== generation) return;
    const payload = payloadFor(resource, values);
    if (initial?.id) payload.expected_version = initial.version;
    const fingerprint = JSON.stringify(payload);
    if (!attempt.current || attempt.current.fingerprint !== fingerprint) attempt.current = { fingerprint, key: crypto.randomUUID() };
    setBusy(true);
    setError(undefined);
    try {
      const output = await api<RecordEntity>(`/records/${resource}${initial?.id ? `/${encodeURIComponent(initial.id)}` : ""}`, { method: initial?.id ? "PUT" : "POST", body: JSON.stringify({ ...payload, request_key: attempt.current.key }) });
      if (useSession.getState().generation !== generation) return;
      attempt.current = null;
      onSaved(output);
    } catch (err) {
      if (useSession.getState().generation !== generation) return;
      setError(err);
      if (err instanceof ApiError) form.setFields(err.fields.map((field) => ({ name: fieldPath(field.field), errors: [field.message] })));
    } finally {
      if (useSession.getState().generation === generation) setBusy(false);
    }
  }

  return <Modal open title={title} width={860} mask={{ closable: false }} keyboard={!busy} closable={!busy} onCancel={() => { if (!busy) onClose(); }} footer={<EditorFooter busy={busy} onCancel={onClose} onSave={() => form.submit()} />}>
    {initial?.id && <Typography.Paragraph type="secondary">{initial.code} · phiên bản {initial.version}. Thay đổi được lưu cùng lịch sử.</Typography.Paragraph>}
    <ErrorNotice error={error} />
    <Form form={form} layout="vertical" initialValues={defaults} disabled={busy} onFinish={(values) => void save(values)} onKeyDown={(event) => { if ((event.ctrlKey || event.metaKey) && event.key === "Enter") { event.preventDefault(); form.submit(); } }}>
      <RecordFields resource={resource} />
      <Typography.Paragraph type="secondary">Tab để chuyển ô, Ctrl+Enter để lưu. Số kg và tiền nhập bằng dấu chấm thập phân; không dùng dấu phân cách hàng nghìn.</Typography.Paragraph>
    </Form>
    {busy && <Alert type="info" title="Đang chờ xác nhận lưu từ dữ liệu local…" />}
  </Modal>;
}
