import { Button, Card, Col, Form, Input, InputNumber, Row, Select, Switch } from "antd";
import { CommerceFormModal } from "./CommerceShared";
import { DecimalInput, required } from "./helpers";
import type { CommerceParty, ProfileKind } from "./commerceTypes";

export function partyPayload(values: Record<string, unknown>, profile: ProfileKind, initial?: CommerceParty): Record<string, unknown> {
  const fields = ["code", "name", "type", "roles", "address", "tax_code", "business_license", "contacts", "bank_details", "representative", "farm", "note", "active"];
  const source: Record<string, unknown> = { ...initial, ...values };
  if (initial?.representative && values.representative) source.representative = { ...initial.representative, ...(values.representative as object) };
  const payload = Object.fromEntries(fields.filter((field) => source[field] !== undefined).map((field) => [field, source[field]]));
  payload.profile_kind = profile;
  payload.type = profile === "farm" ? "person" : "organization";
  payload.roles ??= [profile === "farm" ? "supplier" : "customer"];
  payload.contacts ??= []; payload.bank_details ??= [];
  const rep = payload.representative as Record<string, unknown> | undefined;
  if (rep && !rep.name) payload.representative = null;
  if (profile === "farm") {
    payload.code = String(payload.code).toUpperCase();
    const farm = payload.farm as Record<string, unknown> ?? {};
    farm.plots = ((farm.plots ?? []) as Record<string, unknown>[]).map((line) => ({ ...line, area_ha: line.area_ha || null, tree_count: line.tree_count ?? null, tree_age: line.tree_age ?? null }));
    farm.surveys = ((farm.surveys ?? []) as Record<string, unknown>[]).map((line) => ({ ...line, ripeness_pct: line.ripeness_pct || null }));
    payload.farm = farm;
    if (!payload.representative && farm.owner_name) payload.representative = { name: farm.owner_name };
  } else payload.farm = null;
  return payload;
}

export function PartyEditor({ profile, initial, requireCompany = false, onClose, onSaved }: { profile: ProfileKind; initial?: CommerceParty; requireCompany?: boolean; onClose: () => void; onSaved: (value: CommerceParty) => void }) {
  const farm = profile === "farm";
  return <CommerceFormModal<CommerceParty> resource="parties" initial={initial} title={`${initial ? "Sửa" : "Thêm"} ${farm ? "Farm" : "công ty khách hàng"}`} defaults={{ active: true, roles: [farm ? "supplier" : "customer"], contacts: [], bank_details: [], farm: farm ? { plots: [], surveys: [] } : null, ...initial }} payload={(values) => partyPayload(values, profile, initial)} onClose={onClose} onSaved={onSaved}>
    <Row gutter={16}><Col span={8}><Form.Item label={farm ? "Mã Farm (4 ký tự)" : "Mã công ty"} name="code" normalize={(value: string) => farm ? value.toUpperCase() : value} rules={[...required, ...(farm ? [{ pattern: /^[A-Z0-9]{4}$/, message: "Mã Farm gồm đúng 4 chữ cái A–Z hoặc chữ số." }] : [])]} extra={farm ? "Mã Farm không đổi sau khi tạo." : undefined}><Input disabled={farm && !!initial} maxLength={farm ? 4 : 80} autoComplete="off" /></Form.Item></Col><Col span={16}><Form.Item label={farm ? "Tên Farm" : "Tên công ty"} name="name" rules={required}><Input /></Form.Item></Col></Row>
    {farm ? <Card title="Chủ Farm và khu vực" size="small"><Row gutter={16}>{[["owner_name", "Tên chủ Farm"], ["owner_id_card", "CCCD / giấy tờ chủ Farm"], ["official_area_code", "Mã vùng chính thức"], ["internal_area_code", "Mã vùng nội bộ"]].map(([name, label]) => <Col span={12} key={name}><Form.Item label={label} name={["farm", name]}><Input /></Form.Item></Col>)}</Row></Card> : <Row gutter={16}><Col span={12}><Form.Item label="Mã số thuế" name="tax_code" rules={requireCompany ? required : []}><Input /></Form.Item></Col><Col span={12}><Form.Item label="Giấy phép kinh doanh" name="business_license"><Input /></Form.Item></Col><Col span={12}><Form.Item label="Người liên hệ / đại diện" name={["representative", "name"]} rules={requireCompany ? required : []}><Input /></Form.Item></Col><Col span={12}><Form.Item label="Chức vụ" name={["representative", "title"]}><Input /></Form.Item></Col></Row>}
    <Form.Item label="Địa chỉ" name="address"><Input /></Form.Item>
    <Form.List name="contacts">{(fields, { add, remove }) => <Card title="Điện thoại và liên hệ" size="small">{fields.map((field) => <Row gutter={12} key={field.key}><Col span={6}><Form.Item label="Loại liên hệ" name={[field.name, "kind"]} rules={required}><Select options={[{ value: "phone", label: "Điện thoại" }, { value: "email", label: "Email" }, { value: "other", label: "Khác" }]} /></Form.Item></Col><Col span={14}><Form.Item label="Thông tin liên hệ" name={[field.name, "value"]} rules={required}><Input /></Form.Item></Col><Col span={4}><Button onClick={() => remove(field.name)}>Bỏ liên hệ</Button></Col></Row>)}<Button onClick={() => add({ kind: "phone" })}>Thêm liên hệ</Button></Card>}</Form.List>
    <Form.List name="bank_details">{(fields, { add, remove }) => <Card title="Thông tin ngân hàng" size="small">{fields.map((field) => <Card key={field.key} size="small" title={`Tài khoản ${field.name + 1}`} extra={<Button onClick={() => remove(field.name)}>Bỏ tài khoản</Button>}><Row gutter={12}>{[["bank_name", "Ngân hàng", true], ["account_number", "Số tài khoản", true], ["account_holder", "Chủ tài khoản", false], ["branch", "Chi nhánh", false]].map(([name, label, mandatory]) => <Col span={12} key={String(name)}><Form.Item label={String(label)} name={[field.name, String(name)]} rules={mandatory ? required : []}><Input /></Form.Item></Col>)}</Row></Card>)}<Button onClick={() => add({})}>Thêm tài khoản ngân hàng</Button></Card>}</Form.List>
    {farm && <><Form.List name={["farm", "plots"]}>{(fields, { add, remove }) => <Card title="Lô trồng" size="small">{fields.map((field) => <Card key={field.key} title={`Lô ${field.name + 1}`} size="small" extra={<Button onClick={() => remove(field.name)}>Bỏ lô</Button>}><Row gutter={12}><Col span={12}><Form.Item label="Mã lô (tùy chọn)" name={[field.name, "plot_code"]}><Input /></Form.Item></Col><Col span={12}><Form.Item label="Giống" name={[field.name, "variety"]}><Input /></Form.Item></Col><Col span={8}><DecimalInput label="Diện tích (ha)" name={[field.name, "area_ha"]} /></Col><Col span={8}><Form.Item label="Số cây" name={[field.name, "tree_count"]}><InputNumber min={0} precision={0} /></Form.Item></Col><Col span={8}><Form.Item label="Tuổi cây" name={[field.name, "tree_age"]}><InputNumber min={0} precision={0} /></Form.Item></Col></Row></Card>)}<Button onClick={() => add({})}>Thêm lô trồng</Button></Card>}</Form.List>
      <Form.List name={["farm", "surveys"]}>{(fields, { add, remove }) => <Card title="Khảo sát mùa vụ" size="small">{fields.map((field) => <Card key={field.key} title={`Khảo sát ${field.name + 1}`} size="small" extra={<Button onClick={() => remove(field.name)}>Bỏ khảo sát</Button>}><Row gutter={12}><Col span={8}><Form.Item label="Năm mùa vụ" name={[field.name, "season_year"]} rules={required}><InputNumber min={1900} max={9999} precision={0} /></Form.Item></Col><Col span={8}><Form.Item label="Grade khảo sát" name={[field.name, "grade"]} rules={required}><Select options={[1, 2, 3, 4, 5].map((value) => ({ value, label: String(value) }))} /></Form.Item></Col><Col span={8}><DecimalInput label="Tỷ lệ chín (%)" name={[field.name, "ripeness_pct"]} /></Col></Row><Form.Item label="Ghi chú khảo sát" name={[field.name, "notes"]}><Input.TextArea /></Form.Item></Card>)}<Button onClick={() => add({})}>Thêm khảo sát</Button></Card>}</Form.List></>}
    <Form.Item label="Ghi chú" name="note"><Input.TextArea /></Form.Item><Form.Item label="Đang sử dụng" name="active" valuePropName="checked"><Switch /></Form.Item>
  </CommerceFormModal>;
}
