import { useId, useState } from "react";
import { Alert, Button, Card, Checkbox, Col, Collapse, ConfigProvider, Input, Row, Select, Space, Tag, Typography } from "antd";
import type { BankAccount, ContractData, ContractLine, ContractTemplate, Party, Weighing } from "./types";
import { defaultTemplateIds, emptyAccount, emptyLine } from "./types";

export function Field({ label, value, onChange, area = false, type = "text", hint, required = false }: {
  label: string; value: string | null | undefined; onChange: (value: string) => void;
  area?: boolean; type?: string; hint?: string; required?: boolean;
}) {
  const id = useId();
  return <div className="contracts-field">
    <label htmlFor={id}>{label}{required && <span aria-hidden="true"> *</span>}</label>
    {area ? <Input.TextArea id={id} value={value ?? ""} onChange={(e) => onChange(e.target.value)} autoSize={{ minRows: 2, maxRows: 6 }} /> :
      <Input id={id} type={type} value={value ?? ""} onChange={(e) => onChange(e.target.value)} autoComplete="off" />}
    {hint && <Typography.Text type="secondary" className="contracts-hint">{hint}</Typography.Text>}
  </div>;
}
const nullable = (value: string) => value || null;

function AccountEditor({ value, onChange }: { value: BankAccount; onChange: (value: BankAccount) => void }) {
  return <Row gutter={12}>
    <Col span={12}><Field label="Ngân hàng" value={value.bank_name} onChange={(bank_name) => onChange({ ...value, bank_name })} /></Col>
    <Col span={12}><Field label="Số tài khoản" value={value.account_number} onChange={(account_number) => onChange({ ...value, account_number })} /></Col>
    <Col span={12}><Field label="Chủ tài khoản" value={value.account_holder} onChange={(account_holder) => onChange({ ...value, account_holder: nullable(account_holder) })} /></Col>
    <Col span={12}><Field label="Chi nhánh" value={value.branch} onChange={(branch) => onChange({ ...value, branch: nullable(branch) })} /></Col>
  </Row>;
}

function PartyEditor({ title, value, onChange }: { title: string; value: Party; onChange: (value: Party) => void }) {
  return <Card size="small" title={title}>
    <div className="contracts-field"><label>Loại đối tác</label><Select aria-label={`${title} · loại đối tác`} value={value.type} onChange={(type) => onChange({ ...value, type })} options={[{ value: "company", label: "Tổ chức / công ty" }, { value: "person", label: "Cá nhân" }]} /></div>
    <Field label="Tên đầy đủ" required value={value.name} onChange={(name) => onChange({ ...value, name })} />
    <Field label="Địa chỉ" value={value.address} onChange={(address) => onChange({ ...value, address: nullable(address) })} />
    <Field label="Mã số thuế / định danh" value={value.tax_code} onChange={(tax_code) => onChange({ ...value, tax_code: nullable(tax_code) })} />
    <Checkbox checked={!!value.representative} onChange={(e) => onChange({ ...value, representative: e.target.checked ? { name: "", title: null, authorization_reference: null } : null })}>Có người đại diện</Checkbox>
    {value.representative && <>
      <Field label="Tên người đại diện" value={value.representative.name} onChange={(name) => onChange({ ...value, representative: { ...value.representative!, name } })} />
      <Field label="Chức vụ" value={value.representative.title} onChange={(title) => onChange({ ...value, representative: { ...value.representative!, title: nullable(title) } })} />
      <Field label="Căn cứ ủy quyền" value={value.representative.authorization_reference} onChange={(authorization_reference) => onChange({ ...value, representative: { ...value.representative!, authorization_reference: nullable(authorization_reference) } })} />
    </>}
    <Collapse className="contracts-section" size="small" items={[
      { key: "contacts", label: `Liên hệ (${value.contacts.length})`, children: <>
        {value.contacts.map((contact, index) => <div className="contracts-subrow" key={index}>
          <Field label="Loại liên hệ" value={contact.kind} onChange={(kind) => onChange({ ...value, contacts: value.contacts.map((item, i) => i === index ? { ...item, kind } : item) })} />
          <Field label="Nội dung liên hệ" value={contact.value} onChange={(content) => onChange({ ...value, contacts: value.contacts.map((item, i) => i === index ? { ...item, value: content } : item) })} />
          <Field label="Nhãn liên hệ" value={contact.label} onChange={(label) => onChange({ ...value, contacts: value.contacts.map((item, i) => i === index ? { ...item, label: nullable(label) } : item) })} />
          <Button danger size="small" onClick={() => onChange({ ...value, contacts: value.contacts.filter((_, i) => i !== index) })}>Bỏ liên hệ</Button>
        </div>)}
        <Button onClick={() => onChange({ ...value, contacts: [...value.contacts, { kind: "phone", value: "", label: null }] })}>Thêm liên hệ</Button>
      </> },
      { key: "banks", label: `Tài khoản đối tác (${value.bank_details.length})`, children: <>
        {value.bank_details.map((account, index) => <div className="contracts-subrow" key={index}>
          <AccountEditor value={account} onChange={(next) => onChange({ ...value, bank_details: value.bank_details.map((item, i) => i === index ? next : item) })} />
          <Button danger size="small" onClick={() => onChange({ ...value, bank_details: value.bank_details.filter((_, i) => i !== index) })}>Bỏ tài khoản</Button>
        </div>)}
        <Button onClick={() => onChange({ ...value, bank_details: [...value.bank_details, emptyAccount()] })}>Thêm tài khoản</Button>
      </> },
    ]} />
  </Card>;
}

function LinesEditor({ lines, onChange }: { lines: ContractLine[]; onChange: (lines: ContractLine[]) => void }) {
  const change = (index: number, patch: Partial<ContractLine>) => onChange(lines.map((line, i) => i === index ? { ...line, ...patch } : line));
  return <>
    <Typography.Paragraph type="secondary">Nhập số thập phân bằng dấu chấm, không có dấu phân cách hàng nghìn. Số lượng dùng trong hợp đồng do bạn chọn; thông tin cân được giữ riêng.</Typography.Paragraph>
    {lines.map((line, index) => <Card key={index} size="small" className="contracts-section" title={<Space wrap>Dòng {index + 1}{line.source && <Tag color="blue">Phiếu {line.source.code} · v{line.source.version} · dòng {line.source.line_index + 1}</Tag>}</Space>} extra={<Button danger size="small" disabled={lines.length === 1} onClick={() => onChange(lines.filter((_, i) => i !== index))}>Bỏ dòng</Button>}>
      <Row gutter={12}>
        <Col span={12}><Field label="Hàng hóa / mô tả" required value={line.description} onChange={(description) => change(index, { description })} /></Col>
        <Col span={6}><Field label="Số lượng hợp đồng (kg)" required value={line.quantity_kg} onChange={(quantity_kg) => change(index, { quantity_kg })} /></Col>
        <Col span={6}><Field label="Đơn giá (VND/kg)" required value={line.unit_price} onChange={(unit_price) => change(index, { unit_price })} /></Col>
      </Row>
      <Collapse size="small" items={[{ key: "weight", label: "Thông tin cân, mã hàng và ghi chú", children: <>
        <Row gutter={12}>
          <Col span={6}><Field label="Cân đầy (kg)" value={line.gross_kg} onChange={(value) => change(index, { gross_kg: nullable(value) })} /></Col>
          <Col span={6}><Field label="Cân bì (kg)" value={line.tare_kg} onChange={(value) => change(index, { tare_kg: nullable(value) })} /></Col>
          <Col span={6}><Field label="Cân tịnh (kg)" value={line.net_kg} onChange={(value) => change(index, { net_kg: nullable(value) })} /></Col>
          <Col span={6}><Field label="Cách xác định kg" value={line.quantity_source} onChange={(value) => change(index, { quantity_source: nullable(value) })} hint="Ví dụ: nhập trực tiếp, tính từ cân đầy/bì" /></Col>
          <Col span={12}><Field label="ID hàng hóa (tùy chọn)" value={line.product_id} onChange={(value) => change(index, { product_id: nullable(value) })} /></Col>
          <Col span={12}><Field label="Ghi chú dòng" value={line.note} onChange={(value) => change(index, { note: nullable(value) })} /></Col>
        </Row>
        {line.source_snapshot && <Typography.Paragraph type="secondary">Số cân nguồn được giữ trong snapshot: đầy {line.source_snapshot.gross_kg ?? "—"}; bì {line.source_snapshot.tare_kg ?? "—"}; tịnh {line.source_snapshot.net_kg ?? "—"} kg. Sửa hợp đồng chỉ thay dữ liệu hợp đồng.</Typography.Paragraph>}
        {line.source && <Button onClick={() => change(index, { source: null, source_snapshot: null })}>Bỏ liên kết nguồn của dòng</Button>}
      </> }]} />
    </Card>)}
    <Button className="contracts-section" onClick={() => onChange([...lines, emptyLine()])}>Thêm dòng hàng</Button>
  </>;
}

export function ContractEditor({ data, onChange, templates, disabled, onLoadParty, onLoadWeighing, weighing, onUseWeighing }: {
  data: ContractData; onChange: (data: ContractData) => void; templates: ContractTemplate[]; disabled: boolean;
  onLoadParty: (id: string, target: "company" | "counterparty") => void;
  onLoadWeighing: (id: string) => void; weighing: Weighing | null;
  onUseWeighing: (lineIndices: number[]) => void;
}) {
  const [partyId, setPartyId] = useState("");
  const [partyTarget, setPartyTarget] = useState<"company" | "counterparty">("counterparty");
  const [weighingId, setWeighingId] = useState("");
  const [selectedLines, setSelectedLines] = useState<number[]>([]);
  const available = templates.filter((template) => template.kind === data.kind);
  return <ConfigProvider componentDisabled={disabled}><fieldset disabled={disabled} className="contracts-fieldset">
    <Card size="small" title="Thông tin hợp đồng">
      <Row gutter={16}>
        <Col span={8}><div className="contracts-field"><label>Loại hợp đồng</label><Select aria-label="Loại hợp đồng" disabled={disabled} value={data.kind} onChange={(kind: ContractData["kind"]) => onChange({ ...data, kind, template_id: defaultTemplateIds[kind] })} options={[{ value: "purchase", label: "Mua vào" }, { value: "sale", label: "Bán ra" }]} /></div></Col>
        <Col span={16}><div className="contracts-field"><label>Mẫu hợp đồng</label><Select aria-label="Mẫu hợp đồng" disabled={disabled} value={data.template_id} onChange={(template_id) => onChange({ ...data, template_id })} options={available.length ? available.map((template) => ({ value: template.id, label: template.title ?? template.name ?? template.id })) : [{ value: defaultTemplateIds[data.kind], label: data.kind === "purchase" ? "Mẫu hợp đồng mua" : "Mẫu hợp đồng bán" }]} /></div></Col>
        <Col span={8}><Field label="Số hợp đồng" required value={data.number} onChange={(number) => onChange({ ...data, number })} /></Col>
        <Col span={8}><Field label="Ngày lập" required type="date" value={data.occurred_on} onChange={(occurred_on) => onChange({ ...data, occurred_on })} /></Col>
        <Col span={8}><Field label="Nơi lập" required value={data.place} onChange={(place) => onChange({ ...data, place })} /></Col>
      </Row>
    </Card>
    <Collapse className="contracts-section" items={[{ key: "sources", label: "Tự điền từ dữ liệu đã lưu (tùy chọn)", children: <>
      <Typography.Paragraph>Có thể nhập thủ công toàn bộ hợp đồng. Dữ liệu nguồn chỉ được sao chép khi bạn chọn; kiểm tra và sửa trước khi lưu.</Typography.Paragraph>
      <Space.Compact block className="contracts-section"><Input aria-label="ID đối tác nguồn" placeholder="ID đối tác đã lưu" value={partyId} onChange={(e) => setPartyId(e.target.value)} /><Select aria-label="Điền vào bên" disabled={disabled} style={{ minWidth: 160 }} value={partyTarget} onChange={setPartyTarget} options={[{ value: "company", label: "Công ty của bạn" }, { value: "counterparty", label: "Đối tác" }]} /><Button disabled={disabled || !partyId.trim()} onClick={() => onLoadParty(partyId.trim(), partyTarget)}>Lấy thông tin đối tác</Button></Space.Compact>
      <Space.Compact block className="contracts-section"><Input aria-label="ID phiếu cân nguồn" placeholder="ID phiếu cân đã lưu" value={weighingId} onChange={(e) => setWeighingId(e.target.value)} /><Button disabled={disabled || !weighingId.trim()} onClick={() => { setSelectedLines([]); onLoadWeighing(weighingId.trim()); }}>Xem dòng phiếu cân</Button></Space.Compact>
      {weighing && <Card size="small" title={`${weighing.code} · ${weighing.occurred_on} · phiên bản ${weighing.version}`}>
        <Checkbox.Group value={selectedLines} onChange={(values) => setSelectedLines(values as number[])} className="contracts-source-lines">{weighing.lines.map((line, index) => <Checkbox disabled={disabled} key={index} value={index}>Dòng {index + 1}: {line.description ?? "Chưa có mô tả"} · kg tịnh {line.net_kg ?? "chưa nhập"} · nguồn kg {line.quantity_source ?? "chưa nhập"}</Checkbox>)}</Checkbox.Group>
        <Button disabled={disabled || !selectedLines.length} onClick={() => { onUseWeighing(selectedLines); setSelectedLines([]); }}>Thêm các dòng đã chọn vào hợp đồng</Button>
      </Card>}
    </> }]} />
    <Row gutter={16} className="contracts-section">
      <Col span={12}><PartyEditor title={`Công ty của bạn · ${data.kind === "purchase" ? "bên mua" : "bên bán"}`} value={data.company} onChange={(company) => onChange({ ...data, company })} /></Col>
      <Col span={12}><PartyEditor title={`Đối tác · ${data.kind === "purchase" ? "bên bán" : "bên mua"}`} value={data.counterparty} onChange={(counterparty) => onChange({ ...data, counterparty })} /></Col>
    </Row>
    <Card size="small" title="Hàng hóa và số cân" className="contracts-section"><LinesEditor lines={data.lines} onChange={(lines) => onChange({ ...data, lines })} /></Card>
    <Card size="small" title="Thuế" className="contracts-section">
      <Row gutter={16}><Col span={12}><div className="contracts-field"><label>Cách ghi thuế</label><Select aria-label="Cách ghi thuế" disabled={disabled} value={data.tax.mode} onChange={(mode) => onChange({ ...data, tax: { mode, rate: mode === "inclusive" || mode === "exclusive" ? data.tax.rate : null } })} options={[{ value: "unspecified", label: "Chưa xác định" }, { value: "none", label: "Không tính thuế" }, { value: "exclusive", label: "Đơn giá chưa bao gồm thuế" }, { value: "inclusive", label: "Đơn giá đã bao gồm thuế" }]} /></div></Col>
      {(data.tax.mode === "inclusive" || data.tax.mode === "exclusive") && <Col span={12}><Field label="Thuế suất (%)" value={data.tax.rate} onChange={(rate) => onChange({ ...data, tax: { ...data.tax, rate: nullable(rate) } })} hint="Nhập thuế suất đã xác định cho hợp đồng." /></Col>}</Row>
    </Card>
    <Card size="small" title="Giao nhận và điều khoản" className="contracts-section">
      <Row gutter={16}>{([ ["delivery", "Giao nhận"], ["packaging", "Đóng gói / bao bì"], ["quality", "Chất lượng"], ["deadline", "Thời hạn thực hiện"], ["responsibilities", "Trách nhiệm các bên"], ["additional", "Điều khoản bổ sung"] ] as const).map(([key, label]) => <Col key={key} span={12}><Field label={label} area value={data.terms[key]} onChange={(value) => onChange({ ...data, terms: { ...data.terms, [key]: value } })} /></Col>)}</Row>
    </Card>
    <Card size="small" title="Thanh toán" className="contracts-section">
      <Row gutter={16}>
        <Col span={12}><div className="contracts-field"><label>Phương thức thanh toán</label><Select aria-label="Phương thức thanh toán" disabled={disabled} value={data.payment.method} onChange={(method) => onChange({ ...data, payment: { ...data.payment, method } })} options={[{ value: "cash", label: "Tiền mặt" }, { value: "bank", label: "Chuyển khoản" }, { value: "mixed", label: "Kết hợp" }, { value: "other", label: "Khác" }]} /></div></Col>
        <Col span={12}><Field label="Hạn thanh toán" type="date" value={data.payment.due_on} onChange={(due_on) => onChange({ ...data, payment: { ...data.payment, due_on: nullable(due_on) } })} /></Col>
        <Col span={12}><Field label="Tiền đặt cọc đã ghi (VND)" value={data.payment.deposit_amount} onChange={(deposit_amount) => onChange({ ...data, payment: { ...data.payment, deposit_amount: nullable(deposit_amount) } })} /></Col>
        <Col span={12}><Field label="Số đã thanh toán do người nhập ghi (VND)" value={data.payment.recorded_paid_amount} onChange={(recorded_paid_amount) => onChange({ ...data, payment: { ...data.payment, recorded_paid_amount: nullable(recorded_paid_amount) } })} /></Col>
        <Col span={24}><Field label="Nội dung và thỏa thuận thanh toán" area value={data.payment.description} onChange={(description) => onChange({ ...data, payment: { ...data.payment, description } })} /></Col>
      </Row>
      <Checkbox disabled={disabled} checked={!!data.payment.receiving_account} onChange={(e) => onChange({ ...data, payment: { ...data.payment, receiving_account: e.target.checked ? emptyAccount() : null } })}>Ghi tài khoản nhận tiền trong hợp đồng</Checkbox>
      {data.payment.receiving_account && <div className="contracts-subrow"><AccountEditor value={data.payment.receiving_account} onChange={(receiving_account) => onChange({ ...data, payment: { ...data.payment, receiving_account } })} /></div>}
      <Typography.Title level={5}>Lịch thanh toán theo đợt (tùy chọn)</Typography.Title>
      {data.payment.schedule.map((item, index) => <Row gutter={12} key={index} align="middle">
        <Col span={6}><Field label={`Ngày đợt ${index + 1}`} type="date" value={item.due_on} onChange={(due_on) => onChange({ ...data, payment: { ...data.payment, schedule: data.payment.schedule.map((entry, i) => i === index ? { ...entry, due_on } : entry) } })} /></Col>
        <Col span={6}><Field label={`Số tiền đợt ${index + 1} (VND)`} value={item.amount} onChange={(amount) => onChange({ ...data, payment: { ...data.payment, schedule: data.payment.schedule.map((entry, i) => i === index ? { ...entry, amount } : entry) } })} /></Col>
        <Col span={9}><Field label={`Ghi chú đợt ${index + 1}`} value={item.note} onChange={(note) => onChange({ ...data, payment: { ...data.payment, schedule: data.payment.schedule.map((entry, i) => i === index ? { ...entry, note } : entry) } })} /></Col>
        <Col span={3}><Button danger onClick={() => onChange({ ...data, payment: { ...data.payment, schedule: data.payment.schedule.filter((_, i) => i !== index) } })}>Bỏ đợt</Button></Col>
      </Row>)}
      <Button onClick={() => onChange({ ...data, payment: { ...data.payment, schedule: [...data.payment.schedule, { due_on: "", amount: "", note: "" }] } })}>Thêm đợt thanh toán</Button>
      <Alert className="contracts-section" type="info" title="Số tiền và tình trạng thanh toán là thông tin bạn nhập trong hợp đồng; thao tác này không chuyển tiền hoặc ghi sổ kế toán." />
    </Card>
  </fieldset></ConfigProvider>;
}
