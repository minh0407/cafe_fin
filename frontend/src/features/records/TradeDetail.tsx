import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert, Button, Checkbox, Descriptions, Drawer, Modal, Space, Table, Typography } from "antd";
import { api } from "../../shared/api";
import { useSession } from "../../shared/session";
import type { Page } from "../../shared/types";
import { CommerceHistory, invalidateRecords, RecordCommands, useCommerceRecord, useRecordsWrite } from "./CommerceShared";
import { priceKindOptions, companyComplete, methodLabels, orderValue, type CommerceParty, type Trade, type TradePayment } from "./commerceTypes";
import { decimal, displayBusinessDate, ErrorNotice } from "./helpers";
import { PaymentEditor } from "./PaymentEditor";
import { PartyEditor } from "./PartyEditor";
import { RecordDetail, ReferenceText } from "./RecordDetail";
import { RecordEditor } from "./RecordEditor";
import type { Entry } from "./types";

export function TradeData({ value }: { value: Trade }) {
  const total = orderValue(value.lines);
  return <><Descriptions bordered size="small" column={2} items={[
    { key: "code", label: "Số đơn", children: value.code }, { key: "version", label: "Phiên bản", children: value.version }, { key: "date", label: "Ngày nghiệp vụ", children: displayBusinessDate(value.occurred_on) }, { key: "direction", label: "Luồng", children: value.direction === "inbound" ? "Mua vào" : "Bán ra" }, { key: "status", label: "Trạng thái", children: value.deleted_at ? "Đã xóa mềm" : value.status === "cancelled" ? "Đã hủy" : "Đã ghi nhận" }, { key: "company", label: "Đối tác", children: <ReferenceText resource="parties" id={value.party_id} /> }, { key: "vehicle", label: "Biển xe", children: value.vehicle_plate || "—" }, { key: "actor", label: "Người thực hiện", children: value.physical_actor || "—" }, { key: "weighing", label: "Phiếu cân", children: <ReferenceText resource="weighings" id={value.weighing_id} /> }, { key: "total", label: "Giá trị hồ sơ (VND)", children: total === null ? "Chưa đủ giá" : decimal(total) }, { key: "note", label: "Ghi chú", children: value.note || "—" },
  ]} /><Typography.Paragraph type="secondary">Giá trị hồ sơ được tính chính xác từ kg × đơn giá. Thu/chi thực tế và lượng đã giao được ghi riêng bên dưới.</Typography.Paragraph><Table rowKey={(_, index) => String(index)} size="small" pagination={false} scroll={{ x: 900 }} dataSource={value.lines} columns={[{ title: "Farm", dataIndex: "farm_id", render: (id) => <ReferenceText resource="parties" id={id} /> }, { title: "Hàng hóa", dataIndex: "product_id", render: (id) => <ReferenceText resource="products" id={id} /> }, { title: "Kg", dataIndex: "quantity_kg", render: decimal }, { title: "Bao", dataIndex: "bag_count" }, { title: "Grade", dataIndex: "grade" }, { title: "VND/kg", dataIndex: "unit_price_vnd", render: decimal }, { title: "Nguồn giá", render: (_, line) => line.pricing_mode === "daily" && line.price_snapshot ? `${priceKindOptions.find((kind) => kind.value === line.price_snapshot!.price_kind)?.label} · ${displayBusinessDate(line.price_snapshot.price_date)}${line.price_snapshot.grade != null ? ` · Grade ${line.price_snapshot.grade}` : ""} · phiên bản ${line.price_snapshot.price_board_version}` : "Nhập tay / dữ liệu cũ" }, { title: "Ghi chú", dataIndex: "note" }]} /></>;
}
export function PaymentData({ value }: { value: TradePayment }) {
  return <Descriptions bordered size="small" column={2} items={[{ key: "code", label: "Chứng từ", children: value.code }, { key: "version", label: "Phiên bản", children: value.version }, { key: "date", label: "Ngày thu/chi", children: displayBusinessDate(value.occurred_on) }, { key: "party", label: "Đối tác", children: <ReferenceText resource="parties" id={value.party_id} /> }, { key: "amount", label: "Số tiền (VND)", children: decimal(value.amount_vnd) }, { key: "method", label: "Phương thức", children: methodLabels[value.method] }, { key: "ref", label: "Tham chiếu", children: value.reference || "—" }, { key: "note", label: "Ghi chú", children: value.note || "—" }, { key: "deleted", label: "Tình trạng", children: value.deleted_at ? "Đã xóa mềm" : "Đang lưu" }]} />;
}
function useLinkedPage<T>(resource: string, tradeId: string, page: number, includeDeleted: boolean) {
  const generation = useSession((state) => state.generation);
  return useQuery({ queryKey: ["records", generation, "trade-linked", resource, tradeId, page, includeDeleted], queryFn: () => api<Page<T>>(`/records/${resource}?${new URLSearchParams({ page: String(page), page_size: "25", sort: "-occurred_on", filters: JSON.stringify({ trade_id: tradeId, include_deleted: includeDeleted }) })}`), retry: false, gcTime: 0 });
}

export function TradeDetail({ trade, onClose, onEdit, onChanged }: { trade: Trade; onClose: () => void; onEdit: () => void; onChanged: () => void }) {
  const canWrite = useRecordsWrite();
  const cache = useQueryClient();
  const [stockPage, setStockPage] = useState(1);
  const [paymentPage, setPaymentPage] = useState(1);
  const [includeDeleted, setIncludeDeleted] = useState(false);
  const stock = useLinkedPage<Entry>("entries", trade.id, stockPage, includeDeleted);
  const payments = useLinkedPage<TradePayment>("trade-payments", trade.id, paymentPage, includeDeleted);
  const [stockId, setStockId] = useState<string>();
  const [paymentId, setPaymentId] = useState<string>();
  const stockDetail = useCommerceRecord<Entry>("entries", stockId);
  const paymentDetail = useCommerceRecord<TradePayment>("trade-payments", paymentId);
  const [stockEditor, setStockEditor] = useState<{ value: Partial<Entry>; key: string }>();
  const [paymentEditor, setPaymentEditor] = useState<{ value?: TradePayment }>();
  const [companyEditor, setCompanyEditor] = useState(false);
  const company = useCommerceRecord<CommerceParty>("parties", trade.direction === "outbound" ? trade.party_id : undefined);
  const effective = !trade.deleted_at && trade.status === "recorded";
  const hasProducts = trade.lines.every((line) => !!line.product_id);
  async function changed() { await invalidateRecords(cache); onChanged(); }
  function newStock() {
    const incoming = trade.direction === "inbound";
    setStockEditor({ key: crypto.randomUUID(), value: { trade_id: trade.id, occurred_on: trade.occurred_on, entry_type: incoming ? "receipt" : "issue", status: "draft", party_id: trade.party_id, weighing_id: trade.weighing_id, lines: trade.lines.map((line) => ({ product_id: line.product_id ?? "", warehouse_id: "", quantity_kg: line.quantity_kg, direction: incoming ? "in" : "out", note: line.note })) } });
  }
  function editPayment(value?: TradePayment) {
    if (trade.direction === "outbound" && !companyComplete(company.data, !!value)) { setCompanyEditor(true); return; }
    setPaymentEditor({ value });
  }
  return <Drawer open size={1180} title={`Chi tiết ${trade.direction === "inbound" ? "mua vào" : "bán ra"} · ${trade.code}`} onClose={onClose} extra={<Space>{canWrite && !trade.deleted_at && <Button onClick={onEdit}>Sửa đơn</Button>}<RecordCommands resource="trades" value={trade} onChanged={onChanged} /></Space>}>
    <Space orientation="vertical" className="full" size="middle"><TradeData value={trade} /><CommerceHistory resource="trades" value={trade} render={(value) => <TradeData value={value} />} /><Checkbox checked={includeDeleted} onChange={(event) => { setIncludeDeleted(event.target.checked); setStockPage(1); setPaymentPage(1); }}>Hiện chứng từ liên kết đã xóa</Checkbox>
      <Typography.Title level={4}>Nhập / xuất kho đã liên kết</Typography.Title><Typography.Paragraph>Lưu đơn chưa thay đổi tồn. Mỗi lần giao có phiếu kho riêng; chỉ phiếu đã ghi sổ tác động tồn và được cộng vào lượng đã giao. Khi lập thêm phiếu, sửa lượng theo lần giao thực tế.</Typography.Paragraph>{canWrite && effective && <Button onClick={newStock} disabled={!hasProducts}>Tạo phiếu {trade.direction === "inbound" ? "nhập" : "xuất"} kho nháp</Button>}{!hasProducts && <Alert type="info" title="Chọn hàng hóa cho từng dòng của đơn trước khi tạo phiếu kho liên kết." />}<ErrorNotice error={stock.error || stockDetail.error} /><Table<Entry> rowKey="id" size="small" loading={stock.isPending} dataSource={stock.data?.items ?? []} pagination={{ current: stockPage, pageSize: 25, total: stock.data?.total ?? 0, showSizeChanger: false, onChange: setStockPage }} columns={[{ title: "Phiếu kho", dataIndex: "code", render: (code, row) => <Button type="link" onClick={() => setStockId(row.id)}>{code}</Button> }, { title: "Ngày", dataIndex: "occurred_on", render: displayBusinessDate }, { title: "Trạng thái", render: (_, row) => row.deleted_at ? "Đã xóa mềm" : row.status === "posted" ? "Đã ghi sổ" : row.status === "draft" ? "Nháp" : "Đã hủy" }, { title: "Thao tác", render: (_, row) => <RecordCommands resource="entries" value={row} onChanged={() => void changed()} /> }]} />
      <Typography.Title level={4}>{trade.direction === "outbound" ? "Thu" : "Chi"} thực tế</Typography.Title>{canWrite && effective && <Button onClick={() => editPayment()}>Ghi {trade.direction === "outbound" ? "thu" : "chi"} thực tế</Button>}<ErrorNotice error={payments.error || paymentDetail.error || company.error} /><Table<TradePayment> rowKey="id" size="small" loading={payments.isPending} dataSource={payments.data?.items ?? []} pagination={{ current: paymentPage, pageSize: 25, total: payments.data?.total ?? 0, showSizeChanger: false, onChange: setPaymentPage }} columns={[{ title: "Chứng từ", dataIndex: "code", render: (code, row) => <Button type="link" onClick={() => setPaymentId(row.id)}>{code}</Button> }, { title: "Ngày", dataIndex: "occurred_on", render: displayBusinessDate }, { title: "Đối tác", dataIndex: "party_id", render: (id) => <ReferenceText resource="parties" id={id} /> }, { title: "VND", dataIndex: "amount_vnd", render: decimal }, { title: "Phương thức", dataIndex: "method", render: (method: TradePayment["method"]) => methodLabels[method] }, { title: "Tình trạng", render: (_, row) => row.deleted_at ? "Đã xóa mềm" : "Đang lưu" }]} />
    </Space>
    {stockDetail.data && stockId && <RecordDetail key={`${stockId}/${stockDetail.data.version}`} resource="entries" value={stockDetail.data} onClose={() => setStockId(undefined)} onEdit={canWrite && !stockDetail.data.deleted_at && stockDetail.data.status !== "cancelled" ? () => { setStockEditor({ value: stockDetail.data!, key: crypto.randomUUID() }); setStockId(undefined); } : undefined} />}
    {stockEditor && <RecordEditor key={stockEditor.key} resource="entries" initial={stockEditor.value} linkedTrade={{ code: trade.code, direction: trade.direction, newDraft: !stockEditor.value.id }} title="Phiếu kho liên kết đơn" onClose={() => setStockEditor(undefined)} onSaved={(value) => { setStockEditor(undefined); setStockId(value.id); void changed(); }} />}
    {paymentId && paymentDetail.data && <Modal open width={850} title={`Chứng từ ${paymentDetail.data.code}`} footer={null} onCancel={() => setPaymentId(undefined)}><Space orientation="vertical" className="full"><PaymentData value={paymentDetail.data} />{canWrite && !paymentDetail.data.deleted_at && <Button onClick={() => editPayment(paymentDetail.data)}>Sửa thu/chi</Button>}<RecordCommands resource="trade-payments" value={paymentDetail.data} onChanged={() => void changed()} /><CommerceHistory resource="trade-payments" value={paymentDetail.data} render={(value) => <PaymentData value={value} />} /></Space></Modal>}
    {paymentEditor && <PaymentEditor key={paymentEditor.value ? `${paymentEditor.value.id}/${paymentEditor.value.version}` : "new"} trade={trade} initial={paymentEditor.value} onClose={() => setPaymentEditor(undefined)} onSaved={(value) => { setPaymentEditor(undefined); setPaymentId(value.id); void changed(); }} />}
    {companyEditor && company.data && <PartyEditor profile="customer_company" initial={company.data} requireCompany onClose={() => setCompanyEditor(false)} onSaved={() => { setCompanyEditor(false); void changed(); }} />}
    {companyEditor && !company.data && <Alert type="warning" title="Chưa đọc được công ty. Tải lại chi tiết trước khi nhập thu/chi." />}
  </Drawer>;
}
