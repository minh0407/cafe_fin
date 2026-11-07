import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert, Button, Checkbox, Descriptions, Drawer, Input, Select, Space, Table, Typography } from "antd";
import { api } from "../../shared/api";
import { useSession } from "../../shared/session";
import type { Page } from "../../shared/types";
import { isDateInputValueValid } from "../../shared/DateInput";
import { CommerceHistory, CommerceNav, invalidateRecords, RecordCommands, useCommerceRecord, useRecordsWrite } from "./CommerceShared";
import { decimal, ErrorNotice } from "./helpers";
import { PartyEditor } from "./PartyEditor";
import type { CommerceParty, ProfileKind } from "./commerceTypes";

export function readCommerceView() {
  const params = new URLSearchParams(location.hash.split("?")[1] ?? "");
  return { page: Math.max(1, Number(params.get("page")) || 1), search: params.get("search") ?? "", sort: params.get("sort") ?? "-updated_at", from_on: params.get("from_on") ?? "", through_on: params.get("through_on") ?? "", selected: params.get("selected") ?? "", include_deleted: params.get("include_deleted") === "true", status: params.get("status") ?? "" };
}
export type CommerceView = ReturnType<typeof readCommerceView>;
export function updateCommerceURL(view: CommerceView) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(view)) if (value !== "" && value !== false && !(key === "page" && value === 1) && (!(key === "from_on" || key === "through_on") || isDateInputValueValid(value))) params.set(key, String(value));
  history.replaceState(null, "", `${location.pathname}${location.search}#${location.hash.slice(1).split("?")[0]}${params.size ? `?${params}` : ""}`);
}

export function PartyData({ value }: { value: CommerceParty }) {
  return <><Descriptions bordered size="small" column={2} items={[
    { key: "code", label: "Mã", children: value.code }, { key: "name", label: "Tên", children: value.name }, { key: "version", label: "Phiên bản", children: value.version }, { key: "status", label: "Tình trạng", children: value.deleted_at ? "Đã xóa mềm" : value.active ? "Đang sử dụng" : "Ngừng sử dụng" },
    { key: "address", label: "Địa chỉ", children: value.address || "—" }, { key: "tax", label: "Mã số thuế", children: value.tax_code || "—" }, { key: "license", label: "Giấy phép", children: value.business_license || "—" }, { key: "rep", label: "Người liên hệ / đại diện", children: value.representative?.name || "—" },
    { key: "contact", label: "Liên hệ", children: value.contacts.map((contact, i) => <div key={i}>{contact.kind}: {contact.value}</div>) }, { key: "bank", label: "Ngân hàng", children: value.bank_details.map((bank, i) => <div key={i}>{bank.bank_name} · {bank.account_number} · {bank.account_holder} · {bank.branch}</div>) },
    ...(value.farm ? [{ key: "owner", label: "Chủ Farm", children: value.farm.owner_name || "—" }, { key: "ownerid", label: "CCCD / giấy tờ", children: value.farm.owner_id_card || "—" }, { key: "official", label: "Mã vùng chính thức", children: value.farm.official_area_code || "—" }, { key: "internal", label: "Mã vùng nội bộ", children: value.farm.internal_area_code || "—" }] : []), { key: "note", label: "Ghi chú", children: value.note || "—" },
  ]} />{value.farm && <><Typography.Title level={5}>Lô trồng</Typography.Title><Table rowKey={(_, i) => String(i)} size="small" pagination={false} dataSource={value.farm.plots} columns={[{ title: "Mã lô", dataIndex: "plot_code" }, { title: "Giống", dataIndex: "variety" }, { title: "Ha", dataIndex: "area_ha", render: decimal }, { title: "Số cây", dataIndex: "tree_count" }, { title: "Tuổi cây", dataIndex: "tree_age" }]} /><Typography.Title level={5}>Khảo sát mùa vụ</Typography.Title><Table rowKey={(_, i) => String(i)} size="small" pagination={false} dataSource={value.farm.surveys} columns={[{ title: "Mùa vụ", dataIndex: "season_year" }, { title: "Grade", dataIndex: "grade" }, { title: "Chín (%)", dataIndex: "ripeness_pct", render: decimal }, { title: "Ghi chú", dataIndex: "notes" }]} /></>}</>;
}

function Catalog({ profile }: { profile: ProfileKind }) {
  const generation = useSession((state) => state.generation);
  return <CatalogSession key={`${profile}/${generation}`} profile={profile} />;
}
function CatalogSession({ profile }: { profile: ProfileKind }) {
  const generation = useSession((state) => state.generation);
  const [view, setView] = useState(readCommerceView);
  const [editor, setEditor] = useState<{ value?: CommerceParty }>();
  const canWrite = useRecordsWrite();
  const cache = useQueryClient();
  useEffect(() => { const change = () => { setView(readCommerceView()); setEditor(undefined); }; window.addEventListener("hashchange", change); return () => window.removeEventListener("hashchange", change); }, []);
  useEffect(() => { updateCommerceURL(view); }, [view]);
  function update(patch: Partial<CommerceView>) { setView((old) => ({ ...old, ...patch })); }
  const filters = { profile_kind: profile, include_deleted: view.include_deleted };
  const query = useQuery({ queryKey: ["records", generation, "catalog", profile, view.page, view.search, view.sort, view.include_deleted], queryFn: () => api<Page<CommerceParty>>(`/records/parties?${new URLSearchParams({ page: String(view.page), page_size: "25", search: view.search, sort: view.sort, filters: JSON.stringify(filters) })}`), gcTime: 0, retry: false });
  const detail = useCommerceRecord<CommerceParty>("parties", view.selected);
  async function saved(value: CommerceParty) { setEditor(undefined); update({ selected: value.id }); await invalidateRecords(cache); }
  const title = profile === "farm" ? "Farm" : "Công ty khách hàng";
  return <><CommerceNav /><Typography.Title level={2}>{title}</Typography.Title>{!canWrite && <Alert type="info" title="Chỉ xem dữ liệu" />}<Space wrap style={{ marginBottom: 16 }}><Input.Search aria-label="Tìm danh mục" value={view.search} onChange={(event) => update({ search: event.target.value, page: 1 })} placeholder="Tìm mã, tên, ghi chú" allowClear /><Select aria-label="Sắp xếp danh mục" value={view.sort} onChange={(sort) => update({ sort, page: 1 })} options={[{ value: "-updated_at", label: "Mới sửa trước" }, { value: "code", label: "Mã tăng dần" }, { value: "name", label: "Tên tăng dần" }]} /><Checkbox checked={view.include_deleted} onChange={(event) => update({ include_deleted: event.target.checked, page: 1 })}>Hiện hồ sơ đã xóa</Checkbox>{canWrite && <Button type="primary" onClick={() => setEditor({})}>Thêm {title}</Button>}<Button onClick={() => void query.refetch()}>Tải lại</Button></Space><ErrorNotice error={query.error || detail.error} />
    <Table<CommerceParty> rowKey="id" size="small" loading={query.isPending} dataSource={query.data?.items ?? []} pagination={{ current: view.page, pageSize: 25, total: query.data?.total ?? 0, showSizeChanger: false, onChange: (page) => update({ page }) }} columns={[{ title: "Mã", dataIndex: "code", render: (code, row) => <Button type="link" onClick={() => update({ selected: row.id })}>{code}</Button> }, { title: "Tên", dataIndex: "name" }, { title: profile === "farm" ? "Chủ Farm" : "Người liên hệ", render: (_, row) => profile === "farm" ? row.farm?.owner_name : row.representative?.name }, { title: "Tình trạng", render: (_, row) => row.deleted_at ? "Đã xóa mềm" : row.active ? "Đang sử dụng" : "Ngừng sử dụng" }]} />
    {view.selected && <Drawer open size={1000} title={detail.data ? `Chi tiết ${detail.data.code}` : "Đang đọc hồ sơ…"} onClose={() => update({ selected: "" })}>{detail.isPending && <Typography.Paragraph>Đang đọc hồ sơ…</Typography.Paragraph>}{detail.data && <Space orientation="vertical" className="full" size="middle"><Space>{canWrite && !detail.data.deleted_at && <Button onClick={() => setEditor({ value: detail.data })}>Sửa dữ liệu</Button>}<RecordCommands resource="parties" value={detail.data} onChanged={() => void detail.refetch()} /></Space><PartyData value={detail.data} /><CommerceHistory resource="parties" value={detail.data} render={(value) => <PartyData value={value} />} /></Space>}</Drawer>}
    {editor && <PartyEditor key={editor.value ? `${editor.value.id}/${editor.value.version}` : "new"} profile={profile} initial={editor.value} onClose={() => setEditor(undefined)} onSaved={(value) => void saved(value)} />}
  </>;
}
export function FarmsPage() { return <Catalog profile="farm" />; }
export function CustomersPage() { return <Catalog profile="customer_company" />; }
