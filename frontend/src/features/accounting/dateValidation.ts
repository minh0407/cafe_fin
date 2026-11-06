import { isDateInputValueValid } from '../../shared/DateInput';
import type { ColumnDefinition, Values } from './types';

export function isInclusiveDateRangeValid(from: string, through: string) {
  return !!from && !!through && isDateInputValueValid(from) && isDateInputValueValid(through) && from <= through;
}

export function dateFilterError(json: string, columns: ColumnDefinition[]): string | undefined {
  let conditions: unknown;
  try { conditions = JSON.parse(json); } catch { return 'Bộ lọc phải là mảng JSON hợp lệ.'; }
  if (!Array.isArray(conditions) || conditions.length > 20 || conditions.some(item => !item || typeof item !== 'object' || Array.isArray(item))) return 'Bộ lọc phải là mảng tối đa 20 điều kiện.';
  for (const condition of conditions) {
    const column = columns.find(item => item.id === condition.column_id);
    if (column?.kind !== 'date') continue;
    const value = condition.value;
    if (condition.op === 'empty' && (value === undefined || value === '')) continue;
    if (typeof value !== 'string' || !value || !isDateInputValueValid(value)) return `${column.name}: ngày lọc không hợp lệ. Nhập DD/MM/YYYY và chọn ngày hợp lệ trước khi áp dụng.`;
  }
  return undefined;
}

export function newRowDateError(columns: ColumnDefinition[], values: Values): string | undefined {
  for (const column of columns) {
    if (column.kind !== 'date') continue;
    const value = values[column.id] ?? '';
    if (column.required && !value) return `${column.name}: cần nhập ngày bắt buộc.`;
    if (!isDateInputValueValid(value)) return `${column.name}: ngày không hợp lệ. Nhập DD/MM/YYYY; bản nháp đang nhập được giữ nguyên.`;
  }
  return undefined;
}
