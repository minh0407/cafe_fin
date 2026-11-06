import type { GridRecord, ColumnDefinition } from './types';
export const CELL_LIMIT = 500;
export interface Position { row: number; col: number }
export interface Range { startRow: number; endRow: number; startCol: number; endCol: number }
export function selectedRange(anchor: Position, active: Position): Range {
  return { startRow: Math.min(anchor.row, active.row), endRow: Math.max(anchor.row, active.row), startCol: Math.min(anchor.col, active.col), endCol: Math.max(anchor.col, active.col) };
}
export function parseTSV(text: string): string[][] {
  if (text.length > 100000) throw new Error('Nội dung vượt 100.000 ký tự. Hãy nhập tệp qua staging.');
  // Excel quotes cells containing tabs/newlines; accept escaped double quotes.
  const rows: string[][] = [[]]; let cell = ''; let quoted = false;
  for (let i = 0; i < text.length; i++) {
    const char = text[i];
    if (char === '"' && (quoted || cell === '')) {
      if (quoted && text[i + 1] === '"') { cell += '"'; i++; } else quoted = !quoted;
    } else if (!quoted && (char === '\t' || char === '\n' || char === '\r')) {
      rows[rows.length - 1].push(cell); cell = '';
      if (char !== '\t') { if (char === '\r' && text[i + 1] === '\n') i++; rows.push([]); }
    } else cell += char;
  }
  if (quoted) throw new Error('Dữ liệu TSV có dấu ngoặc kép chưa đóng.');
  rows[rows.length - 1].push(cell);
  if (rows.length > 1 && rows.at(-1)?.length === 1 && rows.at(-1)?.[0] === '') rows.pop();
  if (rows.reduce((sum, row) => sum + row.length, 0) > CELL_LIMIT) throw new Error('Chỉ dán tối đa 500 ô mỗi lần; dữ liệu lớn dùng nhập tệp.');
  return rows;
}
export function encodeTSV(rows: string[][]) {
  return rows.map(row => row.map(value => /[\t\r\n"]/.test(value) ? `"${value.replaceAll('"', '""')}"` : value).join('\t')).join('\r\n');
}
export function applyCells(rows: GridRecord[], columns: ColumnDefinition[], start: Position, values: string[][]): GridRecord[] {
  if (start.row < 0 || start.col < 0 || start.row + values.length > rows.length || values.some(row => start.col + row.length > columns.length)) throw new Error('Vùng vượt trang đang tải. Chuyển trang hoặc dùng nhập tệp; không điền vào dòng chưa tải.');
  if (values.reduce((sum, row) => sum + row.length, 0) > CELL_LIMIT) throw new Error('Tối đa 500 ô mỗi lần.');
  values.forEach((row, r) => row.forEach((_value, c) => {
    const column = columns[start.col + c];
    if (rows[start.row + r].locked || column.editable === false || column.kind === 'formula') throw new Error('Vùng chứa ô chỉ đọc, công thức hoặc dòng đã nhập/xóa.');
  }));
  return rows.map((row, index) => {
    const patch = values[index - start.row];
    if (!patch) return row;
    const next = { ...row.values };
    patch.forEach((value, offset) => { next[columns[start.col + offset].id] = value === '' ? null : value; });
    return { ...row, values: next };
  });
}
export function changedRows(source: GridRecord[], draft: GridRecord[]) {
  const originals = new Map(source.map(row => [row.id, row]));
  return draft.filter(row => JSON.stringify(row.values) !== JSON.stringify(originals.get(row.id)?.values));
}
export function draftProblem(column: ColumnDefinition, value: string | null | undefined): string | undefined {
  if (value === null || value === undefined || value === '') return column.required ? 'Ô bắt buộc đang trống.' : undefined;
  if (column.kind === 'choice' && !column.choices?.includes(value)) return 'Giá trị chưa có trong danh sách lựa chọn của cột.';
  if (column.kind === 'integer' && !/^-?\d+$/.test(value)) return 'Cần số nguyên dạng chuỗi; không dùng dấu phân nhóm.';
  if (column.kind === 'decimal' || column.kind === 'money') {
    if (!/^-?\d+(?:\.\d+)?$/.test(value)) return 'Cần số thập phân chính xác, dấu chấm thập phân; không dùng dấu phân nhóm.';
    const scale = column.kind === 'money' ? 2 : column.scale ?? 2;
    if ((value.split('.')[1]?.length ?? 0) > scale) return `Vượt scale ${scale}; không tự làm tròn.`;
  }
  if (column.validation?.max_length && value.length > column.validation.max_length) return `Vượt độ dài ${column.validation.max_length}.`;
  return undefined;
}
