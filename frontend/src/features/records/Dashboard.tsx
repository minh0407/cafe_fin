import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Alert, Button, Card, Col, Row, Segmented, Space, Spin, Table, Typography } from "antd";
import { api } from "../../shared/api";
import { DateInput } from "../../shared/DateInput";
import { useSession } from "../../shared/session";
import { Coverage, dateRangeValid, decimal, displayBusinessDate, ErrorNotice, todayVN } from "./helpers";
import type { InventorySummary } from "./types";

interface Measures {
  inbound_kg: string;
  outbound_kg: string;
  cash_in_vnd: string;
  cash_out_vnd: string;
  sales_order_value_vnd: string;
  unpriced_sales_orders: number;
}
interface DashboardData {
  coverage: "entered_records_only";
  cutoff: string;
  from_on: string;
  through_on: string;
  counts: { farms: number; farm_surveys: number; customer_companies: number; inbound_trades: number; outbound_trades: number };
  inventory: InventorySummary;
  period: Measures;
  daily: (Measures & { occurred_on: string })[];
}
type Period = "week" | "month" | "custom";
function periodDates(period: Exclude<Period, "custom">) {
  const today = todayVN();
  if (period === "month") return { from: `${today.slice(0, 7)}-01`, through: today };
  const utcDay = new Date(`${today}T00:00:00Z`);
  utcDay.setUTCDate(utcDay.getUTCDate() - (utcDay.getUTCDay() + 6) % 7);
  return { from: utcDay.toISOString().slice(0, 10), through: today };
}
function routeDates() {
  const params = new URLSearchParams(location.hash.split("?")[1]);
  const from = params.get("from_on") ?? "";
  const through = params.get("through_on") ?? "";
  return dateRangeValid(from, through, true) ? { from, through } : periodDates("week");
}
function listLink(flow: "inbound" | "outbound", from: string, through: string) {
  return `#/records/${flow}?from_on=${from}&through_on=${through}`;
}
function scaled(value: string, precision: number): bigint {
  const match = /^(-?)(\d+)(?:\.(\d+))?$/.exec(value);
  if (!match || (match[3]?.length ?? 0) > precision) throw new Error("Số liệu tổng hợp không hợp lệ.");
  return (match[1] ? -1n : 1n) * BigInt(`${match[2]}${(match[3] ?? "").padEnd(precision, "0")}`);
}
function totalStock(items: InventorySummary["items"]) {
  const sum = items.reduce((value, item) => value + scaled(item.closing_kg, 3), 0n);
  const sign = sum < 0n ? "-" : "";
  const absolute = sum < 0n ? -sum : sum;
  return `${sign}${absolute / 1000n}.${String(absolute % 1000n).padStart(3, "0")}`;
}
function Metric({ label, value, unit, href, color = "#24604d" }: { label: string; value: string; unit?: string; href?: string; color?: string }) {
  return <Card size="small" style={{ height: "100%", borderTop: `3px solid ${color}` }}>
    <Typography.Text type="secondary">{label}</Typography.Text>
    <div style={{ fontSize: 25, fontWeight: 650, margin: "8px 0", overflowWrap: "anywhere" }}>
      {href ? <a href={href} style={{ color }}>{value}</a> : <span style={{ color }}>{value}</span>}
      {unit && <Typography.Text type="secondary" style={{ marginLeft: 6, fontSize: 13 }}>{unit}</Typography.Text>}
    </div>
  </Card>;
}
/** Geometry is a bounded integer ratio; source values and all totals stay exact. */
function Trend({ rows, keys, precision, label }: { rows: DashboardData["daily"]; keys: [keyof Measures, keyof Measures]; precision: number; label: string }) {
  const series = rows.map((row) => keys.map((key) => scaled(String(row[key]), precision)));
  const maximum = series.reduce((max, values) => values.reduce((a, b) => b > a ? b : a, max), 0n);
  const width = Math.max(560, rows.length * 18);
  const height = 136;
  const colors = ["#24604d", "#d29039"];
  return <div style={{ overflowX: "auto" }}>
    <svg role="img" aria-label={label} viewBox={`0 0 ${width} ${height + 22}`} style={{ width: "100%", minWidth: 560, height: 160 }}>
      <line x1="0" x2={width} y1={height} y2={height} stroke="#dde5df" />
      {series.map((values, index) => values.map((value, s) => {
        const barHeight = maximum > 0n ? Number(value * 116n / maximum) : 0;
        const step = width / Math.max(1, series.length);
        return <rect key={`${index}-${s}`} x={index * step + step * (s === 0 ? 0.15 : 0.51)} y={height - barHeight} width={step * 0.3} height={barHeight} fill={colors[s]}>
          <title>{displayBusinessDate(rows[index].occurred_on)}: {decimal(String(rows[index][keys[s]]))}</title>
        </rect>;
      }))}
      <text x="0" y={height + 18} fontSize="11" fill="#66736d">{rows[0] ? displayBusinessDate(rows[0].occurred_on) : ""}</text>
      <text x={width} y={height + 18} textAnchor="end" fontSize="11" fill="#66736d">{rows.at(-1) ? displayBusinessDate(rows.at(-1)!.occurred_on) : ""}</text>
    </svg>
  </div>;
}

export function DashboardPage() {
  const [dates, setDates] = useState(routeDates);
  const [draft, setDraft] = useState(dates);
  const [period, setPeriod] = useState<Period>(() => location.hash.includes("from_on=") ? "custom" : "week");
  const [rangeError, setRangeError] = useState("");
  const generation = useSession((s) => s.generation);
  const query = useQuery({
    queryKey: ["records", "dashboard", generation, dates.from, dates.through],
    queryFn: () => api<DashboardData>(`/records/records-dashboard?from_on=${dates.from}&through_on=${dates.through}`),
    retry: false,
  });
  useEffect(() => {
    const change = () => { const next = routeDates(); setDates(next); setDraft(next); setPeriod(location.hash.includes("from_on=") ? "custom" : "week"); setRangeError(""); };
    addEventListener("hashchange", change);
    return () => removeEventListener("hashchange", change);
  }, []);
  function apply(next: { from: string; through: string }, mode: Period) {
    if (!dateRangeValid(next.from, next.through, true)) { setRangeError("Nhập đủ ngày hợp lệ; ngày đầu không được sau ngày cuối."); return; }
    const days = (Date.parse(`${next.through}T00:00:00Z`) - Date.parse(`${next.from}T00:00:00Z`)) / 86400000 + 1;
    if (days > 366) { setRangeError("Chọn khoảng không quá 366 ngày."); return; }
    setRangeError(""); setDates(next); setDraft(next); setPeriod(mode);
    history.replaceState(null, "", `${location.pathname}${location.search}#/records/dashboard?from_on=${next.from}&through_on=${next.through}`);
  }
  const data = query.error ? undefined : query.data;
  return <Space orientation="vertical" size="large" style={{ width: "100%" }}>
    <div><Typography.Title level={2} style={{ marginBottom: 4 }}>Tổng quan kinh doanh</Typography.Title><Coverage cutoff={data?.cutoff} /></div>
    <Card size="small">
      <Space wrap>
        <Segmented aria-label="Kỳ tổng quan" value={period} options={[{ label: "Tuần này", value: "week" }, { label: "Tháng này", value: "month" }, { label: "Tùy chọn", value: "custom" }]} onChange={(value) => value === "custom" ? setPeriod("custom") : apply(periodDates(value as "week" | "month"), value as Period)} />
        <DateInput aria-label="Tổng quan từ ngày" value={draft.from} onChange={(from) => { setDraft({ ...draft, from }); setPeriod("custom"); }} />
        <DateInput aria-label="Tổng quan đến ngày" value={draft.through} onChange={(through) => { setDraft({ ...draft, through }); setPeriod("custom"); }} />
        <Button onClick={() => apply(draft, "custom")}>Xem tổng quan</Button>
        <Button loading={query.isFetching} onClick={() => void query.refetch()}>Làm mới</Button>
      </Space>
      {rangeError && <Alert type="error" title={rangeError} style={{ marginTop: 12 }} />}
    </Card>
    {query.error && <><ErrorNotice error={query.error} /><Typography.Text type="secondary">Chưa có số liệu đã xác minh cho kỳ này. Bấm Làm mới để thử lại.</Typography.Text></>}
    {query.isPending && <Spin tip="Đang tổng hợp dữ liệu trên máy…"><div style={{ height: 120 }} /></Spin>}
    {data && <>
      <Row gutter={[14, 14]}>
        <Col xs={24} md={8} xl={4}><Metric label="Farm đang quản lý" value={String(data.counts.farms)} href="#/records/farms" /></Col>
        <Col xs={24} md={8} xl={4}><Metric label="Lần khảo sát farm" value={String(data.counts.farm_surveys)} href="#/records/farms" /></Col>
        <Col xs={24} md={8} xl={4}><Metric label="Công ty khách hàng" value={String(data.counts.customer_companies)} href="#/records/customers" /></Col>
        <Col xs={24} md={8} xl={4}><Metric label="Hồ sơ đầu vào trong kỳ" value={String(data.counts.inbound_trades)} href={listLink("inbound", dates.from, dates.through)} /></Col>
        <Col xs={24} md={8} xl={4}><Metric label="Đơn đầu ra trong kỳ" value={String(data.counts.outbound_trades)} href={listLink("outbound", dates.from, dates.through)} color="#a66c20" /></Col>
        <Col xs={24} md={8} xl={4}><Metric label="Tồn kho cuối kỳ" value={decimal(totalStock(data.inventory.items))} unit="kg" href={`#/records?tab=inventory&from_on=${dates.from}&through_on=${dates.through}`} /></Col>
      </Row>
      <Row gutter={[14, 14]}>
        <Col xs={24} md={12} xl={6}><Metric label="Nhập kho đã ghi sổ" value={decimal(data.period.inbound_kg)} unit="kg" href={`#/records?tab=entries&entry_type=receipt&status=posted&from_on=${dates.from}&through_on=${dates.through}`} /></Col>
        <Col xs={24} md={12} xl={6}><Metric label="Xuất kho đã ghi sổ" value={decimal(data.period.outbound_kg)} unit="kg" href={`#/records?tab=entries&entry_type=issue&status=posted&from_on=${dates.from}&through_on=${dates.through}`} color="#a66c20" /></Col>
        <Col xs={24} md={12} xl={6}><Metric label="Đã ghi thu từ khách hàng" value={decimal(data.period.cash_in_vnd)} unit="đ" href={listLink("outbound", dates.from, dates.through)} /></Col>
        <Col xs={24} md={12} xl={6}><Metric label="Đã ghi chi cho farm" value={decimal(data.period.cash_out_vnd)} unit="đ" href={listLink("inbound", dates.from, dates.through)} color="#a66c20" /></Col>
      </Row>
      <Card size="small" title="Giá trị đơn bán được ghi trong kỳ">
        <Typography.Title level={3} style={{ margin: 0 }}>{decimal(data.period.sales_order_value_vnd)} đ</Typography.Title>
        <Typography.Paragraph type="secondary" style={{ marginBottom: 0 }}>Tính từ số lượng và giá trên đơn đã ghi, chưa phản ánh doanh thu hoặc tiền đã thu. {data.period.unpriced_sales_orders > 0 ? `${data.period.unpriced_sales_orders} đơn chưa đủ giá được tách khỏi tổng này.` : "Các đơn trong tổng đã có đủ giá."} Thu/chi bên trên chỉ lấy từ giao dịch gắn hồ sơ mua/bán; sổ Excel kế toán được tổng hợp riêng ở Báo cáo.</Typography.Paragraph>
      </Card>
      <Row gutter={[14, 14]}>
        <Col xs={24} xl={12}><Card size="small" title="Nhập / xuất kho theo ngày (kg)"><Typography.Text style={{ color: "#24604d" }}>■ Nhập kho</Typography.Text> <Typography.Text style={{ color: "#a66c20" }}>■ Xuất kho</Typography.Text><Trend rows={data.daily} keys={["inbound_kg", "outbound_kg"]} precision={3} label="Xu hướng kg nhập và xuất theo ngày" /></Card></Col>
        <Col xs={24} xl={12}><Card size="small" title="Thu / chi đã ghi theo ngày (đ)"><Typography.Text style={{ color: "#24604d" }}>■ Thu khách hàng</Typography.Text> <Typography.Text style={{ color: "#a66c20" }}>■ Chi farm</Typography.Text><Trend rows={data.daily} keys={["cash_in_vnd", "cash_out_vnd"]} precision={2} label="Xu hướng thu và chi theo ngày" /></Card></Col>
      </Row>
      <Card title="Chi tiết theo ngày" size="small">
        <Table size="small" rowKey="occurred_on" dataSource={data.daily} scroll={{ x: 900 }} pagination={{ pageSize: 15, showSizeChanger: false }} columns={[
          { title: "Ngày", dataIndex: "occurred_on", render: displayBusinessDate },
          { title: "Nhập kho (kg)", dataIndex: "inbound_kg", align: "right", render: decimal },
          { title: "Xuất kho (kg)", dataIndex: "outbound_kg", align: "right", render: decimal },
          { title: "Thu khách hàng (đ)", dataIndex: "cash_in_vnd", align: "right", render: decimal },
          { title: "Chi farm (đ)", dataIndex: "cash_out_vnd", align: "right", render: decimal },
          { title: "Giá trị đơn bán (đ)", dataIndex: "sales_order_value_vnd", align: "right", render: decimal },
          { title: "Đơn thiếu giá", dataIndex: "unpriced_sales_orders", align: "right" },
        ]} />
      </Card>
      {data.inventory.validation_flags.length > 0 && <Alert type="warning" showIcon title="Lưu ý dữ liệu kho" description={data.inventory.validation_flags.join("; ")} />}
    </>}
  </Space>;
}
