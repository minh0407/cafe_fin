import { useEffect, useMemo, useRef, useState, type ClipboardEvent } from 'react';
import { Alert, Button, Modal, Space, Tag, Typography } from 'antd';
import { DataGrid, renderTextEditor, type Column, type DataGridHandle, type RenderCellContentProps, type RenderEditCellContentProps } from 'react-data-grid';
import 'react-data-grid/lib/styles.css';
import { messageOf } from '../../shared/api';
import { applyCells, changedRows, ClipboardLimitError, draftProblem, encodeTSV, parseTSV, selectedRange, type Position } from './drafts';
import type { ColumnDefinition, GridRecord, Issue } from './types';
import { registerDraftGuard } from './navigation';

export function useDraftGuard(dirty: boolean) {
  const dirtyRef = useRef(dirty); dirtyRef.current = dirty;
  useEffect(() => registerDraftGuard(() => dirtyRef.current), []);
}

interface Props {
  scope: string; columns: ColumnDefinition[]; source: GridRecord[]; canWrite: boolean;
  busy?: boolean; onSave: (changed: GridRecord[]) => Promise<GridRecord[] | void>; onDirty: (dirty: boolean) => void;
  onSelect?: (id: string) => void;
  validationIssues?: Record<string, Issue[]>;
  focusCell?: { rowId: string; columnId?: string; request: number };
  onLargeClipboard?: (text: string, hasDraft: boolean) => void;
}
export function WorkbookGrid({ scope, columns, source, canWrite, busy, onSave, onDirty, onSelect, validationIssues, focusCell, onLargeClipboard }: Props) {
  const [rows, setRows] = useState(source);
  const [baseline, setBaseline] = useState(source);
  const [past, setPast] = useState<GridRecord[][]>([]); const [future, setFuture] = useState<GridRecord[][]>([]);
  const [notice, setNotice] = useState(''); const [active, setActive] = useState<Position>({ row: 0, col: 0 });
  const [anchor, setAnchor] = useState<Position>({ row: 0, col: 0 });
  const [preview, setPreview] = useState<GridRecord[] | null>(null);
  const filling = useRef(false);
  const grid = useRef<DataGridHandle>(null);
  const changed = changedRows(baseline, rows); const dirty = changed.length > 0;
  const dirtyRef = useRef(dirty); dirtyRef.current = dirty;
  const priorScope = useRef(scope);
  useDraftGuard(dirty);
  useEffect(() => { onDirty(dirty); }, [dirty, onDirty]);
  useEffect(() => {
    if (priorScope.current === scope && dirtyRef.current) return;
    priorScope.current = scope; setRows(source); setBaseline(source); setPast([]); setFuture([]); setPreview(null); setNotice('');
  }, [scope, source]);
  useEffect(() => {
    if (!focusCell) return;
    const rowIdx = rows.findIndex(row => row.id === focusCell.rowId); const idx = Math.max(1, columns.findIndex(column => column.id === focusCell.columnId) + 1);
    if (rowIdx < 0) return;
    grid.current?.scrollToCell({ rowIdx, idx }); grid.current?.setActivePosition({ rowIdx, idx });
    grid.current?.element?.focus(); setActive({ row: rowIdx, col: idx - 1 }); setAnchor({ row: rowIdx, col: idx - 1 });
  }, [focusCell]);
  function edit(next: GridRecord[]) {
    if (!canWrite || busy) return;
    const originals = new Map(baseline.map(row => [row.id, row]));
    const cells = next.reduce((total, row) => total + columns.filter(column => row.values[column.id] !== originals.get(row.id)?.values[column.id]).length, 0);
    if (cells > 500) { setNotice('Bản nháp trên trang giới hạn 500 ô đã thay đổi. Lưu hoặc bỏ nháp trước khi sửa tiếp.'); return; }
    setPast(old => [...old.slice(-19), rows]); setFuture([]); setRows(next);
  }
  const gridColumns = useMemo<Column<GridRecord>[]>(() => [
    { key: '__source', name: 'Dòng / nguồn', width: 150, frozen: 'start', renderCell: ({ row }) => <span title={row.id}>{row.label}{row.locked ? ' · khóa' : ''}</span> },
    ...columns.map(column => ({
      key: column.id, name: `${column.name}${column.required ? ' *' : ''}`, width: 180, resizable: true,
      frozen: column.display?.frozen === true ? 'start' as const : undefined,
      cellClass: (row: GridRecord) => {
        const range = selectedRange(anchor, active); const rowIndex = rows.findIndex(item => item.id === row.id); const colIndex = columns.findIndex(item => item.id === column.id);
        return rowIndex >= range.startRow && rowIndex <= range.endRow && colIndex >= range.startCol && colIndex <= range.endCol ? 'accounting-range-cell' : '';
      },
      editable: (row: GridRecord) => canWrite && !busy && !row.locked && column.editable !== false && column.kind !== 'formula',
      renderEditCell: (props: RenderEditCellContentProps<GridRecord>) => renderTextEditor({ ...props, row: { ...props.row, [column.id]: props.row.values[column.id] ?? '' }, onRowChange: (next, commit) => props.onRowChange({ ...props.row, values: { ...props.row.values, [column.id]: (next as unknown as Record<string, string>)[column.id] || null } }, commit) }),
      renderCell: ({ row }: RenderCellContentProps<GridRecord>) => {
        const issues = (validationIssues?.[row.id] ?? row.issues).filter(issue => issue.column_id === column.id);
        const problem = draftProblem(column, row.values[column.id]);
        return <span className={issues.length || problem ? 'accounting-cell-error' : ''} title={[problem ? `Kiểm tra nháp: ${problem} Backend vẫn quyết định khi lưu/validate.` : '', ...issues.map(issue => `${issue.cell ?? ''} ${issue.code}: ${issue.message} ${issue.suggestion ?? ''}`)].filter(Boolean).join('\n') || `${column.kind}: ${row.values[column.id] ?? ''}`}>{row.values[column.id] ?? ''}{issues.length || problem ? ' ⚠' : ''}</span>;
      },
    })),
  ], [columns, canWrite, busy, rows, anchor, active, validationIssues]);
  function copy(event: ClipboardEvent) {
    event.preventDefault(); event.stopPropagation();
    const range = selectedRange(anchor, active);
    if ((range.endRow - range.startRow + 1) * (range.endCol - range.startCol + 1) > 500) { setNotice('Chọn tối đa 500 ô để sao chép.'); return; }
    event.clipboardData.setData('text/plain', encodeTSV(rows.slice(range.startRow, range.endRow + 1).map(row => columns.slice(range.startCol, range.endCol + 1).map(column => row.values[column.id] ?? ''))));
  }
  function paste(event: ClipboardEvent) {
    event.preventDefault(); event.stopPropagation();
    if (!canWrite || busy) return;
    const text = event.clipboardData.getData('text/plain');
    try { setPreview(applyCells(rows, columns, active, parseTSV(text))); setNotice(''); }
    catch (error) { setNotice(messageOf(error)); if (error instanceof ClipboardLimitError) onLargeClipboard?.(text, dirty); }
  }
  function fill() {
    const range = selectedRange(anchor, active);
    try {
      const values = Array.from({ length: range.endRow - range.startRow + 1 }, () => columns.slice(range.startCol, range.endCol + 1).map(column => rows[range.startRow]?.values[column.id] ?? ''));
      setPreview(applyCells(rows, columns, { row: range.startRow, col: range.startCol }, values));
    } catch (error) { setNotice(messageOf(error)); }
  }
  async function save() {
    if (!window.confirm(`Lưu ${changed.length} dòng đã sửa? Backend sẽ kiểm dữ liệu và phiên bản trước khi xác nhận.`)) return;
    try {
      const saved = await onSave(changed);
      if (saved) {
        const byId = new Map(saved.map(row => [row.id, row]));
        setBaseline(old => old.map(row => byId.get(row.id) ?? row));
        setRows(old => old.map(row => byId.get(row.id) ?? row));
        setPast([]); setFuture([]);
        setNotice(`Backend đã xác nhận ${saved.length}/${changed.length} dòng. Dòng chưa lưu vẫn giữ bản nháp.`);
      } else setNotice('Backend đã xác nhận lưu.');
    } catch (error) { setNotice(messageOf(error)); }
  }
  return <div>
    <Space wrap className="toolbar">
      <Tag color={dirty ? 'orange' : 'green'}>{dirty ? `${changed.length} dòng nháp` : 'Dữ liệu đã tải từ sổ'}</Tag>
      <Button disabled={!past.length || busy} onClick={() => { setFuture(old => [rows, ...old].slice(0, 20)); setRows(past[past.length - 1]); setPast(old => old.slice(0, -1)); }}>Hoàn tác nháp</Button>
      <Button disabled={!future.length || busy} onClick={() => { setPast(old => [...old.slice(-19), rows]); setRows(future[0]); setFuture(old => old.slice(1)); }}>Làm lại nháp</Button>
      <Button disabled={!dirty || busy} onClick={() => { if (window.confirm('Bỏ toàn bộ thay đổi trên trang này?')) { setRows(baseline); setPast([]); setFuture([]); } }}>Bỏ nháp</Button>
      <Button disabled={!canWrite || busy || !rows.length} onClick={fill}>Điền vùng từ dòng đầu · xem trước</Button>
      <Button type="primary" loading={busy} disabled={!canWrite || !dirty} onClick={() => void save()}>Lưu bản nháp</Button>
      <Typography.Text type="secondary">{rows.length} dòng đang tải · chọn vùng: Shift + click · sao chép/dán/nháp ≤500 ô · lịch sử 20 bước trên trang</Typography.Text>
    </Space>
    {notice && <Alert title={notice} type="warning" showIcon closable onClose={() => setNotice('')} />}
    <div onCopyCapture={copy} onPasteCapture={paste}>
      <DataGrid ref={grid} aria-label="Sổ kế toán theo ô" className="rdg-light accounting-grid" columns={gridColumns} rows={rows} getRowKey={row => row.id} enableVirtualization
        onRowsChange={next => { if (filling.current) { filling.current = false; if (changedRows(rows, next).length <= 500) setPreview(next); else setNotice('Kéo điền tối đa 500 ô trên trang đã tải.'); } else edit(next); }}
        onFill={canWrite && !busy ? ({ columnKey, sourceRow, targetRow }) => { filling.current = true; return { ...targetRow, values: { ...targetRow.values, [columnKey]: sourceRow.values[columnKey] ?? null } }; } : undefined}
        onCellMouseDown={(args, event) => { const position = { row: args.rowIdx, col: Math.max(0, args.column.idx - 1) }; setActive(position); if (!event.shiftKey) setAnchor(position); onSelect?.(args.row.id); }}
        onActivePositionChange={args => { if (args.column) setActive({ row: args.rowIdx, col: Math.max(0, args.column.idx - 1) }); }}
        onCellKeyDown={(args, event) => { if (!event.shiftKey && args.column) setAnchor({ row: args.rowIdx, col: Math.max(0, args.column.idx - 1) }); }} />
    </div>
    <Modal title="Xem trước thay đổi vùng" open={!!preview} onCancel={() => setPreview(null)} onOk={() => { if (preview) edit(preview); setPreview(null); }} okText="Áp dụng vào nháp" width={850}>
      <p>{preview ? changedRows(rows, preview).length : 0} dòng trên trang hiện tại sẽ đổi. Chưa ghi vào sổ; cần Lưu bản nháp để backend kiểm lại.</p>
      {preview && <p>Ô cần kiểm tra theo kiểu / yêu cầu cơ bản: {changedRows(rows, preview).reduce((count, row) => count + columns.filter(column => draftProblem(column, row.values[column.id])).length, 0)}. Backend kiểm đầy đủ phiên bản, precision, công thức và quy tắc khi lưu / validate.</p>}
      <div className="accounting-preview">{preview && changedRows(rows, preview).map(row => <pre key={row.id}>{row.label}: {JSON.stringify(row.values)}</pre>)}</div>
    </Modal>
  </div>;
}
