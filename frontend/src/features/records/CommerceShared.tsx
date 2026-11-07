import { createContext, useContext, useEffect, useRef, useState, type ReactNode, type MutableRefObject } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert, Button, Form, List, Modal, Popconfirm, Select, Space, Typography } from "antd";
import type { FormInstance } from "antd";
import { api, ApiError, messageOf } from "../../shared/api";
import { useSession } from "../../shared/session";
import type { Page } from "../../shared/types";
import { ErrorNotice, fieldPath } from "./helpers";
import type { Entity } from "./types";
import type { CommerceResource, ProfileKind } from "./commerceTypes";

export function useRecordsWrite() {
  const user = useSession((state) => state.user);
  return !!user && (user.role === "admin" || user.permissions.includes("*") || user.permissions.includes("records.write"));
}
export function useCommerceRecord<T>(resource: string, id?: string | null) {
  const generation = useSession((state) => state.generation);
  return useQuery({ queryKey: ["records", generation, resource, id], queryFn: () => api<T>(`/records/${resource}/${encodeURIComponent(id!)}`), enabled: !!id, retry: false, gcTime: 0 });
}
export function CommerceNav() {
  return <Space wrap style={{ marginBottom: 16 }}>{[["dashboard", "Tổng quan"], ["inbound", "Đầu vào"], ["outbound", "Đầu ra"], ["prices", "Bảng giá mua / nhập / bán"], ["farms", "Farm"], ["customers", "Công ty khách hàng"], ["", "Kho / phiếu"]].map(([route, label]) => <a key={route} href={`#/records${route ? `/${route}` : ""}`}>{label}</a>)}</Space>;
}
export async function invalidateRecords(cache: ReturnType<typeof useQueryClient>) {
  await Promise.all([cache.invalidateQueries({ queryKey: ["records"] }), cache.invalidateQueries({ queryKey: ["records-reference"] })]);
}

/** A selected value is read independently; lookup pages never exceed 50 rows. */
export function PartySelect({ value, onChange, profile, id, label, disabled }: { value?: string | null; onChange?: (id?: string) => void; profile: ProfileKind; id?: string; label?: string; disabled?: boolean }) {
  const generation = useSession((state) => state.generation);
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [term, setTerm] = useState("");
  useEffect(() => { const timer = setTimeout(() => { setTerm(search); setPage(1); }, 180); return () => clearTimeout(timer); }, [search]);
  const query = useQuery({ queryKey: ["records", generation, "party-lookup", profile, page, term], queryFn: () => api<Page<Entity>>(`/records/parties?${new URLSearchParams({ page: String(page), page_size: "50", search: term, sort: "code", filters: JSON.stringify({ profile_kind: profile, active: true }) })}`), gcTime: 0, retry: false });
  const selected = useCommerceRecord<Entity>("parties", value);
  const options = (query.data?.items ?? []).map((item) => ({ value: item.id, label: `${item.code} — ${item.name}` }));
  if (value && !options.some((item) => item.value === value)) options.unshift({ value, label: selected.data ? `${selected.data.code} — ${selected.data.name}` : value });
  return <><Select id={id} aria-label={label} style={{ width: "100%" }} allowClear showSearch filterOption={false} value={value ?? undefined} disabled={disabled} onChange={onChange} onSearch={setSearch} loading={query.isFetching} options={options} placeholder="Tìm mã hoặc tên" notFoundContent={query.error ? messageOf(query.error) : "Không tìm thấy"} popupRender={(menu) => <>{menu}<Space style={{ padding: 8 }}><Button size="small" disabled={page === 1} onClick={() => setPage(page - 1)}>Trang trước</Button><span>Trang {page}</span><Button size="small" disabled={!query.data || page * 50 >= query.data.total} onClick={() => setPage(page + 1)}>Trang sau</Button></Space></>} /><ErrorNotice error={selected.error} /></>;
}

const WriteLock = createContext<{ locked: boolean; isLocked: () => boolean }>({ locked: false, isLocked: () => false });
export const useCommerceWriteLock = () => useContext(WriteLock);
export function CommerceFormModal<T extends Entity>({ resource, initial, title, defaults, payload, children, onClose, onSaved, form: suppliedForm, canSubmit = true, writeGuard, onValuesChange }: { resource: CommerceResource | "price-boards"; initial?: Partial<T>; title: string; defaults: Record<string, unknown>; payload: (values: Record<string, unknown>) => Record<string, unknown>; children: ReactNode; onClose: () => void; onSaved: (value: T) => void; form?: FormInstance; canSubmit?: boolean; writeGuard?: MutableRefObject<boolean>; onValuesChange?: (changed: Record<string, unknown>) => void }) {
  const [localForm] = Form.useForm();
  const form = suppliedForm ?? localForm;
  const [busy, setBusy] = useState(false);
  const [uncertain, setUncertain] = useState(false);
  const [error, setError] = useState<unknown>();
  const canWrite = useRecordsWrite();
  const generation = useRef(useSession.getState().generation).current;
  const attempt = useRef<{ fingerprint: string; key: string; body: Record<string, unknown> } | null>(null);
  const lock = useRef(false);
  const held = useRef(false);
  held.current = busy || uncertain;
  if (writeGuard) writeGuard.current = busy || uncertain;
  async function save(values: Record<string, unknown>) {
    if (lock.current || !canWrite || (!canSubmit && !uncertain) || useSession.getState().generation !== generation) return;
    const body = uncertain && attempt.current ? attempt.current.body : structuredClone(payload(values));
    if (initial?.id) body.expected_version = initial.version;
    const fingerprint = JSON.stringify(body);
    if (!attempt.current || fingerprint !== attempt.current.fingerprint) attempt.current = { fingerprint, key: crypto.randomUUID(), body };
    lock.current = true; held.current = true; if (writeGuard) writeGuard.current = true; setBusy(true); setError(undefined);
    try {
      const result = await api<T>(`/records/${resource}${initial?.id ? `/${encodeURIComponent(initial.id)}` : ""}`, { method: initial?.id ? "PUT" : "POST", body: JSON.stringify({ ...body, request_key: attempt.current.key }) });
      if (generation !== useSession.getState().generation) return;
      attempt.current = null; setUncertain(false); onSaved(result);
    } catch (error) {
      if (generation !== useSession.getState().generation) return;
      setError(error);
      setUncertain(error instanceof ApiError && ["BACKEND_UNAVAILABLE", "INVALID_API_RESPONSE", "API_ERROR", "INTERNAL_ERROR"].includes(error.code));
      if (error instanceof ApiError) form.setFields(error.fields.map((field) => ({ name: fieldPath(field.field), errors: [field.message] })));
    } finally { lock.current = false; if (generation === useSession.getState().generation) setBusy(false); }
  }
  return <Modal open title={title} width={940} mask={{ closable: false }} keyboard={!busy && !uncertain} closable={!busy && !uncertain} onCancel={() => { if (!busy && !uncertain) onClose(); }} footer={<Space><Button disabled={busy || uncertain} onClick={onClose}>Đóng</Button><Button type="primary" loading={busy} disabled={busy || !canWrite || (!canSubmit && !uncertain)} onClick={() => uncertain ? void save(attempt.current!.body) : form.submit()}>{uncertain ? "Kiểm tra lại cùng yêu cầu" : "Lưu dữ liệu"}</Button></Space>}><ErrorNotice error={error} />{uncertain && <Alert type="warning" title="Chưa xác nhận kết quả lưu. Dữ liệu đang được giữ nguyên; kiểm tra lại cùng yêu cầu để tránh tạo chứng từ lặp." />}{initial?.id && <Typography.Paragraph>Phiên bản {initial.version} · lưu cùng lịch sử sửa đổi.</Typography.Paragraph>}<WriteLock.Provider value={{ locked: busy || uncertain || !canWrite, isLocked: () => held.current || !canWrite }}><Form form={form} layout="vertical" initialValues={defaults} disabled={busy || uncertain || !canWrite} onValuesChange={onValuesChange} onFinish={() => void save(form.getFieldsValue(true))}><fieldset disabled={busy || uncertain || !canWrite} style={{ border: 0, padding: 0, margin: 0, minWidth: 0 }}>{children}</fieldset></Form></WriteLock.Provider></Modal>;
}

export function RecordCommands({ resource, value, onChanged }: { resource: string; value: Entity; onChanged: () => void }) {
  const canWrite = useRecordsWrite();
  const generation = useSession((state) => state.generation);
  const cache = useQueryClient();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>();
  const keys = useRef(new Map<string, string>());
  const lock = useRef(false);
  async function run(action: string) {
    if (lock.current || !canWrite) return;
    const identity = `${value.id}/${value.version}/${action}`;
    if (!keys.current.has(identity)) keys.current.set(identity, crypto.randomUUID());
    lock.current = true; setBusy(true); setError(undefined);
    try {
      await api(`/records/${resource}/${encodeURIComponent(value.id)}${action === "delete" ? "" : `/${action}`}`, { method: action === "delete" ? "DELETE" : "POST", body: JSON.stringify({ expected_version: value.version, request_key: keys.current.get(identity) }) });
      if (generation !== useSession.getState().generation) return;
      keys.current.delete(identity); await invalidateRecords(cache); onChanged();
    } catch (error) { if (generation === useSession.getState().generation) setError(error); }
    finally { lock.current = false; if (generation === useSession.getState().generation) setBusy(false); }
  }
  if (!canWrite) return null;
  const status = (value as Entity & { status?: string }).status;
  return <><Space wrap>{value.deleted_at ? <Button loading={busy} onClick={() => void run("restore")}>Khôi phục</Button> : <><Popconfirm title="Xóa mềm hồ sơ?" description="Hệ thống kiểm tra liên kết và tồn kho trước khi lưu. Lịch sử được giữ." onConfirm={() => run("delete")} okText="Xóa mềm" cancelText="Đóng"><Button danger disabled={busy}>Xóa mềm</Button></Popconfirm>{resource === "entries" && <Popconfirm title={status === "posted" ? "Hủy tác động kho?" : "Ghi phiếu vào sổ kho?"} description="Tồn kho và giới hạn đơn hàng sẽ được kiểm tra lại." onConfirm={() => run(status === "posted" ? "cancel" : "post")} okText="Xác nhận" cancelText="Đóng"><Button disabled={busy}>{status === "posted" ? "Hủy phiếu kho" : "Ghi vào sổ kho"}</Button></Popconfirm>}</>}</Space><ErrorNotice error={error} /></>;
}

export function CommerceHistory<T extends Entity>({ resource, value, render }: { resource: string; value: T; render: (value: T) => ReactNode }) {
  const generation = useSession((state) => state.generation);
  const [open, setOpen] = useState(false);
  const [page, setPage] = useState(1);
  const [revision, setRevision] = useState<T>();
  const query = useQuery({ queryKey: ["records", generation, "commerce-history", resource, value.id, value.version, page], queryFn: () => api<Page<{ version: number; action: string; recorded_at: string; data: T }>>(`/records/${resource}/${encodeURIComponent(value.id)}/history?page=${page}&page_size=20`), enabled: open, retry: false, gcTime: 0 });
  return <><Button onClick={() => setOpen(!open)}>{open ? "Ẩn lịch sử" : "Xem lịch sử"}</Button>{open && <><ErrorNotice error={query.error} /><List loading={query.isPending} dataSource={query.data?.items ?? []} pagination={{ current: page, pageSize: 20, total: query.data?.total ?? 0, onChange: setPage }} renderItem={(item) => <List.Item actions={[<Button key="view" onClick={() => setRevision(item.data)}>Xem bản {item.version}</Button>]}>{item.action} · {new Date(item.recorded_at).toLocaleString("vi-VN", { timeZone: "Asia/Ho_Chi_Minh" })}</List.Item>} />{revision && <><Typography.Title level={5}>Bản lịch sử {revision.version}</Typography.Title>{render(revision)}</>}</>}</>;
}
