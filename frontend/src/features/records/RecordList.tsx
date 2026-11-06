import { useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Button, Checkbox, Input, Popconfirm, Select, Space, Table, Tag, Typography } from "antd";
import { api } from "../../shared/api";
import { useSession } from "../../shared/session";
import type { Page } from "../../shared/types";
import { ErrorNotice } from "./helpers";
import { ReferenceText } from "./RecordDetail";
import { ReferenceSelect } from "./ReferenceSelect";
import { entryLabels, type Entry, type RecordEntity, type Resource } from "./types";

export interface ViewFilters { page: number; from_on: string; through_on: string; entry_type: string; status: string; active: string; include_deleted: boolean }
export function readView(): ViewFilters {
  const params = new URLSearchParams(location.hash.split("?")[1] || "");
  return { page: Math.max(1, Number(params.get("page")) || 1), from_on: params.get("from_on") || "", through_on: params.get("through_on") || "", entry_type: params.get("entry_type") || "", status: params.get("status") || "", active: params.get("active") || "", include_deleted: params.get("include_deleted") === "true" };
}

export function RecordList({ resource, canWrite, onCreate, onView, onEdit }: { resource: Resource; canWrite: boolean; onCreate: () => void; onView: (value: RecordEntity) => void; onEdit: (value: RecordEntity) => void }) {
  const generation = useSession((state) => state.generation);
  const cache = useQueryClient();
  const [view, setView] = useState<ViewFilters>(readView);
  const [search, setSearch] = useState("");
  const [party, setParty] = useState<string>();
  const [sort, setSort] = useState("-updated_at");
  const [error, setError] = useState<unknown>();
  const [busy, setBusy] = useState<string | null>(null);
  const commands = useRef(new Map<string, string>());
  const dated = ["entries", "weighings"].includes(resource);
  const filters = { ...(view.from_on && dated ? { from_on: view.from_on } : {}), ...(view.through_on && dated ? { through_on: view.through_on } : {}), ...(party && dated ? { party_id: party } : {}), ...(resource === "entries" && view.entry_type ? { entry_type: view.entry_type } : {}), ...(resource === "entries" && view.status ? { status: view.status } : {}), ...(!dated && view.active ? { active: view.active === "true" } : {}), include_deleted: view.include_deleted };
  const query = useQuery({ queryKey: ["records", generation, "list", resource, view.page, search, sort, filters], queryFn: () => {
    const params = new URLSearchParams({ page: String(view.page), page_size: "25", search, sort, filters: JSON.stringify(filters) });
    return api<Page<RecordEntity>>(`/records/${resource}?${params}`);
  }, gcTime: 0, retry: false });
  function update(patch: Partial<ViewFilters>) {
    const next = { ...view, ...patch };
    setView(next);
    const params = new URLSearchParams(location.hash.split("?")[1] || "");
    for (const [key, value] of Object.entries(next)) {
      if (value === "" || value === false || (key === "page" && value === 1)) params.delete(key);
      else params.set(key, String(value));
    }
    // Only display metadata is kept in the URL; contact/name search stays in memory.
    history.replaceState(null, "", `${location.pathname}${location.search}#${location.hash.slice(1).split("?")[0] || "/records"}?${params}`);
  }
  async function load(row: RecordEntity, edit: boolean) {
    if (busy) return;
    setBusy(row.id); setError(undefined);
    try {
      const value = await api<RecordEntity>(`/records/${resource}/${encodeURIComponent(row.id)}`);
      if (useSession.getState().generation === generation) (edit ? onEdit : onView)(value);
    } catch (err) { if (useSession.getState().generation === generation) setError(err); }
    finally { if (useSession.getState().generation === generation) setBusy(null); }
  }
  async function command(row: RecordEntity, action: "delete" | "restore" | "post" | "cancel") {
    if (busy) return;
    const identity = `${resource}/${row.id}/${row.version}/${action}`;
    let key = commands.current.get(identity);
    if (!key) { key = crypto.randomUUID(); commands.current.set(identity, key); }
    setBusy(row.id); setError(undefined);
    try {
      await api(`/records/${resource}/${encodeURIComponent(row.id)}${action === "delete" ? "" : `/${action}`}`, { method: action === "delete" ? "DELETE" : "POST", body: JSON.stringify({ request_key: key, expected_version: row.version }) });
      if (useSession.getState().generation !== generation) return;
      commands.current.delete(identity);
      await cache.invalidateQueries({ queryKey: ["records"] });
    } catch (err) { if (useSession.getState().generation === generation) setError(err); }
    finally { if (useSession.getState().generation === generation) setBusy(null); }
  }
  return <Space orientation="vertical" className="full" size="middle">
    <Space wrap><Input.Search aria-label="Tìm hồ sơ" placeholder="Tìm mã, tên, ghi chú" allowClear onSearch={(value) => { setSearch(value); update({ page: 1 }); }} style={{ width: 280 }} /><Select aria-label="Sắp xếp hồ sơ" value={sort} onChange={(value) => { setSort(value); update({ page: 1 }); }} options={[{ value: "-updated_at", label: "Mới sửa trước" }, { value: "code", label: "Mã tăng dần" }, { value: "-code", label: "Mã giảm dần" }, ...(dated ? [{ value: "-occurred_on", label: "Ngày mới trước" }, { value: "occurred_on", label: "Ngày cũ trước" }] : [])]} style={{ width: 180 }} />{canWrite && <Button type="primary" onClick={onCreate}>Thêm mới</Button>}<Button loading={query.isFetching} onClick={() => void query.refetch()}>Tải lại</Button></Space>
    <Space wrap>{dated && <><label>Từ ngày <Input aria-label="Từ ngày" type="date" value={view.from_on} onChange={(event) => update({ from_on: event.target.value, page: 1 })} /></label><label>Đến ngày <Input aria-label="Đến ngày" type="date" value={view.through_on} onChange={(event) => update({ through_on: event.target.value, page: 1 })} /></label><div style={{ width: 260 }}><Typography.Text>Đối tác</Typography.Text><ReferenceSelect resource="parties" label="Lọc đối tác" value={party} onChange={(value) => { setParty(value); update({ page: 1 }); }} /></div></>}{resource === "entries" && <><Select aria-label="Lọc loại phiếu" allowClear placeholder="Mọi loại phiếu" value={view.entry_type || undefined} onChange={(value) => update({ entry_type: value || "", page: 1 })} options={Object.entries(entryLabels).map(([value, label]) => ({ value, label }))} style={{ width: 185 }} /><Select aria-label="Lọc trạng thái" allowClear placeholder="Mọi trạng thái" value={view.status || undefined} onChange={(value) => update({ status: value || "", page: 1 })} options={[{ value: "draft", label: "Nháp" }, { value: "posted", label: "Đã ghi" }, { value: "cancelled", label: "Đã hủy" }]} style={{ width: 150 }} /></>}{!dated && <Select aria-label="Lọc đang sử dụng" allowClear placeholder="Mọi tình trạng" value={view.active || undefined} onChange={(value) => update({ active: value || "", page: 1 })} options={[{ value: "true", label: "Đang sử dụng" }, { value: "false", label: "Ngừng sử dụng" }]} style={{ width: 180 }} />}<Checkbox checked={view.include_deleted} onChange={(event) => update({ include_deleted: event.target.checked, page: 1 })}>Hiện hồ sơ đã xóa</Checkbox></Space>
    <ErrorNotice error={error || query.error} />
    <Table<RecordEntity> rowKey="id" size="small" scroll={{ x: 900 }} loading={query.isPending} dataSource={query.data?.items ?? []} pagination={{ current: view.page, pageSize: 25, total: query.data?.total ?? 0, showSizeChanger: false, onChange: (page) => update({ page }), showTotal: (total) => `${total} hồ sơ` }} columns={[
      { title: "Mã / số phiếu", dataIndex: "code", render: (code: string, row) => <Button type="link" onClick={() => void load(row, false)}>{code}</Button> },
      ...(dated ? [{ title: "Ngày nghiệp vụ", key: "date", render: (_: unknown, row: RecordEntity) => (row as Entry).occurred_on }, { title: "Đối tác", key: "party", render: (_: unknown, row: RecordEntity) => <ReferenceText resource="parties" id={(row as Entry).party_id} /> }] : [{ title: "Tên", dataIndex: "name" }]),
      ...(resource === "entries" ? [{ title: "Loại", key: "entry_type", render: (_: unknown, row: RecordEntity) => entryLabels[(row as Entry).entry_type] }] : []),
      { title: "Tình trạng", render: (_, row) => row.deleted_at ? <Tag>Đã xóa mềm</Tag> : resource === "entries" ? <Tag color={(row as Entry).status === "posted" ? "green" : undefined}>{(row as Entry).status === "posted" ? "Đã ghi" : (row as Entry).status === "draft" ? "Nháp" : "Đã hủy"}</Tag> : row.active === false ? <Tag>Ngừng sử dụng</Tag> : <Tag>Đang lưu</Tag> },
      { title: "Ghi chú", dataIndex: "note", ellipsis: true },
      { title: "Thao tác", width: 285, render: (_, row) => <Space wrap>{canWrite && (row.deleted_at ? <Button disabled={!!busy} onClick={() => void command(row, "restore")}>Khôi phục</Button> : <><Button disabled={!!busy || (resource === "entries" && (row as Entry).status === "cancelled")} onClick={() => void load(row, true)}>Sửa</Button>{resource === "entries" && (row as Entry).status !== "posted" && <Popconfirm title={(row as Entry).status === "cancelled" ? "Ghi lại phiếu đã hủy vào sổ?" : "Ghi phiếu vào sổ kho?"} description="Tồn kho sẽ được kiểm lại tại các mốc liên quan." onConfirm={() => command(row, "post")} okText="Ghi vào sổ" cancelText="Đóng"><Button disabled={!!busy}>{(row as Entry).status === "cancelled" ? "Ghi lại" : "Ghi vào sổ"}</Button></Popconfirm>}{resource === "entries" && (row as Entry).status === "posted" ? <Popconfirm title="Hủy tác động kho của phiếu này?" description="Lịch sử được giữ. Nếu thiếu tồn ở một mốc, thao tác sẽ bị từ chối." onConfirm={() => command(row, "cancel")} okText="Hủy phiếu" cancelText="Đóng"><Button danger disabled={!!busy}>Hủy phiếu</Button></Popconfirm> : <Popconfirm title="Xóa mềm hồ sơ này?" description="Lịch sử vẫn được giữ để xem hoặc khôi phục." onConfirm={() => command(row, "delete")} okText="Xóa mềm" cancelText="Đóng"><Button danger disabled={!!busy}>Xóa</Button></Popconfirm>}</>)}</Space> },
    ]} />
  </Space>;
}
