import { test, expect } from '../../../frontend/node_modules/@playwright/test';
import { applyCells, draftProblem, encodeTSV, parseTSV } from '../../../frontend/src/features/accounting/drafts';
import type { ColumnDefinition, GridRecord } from '../../../frontend/src/features/accounting/types';
import { query } from '../../../frontend/src/features/accounting/client';
import { vietnamBusinessToday } from '../../../frontend/src/features/accounting/businessDate';
const columns: ColumnDefinition[] = [{ id: 'code', name: 'Mã', kind: 'text' }, { id: 'amount', name: 'Tiền', kind: 'money' }];
const rows: GridRecord[] = [{ id: 'r1', version: 2, label: '1', values: { code: '001', amount: '92233720368547758.07' }, issues: [] }, { id: 'r2', version: 1, label: '2', values: { code: null, amount: null }, issues: [] }];
test('TSV quote/newline roundtrip and exact money preserve text', () => {
  const values = [['001', '92233720368547758.07'], ['tabs\tand\nlines', 'quote"value']];
  expect(parseTSV(encodeTSV(values))).toEqual(values);
  const edited = applyCells(rows, columns, { row: 0, col: 0 }, values);
  expect(edited[0].values).toEqual({ code: '001', amount: '92233720368547758.07' });
  expect(rows[1].values.code).toBeNull();
});
test('bounds reject unloaded pages, more than 500 cells, malformed input and readonly atomically', () => {
  expect(() => applyCells(rows, columns, { row: 1, col: 0 }, [['a'], ['b']])).toThrow(/trang/);
  expect(() => parseTSV(Array.from({ length: 501 }, () => 'x').join('\t'))).toThrow(/500/);
  expect(() => parseTSV('"unclosed')).toThrow(/chưa đóng/);
  expect(() => applyCells(rows, [{ ...columns[0], editable: false }, columns[1]], { row: 0, col: 0 }, [['changed']])).toThrow(/chỉ đọc/);
  expect(rows[0].values.code).toBe('001');
  expect(parseTSV(Array(500).fill('x').join('\n') + '\n')).toHaveLength(500);
});
test('encoded filters/search retain punctuation allowed by the shared API path guard', () => {
  const text = "Mã O'Reilly !*()~ .. / tiếng Việt"; const encoded = query({ search: text, filters: JSON.stringify([{ column_id: 'code', op: 'eq', value: text }]) });
  expect(`/books?${encoded}`).toMatch(/^\/[a-z0-9/_?=&%.,:+-]*$/i);
  expect(new URLSearchParams(encoded).get('search')).toBe(text);
  expect(encoded).not.toContain('..');
});
test('draft money hints check string syntax and scale without rounding or converting money', () => {
  expect(draftProblem(columns[1], '92233720368547758.07')).toBeUndefined();
  expect(draftProblem(columns[1], '12.345')).toContain('scale 2');
  expect(draftProblem(columns[1], '1,000.00')).toContain('dấu phân nhóm');
  expect(draftProblem({ ...columns[0], required: true }, null)).toContain('bắt buộc');
});
test('Vietnam business date follows its own midnight and year boundary', () => {
  expect(vietnamBusinessToday(new Date('2026-12-31T16:59:59Z'))).toBe('2026-12-31');
  expect(vietnamBusinessToday(new Date('2026-12-31T17:00:00Z'))).toBe('2027-01-01');
  expect(vietnamBusinessToday(new Date('2026-06-10T18:30:00Z'))).toBe('2026-06-11');
});
