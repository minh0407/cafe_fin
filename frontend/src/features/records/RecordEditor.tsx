import { useRef, useState } from "react";
import { Alert, Button, Form, Modal, Typography } from "antd";
import { api, ApiError } from "../../shared/api";
import { useSession } from "../../shared/session";
import { EditorFooter, ErrorNotice, fieldPath, todayVN } from "./helpers";
import { RecordFields } from "./RecordFields";
import type { RecordEntity, Resource } from "./types";
import type { Direction } from "./commerceTypes";

const dataFields: Record<Resource, string[]> = {
  parties: ["code", "name", "type", "roles", "address", "tax_code", "contacts", "bank_details", "representative", "note", "active", "profile_kind", "business_license", "farm"],
  products: ["code", "name", "unit_id", "note", "active"],
  "products/units": ["code", "name", "note", "active"],
  "products/warehouses": ["code", "name", "note", "active"],
  weighings: ["code", "occurred_on", "occurred_at", "physical_actor", "party_id", "vehicle_plate", "note", "lines"],
  entries: ["code", "occurred_on", "occurred_at", "physical_actor", "entry_type", "status", "party_id", "weighing_id", "trade_id", "note", "commercial_amount_vnd", "lines"],
};

export function payloadFor(resource: Resource, values: Record<string, unknown>): Record<string, unknown> {
  const payload = Object.fromEntries(dataFields[resource].filter((field) => values[field] !== undefined).map((field) => [field, values[field]]));
  for (const field of ["party_id", "weighing_id", "trade_id", "unit_id", "commercial_amount_vnd", "occurred_at"]) if (payload[field] === "") payload[field] = null;
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

export function RecordEditor({ resource, initial, title, onClose, onSaved, linkedTrade }: { resource: Resource; initial?: Partial<RecordEntity>; title: string; onClose: () => void; onSaved: (value: RecordEntity) => void; linkedTrade?: { direction: Direction; code: string; newDraft?: boolean } }) {
  const [form] = Form.useForm();
  const [busy, setBusy] = useState(false);
  const [uncertain, setUncertain] = useState(false);
  const [error, setError] = useState<unknown>();
  const generation = useRef(useSession.getState().generation).current;
  const attempt = useRef<{ fingerprint: string; key: string; payload: Record<string, unknown> } | null>(null);
  const lock = useRef(false);
  const defaults = { active: true, type: "organization", roles: [], contacts: [], bank_details: [], occurred_on: todayVN(), entry_type: "receipt", status: "draft", lines: resource === "weighings" ? [{ quantity_source: "direct_net" }] : [{ direction: "in" }], ...initial };

  async function save(values: Record<string, unknown>) {
    if (lock.current || useSession.getState().generation !== generation) return;
    // Preserve additive profile/link fields even when the legacy form does not
    // register them. Editing an old tool must not detach a trade or erase a farm.
    const preserved = Object.fromEntries((resource === "parties" ? ["profile_kind", "business_license", "farm"] : resource === "entries" ? ["trade_id"] : []).filter((key) => initial && key in initial).map((key) => [key, (initial as unknown as Record<string, unknown>)[key]]));
    const payload = uncertain && attempt.current ? attempt.current.payload : payloadFor(resource, { ...preserved, ...values });
    if (initial?.id) payload.expected_version = initial.version;
    const fingerprint = JSON.stringify(payload);
    if (!attempt.current || attempt.current.fingerprint !== fingerprint) attempt.current = { fingerprint, key: crypto.randomUUID(), payload };
    lock.current = true;
    setBusy(true);
    setError(undefined);
    try {
      const output = await api<RecordEntity>(`/records/${resource}${initial?.id ? `/${encodeURIComponent(initial.id)}` : ""}`, { method: initial?.id ? "PUT" : "POST", body: JSON.stringify({ ...payload, request_key: attempt.current.key }) });
      if (useSession.getState().generation !== generation) return;
      attempt.current = null;
      setUncertain(false);
      onSaved(output);
    } catch (err) {
      if (useSession.getState().generation !== generation) return;
      setError(err);
      setUncertain(err instanceof ApiError && ["BACKEND_UNAVAILABLE", "INVALID_API_RESPONSE", "API_ERROR", "INTERNAL_ERROR"].includes(err.code));
      if (err instanceof ApiError) form.setFields(err.fields.map((field) => ({ name: fieldPath(field.field), errors: [field.message] })));
    } finally {
      lock.current = false;
      if (useSession.getState().generation === generation) setBusy(false);
    }
  }

  return <Modal open title={title} width={860} mask={{ closable: false }} keyboard={!busy && !uncertain} closable={!busy && !uncertain} onCancel={() => { if (!busy && !uncertain) onClose(); }} footer={uncertain ? <Button disabled={busy} onClick={() => void save(attempt.current!.payload)}>Kiểm tra lại cùng yêu cầu</Button> : <EditorFooter busy={busy} onCancel={onClose} onSave={() => form.submit()} />}>
    {initial?.id && <Typography.Paragraph type="secondary">{initial.code} · phiên bản {initial.version}. Thay đổi được lưu cùng lịch sử.</Typography.Paragraph>}
    <ErrorNotice error={error} />
    {uncertain && <Alert type="warning" title="Chưa xác nhận kết quả lưu. Dữ liệu được giữ nguyên; kiểm tra lại cùng yêu cầu để tránh ghi lặp." />}
    <Form form={form} layout="vertical" initialValues={defaults} disabled={busy || uncertain} onFinish={() => void save(form.getFieldsValue(true))} onKeyDown={(event) => { if (!uncertain && (event.ctrlKey || event.metaKey) && event.key === "Enter") { event.preventDefault(); form.submit(); } }}>
      <RecordFields resource={resource} linkedTrade={linkedTrade} />
      <Typography.Paragraph type="secondary">Tab để chuyển ô, Ctrl+Enter để lưu. Số kg và tiền nhập bằng dấu chấm thập phân; không dùng dấu phân cách hàng nghìn.</Typography.Paragraph>
    </Form>
    {busy && <Alert type="info" title="Đang chờ xác nhận lưu từ dữ liệu local…" />}
  </Modal>;
}
