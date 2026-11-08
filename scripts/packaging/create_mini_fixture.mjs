// Developer fixture authoring only; use the bundled workspace runtime/artifact-tool.
// No workbook or runtime dependency is added to the application.
import fs from 'node:fs/promises';
import { SpreadsheetFile, Workbook } from '@oai/artifact-tool';

const output = process.argv[2];
if (!output) throw new Error('A new external fixture output directory is required');
await fs.mkdir(output, { recursive: true });
const workbook = Workbook.create();
const sheet = workbook.worksheets.add('Mini');
sheet.showGridLines = false;
sheet.getRange('A1:F6').values = [
  ['Ngày', 'Mã', 'Diễn giải', 'Thu', 'Chi', 'Kg'],
  [new Date('2026-11-08T00:00:00Z'), '0001', 'Thu tổng hợp', 15000000, 0, 1250.5],
  [new Date('2026-11-08T00:00:00Z'), '0002', 'Chi tổng hợp', 0, 10000000, 800.25],
  [new Date('2026-11-08T00:00:00Z'), '0001', 'Thu tổng hợp', 15000000, 0, 1250.5],
  ['2026-13-40', '0004', 'Dòng lỗi cố ý', 'không phải số', 0, '1.2345'],
  [new Date('2026-11-08T00:00:00Z'), '0003', 'Ô tiền trống khác 0', null, 0, null],
];
sheet.getRange('A1:F6').format.font = { name: 'Arial', size: 11 };
sheet.getRange('A1:F6').format.rowHeight = 24;
sheet.getRange('A1:F1').format.fill = '#4B3525';
sheet.getRange('A1:F1').format.font = { name: 'Arial', size: 11, bold: true, color: '#FFFFFF' };
sheet.getRange('A1:F1').format.horizontalAlignment = 'center';
sheet.getRange('A2:A6').setNumberFormat('yyyy-mm-dd');
// Exported IDs remain string cells. Explicit width format also avoids the
// preview engine dropping leading zeros when rendering numeric-looking text.
sheet.getRange('B2:B6').setNumberFormat('0000');
sheet.getRange('D2:E6').setNumberFormat('#,##0.00');
sheet.getRange('F2:F6').setNumberFormat('0.000');
sheet.getRange('F5').setNumberFormat('@');
sheet.getRange('A2:B6').format.horizontalAlignment = 'center';
sheet.getRange('A1:A6').format.columnWidth = 16;
sheet.getRange('B1:B6').format.columnWidth = 10;
sheet.getRange('C1:C6').format.columnWidth = 29;
sheet.getRange('D1:E6').format.columnWidth = 20;
sheet.getRange('F1:F6').format.columnWidth = 15;
sheet.getRange('A5:F5').format.fill = '#FFF0DB';
workbook.recalculate();
console.log((await workbook.inspect({kind:'table',range:'Mini!A1:F6',include:'values,formulas',tableMaxRows:6,tableMaxCols:6,maxChars:1600})).ndjson);
const preview = await workbook.render({sheetName:'Mini',range:'A1:F6',scale:1.5,format:'png'});
await fs.writeFile(`${output}/mini-preview.png`,new Uint8Array(await preview.arrayBuffer()));
await (await SpreadsheetFile.exportXlsx(workbook)).save(`${output}/mini.xlsx`);
await fs.writeFile(`${output}/mini.csv`, '\uFEFFNgày,Mã,Diễn giải,Thu,Chi,Kg\r\n'
  + '2026-11-08,0001,Thu tổng hợp,15000000.00,0.00,1250.500\r\n'
  + '2026-11-08,0002,Chi tổng hợp,0.00,10000000.00,800.250\r\n'
  + '2026-11-08,0001,Thu tổng hợp,15000000.00,0.00,1250.500\r\n'
  + '2026-13-40,0004,Dòng lỗi cố ý,không phải số,0.00,1.2345\r\n'
  + '2026-11-08,0003,Ô tiền trống khác 0,,0.00,\r\n','utf8');
