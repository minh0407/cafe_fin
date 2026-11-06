export const CLIPBOARD_BYTE_LIMIT = 100 * 1024 * 1024;
export const clipboardProfile = {
  sheet_id: 'csv', header_row: 0, encoding: 'utf-8', delimiter: '\t',
  date_format: '%d/%m/%Y', decimal_separator: '.', thousands_separator: '',
  skip_blank: true, hidden_rows: 'include', merged_cells: 'reject',
};
export interface ClipboardImportSource { id: string; file: File; actor: string; book_id: string }
export function clipboardFile(text: string): File {
  if (text.length > CLIPBOARD_BYTE_LIMIT) throw new Error('Clipboard vượt giới hạn 100 MiB. Chia thành các tệp nguồn nhỏ hơn để nhập.');
  // File encodes the unchanged clipboard string as UTF-8. Do not split/parse the
  // large input, construct a JSON row payload, or allocate workbook rows here.
  const file = new File([text], `clipboard-${crypto.randomUUID()}.csv`, { type: 'text/csv;charset=utf-8' });
  if (file.size > CLIPBOARD_BYTE_LIMIT) throw new Error('Clipboard UTF-8 vượt giới hạn 100 MiB. Chia thành các tệp nguồn nhỏ hơn để nhập.');
  return file;
}
