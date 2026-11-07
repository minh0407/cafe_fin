import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert, Button, Checkbox, Input, Select, Space, Table, Typography } from "antd";
import { api } from "../../shared/api";
import { DateInput } from "../../shared/DateInput";
import { useSession } from "../../shared/session";
import type { Page } from "../../shared/types";
import { CommerceNav, invalidateRecords, useCommerceRecord, useRecordsWrite } from "./CommerceShared";
import { orderValue, type Direction, type Trade } from "./commerceTypes";
import { Coverage, dateRangeValid, decimal, displayBusinessDate, ErrorNotice, OPTIONAL_DATE_RANGE_MESSAGE } from "./helpers";
import { readCommerceView, updateCommerceURL, type CommerceView } from "./PartyCatalog";
import { ReferenceText } from "./RecordDetail";
import { TradeDetail } from "./TradeDetail";
import { TradeEditor } from "./TradeEditor";

function TradePage({ direction }: { direction: Direction }) {
  const generation = useSession((state) => state.generation);
  return <TradeSession key={`${direction}/${generation}`} direction={direction} />;
}
function TradeSession({ direction }: { direction: Direction }) {
  const [view, setView] = useState(readCommerceView);
  const [editor, setEditor] = useState<{ value?: Trade }>();
  const canWrite = useRecordsWrite();
  const cache = useQueryClient();
  const generation = useSession((state) => state.generation);
  const validDates = dateRangeValid(view.from_on, view.through_on);
  const inbound = direction === "inbound";
  useEffect(() => { const change = () => { setView(readCommerceView()); setEditor(undefined); }; window.addEventListener("hashchange", change); return () => window.removeEventListener("hashchange", change); }, []);
  useEffect(() => { updateCommerceURL(view); }, [view]);
  function update(patch: Partial<CommerceView>) { setView((old) => ({ ...old, ...patch })); }
  const filters = { direction, include_deleted: view.include_deleted, ...(view.from_on ? { from_on: view.from_on } : {}), ...(view.through_on ? { through_on: view.through_on } : {}), ...(view.status ? { status: view.status } : {}) };
  const query = useQuery({ queryKey: ["records", generation, "trades-list", direction, view.page, view.search, view.sort, filters], queryFn: () => api<Page<Trade>>(`/records/trades?${new URLSearchParams({ page: String(view.page), page_size: "25", search: view.search, sort: view.sort, filters: JSON.stringify(filters) })}`), enabled: validDates, retry: false, gcTime: 0 });
  const detail = useCommerceRecord<Trade>("trades", view.selected);
  async function saved(value: Trade) { setEditor(undefined); update({ selected: value.id }); await invalidateRecords(cache); }
  return <><CommerceNav /><Typography.Title level={2}>{inbound ? "Đầu vào · Mua từ Farm" : "Đầu ra · Bán cho công ty"}</Typography.Title><Coverage />{!canWrite && <Alert type="info" title="Tài khoản chỉ xem dữ liệu." />}<Space wrap style={{ marginBottom: 16 }}><Input.Search aria-label="Tìm đơn" value={view.search} onChange={(event) => update({ search: event.target.value, page: 1 })} placeholder="Tìm mã hoặc ghi chú" allowClear /><Select aria-label="Sắp xếp đơn" value={view.sort} onChange={(sort) => update({ sort, page: 1 })} options={[{ value: "-updated_at", label: "Mới sửa trước" }, { value: "code", label: "Mã tăng dần" }, { value: "-occurred_on", label: "Ngày mới trước" }, { value: "occurred_on", label: "Ngày cũ trước" }]} />{canWrite && <Button type="primary" onClick={() => setEditor({})}>Thêm {inbound ? "mua vào" : "bán ra"}</Button>}<Button disabled={!validDates} onClick={() => void query.refetch()}>Tải lại</Button></Space><Space wrap style={{ marginBottom: 16 }}><label>Từ ngày <DateInput aria-label="Từ ngày" value={view.from_on} onChange={(from_on) => update({ from_on, page: 1 })} /></label><label>Đến ngày <DateInput aria-label="Đến ngày" value={view.through_on} onChange={(through_on) => update({ through_on, page: 1 })} /></label><Select aria-label="Trạng thái đơn" allowClear placeholder="Mọi trạng thái" value={view.status || undefined} onChange={(status) => update({ status: status || "", page: 1 })} options={[{ value: "recorded", label: "Đã ghi nhận" }, { value: "cancelled", label: "Đã hủy" }]} /><Checkbox checked={view.include_deleted} onChange={(event) => update({ include_deleted: event.target.checked, page: 1 })}>Hiện đơn đã xóa</Checkbox></Space>{!validDates && <Alert type="warning" title={OPTIONAL_DATE_RANGE_MESSAGE} />}<ErrorNotice error={query.error || detail.error} />
    <Table<Trade> rowKey="id" size="small" scroll={{ x: 800 }} dataSource={query.data?.items ?? []} loading={validDates && query.isPending} pagination={{ current: view.page, pageSize: 25, total: query.data?.total ?? 0, showSizeChanger: false, onChange: (page) => update({ page }) }} columns={[{ title: "Số đơn", dataIndex: "code", render: (code, row) => <Button type="link" onClick={() => update({ selected: row.id })}>{code}</Button> }, { title: "Ngày nghiệp vụ", dataIndex: "occurred_on", render: displayBusinessDate }, { title: inbound ? "Farm" : "Công ty", render: (_, row) => inbound ? [...new Set(row.lines.map((line) => line.farm_id))].map((id) => <div key={id}><ReferenceText resource="parties" id={id} /></div>) : <ReferenceText resource="parties" id={row.party_id} /> }, { title: "Biển xe", dataIndex: "vehicle_plate" }, { title: "Giá trị hồ sơ (VND)", render: (_, row) => { const total = orderValue(row.lines); return total === null ? "Chưa đủ giá" : decimal(total); } }, { title: "Tình trạng", render: (_, row) => row.deleted_at ? "Đã xóa mềm" : row.status === "cancelled" ? "Đã hủy" : "Đã ghi nhận" }]} />
    {view.selected && detail.isPending && <Typography.Paragraph>Đang đọc chi tiết…</Typography.Paragraph>}{detail.data && view.selected && (detail.data.direction === direction ? <TradeDetail key={detail.data.id} trade={detail.data} onClose={() => update({ selected: "" })} onEdit={() => setEditor({ value: detail.data })} onChanged={() => void detail.refetch()} /> : <Alert type="error" title="Hồ sơ được chọn thuộc luồng khác." />)}
    {editor && <TradeEditor key={editor.value ? `${editor.value.id}/${editor.value.version}` : "new"} direction={direction} initial={editor.value} onClose={() => setEditor(undefined)} onSaved={(value) => void saved(value)} />}
  </>;
}
export function InboundPage() { return <TradePage direction="inbound" />; }
export function OutboundPage() { return <TradePage direction="outbound" />; }
