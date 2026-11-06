import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Button, Descriptions, Drawer, List, Space, Table, Tag, Typography } from "antd";
import { api } from "../../shared/api";
import { useSession } from "../../shared/session";
import type { Page } from "../../shared/types";
import { Coverage, decimal, displayBusinessDate, ErrorNotice } from "./helpers";
import { entryLabels, type Entity, type Entry, type EntryLine, type Party, type RecordEntity, type Resource, type Weighing, type WeighingLine } from "./types";

export function ReferenceText({ resource, id }: { resource: Resource; id?: string | null }) {
  const generation = useSession((state) => state.generation);
  const query = useQuery({ queryKey: ["records-reference", generation, resource, id], queryFn: () => api<Entity>(`/records/${resource}/${encodeURIComponent(id!)}`), enabled: !!id, staleTime: 60000, gcTime: 0, retry: false });
  if (!id) return <>—</>;
  return <span title={query.error ? "Không đọc được hồ sơ liên quan; mã định danh vẫn được giữ." : undefined}>{query.data ? `${query.data.code}${query.data.name ? ` — ${query.data.name}` : ""}` : query.isPending ? "Đang đọc…" : id}</span>;
}

function DataView({ resource, value }: { resource: Resource; value: RecordEntity }) {
  const party = value as Party;
  const dated = value as Entry | Weighing;
  const entry = value as Entry;
  return <>
    <Descriptions bordered size="small" column={2} items={[
      { key: "code", label: "Mã / số phiếu", children: value.code },
      { key: "version", label: "Phiên bản", children: value.version },
      ...(value.name ? [{ key: "name", label: "Tên", children: value.name }] : []),
      ...(dated.occurred_on ? [{ key: "date", label: "Ngày nghiệp vụ (VN)", children: displayBusinessDate(dated.occurred_on) }, { key: "party", label: "Đối tác", children: <ReferenceText resource="parties" id={dated.party_id} /> }] : []),
      ...(entry.entry_type ? [{ key: "type", label: "Loại phiếu", children: entryLabels[entry.entry_type] }, { key: "status", label: "Trạng thái", children: entry.status === "posted" ? "Đã ghi" : entry.status === "draft" ? "Nháp" : "Đã hủy" }, { key: "weighing", label: "Phiếu cân liên kết", children: <ReferenceText resource="weighings" id={entry.weighing_id} /> }, { key: "commercial", label: "Số dư thương mại (VND)", children: decimal(entry.commercial_amount_vnd) }] : []),
      ...("vehicle_plate" in value ? [{ key: "vehicle", label: "Biển xe", children: value.vehicle_plate || "—" }] : []),
      ...(resource === "parties" ? [{ key: "partytype", label: "Loại đối tác", children: party.type === "person" ? "Cá nhân" : party.type === "organization" ? "Tổ chức" : party.type }, { key: "roles", label: "Vai trò", children: party.roles.map((role) => <Tag key={role}>{role === "customer" ? "Khách mua" : role === "supplier" ? "Nhà cung cấp" : role}</Tag>) }, { key: "address", label: "Địa chỉ", children: party.address || "—" }, { key: "tax", label: "Mã số thuế", children: party.tax_code || "—" }, { key: "contacts", label: "Liên hệ", children: party.contacts.map((contact, index) => <div key={index}>{contact.label || contact.kind}: {contact.value}</div>) }, { key: "representative", label: "Đại diện", children: party.representative ? `${party.representative.name}${party.representative.title ? ` — ${party.representative.title}` : ""}` : "—" }, { key: "banks", label: "Ngân hàng", children: (party.bank_details ?? []).map((bank, index) => <div key={index}>{bank.bank_name}: {bank.account_number} — {bank.account_holder}</div>) }] : []),
      { key: "note", label: "Ghi chú", children: value.note || "—" },
      { key: "active", label: "Tình trạng hồ sơ", children: value.deleted_at ? "Đã xóa mềm" : value.active === false ? "Ngừng sử dụng" : "Đang lưu" },
      { key: "updated", label: "Lưu lúc (VN)", children: new Date(value.updated_at).toLocaleString("vi-VN", { timeZone: "Asia/Ho_Chi_Minh" }) },
    ]} />
    {resource === "weighings" && <Table<WeighingLine & { _line: number }> rowKey="_line" size="small" pagination={false} dataSource={(value as Weighing).lines.map((line, index) => ({ ...line, _line: index + 1 }))} columns={[
      { title: "Dòng", render: (_, __, index) => index + 1 },
      { title: "Hàng / mô tả", render: (_, line) => <><ReferenceText resource="products" id={line.product_id} />{line.description && <div>{line.description}</div>}</> },
      { title: "Cách ghi", dataIndex: "quantity_source", render: (source) => source === "gross_tare" ? "Đầy / rỗng" : "Tịnh trực tiếp" },
      { title: "Đầy (kg)", dataIndex: "gross_kg", render: decimal },
      { title: "Rỗng (kg)", dataIndex: "tare_kg", render: decimal },
      { title: "Tịnh (kg)", dataIndex: "net_kg", render: decimal },
      { title: "Ghi chú", dataIndex: "note" },
    ]} />}
    {resource === "entries" && <Table<EntryLine & { _line: number }> rowKey="_line" size="small" pagination={false} dataSource={entry.lines.map((line, index) => ({ ...line, _line: index + 1 }))} columns={[
      { title: "Dòng", render: (_, __, index) => index + 1 },
      { title: "Hàng", dataIndex: "product_id", render: (id: string) => <ReferenceText resource="products" id={id} /> },
      { title: "Vị trí", dataIndex: "warehouse_id", render: (id: string) => <ReferenceText resource="products/warehouses" id={id} /> },
      { title: "Chiều", dataIndex: "direction", render: (value) => value === "in" ? "Vào" : "Ra" },
      { title: "Kg", dataIndex: "quantity_kg", render: decimal },
      { title: "Diễn giải", dataIndex: "note" },
    ]} />}
  </>;
}

interface Revision { version: number; action: string; recorded_at: string; actor: string; data: RecordEntity }

export function RecordDetail({ resource, value, saved = false, onClose, onEdit, onUseWeighing }: { resource: Resource; value: RecordEntity; saved?: boolean; onClose: () => void; onEdit?: () => void; onUseWeighing?: (value: Weighing) => void }) {
  const [history, setHistory] = useState(false);
  const [page, setPage] = useState(1);
  const [revision, setRevision] = useState<RecordEntity | null>(null);
  const generation = useSession((state) => state.generation);
  const query = useQuery({ queryKey: ["records-history", generation, resource, value.id, value.version, page], queryFn: () => api<Page<Revision>>(`/records/${resource}/${encodeURIComponent(value.id)}/history?page=${page}&page_size=20`), enabled: history, gcTime: 0, retry: false });
  return <Drawer open size={1050} title={`${saved ? "Đã lưu " : "Chi tiết "}${value.code}`} onClose={onClose} extra={<Space>{onEdit && !value.deleted_at && <Button onClick={onEdit}>Sửa dữ liệu</Button>}{onUseWeighing && !value.deleted_at && <Button type="primary" onClick={() => onUseWeighing(value as Weighing)}>Lập phiếu nhập từ cân</Button>}<Button onClick={() => setHistory(!history)}>{history ? "Ẩn lịch sử" : "Xem lịch sử"}</Button></Space>}>
    <Coverage />
    <DataView resource={resource} value={value} />
    {resource === "weighings" && <Typography.Paragraph type="secondary">Lưu hoặc sửa phiếu cân không tự thay đổi kho. Dữ liệu đã chụp trong hợp đồng được giữ độc lập.</Typography.Paragraph>}
    {history && <><Typography.Title level={4}>Lịch sử đã lưu</Typography.Title><ErrorNotice error={query.error} /><List loading={query.isPending} dataSource={query.data?.items ?? []} pagination={{ current: page, pageSize: 20, total: query.data?.total ?? 0, onChange: setPage }} renderItem={(item) => <List.Item actions={[<Button key="show" onClick={() => setRevision(item.data)}>Xem bản {item.version}</Button>]}><List.Item.Meta title={`Phiên bản ${item.version} · ${item.action}`} description={new Date(item.recorded_at).toLocaleString("vi-VN", { timeZone: "Asia/Ho_Chi_Minh" })} /></List.Item>} />{revision && <><Typography.Title level={5}>Bản lịch sử {revision.version}</Typography.Title><DataView resource={resource} value={revision} /></>}</>}
  </Drawer>;
}
