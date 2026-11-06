import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Alert, Button, Checkbox, Input, InputNumber, Modal, Pagination, Select, Space, Table, Tag, Typography } from 'antd';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api, messageOf, uploadOriginal } from '../../shared/api';
import { useSession } from '../../shared/session';
import type { FileDTO, Page } from '../../shared/types';
import { downloadFile, get, query, requestKey, write } from './client';
import { WorkbookGrid, useDraftGuard } from './WorkbookGrid';
import { ClipboardImportChoice } from './ClipboardImportChoice';
import { clipboardFile, clipboardProfile, type ClipboardImportSource } from './clipboard';
import { encodeTSV } from './drafts';
import type { Batch, Book, GridRecord, Issue, StageRow } from './types';

const defaultProfile = { sheet_id: '1', header_row: 1, encoding: 'utf-8-sig', delimiter: ',', date_format: '%d/%m/%Y', decimal_separator: '.', thousands_separator: '', skip_blank: true, hidden_rows: 'include', merged_cells: 'reject' };
interface SourceManifest { sheets?: { id: string; name: string; columns?: string[] }[] }
type BatchDetail = Batch & { source_manifest?: SourceManifest };
interface MappingProfile { id: string; name: string; version: number; schema_revision: number; mapping: Record<string, string>; profile: Record<string, unknown> }
interface DuplicateReview { row_id: string; source_row: number; matches?: unknown; file_matches?: unknown; duplicate_count: number }
export function ImportWorkspace({ book, canWrite, disabled, onPublished, range, clipboardSource, onClipboardConsumed }: { book: Book; canWrite: boolean; disabled?: boolean; onPublished: () => void; range: { from: string; through: string }; clipboardSource?: ClipboardImportSource; onClipboardConsumed?: () => void }) {
  const actor = useSession(state => `${state.generation}:${state.user?.id}`);
  const cache = useQueryClient(); const [open, setOpen] = useState(false); const [selected, setSelected] = useState<string>();
  const [page, setPage] = useState(1); const [status, setStatus] = useState(''); const [search, setSearch] = useState('');
  const [dirty, setDirty] = useState(false); const [busy, setBusy] = useState(false); const [error, setError] = useState('');
  const [profile, setProfile] = useState(JSON.stringify(defaultProfile, null, 2)); const [mapping, setMapping] = useState<Record<string, string>>({});
  const [review, setReview] = useState<'issues' | 'duplicates' | null>(null); const [reviewPage, setReviewPage] = useState(1);
  const [allowDuplicate, setAllowDuplicate] = useState(false); const [file, setFile] = useState<File>();
  const [jobsPage, setJobsPage] = useState(1); const [sourceId, setSourceId] = useState<string>();
  const [profileName, setProfileName] = useState('');
  const [errorExport, setErrorExport] = useState<string>();
  const [clipboardCandidate, setClipboardCandidate] = useState<File | null>(null); const [isClipboardFile, setIsClipboardFile] = useState(false);
  useDraftGuard(!!clipboardCandidate || (isClipboardFile && !!file));
  const uploadKey = useRef(requestKey()); const creationKey = useRef(requestKey()); const originalId = useRef<string | undefined>(undefined);
  const pendingMapping = useRef<Record<string, string> | undefined>(undefined);
  const published = useRef<{ id: string; count: number } | undefined>(undefined);
  const publishedCallback = useRef(onPublished); publishedCallback.current = onPublished;
  const jobs = useQuery({ queryKey: ['accounting', actor, 'imports', book.id, book.schema_revision, book.data_revision, jobsPage], gcTime: 0, retry: false, queryFn: ({ signal }) => get<Page<Batch>>(`/import-jobs?${query({ book_id: book.id, page: jobsPage, page_size: 50 })}`, signal), refetchInterval: open ? 3000 : false });
  const profiles = useQuery({ queryKey: ['accounting', actor, 'mapping-profiles', book.id, book.schema_revision], gcTime: 0, retry: false, enabled: open, queryFn: ({ signal }) => get<{ items: MappingProfile[] }>(`/books/${book.id}/mapping-profiles`, signal) });
  const batchKey = ['accounting', actor, 'batch', book.id, book.schema_revision, book.data_revision, selected];
  const detail = useQuery({ queryKey: batchKey, gcTime: 0, retry: false, enabled: !!selected && open, queryFn: ({ signal }) => get<BatchDetail>(`/import-jobs/${selected}`, signal), refetchInterval: dirty ? false : 2000 });
  const batch = detail.data;
  const original = useQuery({ queryKey: ['accounting', actor, 'original', book.id, batch?.file_id], gcTime: 0, retry: false, enabled: open && !!batch?.file_id, queryFn: ({ signal }) => api<FileDTO>(`/files/${batch?.file_id}`, { signal }) });
  const running = !!batch && ['UPLOADED', 'PARSING', 'VALIDATING', 'COMMITTING'].includes(batch.state);
  const stages = useQuery({ queryKey: ['accounting', actor, 'stage', book.id, book.schema_revision, book.data_revision, selected, batch?.revision, batch?.mapping_revision, batch?.decision_revision, page, status, search], gcTime: 0, retry: false, enabled: open && !!batch && !running, queryFn: ({ signal }) => get<Page<StageRow>>(`/import-jobs/${selected}/staging?${query({ page, page_size: 200, status, search })}`, signal) });
  const reviewData = useQuery({ queryKey: ['accounting', actor, 'review', book.id, book.schema_revision, book.data_revision, selected, batch?.revision, batch?.mapping_revision, batch?.decision_revision, review, reviewPage], gcTime: 0, retry: false, enabled: !!review && !!selected, queryFn: ({ signal }) => get<Page<Issue | DuplicateReview>>(`/import-jobs/${selected}/${review}?${query({ page: reviewPage, page_size: 100 })}`, signal) });
  const errorExportStatus = useQuery({ queryKey: ['accounting', actor, 'error-export', errorExport], gcTime: 0, retry: false, enabled: !!errorExport, queryFn: ({ signal }) => get<{ state: string; file_id?: string; error_code?: string }>(`/exports/${errorExport}`, signal), refetchInterval: query => ['COMPLETED', 'FAILED', 'CANCELLED'].includes(query.state.data?.state ?? '') ? false : 1500 });
  type Totals = Record<string, { income: string; expense: string }>;
  const comparison = useQuery({ queryKey: ['accounting', actor, 'batch-summary', book.id, book.schema_revision, book.data_revision, selected, batch?.revision, batch?.mapping_revision, batch?.decision_revision, range.from, range.through], gcTime: 0, retry: false, enabled: open && !!batch?.validation_token && !running && !!range.from && !!range.through && range.from <= range.through, queryFn: ({ signal }) => get<{ before: { totals: Totals; has_valid_money_mapping: boolean }; new_batch: Totals; after: Totals; provisional: boolean }>(`/import-jobs/${selected}/summary?${query({ from_on: range.from, through_on: range.through })}`, signal) });
  useEffect(() => { setSelected(undefined); setOpen(false); setDirty(false); setError(''); setReview(null); setFile(undefined); setClipboardCandidate(null); setIsClipboardFile(false); setMapping({}); setProfile(JSON.stringify(defaultProfile, null, 2)); setSearch(''); setStatus(''); setJobsPage(1); setPage(1); setSourceId(undefined); setErrorExport(undefined); pendingMapping.current = undefined; published.current = undefined; originalId.current = undefined; uploadKey.current = requestKey(); creationKey.current = requestKey(); }, [actor, book.id]);
  function startClipboard(file: File) { setSelected(undefined); setPage(1); setStatus(''); setSearch(''); setSourceId(undefined); setReview(null); setClipboardCandidate(null); setFile(file); setIsClipboardFile(true); setProfile(JSON.stringify(clipboardProfile, null, 2)); setMapping({}); setAllowDuplicate(false); pendingMapping.current = undefined; originalId.current = undefined; uploadKey.current = requestKey(); creationKey.current = requestKey(); setError(''); setOpen(true); }
  useEffect(() => { if (!clipboardSource || clipboardSource.actor !== actor || clipboardSource.book_id !== book.id) return; if (dirty || busy || disabled) setError('Lưu hoặc bỏ bản nháp trước khi tạo lượt nhập mới từ clipboard.'); else startClipboard(clipboardSource.file); onClipboardConsumed?.(); }, [clipboardSource?.id]);
  function largeClipboard(text: string, hasDraft: boolean) { if (!canWrite || busy) return; if (dirty || hasDraft) { setError('Lưu hoặc bỏ bản nháp staging hiện tại trước khi đưa clipboard lớn vào lượt nhập mới.'); return; } try { setClipboardCandidate(clipboardFile(text)); setError(''); } catch (err) { setError(messageOf(err)); } }
  function discardClipboard() { if (isClipboardFile) { setProfile(JSON.stringify(defaultProfile, null, 2)); setMapping({}); } setFile(undefined); setIsClipboardFile(false); setClipboardCandidate(null); originalId.current = undefined; pendingMapping.current = undefined; uploadKey.current = requestKey(); creationKey.current = requestKey(); }
  useEffect(() => { if (batch) { setMapping(Object.keys(batch.mapping).length ? batch.mapping : pendingMapping.current ?? batch.mapping); pendingMapping.current = undefined; setProfile(JSON.stringify(batch.profile, null, 2)); } }, [batch?.id, batch?.mapping_revision]);
  useEffect(() => { if (!batch) return; const count = batch.counts.published_rows ?? 0; if (published.current?.id === batch.id && count > published.current.count) publishedCallback.current(); published.current = { id: batch.id, count }; }, [batch?.id, batch?.counts.published_rows]);
  const mapRows = (items: StageRow[]): GridRecord[] => items.map(row => ({ id: row.row_id, version: row.revision, label: `${row.source_sheet}!${row.source_row}`, values: Object.fromEntries(book.columns.map(column => [column.id, Object.hasOwn(row.edited_values ?? {}, column.id) ? row.edited_values[column.id] : row.typed_values?.[column.id] ?? row.raw_values?.[batch?.mapping[column.id] ?? ''] ?? null])), issues: row.issues ?? [], locked: row.imported }));
  const rows = useMemo<GridRecord[]>(() => mapRows(stages.data?.items ?? []), [stages.data, book.columns, batch?.mapping_revision]);
  const onDirty = useCallback((value: boolean) => setDirty(value), []);
  function profileValue(): Record<string, unknown> { try { const parsed = JSON.parse(profile); return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : {}; } catch { return {}; } }
  function patchProfile(key: string, value: unknown) { setProfile(JSON.stringify({ ...profileValue(), [key]: value }, null, 2)); creationKey.current = requestKey(); }
  async function saveProfile() { setBusy(true); setError(''); try { const parsed = JSON.parse(profile); await write(`/books/${book.id}/mapping-profiles`, { name: profileName, profile: parsed, mapping, request_key: requestKey() }); await profiles.refetch(); setProfileName(''); } catch (err) { setError(messageOf(err)); } finally { setBusy(false); } }
  async function exportErrors() { if (!batch) return; setBusy(true); setError(''); try { const result = await write<{ job_id: string }>(`/import-jobs/${batch.id}/exports`, { format: 'csv', request_key: requestKey() }); setErrorExport(result.job_id); } catch (err) { setError(messageOf(err)); } finally { setBusy(false); } }
  const selectedSource = stages.data?.items.find(row => row.row_id === sourceId);
  function downloadIssuePage() {
    const issues = (reviewData.data?.items ?? []) as Issue[];
    const text = encodeTSV([['sheet', 'source_row', 'cell', 'code', 'message', 'suggestion', 'raw_value'], ...issues.map(issue => [issue.source_sheet ?? '', String(issue.source_row ?? ''), issue.cell ?? '', issue.code, issue.message, issue.suggestion ?? '', issue.raw_value ?? ''])]);
    const url = URL.createObjectURL(new Blob(['\uFEFF', text], { type: 'text/tab-separated-values;charset=utf-8' })); const link = document.createElement('a'); link.href = url; link.download = `loi-${selected}-trang-${reviewPage}.tsv`; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  async function refresh() { await Promise.all([detail.refetch(), jobs.refetch()]); await cache.invalidateQueries({ queryKey: ['accounting', actor, 'stage'] }); }
  async function action(path: string, body: object = {}) {
    if (!batch || dirty) return;
    setBusy(true); setError('');
    try { const result = await write<Batch>(`/import-jobs/${batch.id}/${path}`, { ...body, request_key: requestKey() }); cache.setQueryData(batchKey, result); await refresh(); if (path === 'confirm') onPublished(); }
    catch (err) { setError(messageOf(err)); } finally { setBusy(false); }
  }
  async function upload() {
    if (!file) return;
    setBusy(true); setError('');
    try {
      const parsed: unknown = JSON.parse(profile);
      if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) throw new Error('Profile phải là một object JSON.');
      const id = originalId.current ?? (await uploadOriginal(file, 'workbooks', uploadKey.current)).id; originalId.current = id;
      const created = await write<Batch>('/import-jobs', { book_id: book.id, file_id: id, profile: parsed, allow_duplicate_file: allowDuplicate, request_key: creationKey.current });
      setSelected(created.id); setPage(1); setFile(undefined); setIsClipboardFile(false); originalId.current = undefined; uploadKey.current = requestKey(); creationKey.current = requestKey(); await jobs.refetch();
    } catch (err) { setError(messageOf(err)); } finally { setBusy(false); }
  }
  async function saveStaging(changed: GridRecord[]) {
    if (!batch) return;
    setBusy(true); setError('');
    try {
      const result = await write<Batch>(`/import-jobs/${batch.id}/patches`, { expected_version: batch.version, patches: changed.map(row => ({ row_id: row.id, expected_version: row.version, values: Object.fromEntries(Object.entries(row.values).filter(([id, value]) => book.columns.some(column => column.id === id && column.editable !== false && column.kind !== 'formula') && value !== rows.find(original => original.id === row.id)?.values[id])) })), request_key: requestKey() });
      cache.setQueryData(batchKey, result); setDirty(false); await refresh(); const updated = await stages.refetch(); return mapRows(updated.data?.items ?? []);
    } catch (err) { setError(messageOf(err)); throw err; } finally { setBusy(false); }
  }
  function close() { if (busy) return; if (dirty && !window.confirm('Bỏ bản nháp chưa lưu trên trang staging? Các patch đã lưu và job vẫn được giữ.')) return; if ((clipboardCandidate || (isClipboardFile && file)) && !window.confirm('Bỏ tệp clipboard chưa gửi và đóng? Job và patch đã lưu vẫn được giữ.')) return; discardClipboard(); setDirty(false); setOpen(false); }
  function choose(id: string) { if (dirty && !window.confirm('Bỏ bản nháp trang hiện tại và mở job khác?')) return; if ((clipboardCandidate || (isClipboardFile && file)) && !window.confirm('Bỏ tệp clipboard chưa gửi và mở job đã lưu?')) return; discardClipboard(); setDirty(false); setSelected(id); setPage(1); setError(''); }
  function confirmImport() {
    if (!batch?.validation_token) return;
    const c = batch.counts;
    if (!window.confirm(`Xác nhận nhập phần hợp lệ đã được backend validate?\nNguồn: ${c.source_rows ?? 0}; hợp lệ: ${c.valid ?? 0}; lỗi: ${c.invalid ?? 0}; nghi trùng: ${c.potential_duplicates ?? 0}; loại: ${c.excluded ?? 0}; đã công bố: ${c.published_rows ?? 0}.\nDòng lỗi / chưa quyết định được giữ lại. Chỉ công bố khi hoàn thành toàn bộ tập xác nhận.`)) return;
    void action('confirm', { expected_version: batch.version, staging_revision: batch.revision, mapping_revision: batch.mapping_revision, decision_revision: batch.decision_revision, validation_token: batch.validation_token, mode: 'valid_rows_only' });
  }
  const download = (id: string, filename: string) => void downloadFile(id, filename).catch(err => setError(messageOf(err)));
  return <>
    <Button disabled={disabled} onClick={() => setOpen(true)}>Nhập Excel / CSV · mở job đã lưu</Button>
    <Modal title={`Nhập dữ liệu · ${book.name}`} open={open} onCancel={close} closable={!busy} mask={{ closable: !busy }} keyboard={!busy} footer={null} width="97vw" destroyOnHidden>
      <Alert type="info" title="Tệp gốc được lưu nguyên bản; grid là dữ liệu diễn giải. Không chạy macro hoặc liên kết ngoài." description="Đóng rồi mở lại để tiếp tục job. Chỉ patch đã lưu được giữ; mỗi trang tối đa 200 dòng. Tiến độ ghi pending chưa phải số dòng đã nhập vào sổ." showIcon />
      <Space wrap className="toolbar"><Select aria-label="Job import đã lưu" style={{ minWidth: 360 }} placeholder="Chọn job đã lưu" value={selected} options={jobs.data?.items.map(job => ({ value: job.id, label: `${job.id.slice(0, 8)} · ${job.state} · đã công bố ${job.counts.published_rows ?? 0}` }))} onChange={choose} /><Button onClick={() => void refresh()} disabled={dirty}>Tải trạng thái</Button></Space>
      {(jobs.data?.total ?? 0) > 50 && <Pagination size="small" current={jobsPage} pageSize={50} total={jobs.data?.total} showSizeChanger={false} onChange={setJobsPage} disabled={dirty} />}
      <Space wrap><Select aria-label="Hồ sơ mapping đã lưu" placeholder="Dùng hồ sơ mapping đã lưu" style={{ minWidth: 300 }} disabled={dirty || busy || running} options={profiles.data?.items.map(item => ({ value: item.id, label: `${item.name} · v${item.version} · schema ${item.schema_revision}` }))} onChange={id => { const item = profiles.data?.items.find(value => value.id === id); if (item) { setMapping(item.mapping); if (!selected) pendingMapping.current = item.mapping; setProfile(JSON.stringify(item.profile, null, 2)); creationKey.current = requestKey(); } }} /><Input aria-label="Tên hồ sơ mapping" placeholder="Tên hồ sơ mapping" value={profileName} onChange={event => setProfileName(event.target.value)} /><Button disabled={!canWrite || busy || dirty || !profileName.trim()} onClick={() => void saveProfile()}>Lưu hồ sơ hiện tại</Button></Space>
      {error && <Alert type="error" title={error} showIcon />}
      <ClipboardImportChoice file={clipboardCandidate} disabled={dirty || busy || !canWrite} onDiscard={() => setClipboardCandidate(null)} onAccept={() => { if (clipboardCandidate && !dirty && !busy) startClipboard(clipboardCandidate); }} />
      {(jobs.error || detail.error || stages.error) && <Alert type="error" title={messageOf(jobs.error || detail.error || stages.error)} showIcon />}
      {!selected && <section>
        {isClipboardFile && file && <Alert type="info" showIcon title={`Tệp clipboard đã chuẩn bị: ${file.name} · ${file.size} byte`} description="CSV dùng dấu phân cách tab, UTF-8, header_row=0. Mapping ban đầu để trống: xem nguồn và ánh xạ sau parse. Chỉ nút Lưu gốc và tạo job gửi dữ liệu; chưa nhập vào sổ." action={<Button disabled={busy} onClick={discardClipboard}>Bỏ tệp clipboard</Button>} />}
        <label>Tệp .xlsx / .xlsm / .csv <input aria-label="Tệp import" type="file" accept=".xlsx,.xlsm,.csv" disabled={!canWrite || busy} onChange={event => { if (isClipboardFile) { setProfile(JSON.stringify(defaultProfile, null, 2)); setMapping({}); } setFile(event.target.files?.[0]); setIsClipboardFile(false); setClipboardCandidate(null); originalId.current = undefined; uploadKey.current = requestKey(); creationKey.current = requestKey(); }} /></label>
        <p>Profile đọc nguồn: sheet_id, header_row, encoding, delimiter, date_format, decimal_separator, thousands_separator, skip_blank, hidden_rows, merged_cells. Ngày mơ hồ cần format chính xác.</p>
        <Input.TextArea aria-label="Profile import JSON" value={profile} onChange={event => setProfile(event.target.value)} rows={8} />
        <Checkbox checked={allowDuplicate} onChange={event => { setAllowDuplicate(event.target.checked); creationKey.current = requestKey(); }}>Tôi chủ động tạo lượt nhập mới từ tệp đã dùng (vẫn phải xem cảnh báo trùng)</Checkbox>
        <Button type="primary" disabled={!file || !canWrite} loading={busy} onClick={() => void upload()}>Lưu gốc và tạo job</Button>
      </section>}
      {selected && <Button disabled={dirty || busy} onClick={() => { setSelected(undefined); setError(''); }}>Nhập tệp khác</Button>}
      {batch && <>
        <Space wrap className="toolbar"><Tag color={running ? 'processing' : 'blue'}>{batch.state}</Tag><span>Job: {batch.job?.phase ?? batch.job?.state ?? 'chưa có worker'}</span><span>Phiên bản {batch.version} · staging {batch.revision} · mapping {batch.mapping_revision} · quyết định {batch.decision_revision}</span></Space>
        <div className="accounting-counts">{[['Nguồn', 'source_rows'], ['Hợp lệ', 'valid'], ['Lỗi', 'invalid'], ['Nghi trùng', 'potential_duplicates'], ['Đã loại', 'excluded'], ['Đã ghi pending', 'staged_committed_rows'], ['Đã công bố vào sổ', 'published_rows'], ['Còn chờ', 'pending']].map(([label, key]) => <Tag key={key}>{label}: {batch.counts[key] ?? 0}</Tag>)}</div>
        <p>Các cờ lỗi / nghi trùng có thể giao nhau; không cộng các nhãn thành tổng nguồn. {batch.error_code || batch.job?.error_code}</p>
        {batch.validation_token && <details><summary>Thu / chi trước và sau nhập dự kiến · {range.from} đến hết {range.through}</summary><p>Ngày nghiệp vụ Asia/Ho_Chi_Minh, bao gồm cả hai mốc; có thể chọn một ngày. Chỉ phần hợp lệ đủ quyết định, chưa công bố, trong kỳ đã chọn. Đây là dự kiến; backend kiểm lại chính xác khi xác nhận.</p>{comparison.error ? <Alert type="error" title={messageOf(comparison.error)} /> : comparison.data?.before.has_valid_money_mapping ? <Table rowKey="currency" pagination={false} size="small" dataSource={Object.keys(comparison.data.after).map(currency => ({ currency, before: comparison.data!.before.totals[currency], addition: comparison.data!.new_batch[currency], after: comparison.data!.after[currency] }))} columns={[{ title: 'Tiền', dataIndex: 'currency' }, ...(['before', 'addition', 'after'] as const).map((key, index) => ({ title: ['Sổ hiện tại', 'Phần sẽ thêm', 'Dự kiến sau nhập'][index], render: (_: unknown, row: { before?: { income: string; expense: string }; addition?: { income: string; expense: string }; after?: { income: string; expense: string } }) => `Thu ${row[key]?.income ?? '0'} · chi ${row[key]?.expense ?? '0'}` }))]} /> : <Alert type="warning" title="Cần mapping ngữ nghĩa tiền hợp lệ để so sánh thu / chi." />}</details>}
        <Space wrap><Button disabled={busy || !original.data} onClick={() => download(batch.file_id, original.data!.original_name)}>Tải tệp gốc nguyên bản</Button><Button onClick={() => { setReview('issues'); setReviewPage(1); }}>Danh sách lỗi toàn job</Button><Button onClick={() => { setReview('duplicates'); setReviewPage(1); }}>Xem ứng viên trùng</Button><Button disabled={!canWrite || dirty || busy || !running} danger onClick={() => { if (window.confirm('Yêu cầu dừng tại checkpoint an toàn? Pending chưa công bố không được coi là nhập thành công.')) void action('cancel'); }}>Hủy / dừng job</Button><Button disabled={!canWrite || dirty || busy || !['FAILED', 'CANCELLED', 'RECOVERABLE'].includes(batch.state)} onClick={() => void action('resume')}>Tiếp tục job</Button></Space>
        {original.data && <p>Tệp gốc: {original.data.original_name} · {original.data.size} byte · SHA-256 <code>{original.data.sha256}</code></p>}{original.error && <Alert type="error" title={messageOf(original.error)} />}
        <details><summary>Sheet, profile và mapping cột</summary>
          {batch.source_manifest?.sheets && <p>Sheet nguồn: {batch.source_manifest.sheets.map(sheet => `${sheet.id}: ${sheet.name}`).join('; ')}</p>}
          <Space wrap><label>Sheet<Select aria-label="Sheet nguồn" value={String(profileValue().sheet_id ?? '')} style={{ minWidth: 180 }} options={batch.source_manifest?.sheets?.map(sheet => ({ value: sheet.id, label: sheet.name }))} onChange={value => patchProfile('sheet_id', value)} /></label><label>Dòng header<InputNumber min={0} value={typeof profileValue().header_row === 'number' ? profileValue().header_row as number : 1} onChange={value => patchProfile('header_row', value ?? 1)} /></label><label>Bắt đầu<InputNumber min={1} value={typeof profileValue().start_row === 'number' ? profileValue().start_row as number : null} onChange={value => patchProfile('start_row', value ?? undefined)} /></label><label>Kết thúc<InputNumber min={1} value={typeof profileValue().end_row === 'number' ? profileValue().end_row as number : null} onChange={value => patchProfile('end_row', value ?? undefined)} /></label></Space>
          <Input.TextArea aria-label="Profile mapping JSON" value={profile} onChange={event => setProfile(event.target.value)} rows={7} />
          <Space wrap>{book.columns.map(column => <label key={column.id}>{column.name} ({column.id}) <Input style={{ width: 80 }} aria-label={`Mapping ${column.name}`} placeholder="A, B…" value={mapping[column.id] ?? ''} onChange={event => setMapping(old => ({ ...old, [column.id]: event.target.value.toUpperCase() }))} /></label>)}</Space>
          <Button disabled={!canWrite || busy || dirty || running} onClick={() => { try { const parsed: unknown = JSON.parse(profile); if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) throw new Error('Profile phải là object.'); void action('mapping', { expected_version: batch.version, mapping: Object.fromEntries(Object.entries(mapping).filter(([, value]) => value)), profile: parsed }); } catch (err) { setError(messageOf(err)); } }}>Lưu mapping / profile · làm mới validation</Button>
        </details>
        <Space wrap className="toolbar">
          <Select aria-label="Lọc staging" value={status} style={{ width: 200 }} disabled={dirty} options={[['', 'Tất cả staging'], ['invalid', 'Lỗi'], ['valid', 'Hợp lệ'], ['duplicates', 'Nghi trùng'], ['pending', 'Chưa nhập'], ['imported', 'Đã nhập'], ['excluded', 'Đã loại']].map(([value, label]) => ({ value, label }))} onChange={value => { setStatus(value); setPage(1); }} />
          <Input.Search aria-label="Tìm staging" placeholder="Tìm toàn bộ staging" disabled={dirty} onSearch={value => { setSearch(value); setPage(1); }} />
          <Button disabled={!canWrite || dirty || busy || running} onClick={() => void action('validate', { expected_version: batch.version })}>Validate toàn bộ</Button>
          <Button type="primary" disabled={!canWrite || dirty || busy || running || !batch.validation_token} onClick={confirmImport}>Xác nhận nhập phần hợp lệ</Button>
        </Space>
        {running && <Alert type="info" title="Worker đang chạy. Có thể đóng modal rồi mở lại; staging bị khóa khi xử lý." />}<WorkbookGrid scope={`${actor}:${batch.id}:${page}:${status}:${search}`} columns={book.columns} source={rows} canWrite={canWrite && !running} busy={busy || running} onDirty={onDirty} onSave={saveStaging} onSelect={setSourceId} onLargeClipboard={largeClipboard} />
        {selectedSource && <details open><summary>Nguồn và diễn giải · {selectedSource.source_sheet}!{selectedSource.source_row} · revision {selectedSource.revision}</summary><Table size="small" pagination={false} rowKey="id" dataSource={book.columns.map(column => ({ id: column.id, name: column.name, source: batch.mapping[column.id], raw: selectedSource.raw_values?.[batch.mapping[column.id]], typed: selectedSource.typed_values?.[column.id], edited: selectedSource.edited_values?.[column.id] }))} columns={[{ title: 'Cột sổ', dataIndex: 'name' }, { title: 'Cột nguồn', dataIndex: 'source' }, { title: 'Giá trị gốc', dataIndex: 'raw' }, { title: 'Đã diễn giải', dataIndex: 'typed' }, { title: 'Patch đã lưu', dataIndex: 'edited' }]} /><p>{selectedSource.issues.map(issue => `${issue.cell ?? ''} ${issue.code}: ${issue.message} ${issue.suggestion ?? ''}`).join('\n')}</p></details>}
        <Pagination current={page} pageSize={200} total={stages.data?.total ?? 0} disabled={dirty || busy} showSizeChanger={false} showQuickJumper onChange={setPage} showTotal={total => `${total} dòng theo bộ lọc · ${rows.length} dòng đã tải`} />
        <Space wrap className="toolbar"><Button disabled={!canWrite || dirty || busy || running} onClick={() => { if (window.confirm('Giữ nghi trùng chưa có quyết định? Lựa chọn riêng từng dòng vẫn được giữ.')) void action('decisions', { expected_version: batch.version, decisions: [], all_pending_duplicates: 'keep' }); }}>Giữ nghi trùng chưa có quyết định</Button><Button disabled={!canWrite || dirty || busy || running} onClick={() => { if (window.confirm('Chủ động loại nghi trùng chưa có quyết định? Lựa chọn riêng từng dòng vẫn được giữ.')) void action('decisions', { expected_version: batch.version, decisions: [], all_pending_duplicates: 'skip' }); }}>Loại nghi trùng chưa có quyết định</Button></Space>
      </>}
    </Modal>
    <Modal title={review === 'issues' ? 'Lỗi theo tọa độ nguồn' : 'Ứng viên trùng · lựa chọn rõ ràng'} open={!!review} onCancel={() => setReview(null)} footer={null} width={1100}>
      {reviewData.error && <Alert type="error" title={messageOf(reviewData.error)} />}
      <Table rowKey={(_, index) => String(index)} dataSource={reviewData.data?.items} pagination={false} size="small" columns={review === 'issues' ? [
        { title: 'Vị trí', render: (_, row) => { const issue = row as Issue; return <Button type="link" disabled={dirty} onClick={() => { setSearch(String(issue.source_row ?? '')); setPage(1); setReview(null); }}>{`${issue.source_sheet ?? ''}!${issue.cell ?? issue.source_row ?? ''}`}</Button>; } },
        { title: 'Mã / lỗi / gợi ý', render: (_, row) => { const issue = row as Issue; return <span>{issue.code}: {issue.message}<br />{issue.suggestion}</span>; } },
        { title: 'Giá trị nguồn', render: (_, row) => String((row as Issue).raw_value ?? '') },
      ] : [
        { title: 'Dòng nguồn / đối chiếu', render: (_, row) => { const duplicate = row as DuplicateReview; return <><p>Dòng nguồn: {duplicate.source_row} · ứng viên: {duplicate.duplicate_count}</p><details open><summary>Ứng viên trong cùng tệp</summary><pre>{JSON.stringify(duplicate.file_matches ?? [], null, 2)}</pre></details><details><summary>Ứng viên trong sổ đã công bố</summary><pre>{JSON.stringify(duplicate.matches ?? [], null, 2)}</pre></details></>; } },
        { title: 'Quyết định', render: (_, row) => { const duplicate = row as { row_id: string }; return <Space><Button disabled={!canWrite || dirty || busy || running} onClick={() => void action('decisions', { expected_version: batch?.version, decisions: [{ row_id: duplicate.row_id, decision: 'keep' }] })}>Giữ</Button><Button disabled={!canWrite || dirty || busy || running} onClick={() => void action('decisions', { expected_version: batch?.version, decisions: [{ row_id: duplicate.row_id, decision: 'skip' }] })}>Loại</Button></Space>; } },
      ]} />
      <Pagination current={reviewPage} pageSize={100} total={reviewData.data?.total ?? 0} onChange={setReviewPage} showSizeChanger={false} />
      {review === 'issues' && <Button onClick={downloadIssuePage} disabled={!reviewData.data?.items.length}>Tải lỗi trang này (TSV · tối đa 100)</Button>}
      {review === 'issues' && <Space wrap><Button onClick={() => void exportErrors()} disabled={busy || !canWrite}>Xuất toàn bộ lỗi còn mở qua job</Button>{errorExport && <Tag>{errorExportStatus.data?.state ?? 'Đang kiểm tra job xuất lỗi'} {errorExportStatus.data?.error_code ?? ''}</Tag>}{errorExportStatus.data?.file_id && <Button onClick={() => download(errorExportStatus.data!.file_id!, `loi-toan-bo-${selected}.csv`)}>Tải toàn bộ lỗi CSV</Button>}{errorExportStatus.error && <Alert type="error" title={messageOf(errorExportStatus.error)} />}</Space>}
      <Typography.Paragraph>Không tự xóa giao dịch giống nhau. Dòng đã công bố không nhập lại qua cùng lineage. Quyết định mới làm thay đổi phiên bản xác nhận.</Typography.Paragraph>
    </Modal>
  </>;
}
