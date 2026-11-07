import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Alert, Button, Card, Col, Descriptions, Form, Input, InputNumber, Row, Select, Space, Typography } from "antd";
import { DateInput, dateInputRule } from "../../shared/DateInput";
import { CommerceFormModal, invalidateRecords, PartySelect, useCommerceRecord } from "./CommerceShared";
import { companyComplete, type CommerceParty, type Direction, type Trade, type TradeLine } from "./commerceTypes";
import { DecimalInput, ErrorNotice, required, todayVN } from "./helpers";
import { PartyEditor } from "./PartyEditor";
import { ReferenceSelect } from "./ReferenceSelect";
import { quoteMatches, TradePriceFields } from "./TradePriceFields";

export function tradePayload(values: Record<string, unknown>, direction: Direction) {
  const fields = ["code", "occurred_on", "occurred_at", "physical_actor", "party_id", "status", "vehicle_plate", "weighing_id", "note"];
  const lineFields = ["farm_id", "product_id", "quantity_kg", "unit_price_vnd", "bag_count", "grade", "note", "pricing_mode", "price_kind", "price_date", "price_snapshot"];
  return { ...Object.fromEntries(fields.filter((key) => values[key] !== undefined).map((key) => [key, values[key] === "" ? null : values[key]])), direction, lines: ((values.lines ?? []) as Record<string, unknown>[]).map((line) => ({ ...Object.fromEntries(lineFields.filter((key) => line[key] !== undefined).map((key) => [key, line[key]])), farm_id: line.farm_id || null, product_id: line.product_id || null, unit_price_vnd: line.unit_price_vnd === "" || line.unit_price_vnd === undefined ? null : line.unit_price_vnd, grade: line.grade ?? null, bag_count: line.bag_count ?? 0, ...(line.pricing_mode !== "daily" ? { pricing_mode: "manual", price_kind: null, price_date: null, price_snapshot: null } : {}) })) };
}

export function TradeEditor({ direction, initial, onClose, onSaved }: { direction: Direction; initial?: Trade; onClose: () => void; onSaved: (value: Trade) => void }) {
  const [form] = Form.useForm();
  const writeGuard = useRef(false);
  const watchedLines = Form.useWatch("lines", { form, preserve: true }) as TradeLine[] | undefined;
  const occurredOn = Form.useWatch("occurred_on", form) as string;
  const quotesReady = !!watchedLines?.length && watchedLines.every((line) => line.pricing_mode !== "daily" || quoteMatches(line, occurredOn));
  const newLine = () => ({ bag_count: 0, pricing_mode: "daily", price_kind: direction === "inbound" ? "purchase_fresh" : "sale" });
  const companyId = Form.useWatch("party_id", form) as string | undefined;
  const company = useCommerceRecord<CommerceParty>("parties", direction === "outbound" ? companyId : undefined);
  const [continued, setContinued] = useState(false);
  const [partyEditor, setPartyEditor] = useState<{ value?: CommerceParty }>();
  const [farmLine, setFarmLine] = useState<number | null>(null);
  const cache = useQueryClient();
  const inbound = direction === "inbound";
  useEffect(() => { setContinued(false); }, [companyId]);
  const showOrder = inbound || (continued && companyComplete(company.data, !!initial && initial.party_id === companyId));
  async function partySaved(party: CommerceParty) {
    if (writeGuard.current) return;
    if (inbound && farmLine !== null) form.setFieldValue(["lines", farmLine, "farm_id"], party.id);
    else form.setFieldValue("party_id", party.id);
    setPartyEditor(undefined); await invalidateRecords(cache);
  }
  return <><CommerceFormModal<Trade> resource="trades" initial={initial} title={`${initial ? "Sửa" : "Thêm"} hồ sơ ${inbound ? "mua vào" : "bán ra"}`} defaults={{ occurred_on: todayVN(), direction, status: "recorded", lines: [newLine()], ...initial, ...(initial ? { lines: initial.lines.map((line) => ({ ...line, pricing_mode: line.pricing_mode ?? "manual" })) } : {}) }} payload={(values) => tradePayload(values, direction)} form={form} canSubmit={showOrder && quotesReady} writeGuard={writeGuard} onValuesChange={(changed) => { if (changed.occurred_on !== undefined && !writeGuard.current) { const rows = form.getFieldValue("lines") as TradeLine[]; form.setFieldValue("lines", rows.map((line) => line.pricing_mode === "daily" ? { ...line, price_date: changed.occurred_on, price_snapshot: null, unit_price_vnd: null } : line)); } }} onClose={onClose} onSaved={onSaved}>
    {!inbound && <Card title="1. Công ty khách hàng" size="small"><Form.Item label="Công ty khách hàng" name="party_id" rules={required}><PartySelect profile="customer_company" label="Chọn công ty khách hàng" /></Form.Item><Space wrap><Button onClick={() => setPartyEditor({})}>Thêm công ty</Button>{company.data && <Button onClick={() => setPartyEditor({ value: company.data })}>Hoàn tất thông tin công ty</Button>}</Space><ErrorNotice error={company.error} />{company.data && <Descriptions column={1} size="small" items={[{ key: "name", label: "Tên công ty", children: company.data.name }, { key: "tax", label: "MST", children: company.data.tax_code || "Chưa nhập" }, { key: "contact", label: "Người liên hệ", children: company.data.representative?.name || "Chưa nhập" }]} />}{companyId && !companyComplete(company.data, !!initial && initial.party_id === companyId) && !company.isPending && <Alert type="warning" showIcon title="Hoàn tất tên công ty, MST và người liên hệ; công ty phải đang sử dụng trước khi tiếp tục." />}<Button type="primary" disabled={!companyComplete(company.data, !!initial && initial.party_id === companyId)} onClick={() => setContinued(true)}>Tiếp tục nhập đơn bán</Button></Card>}
    {showOrder && <><Typography.Title level={5}>{inbound ? "Thông tin mua vào" : "2. Thông tin đơn bán"}</Typography.Title><Alert type="info" showIcon title="Lưu hồ sơ chưa thay đổi tồn kho. Tạo phiếu kho riêng từ màn hình chi tiết khi có giao nhận thực tế." /><Row gutter={16}><Col span={12}><Form.Item label="Mã / số đơn" name="code" rules={required}><Input /></Form.Item></Col><Col span={12}><Form.Item label="Ngày nghiệp vụ" name="occurred_on" rules={[...required, dateInputRule]}><DateInput aria-label="Ngày nghiệp vụ" /></Form.Item></Col><Col span={12}><Form.Item label="Biển xe" name="vehicle_plate"><Input /></Form.Item></Col><Col span={12}><Form.Item label="Người thực hiện thực tế" name="physical_actor"><Input /></Form.Item></Col></Row><Form.Item label="Trạng thái hồ sơ" name="status" rules={required}><Select options={[{ value: "recorded", label: "Đã ghi nhận" }, { value: "cancelled", label: "Đã hủy" }]} /></Form.Item><Form.Item label="Thời điểm nghiệp vụ có múi giờ (tùy chọn)" name="occurred_at"><Input placeholder="2026-11-07T08:30:00+07:00" /></Form.Item><Form.Item label="Phiếu cân liên kết (tùy chọn)" name="weighing_id"><ReferenceSelect resource="weighings" /></Form.Item>
      <Form.List name="lines" rules={[{ validator: async (_, lines) => { if (!lines?.length || lines.length > 500) throw new Error("Hồ sơ cần từ 1 đến 500 dòng."); } }]}>{(fields, { add, remove }, meta) => <Space orientation="vertical" className="full">{fields.map((field) => <Card key={field.key} title={`Dòng ${field.name + 1}`} size="small" extra={<Button disabled={fields.length === 1} onClick={() => remove(field.name)}>Bỏ dòng</Button>}>{inbound && <><Form.Item label="Farm cung cấp" name={[field.name, "farm_id"]} rules={required}><PartySelect profile="farm" label={`Farm dòng ${field.name + 1}`} /></Form.Item><Button onClick={() => { setFarmLine(field.name); setPartyEditor({}); }}>Thêm Farm cho dòng này</Button></>}<Row gutter={12}><Col span={12}><Form.Item label={inbound ? "Hàng hóa (chọn trước khi ghi sổ kho)" : "Hàng hóa"} name={[field.name, "product_id"]} rules={inbound ? [] : required}><ReferenceSelect resource="products" /></Form.Item></Col><Col span={12}><DecimalInput label="Số kg" name={[field.name, "quantity_kg"]} requiredValue /></Col><Col span={8}><Form.Item label="Số bao" name={[field.name, "bag_count"]}><InputNumber min={0} precision={0} /></Form.Item></Col></Row><TradePriceFields form={form} index={field.name} direction={direction} /><Form.Item label="Ghi chú dòng" name={[field.name, "note"]}><Input /></Form.Item></Card>)}<Form.ErrorList errors={meta.errors} /><Button disabled={fields.length >= 500} onClick={() => add(newLine())}>Thêm dòng hàng</Button></Space>}</Form.List><Form.Item label="Ghi chú" name="note"><Input.TextArea /></Form.Item></>}
  </CommerceFormModal>{partyEditor && <PartyEditor profile={inbound ? "farm" : "customer_company"} initial={partyEditor.value} requireCompany={!inbound} onClose={() => setPartyEditor(undefined)} onSaved={(value) => void partySaved(value)} />}</>;
}
