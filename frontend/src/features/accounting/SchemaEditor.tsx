import { useEffect, useRef, useState } from 'react';
import { Alert, Button, Checkbox, Input, InputNumber, Modal, Select, Space, Table } from 'antd';
import { messageOf } from '../../shared/api';
import { requestKey, write } from './client';
import type { Book, ColumnDefinition } from './types';
const kinds: ColumnDefinition['kind'][] = ['text', 'date', 'integer', 'decimal', 'money', 'choice', 'formula'];
const metricMeaningOptions = [
  { value: 'cash_receipts', label: 'Thu tiền' },
  { value: 'cash_payments', label: 'Chi tiền' },
  { value: 'cash_receipt_deposits', label: 'Nhận tiền đặt cọc' },
  { value: 'cash_payment_deposits', label: 'Chi tiền đặt cọc' },
  { value: 'noncash_offsets', label: 'Bù trừ không bằng tiền' },
  { value: 'other', label: 'Khác' },
];
export function SchemaEditor({ open, book, onClose, onSaved }: { open: boolean; book?: Book; onClose: () => void; onSaved: (book: Book) => void }) {
  const [name, setName] = useState(''); const [columns, setColumns] = useState<ColumnDefinition[]>([]);
  const [semantics, setSemantics] = useState('{}'); const [busy, setBusy] = useState(false); const [error, setError] = useState('');
  const command = useRef<{ signature: string; key: string } | null>(null);
  useEffect(() => { if (open) { setName(book?.name ?? 'Sổ mới'); setColumns(book?.columns ?? []); setSemantics(JSON.stringify(book?.semantics ?? {}, null, 2)); setError(''); command.current = null; } }, [open, book]);
  function patch(index: number, value: Partial<ColumnDefinition>) { setColumns(old => old.map((column, i) => i === index ? { ...column, ...value } : column)); }
  function semanticsValue(): Record<string, unknown> { try { const value = JSON.parse(semantics); return value && !Array.isArray(value) && typeof value === 'object' ? value : {}; } catch { return {}; } }
  function updateSemantic(key: string, value: unknown) { const next = { ...semanticsValue() }; if (value === undefined || value === '') delete next[key]; else next[key] = value; setSemantics(JSON.stringify(next, null, 2)); }
  function metricMeanings(): Record<string, unknown> { const value = semanticsValue().metric_meanings; return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {}; }
  function metricMeaning(direction: 'income' | 'expense'): string | undefined { const value = metricMeanings()[direction]; return typeof value === 'string' && metricMeaningOptions.some(option => option.value === value) ? value : undefined; }
  function updateMetricMeaning(direction: 'income' | 'expense', value: string | undefined) { const next = { ...metricMeanings() }; if (value) next[direction] = value; else delete next[direction]; updateSemantic('metric_meanings', Object.keys(next).length ? next : undefined); }
  async function save() {
    setBusy(true); setError('');
    try {
      const parsed: unknown = JSON.parse(semantics);
      if (!parsed || Array.isArray(parsed) || typeof parsed !== 'object') throw new Error('Ngữ nghĩa phải là một object JSON.');
      if (!name.trim() || columns.some(column => !column.name.trim() || !column.id.trim())) throw new Error('Nhập tên sổ và ID/tên của từng cột.');
      const payload = book ? { expected_version: book.version, columns, semantics: parsed } : { name: name.trim(), columns, semantics: parsed };
      const signature = JSON.stringify(payload); if (command.current?.signature !== signature) command.current = { signature, key: requestKey() };
      const result = book ? await write<Book>(`/books/${book.id}/schema`, { ...payload, request_key: command.current.key }, 'PATCH') : await write<Book>('/books', { ...payload, request_key: command.current.key });
      onSaved(result); onClose();
    } catch (err) { setError(messageOf(err)); } finally { setBusy(false); }
  }
  return <Modal title={book ? `Cấu hình ${book.name} · phiên bản ${book.version}` : 'Tạo sổ độc lập'} open={open} onCancel={() => { if (!busy && window.confirm('Đóng cấu hình chưa lưu?')) onClose(); }} onOk={() => void save()} confirmLoading={busy} okText="Lưu cấu hình" width="95vw">
    {error && <Alert type="error" title={error} showIcon />}
    <p>ID cột ổn định dùng cho mapping và công thức. Backend kiểm tương thích với dữ liệu đã lưu. Đổi tên hiển thị không đổi ID.</p>
    <label>Tên sổ <Input aria-label="Tên sổ" value={name} disabled={!!book} onChange={event => setName(event.target.value)} /></label>
    <Table size="small" rowKey="id" pagination={false} scroll={{ x: 1400 }} dataSource={columns} columns={[
      { title: 'ID ổn định', render: (_, row) => <code>{row.id}</code> },
      { title: 'Tên hiển thị', render: (_, row, index) => <Input aria-label={`Tên cột ${index + 1}`} value={row.name} onChange={event => patch(index, { name: event.target.value })} /> },
      { title: 'Kiểu', render: (_, row, index) => <Select aria-label={`Kiểu cột ${index + 1}`} virtual={false} value={row.kind} style={{ width: 110 }} options={kinds.map(kind => ({ value: kind, label: kind }))} onChange={kind => patch(index, { kind, editable: kind !== 'formula' })} /> },
      { title: 'Bắt buộc', render: (_, row, index) => <Checkbox checked={row.required} onChange={event => patch(index, { required: event.target.checked })} /> },
      { title: 'Cho sửa', render: (_, row, index) => <Checkbox disabled={row.kind === 'formula'} checked={row.editable !== false && row.kind !== 'formula'} onChange={event => patch(index, { editable: event.target.checked })} /> },
      { title: 'Precision / scale', render: (_, row, index) => <Space><InputNumber aria-label="Precision" min={1} max={19} value={row.precision} onChange={value => patch(index, { precision: value ?? undefined })} /><InputNumber aria-label="Scale" min={0} max={9} disabled={row.kind === 'money' || row.kind === 'integer'} value={row.kind === 'money' ? 2 : row.kind === 'integer' ? 0 : row.scale} onChange={value => patch(index, { scale: value ?? undefined })} /></Space> },
      { title: 'Lựa chọn (mỗi dòng một mục) / công thức', render: (_, row, index) => row.kind === 'choice' ? <Input.TextArea value={row.choices?.join('\n')} onChange={event => patch(index, { choices: event.target.value.split('\n') })} /> : row.kind === 'formula' ? <Input value={row.formula} onChange={event => patch(index, { formula: event.target.value })} /> : null },
      { title: 'Quy tắc dữ liệu', render: (_, row, index) => <Space orientation="vertical"><Input aria-label={`Giới hạn nhỏ nhất cột ${index + 1}`} placeholder="Nhỏ nhất (số chính xác)" value={row.validation?.min ?? ''} onChange={event => patch(index, { validation: { ...row.validation, min: event.target.value || undefined } })} /><Input aria-label={`Giới hạn lớn nhất cột ${index + 1}`} placeholder="Lớn nhất (số chính xác)" value={row.validation?.max ?? ''} onChange={event => patch(index, { validation: { ...row.validation, max: event.target.value || undefined } })} /><InputNumber aria-label={`Độ dài tối đa cột ${index + 1}`} min={1} max={32767} placeholder="Độ dài tối đa" value={row.validation?.max_length} onChange={value => patch(index, { validation: { ...row.validation, max_length: value ?? undefined } })} /></Space> },
      { title: 'Cố định', render: (_, row, index) => <Checkbox checked={row.display?.frozen === true} onChange={event => patch(index, { display: { ...row.display, frozen: event.target.checked } })} /> },
      { title: '', render: (_, row, index) => <Space><Button disabled={index === 0} onClick={() => setColumns(old => { const next = [...old]; [next[index - 1], next[index]] = [next[index], next[index - 1]]; return next; })}>↑</Button><Button danger onClick={() => setColumns(old => old.filter(column => column.id !== row.id))}>Bỏ cột</Button></Space> },
    ]} />
    <Button className="toolbar" onClick={() => setColumns(old => [...old, { id: `c_${crypto.randomUUID().replaceAll('-', '').slice(0, 12)}`, name: `Cột ${old.length + 1}`, kind: 'text', editable: true, required: false }])}>Thêm cột</Button>
    <p>Ngữ nghĩa báo cáo. Để trống nếu chưa xác định; không tự cộng số thành tiền. Tiền VND scale 2.</p>
    <Space wrap>{[['date_column', 'Cột ngày'], ['income_column', 'Cột thu'], ['expense_column', 'Cột chi'], ['direction_column', 'Cột chiều'], ['amount_column', 'Cột số tiền'], ['currency_column', 'Cột đơn vị tiền']].map(([key, label]) => <label key={key}>{label}<Select allowClear aria-label={label} style={{ width: 180 }} value={typeof semanticsValue()[key] === 'string' ? semanticsValue()[key] as string : undefined} options={columns.map(column => ({ value: column.id, label: column.name }))} onChange={value => updateSemantic(key, value)} /></label>)}<label>Đơn vị tiền<Input value={typeof semanticsValue().currency === 'string' ? semanticsValue().currency as string : ''} placeholder="VND" onChange={event => updateSemantic('currency', event.target.value)} /></label></Space>
    <p>Ý nghĩa chỉ tiêu thu/chi cho báo cáo</p>
    <Space wrap>{(['income', 'expense'] as const).map(direction => { const label = `Ý nghĩa chỉ tiêu ${direction === 'income' ? 'thu' : 'chi'}`; return <label key={direction}>{label}<Select aria-label={label} allowClear virtual={false} placeholder="Chưa phân loại" style={{ width: 250 }} value={metricMeaning(direction)} options={metricMeaningOptions} onChange={value => updateMetricMeaning(direction, value)} /></label>; })}</Space>
    {(!metricMeaning('income') || !metricMeaning('expense')) && <Alert type="warning" showIcon title="Còn chiều chỉ tiêu chưa được phân loại." description="Chỉ chiều có ý nghĩa được bạn khai báo rõ mới được tổng hợp theo ý nghĩa dòng tiền trong báo cáo ngày. Bạn vẫn có thể ghi và sửa sổ. Ý nghĩa không được suy ra từ tên cột hoặc mã cột." />}
    <Space wrap>{[['duplicate_columns', 'Cột so trùng (cảnh báo)'], ['business_key_columns', 'Khóa nghiệp vụ đã xác định'], ['group_columns', 'Cột nhóm']].map(([key, label]) => <label key={key}>{label}<Select mode="multiple" style={{ minWidth: 230 }} aria-label={label} value={Array.isArray(semanticsValue()[key]) ? semanticsValue()[key] as string[] : []} options={columns.map(column => ({ value: column.id, label: column.name }))} onChange={value => updateSemantic(key, value)} /></label>)}</Space>
    <p>Cấu hình chi tiết JSON (ID cột ổn định). Với chiều + số tiền, nhập income_value / expense_value theo dữ liệu thật.</p>
    <Input.TextArea aria-label="Ngữ nghĩa sổ JSON" rows={7} value={semantics} onChange={event => setSemantics(event.target.value)} />
    <p><code>{'{"date_column":"ngay","income_column":"thu","expense_column":"chi","currency":"VND","duplicate_columns":[],"business_key_columns":[]}'}</code></p>
    <p>Công thức được backend kiểm và tính lại: SUM, AVERAGE, MIN, MAX, COUNT, IF, ROUND, SUMIF, COUNTIF. Lỗi / công thức không hỗ trợ hiện ở ô; không chạy macro hay liên kết ngoài.</p>
    <p>Công thức mẫu cho cột sổ đã lưu dùng tham chiếu cùng dòng <code>{'A{row}'}</code>, <code>{'B{row}'}</code>, ví dụ <code>{'=SUM(A{row}:B{row})'}</code>. Tham chiếu cố định hoặc chéo dòng trong mẫu cột sổ bị từ chối với mã <code>FORMULA_BOOK_SCOPE</code>. Công thức từ tệp nhập được xử lý trong phạm vi nguồn riêng.</p>
  </Modal>;
}
