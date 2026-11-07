import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert, Button, Checkbox, Descriptions, Drawer, Form, Input, Select, Space, Table, Typography } from "antd";
import type { FormInstance } from "antd";
import { api } from "../../shared/api";
import { DateInput, dateInputRule, isDateInputValueValid } from "../../shared/DateInput";
import { useSession } from "../../shared/session";
import type { Page } from "../../shared/types";
import { CommerceFormModal, CommerceHistory, CommerceNav, invalidateRecords, RecordCommands, useCommerceRecord, useCommerceWriteLock, useRecordsWrite } from "./CommerceShared";
import { priceKindOptions, type PriceBoard } from "./commerceTypes";
import { decimal, DecimalInput, displayBusinessDate, ErrorNotice, required, todayVN } from "./helpers";
import { ReferenceSelect } from "./ReferenceSelect";
import { ReferenceText } from "./RecordDetail";
import { MarketProvenance, ProcessedMarketCard, useProcessedMarket } from "./ProcessedMarket";

interface Preview { pricing_method: "flat" | "grade"; flat_price_vnd: string | null; grade_prices: { grade: number; unit_price_vnd: string }[]; formula_version: 1 }
export function priceBoardPayload(values: Record<string, unknown>) {
  const fields = ["price_date", "price_kind", "product_id", "pricing_method", "active", "note"];
  return { ...Object.fromEntries(fields.filter((key) => values[key] !== undefined).map((key) => [key, values[key] === "" ? null : values[key]])), product_id: values.product_id || null, flat_price_vnd: values.pricing_method === "flat" ? values.flat_price_vnd : null, grade5_price_vnd: values.pricing_method === "grade" ? values.grade5_price_vnd : null };
}
function PriceFields({ form, initial }: { form: FormInstance; initial?: PriceBoard }) {
  const kind = Form.useWatch("price_kind", form);
  const method = Form.useWatch("pricing_method", form);
  const flat = Form.useWatch("flat_price_vnd", form);
  const grade5 = Form.useWatch("grade5_price_vnd", form);
  const fingerprint = JSON.stringify([method, flat, grade5]);
  const [preview, setPreview] = useState<Preview>();
  const [previewKey, setPreviewKey] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>();
  const serial = useRef(0);
  const generation = useRef(useSession.getState().generation).current;
  const { locked, isLocked } = useCommerceWriteLock();
  const latest = useRef(fingerprint); latest.current = fingerprint;
  useEffect(() => () => { serial.current++; }, []);
  useEffect(() => { if (locked) serial.current++; else setBusy(false); }, [locked]);
  async function showPreview() {
    if (isLocked()) return;
    try { await form.validateFields([method === "flat" ? "flat_price_vnd" : "grade5_price_vnd"]); } catch { return; }
    const request = ++serial.current;
    const identity = fingerprint;
    setBusy(true); setError(undefined);
    const fresh = () => request === serial.current && identity === latest.current && !isLocked() && generation === useSession.getState().generation;
    try {
      const result = await api<Preview>("/records/price-board-preview", { method: "POST", body: JSON.stringify({ pricing_method: method, flat_price_vnd: method === "flat" ? flat : null, grade5_price_vnd: method === "grade" ? grade5 : null }) });
      if (fresh()) { setPreview(result); setPreviewKey(identity); }
    } catch (failure) { if (fresh()) setError(failure); }
    finally { if (request === serial.current && !isLocked()) setBusy(false); }
  }
  return <><Alert type="info" title="Bảng chỉ áp dụng đúng ngày. Giá bán cài riêng theo hàng; giá mua / nhập là giá đầu vào, không dùng thay giá bán." />
    {initial && <Typography.Paragraph>{initial.code} · {initial.name} · Khóa ngày / nhóm / hàng được giữ nguyên khi sửa.</Typography.Paragraph>}
    <Form.Item label="Ngày bảng giá" name="price_date" rules={[...required, dateInputRule]}><DateInput disabled={!!initial || locked} /></Form.Item>
    <Form.Item label="Nhóm bảng giá" name="price_kind" rules={required}><Select disabled={!!initial || locked} options={priceKindOptions} onChange={(value) => { form.setFieldsValue({ pricing_method: value === "sale" ? "flat" : "grade", flat_price_vnd: null, grade5_price_vnd: null }); }} /></Form.Item>
    <Form.Item label={kind === "sale" ? "Hàng hóa áp dụng (bắt buộc cho bán)" : "Hàng hóa áp dụng (bỏ trống = giá mua chung)"} name="product_id" rules={kind === "sale" ? required : []}><ReferenceSelect resource="products" disabled={!!initial || locked} /></Form.Item>
    <Form.Item label="Cách tính giá" name="pricing_method" rules={required}><Select options={[{ value: "grade", label: "Grade5 → Grade1, 90% từng bước" }, { value: "flat", label: "Một giá cố định" }]} /></Form.Item>
    {method === "flat" ? <DecimalInput label="Giá cố định (VND/kg)" name="flat_price_vnd" money requiredValue /> : <><DecimalInput label="Giá Grade5 (VND/kg)" name="grade5_price_vnd" money requiredValue /><Typography.Paragraph>Grade4 = Grade5 × 90%, tiếp tục đến Grade1. Làm tròn tới 2 số lẻ ở từng bước (chữ số thứ ba từ 5 làm tròn lên) như CRM cũ; không làm tròn kg đã nhập.</Typography.Paragraph></>}
    <Button disabled={locked} loading={busy} onClick={() => void showPreview()}>Xem trước giá</Button><ErrorNotice error={error} />
    {preview && previewKey === fingerprint && <><Typography.Paragraph>Giá xem trước · quy tắc phiên bản {preview.formula_version}.</Typography.Paragraph>{preview.pricing_method === "flat" ? <Typography.Paragraph>Giá cố định: {decimal(preview.flat_price_vnd)} VND/kg</Typography.Paragraph> : <Table rowKey="grade" size="small" pagination={false} dataSource={preview.grade_prices} columns={[{ title: "Grade", dataIndex: "grade" }, { title: "VND/kg", dataIndex: "unit_price_vnd", render: decimal }]} />}</>}
    <Form.Item name="active" valuePropName="checked"><Checkbox>Đang áp dụng</Checkbox></Form.Item><Form.Item label="Ghi chú bảng giá" name="note"><Input.TextArea /></Form.Item>
  </>;
}
function PriceData({ value }: { value: PriceBoard }) {
  return <Descriptions bordered column={1} items={[{ key: "code", label: "Mã / tên tự sinh", children: `${value.code} · ${value.name}` }, { key: "version", label: "Phiên bản", children: value.version }, { key: "date", label: "Ngày", children: displayBusinessDate(value.price_date) }, { key: "kind", label: "Nhóm giá", children: priceKindOptions.find((x) => x.value === value.price_kind)?.label }, { key: "product", label: "Hàng hóa", children: value.product_id ? <ReferenceText resource="products" id={value.product_id} /> : "Giá mua chung" }, { key: "method", label: "Cách tính", children: value.pricing_method === "grade" ? "Grade5 × 90% từng bước, làm tròn 2 số lẻ" : "Giá cố định" }, { key: "price", label: value.pricing_method === "grade" ? "Giá Grade5" : "Giá cố định", children: decimal(value.pricing_method === "grade" ? value.grade5_price_vnd : value.flat_price_vnd) }, { key: "active", label: "Tình trạng", children: value.deleted_at ? "Đã xóa mềm" : value.active ? "Đang áp dụng" : "Ngừng áp dụng" }, { key: "note", label: "Ghi chú", children: value.note || "—" }]} />;
}
function readView() {
  const q = new URLSearchParams(location.hash.split("?")[1]);
  return { page: Math.max(1, Number(q.get("page")) || 1), search: q.get("search") || "", sort: q.get("sort") || "-price_date", price_date: q.get("price_date") || "", price_kind: q.get("price_kind") || "", product_id: q.get("product_id") || "", include_deleted: q.get("include_deleted") === "true", selected: q.get("selected") || "" };
}
export function PricesPage() {
  const generation = useSession((state) => state.generation);
  return <PricesSession key={generation} />;
}
function PricesSession() {
  const generation = useSession((state) => state.generation);
  const [view, setView] = useState(readView);
  const [editor, setEditor] = useState<{ value?: PriceBoard }>();
  const cache = useQueryClient();
  const canWrite = useRecordsWrite();
  const validDate = isDateInputValueValid(view.price_date);
  const update = (patch: Partial<typeof view>) => setView((old) => ({ ...old, ...patch }));
  useEffect(() => { const listener = () => { if (location.hash.split("?")[0] !== "#/records/prices") return; setView(readView()); setEditor(undefined); }; window.addEventListener("hashchange", listener); return () => window.removeEventListener("hashchange", listener); }, []);
  useEffect(() => { if (location.hash.split("?")[0] !== "#/records/prices") return; const q = new URLSearchParams(); Object.entries(view).forEach(([key, value]) => { if (value !== "" && value !== false && (key !== "price_date" || isDateInputValueValid(String(value)))) q.set(key, String(value)); }); history.replaceState(null, "", `${location.pathname}${location.search}#/records/prices?${q}`); }, [view]);
  const filters = { include_deleted: view.include_deleted, ...(view.price_date ? { price_date: view.price_date } : {}), ...(view.price_kind ? { price_kind: view.price_kind } : {}), ...(view.product_id ? { product_id: view.product_id } : {}) };
  const query = useQuery({ queryKey: ["records", generation, "prices-list", view.page, view.search, view.sort, filters], queryFn: () => api<Page<PriceBoard>>(`/records/price-boards?${new URLSearchParams({ page: String(view.page), page_size: "25", search: view.search, sort: view.sort, filters: JSON.stringify(filters) })}`), enabled: validDate, retry: false, gcTime: 0 });
  const detail = useCommerceRecord<PriceBoard>("price-boards", view.selected);
  const selectedMarket = useProcessedMarket(detail.data?.price_date, !!detail.data && !!view.selected);
  const managed = selectedMarket.data?.status === "APPLIED" && selectedMarket.data.board_id === detail.data?.id;
  const managementKnown = !!selectedMarket.data && !selectedMarket.error && selectedMarket.data.price_date === detail.data?.price_date;
  async function saved(value: PriceBoard) { setEditor(undefined); update({ selected: value.id }); await invalidateRecords(cache); }
  function edit(value?: PriceBoard) { setEditor({ value }); }
  return <><CommerceNav /><Typography.Title level={2}>Bảng giá mua / nhập / bán</Typography.Title><ProcessedMarketCard onOpenBoard={(selected) => update({ selected })} /><Space wrap style={{ marginBottom: 16 }}><Input.Search aria-label="Tìm bảng giá" value={view.search} onChange={(e) => update({ search: e.target.value, page: 1 })} /><DateInput aria-label="Lọc ngày bảng giá" value={view.price_date} onChange={(price_date) => update({ price_date, page: 1 })} /><Select aria-label="Lọc nhóm giá" allowClear placeholder="Mọi nhóm giá" value={view.price_kind || undefined} options={priceKindOptions} onChange={(price_kind) => update({ price_kind: price_kind || "", page: 1 })} /><ReferenceSelect label="Lọc hàng bảng giá" resource="products" value={view.product_id} onChange={(product_id) => update({ product_id: product_id || "", page: 1 })} /><Select aria-label="Sắp xếp bảng giá" value={view.sort} onChange={(sort) => update({ sort, page: 1 })} options={[{ value: "-price_date", label: "Ngày mới trước" }, { value: "price_date", label: "Ngày cũ trước" }, { value: "code", label: "Mã tăng dần" }, { value: "-updated_at", label: "Mới sửa trước" }]} /><Checkbox checked={view.include_deleted} onChange={(e) => update({ include_deleted: e.target.checked, page: 1 })}>Hiện bảng đã xóa</Checkbox>{canWrite && <Button type="primary" onClick={() => edit()}>Thêm bảng giá</Button>}<Button onClick={() => void query.refetch()} disabled={!validDate}>Tải lại</Button></Space>{!validDate && <Alert type="warning" title="Nhập ngày theo DD/MM/YYYY." />}<ErrorNotice error={query.error || detail.error} />
    <Table<PriceBoard> rowKey="id" size="small" loading={validDate && query.isPending} dataSource={query.data?.items ?? []} pagination={{ current: view.page, pageSize: 25, total: query.data?.total ?? 0, showSizeChanger: false, onChange: (page) => update({ page }) }} columns={[{ title: "Bảng giá", dataIndex: "code", render: (code, row) => <Button type="link" onClick={() => update({ selected: row.id })}>{code}</Button> }, { title: "Ngày", dataIndex: "price_date", render: displayBusinessDate }, { title: "Nhóm", dataIndex: "price_kind", render: (kind) => priceKindOptions.find((x) => x.value === kind)?.label }, { title: "Hàng", dataIndex: "product_id", render: (id) => id ? <ReferenceText resource="products" id={id} /> : "Giá mua chung" }, { title: "Giá cơ sở (VND/kg)", render: (_, row) => decimal(row.pricing_method === "grade" ? row.grade5_price_vnd : row.flat_price_vnd) }, { title: "Trạng thái", render: (_, row) => row.deleted_at ? "Đã xóa mềm" : row.active ? "Đang áp dụng" : "Ngừng áp dụng" }]} />
    {detail.data && view.selected && <Drawer open title={`Bảng giá · ${detail.data.code}`} size={850} onClose={() => update({ selected: "" })}><Space orientation="vertical" className="full"><PriceData value={detail.data} />{managed && <><Alert type="info" title="Bảng giá tự động chỉ đọc" description="Giá và nguồn đã được lưu cùng nhau. Không sửa, ngừng áp dụng, xóa hoặc khôi phục bảng tự động; có thể thêm bảng giá riêng theo hàng." /><MarketProvenance value={selectedMarket.data!} /></>}{!managementKnown && <><Alert type="warning" title="Chưa xác minh được nguồn bảng giá; thao tác sửa / xóa đang tạm khóa." /><ErrorNotice error={selectedMarket.error} /><Button onClick={() => void selectedMarket.refetch()}>Kiểm tra nguồn bảng giá</Button></>}{managementKnown && !managed && <>{canWrite && !detail.data.deleted_at && <Button onClick={() => edit(detail.data)}>Sửa bảng giá / ngừng áp dụng</Button>}<RecordCommands resource="price-boards" value={detail.data} onChanged={() => void detail.refetch()} /></>}<CommerceHistory resource="price-boards" value={detail.data} render={(value) => <PriceData value={value} />} /></Space></Drawer>}
    {editor && <PriceBoardEditor key={editor.value ? `${editor.value.id}/${editor.value.version}` : "new"} initial={editor.value} onClose={() => setEditor(undefined)} onSaved={(value) => void saved(value)} />}
  </>;
}

export function PriceBoardEditor({ initial, defaults, onClose, onSaved }: { initial?: PriceBoard; defaults?: Record<string, unknown>; onClose: () => void; onSaved: (value: PriceBoard) => void }) {
  const [form] = Form.useForm();
  return <CommerceFormModal<PriceBoard> resource="price-boards" title={initial ? "Sửa bảng giá" : "Thêm bảng giá"} initial={initial} defaults={{ price_date: todayVN(), price_kind: "purchase_fresh", pricing_method: "grade", active: true, ...defaults, ...initial }} form={form} payload={priceBoardPayload} onClose={onClose} onSaved={onSaved}><PriceFields form={form} initial={initial} /></CommerceFormModal>;
}
