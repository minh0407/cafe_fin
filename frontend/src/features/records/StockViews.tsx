import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Alert, Button, Input, Space, Table, Typography } from "antd";
import { api } from "../../shared/api";
import { useSession } from "../../shared/session";
import type { Page } from "../../shared/types";
import { Coverage, decimal, ErrorNotice, todayVN } from "./helpers";
import { ReferenceText } from "./RecordDetail";
import { entryLabels, type Entry, type InventorySummary, type Receivables, type StockMovement } from "./types";

function DateRange({ from, through, onChange }: { from: string; through: string; onChange: (from: string, through: string) => void }) {
  return <Space wrap><label>Từ ngày <Input aria-label="Từ ngày báo cáo" type="date" value={from} onChange={(event) => onChange(event.target.value, through)} /></label><label>Đến ngày <Input aria-label="Đến ngày báo cáo" type="date" value={through} onChange={(event) => onChange(from, event.target.value)} /></label></Space>;
}
function rangeDefaults() {
  const today = todayVN();
  return { from: today.slice(0, 8) + "01", through: today };
}
function Flags({ flags }: { flags?: string[] }) {
  const messages: Record<string, string> = { commercial_balances_only: "Chỉ gồm số dư thương mại người dùng ghi trên phiếu hàng.", accounting_not_reconciled: "Chưa đối chiếu với nhật ký kế toán độc lập." };
  const visible = flags?.filter((flag) => flag !== "entered_records_only") ?? [];
  if (!visible.length) return null;
  return <Alert type="warning" showIcon title="Lưu ý phạm vi tổng hợp" description={visible.map((flag) => <div key={flag}>{messages[flag] || "Một phần dữ liệu tổng hợp cần kiểm tra thêm."}</div>)} />;
}

export function InventoryView() {
  const [range, setRange] = useState(rangeDefaults);
  const generation = useSession((state) => state.generation);
  const valid = !!range.from && !!range.through && range.from <= range.through;
  const query = useQuery({ queryKey: ["records", generation, "inventory", range], queryFn: () => api<InventorySummary>(`/records/stock-balances?${new URLSearchParams({ from_on: range.from, through_on: range.through })}`), enabled: valid, gcTime: 0, retry: false });
  return <Space orientation="vertical" className="full" size="middle"><DateRange {...range} onChange={(from, through) => setRange({ from, through })} /><Coverage cutoff={query.data?.cutoff} />{!valid && <Alert type="warning" title="Chọn khoảng ngày hợp lệ; ngày đầu không sau ngày cuối." />}<ErrorNotice error={query.error} /><Flags flags={query.data?.validation_flags} /><Table rowKey={(row) => `${row.product_id}/${row.warehouse_id}`} loading={query.isPending && valid} dataSource={query.data?.items ?? []} size="small" pagination={{ pageSize: 25, showSizeChanger: false }} columns={[
    { title: "Hàng hóa", dataIndex: "product_id", render: (id: string) => <ReferenceText resource="products" id={id} /> },
    { title: "Vị trí", dataIndex: "warehouse_id", render: (id: string) => <ReferenceText resource="products/warehouses" id={id} /> },
    { title: "Đầu kỳ (kg)", dataIndex: "opening_kg", render: decimal, align: "right" },
    { title: "Tăng trong kỳ (kg)", dataIndex: "received_kg", render: decimal, align: "right" },
    { title: "Giảm trong kỳ (kg)", dataIndex: "issued_kg", render: decimal, align: "right" },
    { title: "Cuối kỳ (kg)", dataIndex: "closing_kg", render: decimal, align: "right" },
  ]} />
    <Typography.Title level={4}>Phân loại biến động trong kỳ</Typography.Title><Typography.Paragraph type="secondary">Nhập mua, xuất bán, sản xuất, chuyển nội bộ, tồn đầu và điều chỉnh được tách theo loại phiếu đã ghi. Số tăng qua sản xuất/chuyển vị trí không được xem là lượng mua mới.</Typography.Paragraph><Table rowKey={(row) => `${row.product_id}/${row.warehouse_id}/${row.entry_type}`} dataSource={query.data?.breakdown ?? []} size="small" pagination={{ pageSize: 25, showSizeChanger: false }} columns={[
      { title: "Hàng hóa", dataIndex: "product_id", render: (id: string) => <ReferenceText resource="products" id={id} /> },
      { title: "Vị trí", dataIndex: "warehouse_id", render: (id: string) => <ReferenceText resource="products/warehouses" id={id} /> },
      { title: "Loại ghi nhận", dataIndex: "entry_type", render: (kind: keyof typeof entryLabels) => entryLabels[kind] },
      { title: "Vào (kg)", dataIndex: "in_kg", render: decimal, align: "right" },
      { title: "Ra (kg)", dataIndex: "out_kg", render: decimal, align: "right" },
    ]} />
  </Space>;
}

export function MovementView({ onView }: { onView: (entry: Entry) => void }) {
  const [range, setRange] = useState(rangeDefaults);
  const [page, setPage] = useState(1);
  const [error, setError] = useState<unknown>();
  const generation = useSession((state) => state.generation);
  const valid = !!range.from && !!range.through && range.from <= range.through;
  const query = useQuery({ queryKey: ["records", generation, "movements", range, page], queryFn: () => api<Page<StockMovement>>(`/records/stock-movements?${new URLSearchParams({ page: String(page), page_size: "25", filters: JSON.stringify({ from_on: range.from, through_on: range.through }), sort: "-occurred_on" })}`), enabled: valid, gcTime: 0, retry: false });
  async function load(id: string) {
    setError(undefined);
    try {
      const entry = await api<Entry>(`/records/entries/${encodeURIComponent(id)}`);
      if (useSession.getState().generation === generation) onView(entry);
    } catch (err) { if (useSession.getState().generation === generation) setError(err); }
  }
  return <Space orientation="vertical" className="full" size="middle"><DateRange {...range} onChange={(from, through) => { setRange({ from, through }); setPage(1); }} /><Coverage /><Typography.Paragraph>Lịch sử chuyển động truy ngược về phiếu nguồn. Các phiên bản/đảo phiếu được giữ theo lịch sử.</Typography.Paragraph><ErrorNotice error={error || query.error} />{!valid && <Alert type="warning" title="Chọn khoảng ngày hợp lệ." />}<Table<StockMovement> rowKey="id" loading={query.isPending && valid} size="small" dataSource={query.data?.items ?? []} pagination={{ current: page, pageSize: 25, total: query.data?.total ?? 0, showSizeChanger: false, onChange: setPage }} columns={[
    { title: "Ngày nghiệp vụ", dataIndex: "occurred_on" },
    { title: "Loại phiếu", dataIndex: "entry_type", render: (kind: keyof typeof entryLabels) => entryLabels[kind] },
    { title: "Hàng hóa", dataIndex: "product_id", render: (id: string) => <ReferenceText resource="products" id={id} /> },
    { title: "Vị trí", dataIndex: "warehouse_id", render: (id: string) => <ReferenceText resource="products/warehouses" id={id} /> },
    { title: "Tác động (kg)", dataIndex: "delta_kg", render: decimal, align: "right" },
    { title: "Bản phiếu", dataIndex: "version" },
    { title: "Nguồn", dataIndex: "entry_id", render: (id: string) => <Button onClick={() => void load(id)}>Xem phiếu</Button> },
  ]} /></Space>;
}

export function ReceivableView() {
  const [asOf, setAsOf] = useState(todayVN);
  const generation = useSession((state) => state.generation);
  const query = useQuery({ queryKey: ["records", generation, "receivables", asOf], queryFn: () => api<Receivables>(`/records/receivables?${new URLSearchParams({ as_of: asOf })}`), enabled: !!asOf, gcTime: 0, retry: false });
  return <Space orientation="vertical" className="full" size="middle"><label>Số dư đến ngày <Input aria-label="Ngày công nợ" type="date" value={asOf} onChange={(event) => setAsOf(event.target.value)} /></label><Coverage cutoff={query.data?.cutoff} /><Typography.Paragraph>Số dư thương mại do người nhập ghi trên phiếu hàng. Nhật ký thu/chi kế toán độc lập; số này chưa khẳng định đã thu, đã trả hoặc đã đối chiếu toàn bộ doanh nghiệp.</Typography.Paragraph><ErrorNotice error={query.error} /><Flags flags={query.data?.validation_flags} /><Table rowKey="party_id" loading={query.isPending && !!asOf} size="small" dataSource={query.data?.items ?? []} pagination={{ pageSize: 25, showSizeChanger: false }} columns={[
    { title: "Đối tác", dataIndex: "party_id", render: (id: string) => <ReferenceText resource="parties" id={id} /> },
    { title: "Số dư ghi nhận (VND, có dấu)", dataIndex: "amount_vnd", render: decimal, align: "right" },
  ]} /></Space>;
}
