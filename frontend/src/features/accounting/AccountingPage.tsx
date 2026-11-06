import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Alert, Button, Input, Modal, Pagination, Select, Space, Table, Tag, Typography } from 'antd';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { ApiError, messageOf } from '../../shared/api';
import { useSession } from '../../shared/session';
import { DateInput, isDateInputValueValid } from '../../shared/DateInput';
import type { Page } from '../../shared/types';
import { downloadFile, get, query, requestKey, write } from './client';
import { ImportWorkspace } from './ImportWorkspace';
import { SchemaEditor } from './SchemaEditor';
import { WorkbookGrid, useDraftGuard } from './WorkbookGrid';
import { ClipboardImportChoice } from './ClipboardImportChoice';
import { clipboardFile, type ClipboardImportSource } from './clipboard';
import type { Book, GridRecord, Issue, LedgerRow, Values } from './types';
import { vietnamBusinessToday } from './businessDate';
import { dateFilterError, isInclusiveDateRangeValid, newRowDateError } from './dateValidation';
import './accounting.css';

function readView() {
  const params = new URLSearchParams(location.hash.split('?')[1]);
  const parsedPage = Number.parseInt(params.get('page') ?? '1', 10);
  const booksPage = Number.parseInt(params.get('books_page') ?? '1', 10);
  return { bookId: params.get('book') ?? '', booksPage: Number.isSafeInteger(booksPage) && booksPage > 0 ? booksPage : 1, page: Number.isSafeInteger(parsedPage) && parsedPage > 0 ? parsedPage : 1, search: params.get('search') ?? '', sort: params.get('sort') ?? '', filters: params.get('filters') ?? '[]', deleted: params.get('deleted') === 'true' };
}
export function AccountingPage() {
  const session = useSession(); const cache = useQueryClient();
  const actor = `${session.generation}:${session.user?.id}`;
  const permission = (name: string) => session.user?.role === 'admin' || session.user?.permissions.includes('*') || session.user?.permissions.includes(name) || false;
  const canWrite = permission('accounting.write'); const canConfigure = permission('accounting.configure'); const canRestore = permission('accounting.restore');
  const [view, setView] = useState(readView); const [dirty, setDirty] = useState(false); const [busy, setBusy] = useState(false);
  const [error, setError] = useState(''); const [notice, setNotice] = useState(''); const [schemaOpen, setSchemaOpen] = useState(false); const [schemaBook, setSchemaBook] = useState<Book>();
  const [newRow, setNewRow] = useState<Values | null>(null); const newKey = useRef(requestKey());
  const [selected, setSelected] = useState<string>();
  const [conflict, setConflict] = useState<{ draft: GridRecord; original?: LedgerRow; current?: LedgerRow }>();
  const [exportJob, setExportJob] = useState<{ id: string; format: 'csv' | 'xlsx' }>();
  const [defaultPeriod] = useState(() => { const today = vietnamBusinessToday(); return { from: `${today.slice(0, 4)}-01-01`, through: today }; });
  const [from, setFrom] = useState(defaultPeriod.from); const [through, setThrough] = useState(defaultPeriod.through);
  const validPeriod = isInclusiveDateRangeValid(from, through);
  const [filterInput, setFilterInput] = useState(view.filters);
  const [validationIssues, setValidationIssues] = useState<Record<string, Issue[]>>({}); const [focusCell, setFocusCell] = useState<{ rowId: string; columnId?: string; request: number }>();
  const [filterColumn, setFilterColumn] = useState(''); const [filterOp, setFilterOp] = useState('eq'); const [filterValue, setFilterValue] = useState('');
  const [clipboardCandidate, setClipboardCandidate] = useState<File | null>(null); const [clipboardSource, setClipboardSource] = useState<ClipboardImportSource>();
  useDraftGuard(!!clipboardCandidate);
  const clipboardConsumed = useCallback(() => setClipboardSource(undefined), []);
  function filterConditions(): { column_id: string; op: string; value?: string }[] { try { const parsed = JSON.parse(filterInput); return Array.isArray(parsed) ? parsed : []; } catch { return []; } }
  const books = useQuery({ queryKey: ['accounting', actor, 'books', view.booksPage], gcTime: 0, retry: false, queryFn: ({ signal }) => get<Page<Book>>(`/books?page=${view.booksPage}&page_size=200`, signal) });
  const book = books.data?.items.find(item => item.id === view.bookId) ?? books.data?.items[0];
  const rowsFilterError = book ? dateFilterError(view.filters, book.columns) : undefined;
  const addFilterError = book && filterColumn ? dateFilterError(JSON.stringify([{ column_id: filterColumn, op: filterOp, ...(filterOp === 'empty' ? {} : { value: filterValue }) }]), book.columns) : undefined;
  const invalidDateFilterDraft = book?.columns.find(column => column.id === filterColumn)?.kind === 'date' && filterOp !== 'empty' && !!filterValue && !isDateInputValueValid(filterValue);
  const rowDateError = book && newRow ? newRowDateError(book.columns, newRow) : undefined;
  useEffect(() => { setClipboardCandidate(null); setClipboardSource(undefined); }, [actor, book?.id]);
  function largeClipboard(text: string, hasDraft: boolean) { if (!canWrite || busy) return; if (dirty || hasDraft) { setError('Lưu hoặc bỏ bản nháp hiện tại trước khi đưa clipboard lớn vào lượt nhập mới.'); return; } try { setClipboardCandidate(clipboardFile(text)); setError(''); } catch (err) { setError(messageOf(err)); } }
  const rowsQuery = useQuery({ queryKey: ['accounting', actor, 'rows', book?.id, book?.schema_revision, book?.data_revision, view.filters, view.search, view.sort, view.page, view.deleted], gcTime: 0, retry: false, enabled: !!book && !rowsFilterError, queryFn: ({ signal }) => { const problem = dateFilterError(view.filters, book?.columns ?? []); if (problem) throw new Error(problem); return get<Page<LedgerRow>>(`/books/${book?.id}/rows?${query({ page: view.page, page_size: 200, search: view.search, sort: view.sort, filters: view.filters, deleted: view.deleted ? 'true' : undefined })}`, signal); } });
  const summary = useQuery({ queryKey: ['accounting', actor, 'summary', book?.id, book?.schema_revision, book?.data_revision, from, through], gcTime: 0, retry: false, enabled: !!book && validPeriod, queryFn: ({ signal }) => { if (!isInclusiveDateRangeValid(from, through)) throw new Error('Chọn kỳ ngày hợp lệ trước khi xem tổng.'); return get<{ totals: Record<string, { income: string; expense: string }>; has_valid_money_mapping: boolean; validation_flags: unknown }>(`/books/${book?.id}/summary?${query({ from_on: from, through_on: through })}`, signal); } });
  const exportStatus = useQuery({ queryKey: ['accounting', actor, 'export', exportJob?.id], gcTime: 0, retry: false, enabled: !!exportJob, queryFn: ({ signal }) => get<{ state: string; file_id?: string; error_code?: string }>(`/exports/${exportJob?.id}`, signal), refetchInterval: query => ['COMPLETED', 'FAILED', 'CANCELLED'].includes(query.state.data?.state ?? '') ? false : 1500 });
  const gridRows = useMemo<GridRecord[]>(() => rowsQuery.data?.items.map(row => ({ id: row.id, version: row.version, label: `${row.logical_row} · v${row.version}`, values: row.values, issues: row.issues ?? [], locked: !!row.deleted_at })) ?? [], [rowsQuery.data]);
  useEffect(() => { const update = () => { const next = readView(); setView(next); setFilterInput(next.filters); }; addEventListener('hashchange', update); return () => removeEventListener('hashchange', update); }, []);
  useEffect(() => useSession.subscribe((current, previous) => { if (current.generation === previous.generation) return; const oldKey = ['accounting', `${previous.generation}:${previous.user?.id}`]; void cache.cancelQueries({ queryKey: oldKey }); cache.removeQueries({ queryKey: oldKey }); }), [cache]);
  useEffect(() => { setDirty(false); setNewRow(null); setConflict(undefined); setExportJob(undefined); setSelected(undefined); setSchemaOpen(false); setSchemaBook(undefined); setValidationIssues({}); setFocusCell(undefined); setError(''); setNotice(''); }, [actor]);
  const onDirty = useCallback((value: boolean) => setDirty(value), []);
  function navigate(patch: Partial<typeof view>) {
    if (dirty) return;
    if (patch.filters !== undefined && book) { const problem = dateFilterError(patch.filters, book.columns); if (problem) { setError(problem); return; } }
    const next = { ...view, bookId: book?.id ?? '', ...patch };
    location.hash = `/accounting?${query({ book: next.bookId, books_page: next.booksPage, page: next.page, search: next.search, sort: next.sort, filters: next.filters, deleted: next.deleted ? 'true' : undefined })}`;
  }
  async function refresh() { await books.refetch(); await Promise.all([...(book && !rowsFilterError ? [rowsQuery.refetch()] : []), ...(book && validPeriod ? [summary.refetch()] : [])]); }
  async function saveRows(changed: GridRecord[]) {
    setBusy(true); setError(''); const savedRows: GridRecord[] = []; const failures: string[] = [];
    try {
      for (const row of changed) {
        if (useSession.getState().generation !== session.generation) return [];
        try { const values = Object.fromEntries(Object.entries(row.values).filter(([id]) => book?.columns.some(column => column.id === id && column.editable !== false && column.kind !== 'formula'))); const result = await write<LedgerRow>(`/rows/${row.id}`, { expected_version: row.version, values, request_key: requestKey() }, 'PATCH'); savedRows.push({ id: result.id, version: result.version, label: `${result.logical_row} · v${result.version}`, values: result.values, issues: result.issues ?? [], locked: !!result.deleted_at }); setValidationIssues(old => ({ ...old, [row.id]: [] })); }
        catch (err) {
          if (useSession.getState().generation !== session.generation) return [];
          const issues = (err as { details?: { issues?: Issue[] } }).details?.issues;
          if (issues) setValidationIssues(old => ({ ...old, [row.id]: issues }));
          failures.push(`${row.label}: ${messageOf(err)}${issues ? `\n${issues.map(issue => `${issue.column_id ?? ''} ${issue.code ?? ''}: ${issue.message ?? ''}`).join('\n')}` : ''}`);
          if (err instanceof ApiError && /CONFLICT|VERSION/i.test(err.code)) {
            let current: LedgerRow | undefined;
            try { current = await get<LedgerRow>(`/rows/${row.id}`); } catch { /* keep draft visible if disconnected */ }
            setConflict({ draft: row, original: rowsQuery.data?.items.find(item => item.id === row.id), current });
          }
        }
      }
      if (failures.length) { setError(`${savedRows.length} dòng đã được backend xác nhận; ${failures.length} dòng chưa lưu.\n${failures.join('\n')}\nChỉ bản nháp chưa lưu được giữ. Tải lại sau khi sao chép giá trị cần giữ; không ghi đè phiên bản mới.`); return savedRows; }
      setDirty(false); setNotice(`Đã xác nhận lưu ${savedRows.length} dòng.`); await refresh(); return savedRows;
    } finally { setBusy(false); }
  }
  async function createRow() {
    if (!newRow || !book) return; setBusy(true); setError('');
    const dateError = newRowDateError(book.columns, newRow); if (dateError) { setError(dateError); setBusy(false); return; }
    try { await write<LedgerRow>(`/books/${book.id}/rows`, { values: newRow, request_key: newKey.current }); setNewRow(null); setNotice('Backend đã xác nhận thêm dòng.'); await refresh(); } catch (err) { setError(messageOf(err)); } finally { setBusy(false); }
  }
  async function changeDeletion(restore: boolean) {
    const row = rowsQuery.data?.items.find(item => item.id === selected);
    if (!row || !window.confirm(`${restore ? 'Khôi phục' : 'Xóa mềm'} dòng ${row.logical_row}? Thao tác lưu lịch sử và kiểm phiên bản ${row.version}.`)) return;
    setBusy(true); setError('');
    try { await write(`/rows/${row.id}/${restore ? 'restore' : 'delete'}`, { expected_version: row.version, request_key: requestKey() }); setNotice('Backend đã xác nhận thao tác.'); await refresh(); } catch (err) { setError(messageOf(err)); } finally { setBusy(false); }
  }
  async function startExport(format: 'csv' | 'xlsx') {
    if (!book) return; setBusy(true); setError('');
    try { const result = await write<{ job_id: string }>(`/books/${book.id}/exports`, { format, request_key: requestKey() }); setExportJob({ id: result.job_id, format }); } catch (err) { setError(messageOf(err)); } finally { setBusy(false); }
  }
  const activeRow = rowsQuery.data?.items.find(row => row.id === selected);
  return <section aria-label="Kế toán độc lập">
    <Typography.Title level={2}>Sổ kế toán</Typography.Title>
    <Typography.Paragraph>Ghi chép độc lập; liên kết CRM là tùy chọn. Số tiền và mã được giữ dạng chuỗi chính xác. Tổng chỉ phản ánh dữ liệu đã nhập và có mapping phù hợp.</Typography.Paragraph>
    <Space wrap className="toolbar"><Select aria-label="Chọn sổ" style={{ minWidth: 260 }} value={book?.id} disabled={dirty || busy} placeholder="Chưa có sổ" options={books.data?.items.map(item => ({ value: item.id, label: item.name }))} onChange={bookId => { setSelected(undefined); navigate({ bookId, page: 1 }); }} /><Button disabled={!canConfigure || dirty} onClick={() => { setSchemaBook(undefined); setSchemaOpen(true); }}>Tạo sổ</Button><Button disabled={!canConfigure || !book || dirty} onClick={() => { setSchemaBook(book); setSchemaOpen(true); }}>Cấu hình cột / ngữ nghĩa</Button><Button disabled={dirty || busy} onClick={() => void refresh()}>Tải lại dữ liệu</Button></Space>
    {(books.data?.total ?? 0) > 200 && <Pagination aria-label="Trang danh sách sổ" current={view.booksPage} pageSize={200} total={books.data?.total} showSizeChanger={false} disabled={dirty || busy} onChange={booksPage => navigate({ booksPage, bookId: '', page: 1 })} showTotal={total => `${total} sổ · mỗi trang chọn tối đa 200 sổ`} />}
    {(error || rowsFilterError || books.error || rowsQuery.error) && <Alert className="toolbar" type="error" title={<span style={{ whiteSpace: 'pre-wrap' }}>{error || rowsFilterError || messageOf(books.error || rowsQuery.error)}</span>} showIcon />}
    {notice && <Alert type="success" title={notice} closable onClose={() => setNotice('')} />}
    {book && <>
      <ClipboardImportChoice file={clipboardCandidate} disabled={dirty || busy || !canWrite} onDiscard={() => setClipboardCandidate(null)} onAccept={() => { if (!clipboardCandidate || dirty || busy) return; setClipboardSource({ id: requestKey(), file: clipboardCandidate, actor, book_id: book.id }); setClipboardCandidate(null); }} />
      <Space wrap className="toolbar"><Tag>Schema {book.schema_revision} · dữ liệu {book.data_revision}</Tag><ImportWorkspace book={book} canWrite={canWrite} disabled={dirty || busy} range={{ from, through }} clipboardSource={clipboardSource} onClipboardConsumed={clipboardConsumed} onPublished={() => void refresh()} /><Button disabled={!canWrite || dirty || busy} onClick={() => { newKey.current = requestKey(); setNewRow(Object.fromEntries(book.columns.filter(column => column.kind !== 'formula').map(column => [column.id, null]))); }}>Thêm dòng</Button><Button danger disabled={!canWrite || dirty || busy || !activeRow || !!activeRow.deleted_at} onClick={() => void changeDeletion(false)}>Xóa dòng chọn</Button><Button disabled={!canRestore || dirty || busy || !activeRow?.deleted_at} onClick={() => void changeDeletion(true)}>Khôi phục dòng chọn</Button><Button disabled={!canWrite || dirty || busy} onClick={() => void startExport('csv')}>Xuất CSV</Button><Button disabled={!canWrite || dirty || busy} onClick={() => void startExport('xlsx')}>Xuất XLSX</Button></Space>
      {exportJob && <Alert type={exportStatus.data?.state === 'FAILED' ? 'error' : 'info'} title={`Xuất dữ liệu dẫn xuất: ${exportStatus.data?.state ?? 'Đang kiểm tra'} ${exportStatus.data?.error_code ?? ''}`} description={exportStatus.error ? messageOf(exportStatus.error) : 'Tệp xuất riêng; không thay tệp gốc và không bảo toàn mọi macro / style / Pivot.'} action={exportStatus.data?.file_id ? <Button onClick={() => void downloadFile(exportStatus.data!.file_id!, `so-dan-xuat.${exportJob.format}`).catch(err => setError(messageOf(err)))}>Tải tệp dẫn xuất</Button> : undefined} />}
      <Space wrap className="toolbar"><Input.Search aria-label="Tìm trong sổ" placeholder="Tìm toàn sổ" defaultValue={view.search} disabled={dirty} onSearch={search => navigate({ search, page: 1 })} /><Select aria-label="Sắp xếp sổ" style={{ minWidth: 220 }} value={view.sort} disabled={dirty} options={[{ value: '', label: 'Thứ tự dòng' }, ...book.columns.flatMap(column => [{ value: `${column.id}:asc`, label: `${column.name} ↑` }, { value: `${column.id}:desc`, label: `${column.name} ↓` }])]} onChange={sort => navigate({ sort, page: 1 })} /></Space>
      <details><summary>Lọc toàn bộ sổ / xem dòng đã xóa</summary>
        <p>Các điều kiện kết hợp đồng thời và áp dụng trên toàn sổ.</p>
        <Space wrap><Select aria-label="Cột lọc" placeholder="Chọn cột" style={{ width: 180 }} disabled={dirty} value={filterColumn || undefined} options={book.columns.map(column => ({ value: column.id, label: column.name }))} onChange={setFilterColumn} /><Select aria-label="Điều kiện lọc" style={{ width: 160 }} disabled={dirty} value={filterOp} options={[['eq', 'Bằng'], ['contains', 'Chứa nội dung'], ['gte', 'Lớn hơn hoặc bằng'], ['lte', 'Nhỏ hơn hoặc bằng'], ['empty', 'Ô trống']].map(([value, label]) => ({ value, label }))} onChange={setFilterOp} />{book.columns.find(column => column.id === filterColumn)?.kind === 'date' ? <DateInput aria-label="Giá trị lọc" disabled={dirty || filterOp === 'empty'} value={filterValue} onChange={setFilterValue} /> : <Input aria-label="Giá trị lọc" disabled={dirty || filterOp === 'empty'} value={filterValue} onChange={event => setFilterValue(event.target.value)} />}<Button disabled={dirty || !filterColumn || !!addFilterError || filterConditions().length >= 20} onClick={() => { if (addFilterError) { setError(addFilterError); return; } setFilterInput(JSON.stringify([...filterConditions(), { column_id: filterColumn, op: filterOp, ...(filterOp === 'empty' ? {} : { value: filterValue }) }])); }}>Thêm điều kiện</Button></Space>
        {addFilterError && <Typography.Paragraph type="danger">{addFilterError}</Typography.Paragraph>}
        <div className="toolbar">{filterConditions().map((condition, index) => <Tag key={index} closable={!dirty} onClose={() => setFilterInput(JSON.stringify(filterConditions().filter((_, i) => i !== index)))}>{book.columns.find(column => column.id === condition.column_id)?.name ?? condition.column_id} · {({ eq: 'bằng', contains: 'chứa', gte: '≥', lte: '≤', empty: 'trống' } as Record<string, string>)[condition.op] ?? condition.op} {condition.value ?? ''}</Tag>)}</div>
        <Space><Button disabled={dirty || invalidDateFilterDraft} onClick={() => { if (invalidDateFilterDraft) { setError(addFilterError ?? 'Ngày lọc chưa hợp lệ.'); return; } try { const parsed: unknown = JSON.parse(filterInput); if (!Array.isArray(parsed)) throw new Error(); navigate({ filters: filterInput, page: 1 }); } catch { setError('Bộ lọc phải là mảng JSON hợp lệ.'); } }}>Áp dụng bộ lọc</Button><Button disabled={dirty} onClick={() => { setFilterInput('[]'); navigate({ filters: '[]', page: 1 }); }}>Bỏ bộ lọc</Button><Button disabled={dirty || !canRestore} onClick={() => navigate({ deleted: !view.deleted, page: 1 })}>{view.deleted ? 'Ẩn dòng đã xóa' : 'Hiện cả dòng đã xóa để khôi phục'}</Button></Space>
        <details><summary>Nâng cao: JSON bộ lọc</summary><Input.TextArea aria-label="Bộ lọc sổ JSON" rows={3} value={filterInput} disabled={dirty} onChange={event => setFilterInput(event.target.value)} /></details>
      </details>
      <WorkbookGrid scope={`${actor}:${book.id}:${book.schema_revision}:${view.page}:${view.filters}:${view.search}:${view.sort}:${view.deleted}`} columns={book.columns} source={gridRows} canWrite={canWrite} busy={busy} onDirty={onDirty} onSave={saveRows} onSelect={setSelected} validationIssues={validationIssues} focusCell={focusCell} onLargeClipboard={largeClipboard} />
      <Pagination current={view.page} pageSize={200} total={rowsQuery.data?.total ?? 0} disabled={dirty || busy || rowsQuery.isFetching} showSizeChanger={false} showQuickJumper onChange={page => navigate({ page })} showTotal={total => `${total} dòng theo bộ lọc · ${gridRows.length} dòng đang tải`} />
      <details><summary>Lỗi trên trang · {rowsQuery.data?.items.reduce((total, row) => total + (validationIssues[row.id] ?? row.issues ?? []).length, 0) ?? 0}</summary><Table size="small" pagination={false} rowKey={issue => `${issue.row.id}:${issue.column_id}:${issue.code}`} dataSource={rowsQuery.data?.items.flatMap(row => (validationIssues[row.id] ?? row.issues ?? []).map(issue => ({ ...issue, row })))} columns={[{ title: 'Dòng / cột', render: (_, issue) => <Button type="link" onClick={() => { setSelected(issue.row.id); setFocusCell({ rowId: issue.row.id, columnId: issue.column_id, request: Date.now() }); }}>{issue.row.logical_row} / {issue.column_id ?? issue.cell}</Button> }, { title: 'Lỗi', render: (_, issue) => `${issue.code}: ${issue.message}` }, { title: 'Gợi ý', dataIndex: 'suggestion' }]} /></details>
      <details><summary>Tổng thu / chi theo đơn vị tiền</summary><p>Ngày nghiệp vụ theo Asia/Ho_Chi_Minh. Tính cả ngày đầu và ngày cuối; có thể chọn cùng một ngày. Nhập DD/MM/YYYY.</p><Space wrap><label>Từ ngày (bao gồm) <DateInput aria-label="Từ ngày (bao gồm)" value={from} onChange={setFrom} /></label><label>Đến hết ngày (bao gồm) <DateInput aria-label="Đến hết ngày (bao gồm)" value={through} onChange={setThrough} /></label></Space>{!validPeriod ? <Alert type="warning" title="Chọn đủ hai ngày hợp lệ DD/MM/YYYY; ngày bắt đầu không được sau ngày kết thúc." /> : summary.error ? <Alert type="error" title={messageOf(summary.error)} /> : summary.data?.has_valid_money_mapping ? Object.entries(summary.data.totals).map(([currency, values]) => <p key={currency}>{currency}: thu {values.income} · chi {values.expense}</p>) : <Alert type="warning" title="Chưa có ngữ nghĩa tiền hợp lệ. Cấu hình cột ngày, thu/chi hoặc chiều + số tiền và đơn vị tiền." />}{validPeriod && <pre>{JSON.stringify(summary.data?.validation_flags, null, 2)}</pre>}</details>
    </>}
    <SchemaEditor open={schemaOpen} book={schemaBook} onClose={() => setSchemaOpen(false)} onSaved={result => { cache.setQueryData<Page<Book>>(['accounting', actor, 'books', view.booksPage], old => ({ items: [...(old?.items.filter(item => item.id !== result.id) ?? []), result], total: old?.items.some(item => item.id === result.id) ? old.total : (old?.total ?? 0) + 1, page: view.booksPage, page_size: 200 })); navigate({ bookId: result.id, page: 1 }); }} />
    <Modal title="Thêm dòng vào sổ" open={!!newRow} onCancel={() => { if (!busy) setNewRow(null); }} onOk={() => void createRow()} confirmLoading={busy} okButtonProps={{ disabled: !!rowDateError }} okText="Xác nhận thêm dòng">
      {rowDateError && <Alert type="error" title={rowDateError} showIcon />}
      {book?.columns.filter(column => column.kind !== 'formula').map(column => <label className="accounting-new-field" key={column.id}>{column.name}{column.required ? ' *' : ''} · {column.kind}{column.kind === 'choice' ? <Select allowClear value={newRow?.[column.id] ?? undefined} options={column.choices?.map(value => ({ value, label: value }))} onChange={value => setNewRow(old => ({ ...old, [column.id]: value ?? null }))} /> : column.kind === 'date' ? <DateInput aria-label={`Dòng mới ${column.name}`} value={newRow?.[column.id] ?? ''} onChange={value => setNewRow(old => ({ ...old, [column.id]: value }))} /> : <Input aria-label={`Dòng mới ${column.name}`} value={newRow?.[column.id] ?? ''} onChange={event => setNewRow(old => ({ ...old, [column.id]: event.target.value || null }))} />}</label>)}
      <p>Backend kiểm dữ liệu. Trống khác với số 0; không chuyển tiền qua số dấu phẩy động.</p>
    </Modal>
    <Modal title="Xung đột phiên bản · bản nháp được giữ" open={!!conflict} onCancel={() => setConflict(undefined)} footer={<Button onClick={() => setConflict(undefined)}>Quay lại bản nháp để sao chép / xử lý</Button>} width={1000}>
      <p>Dữ liệu đã thay đổi sau khi tải. Không tự ghi đè. Sao chép phần cần giữ, bỏ nháp rồi tải lại để sửa trên phiên bản mới.</p>
      <Table rowKey="label" pagination={false} dataSource={[{ label: 'Lúc tải', values: conflict?.original?.values }, { label: 'Bản nháp của bạn', values: conflict?.draft.values }, { label: 'Hiện tại từ server (nếu còn trong trang)', values: conflict?.current?.values }]} columns={[{ title: 'Phiên bản', dataIndex: 'label' }, { title: 'Giá trị', render: (_, item) => <pre>{JSON.stringify(item.values ?? 'Chưa tải được; kiểm tra lại khi kết nối.', null, 2)}</pre> }]} />
    </Modal>
  </section>;
}
