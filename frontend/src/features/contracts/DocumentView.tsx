import { Alert, Card, Descriptions, Space, Table, Tag, Typography } from "antd";
import type { Preview } from "./types";
import { decimalText } from "./types";

const totalLabels: Record<string, string> = {
  quantity_kg: "Tổng khối lượng (kg)", subtotal: "Tiền hàng (VND)", net_amount: "Giá trị trước thuế (VND)",
  tax_amount: "Tiền thuế (VND)", grand_total: "Tổng thanh toán (VND)", tax_rate: "Thuế suất (%)",
};
export function TotalsView({ totals }: { totals: Record<string, unknown> }) {
  return <Card size="small" title="Số liệu được tính từ dữ liệu hợp đồng">
    <Descriptions size="small" column={2} items={Object.entries(totalLabels).filter(([key]) => key in totals).map(([key, label]) => ({ key, label, children: <strong>{decimalText(totals[key])}</strong> }))} />
    {totals.tax_mode === "unspecified" && <Alert type="warning" title="Chưa xác định thuế; tổng thanh toán chưa được kết luận." />}
    {typeof totals.amount_in_words === "string" && <Typography.Paragraph className="contracts-section"><strong>Bằng chữ:</strong> {totals.amount_in_words}</Typography.Paragraph>}
    {typeof totals.rounding_policy === "string" && <Typography.Text type="secondary">Từng dòng làm tròn đến 0,01 VND theo quy tắc nửa lên; thuế làm tròn một lần trên tổng tiền hàng.</Typography.Text>}
  </Card>;
}
export function DocumentView({ preview, historical = false }: { preview: Preview; historical?: boolean }) {
  const doc = preview.document;
  const fields = Array.isArray(doc.fields) ? doc.fields : Object.entries(doc.fields ?? {});
  return <>
    <TotalsView totals={preview.totals} />
    <article className="contracts-paper">
      <Space className="contracts-paper-label" wrap><Tag color={historical ? "purple" : "blue"}>{historical ? "Snapshot đã xuất · chỉ đọc" : "Xem trước nội dung"}</Tag></Space>
      <Typography.Title level={3} style={{ textAlign: "center" }}>{doc.title}</Typography.Title>
      {doc.subtitle && <Typography.Paragraph style={{ textAlign: "center", whiteSpace: "pre-wrap" }}>{doc.subtitle}</Typography.Paragraph>}
      {fields.map(([label, value], index) => <Typography.Paragraph key={index} style={{ whiteSpace: "pre-wrap" }}><strong>{label}: </strong>{String(value ?? "")}</Typography.Paragraph>)}
      {(doc.paragraphs ?? []).map((text, index) => <Typography.Paragraph key={index} className="contracts-section" style={{ whiteSpace: "pre-wrap" }}>{text}</Typography.Paragraph>)}
      {!!doc.column_headers?.length && <Table size="small" pagination={false} bordered scroll={{ x: "max-content" }} rowKey="key"
        columns={doc.column_headers.map((title, index) => ({ title, dataIndex: `c${index}`, key: index, render: (value: unknown) => <span style={{ whiteSpace: "pre-wrap" }}>{String(value ?? "")}</span> }))}
        dataSource={(doc.rows ?? []).map((row, index) => ({ key: index, ...Object.fromEntries((Array.isArray(row) ? row : Object.values(row)).map((value, i) => [`c${i}`, value])) }))} />}
    </article>
  </>;
}
