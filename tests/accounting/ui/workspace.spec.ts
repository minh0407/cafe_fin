import { test, expect, type Page } from '../../../frontend/node_modules/@playwright/test';
import type { Batch } from '../../../frontend/src/features/accounting/types';
const initial = { id: 'row1', version: 3, logical_row: 1, values: { code: '001', amount: '92233720368547758.07' }, issues: [] };
const book = { id: 'book1', name: 'Sổ tổng hợp', version: 1, schema_revision: 1, data_revision: 1, columns: [{ id: 'code', name: 'Mã', kind: 'text', editable: true }, { id: 'amount', name: 'Số tiền', kind: 'money', editable: true }], semantics: {} };
const batch = { id: 'batch1', book_id: 'book1', file_id: 'file1', state: 'READY_FOR_CONFIRM', version: 7, revision: 4, mapping_revision: 2, decision_revision: 3, validation_token: 'validated-exact-revisions', mapping: { code: 'A', amount: 'B' }, profile: {}, counts: { source_rows: 5, valid: 3, invalid: 1, potential_duplicates: 1, excluded: 0, published_rows: 0, staged_committed_rows: 0, pending: 5 } };
async function setup(page: Page, conflict = false, secondRow = false, dates = false) {
  page.on('pageerror', error => console.error('Browser error:', error.message));
  page.on('console', message => { if (message.type() === 'error') console.error('Browser console:', message.text()); });
  const writes: { path: string; body: any }[] = []; let row = structuredClone(initial); let currentBatch: Batch = structuredClone(batch);
  const activeBook = dates ? { ...book, columns: [...book.columns, { id: 'day', name: 'Ngày nghiệp vụ', kind: 'date', editable: true, required: true }, { id: 'due', name: 'Hạn tùy chọn', kind: 'date', editable: true, required: false }] } : book;
  if (dates) row = { ...row, values: { ...row.values, day: '2026-11-06', due: '2026-11-07' } } as typeof row;
  await page.route('**/src/app/main.tsx', async route => {
    const response = await route.fetch();
    const source = (await response.text())
      .replace(/import \{ App \} from [^;]+;/, 'import { AccountingPage as App } from "/src/features/accounting/AccountingPage.tsx"; import { useSession } from "/src/shared/session.ts";')
      .replace('const queryClient =', `useSession.getState().setBoot({protocol_version:1,api_base:location.origin+'/api/v1',session_token:'synthetic',data_root:'synthetic'}); useSession.getState().login('synthetic',{id:'actor1',username:'admin',role:'admin',permissions:['*'],version:1}); window.__testSession=useSession; const queryClient =`);
    await route.fulfill({ response, body: source });
  });
  await page.route('**/api/v1/**', async route => {
    const request = route.request(); const url = new URL(request.url()); const path = url.pathname.replace('/api/v1/accounting', '');
    const respond = (json: unknown, status = 200) => route.fulfill({ json, status });
    if (request.method() !== 'GET') {
      if (url.pathname.endsWith('/api/v1/files')) { const raw = request.postDataBuffer()!; writes.push({ path: '/files', body: { raw: raw.toString('utf8'), category: url.searchParams.get('category') } }); return respond({ id: 'clipboard-file', original_name: 'clipboard-synthetic.csv', sha256: '0'.repeat(64), size: raw.length, category: 'workbooks', media_type: 'text/csv' }); }
      const body = request.postDataJSON(); writes.push({ path, body });
      if (path === '/rows/row1') {
        if (conflict) return respond({ error: { code: 'VERSION_CONFLICT', message: 'Phiên bản mới đã được ghi.', field_errors: [] } }, 409);
        row = { ...row, version: 4, values: body.values }; return respond(row);
      }
      if (path === '/import-jobs/batch1/confirm') return respond({ ...batch, state: 'COMMITTING' });
      if (path === '/import-jobs') { currentBatch = { ...batch, id: 'clipboard-batch', file_id: body.file_id, profile: body.profile, mapping: {}, state: 'READY_FOR_MAPPING', validation_token: null, counts: { source_rows: 501, valid: 0, invalid: 0, potential_duplicates: 0, excluded: 0, published_rows: 0, pending: 501 } }; return respond(currentBatch); }
      if (path === '/books/book1/exports') return respond({ job_id: 'whole-book-export' });
      if (path === '/books/book1/rows') return respond({ ...initial, id: 'created-row', logical_row: 2, version: 1, values: body.values });
      return respond(batch);
    }
    if (path === '/books') return respond({ items: [activeBook], total: 1, page: 1, page_size: 200 });
    if (path === '/books/book1/rows') return respond({ items: [row, ...(secondRow ? [{ ...initial, id: 'row2', version: 1, logical_row: 2, values: { code: '002', amount: '1.00' } }] : [])], total: secondRow ? 2 : 1, page: 1, page_size: 200 });
    if (path === '/rows/row1') return respond({ ...initial, version: 4, values: { code: 'OTHER', amount: '11.00' } });
    if (path === '/books/book1/summary') return respond(dates ? { totals: { VND: { income: '12.34', expense: '0.00' } }, has_valid_money_mapping: true, validation_flags: [] } : { totals: {}, has_valid_money_mapping: false, validation_flags: ['MAPPING_REQUIRED'] });
    if (path === '/import-jobs') return respond({ items: [currentBatch], total: 1, page: 1, page_size: 50 });
    if (path === `/import-jobs/${currentBatch.id}`) return respond(currentBatch);
    if (path === '/import-jobs/batch1/summary') return respond(dates ? { before: { totals: { VND: { income: '12.34', expense: '0.00' } }, has_valid_money_mapping: true }, new_batch: { VND: { income: '8.00', expense: '0.00' } }, after: { VND: { income: '20.34', expense: '0.00' } }, provisional: true } : { before: { totals: {}, has_valid_money_mapping: false }, new_batch: {}, after: {}, provisional: true });
    if (path === '/exports/whole-book-export') return respond({ state: 'COMPLETED', file_id: 'derived-file' });
    if (path === '/import-jobs/batch1/duplicates') return respond({ items: [{ row_id: 'stage1', source_row: 2, duplicate_count: 1, file_matches: [{ source_sheet: 'Sheet1', source_row: 4, raw_values: { A: 'MATCH_IN_FILE' } }], matches: [] }], total: 1, page: 1, page_size: 100 });
    if (path === `/import-jobs/${currentBatch.id}/staging`) return respond({ items: [{ row_id: 'stage1', revision: 1, source_sheet: 'Sheet1', source_row: 2, raw_values: { A: '001', B: '12.00' }, typed_values: { code: '001', amount: '12.00' }, edited_values: {}, issues: [], duplicate_count: 0, decision: null, imported: false }], total: currentBatch.id === 'clipboard-batch' ? 501 : 1, page: 1, page_size: 200 });
    return respond({ items: [], total: 0, page: 1, page_size: 100 });
  });
  await page.goto('/#/accounting');
  await expect(page.getByRole('grid', { name: 'Sổ kế toán theo ô' })).toBeVisible();
  return writes;
}
async function paste(page: Page, value: string) {
  await page.getByRole('gridcell', { name: '001', exact: true }).click();
  await page.getByRole('grid', { name: 'Sổ kế toán theo ô' }).evaluate((node, text) => {
    const transfer = new DataTransfer(); transfer.setData('text/plain', text);
    node.dispatchEvent(new ClipboardEvent('paste', { bubbles: true, cancelable: true, clipboardData: transfer }));
  }, value);
}
test('paste requires preview, undo/redo and confirmed versioned string save', async ({ page }) => {
  const writes = await setup(page); await paste(page, '0009\t9007199254740993.01');
  await expect(page.getByRole('dialog', { name: 'Xem trước thay đổi vùng' })).toBeVisible();
  expect(writes).toHaveLength(0);
  await page.getByRole('button', { name: 'Áp dụng vào nháp' }).click();
  await expect(page.getByRole('gridcell', { name: '0009', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Hoàn tác nháp' }).click();
  await expect(page.getByRole('gridcell', { name: '001', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Làm lại nháp' }).click();
  page.once('dialog', dialog => dialog.accept()); await page.getByRole('button', { name: 'Lưu bản nháp' }).click();
  await expect.poll(() => writes.length).toBe(1);
  expect(writes[0]).toMatchObject({ path: '/rows/row1', body: { expected_version: 3, values: { code: '0009', amount: '9007199254740993.01' } } });
});
test('conflict preserves draft and displays old/current without overwrite', async ({ page }) => {
  const writes = await setup(page, true); await paste(page, 'mine'); await page.getByRole('button', { name: 'Áp dụng vào nháp' }).click();
  page.once('dialog', dialog => dialog.accept()); await page.getByRole('button', { name: 'Lưu bản nháp' }).click();
  await expect(page.getByRole('dialog', { name: 'Xung đột phiên bản · bản nháp được giữ' })).toBeVisible();
  await expect(page.getByText('OTHER', { exact: false }).last()).toBeVisible(); expect(writes).toHaveLength(1);
});
test('import modal reopens durable job and confirm pins exact validation revisions', async ({ page }) => {
  const writes = await setup(page);
  await page.getByRole('button', { name: 'Nhập Excel / CSV · mở job đã lưu' }).click();
  await page.getByRole('combobox', { name: 'Job import đã lưu' }).click(); await page.getByText('batch1 · READY_FOR_CONFIRM', { exact: false }).click();
  await expect(page.getByText('Đã công bố vào sổ: 0')).toBeVisible();
  await page.getByRole('dialog', { name: 'Nhập dữ liệu · Sổ tổng hợp' }).getByRole('button', { name: 'Đóng', exact: true }).click();
  await page.getByRole('button', { name: 'Nhập Excel / CSV · mở job đã lưu' }).click();
  await expect(page.getByText('Đã công bố vào sổ: 0')).toBeVisible();
  page.once('dialog', dialog => dialog.accept()); await page.getByRole('button', { name: 'Xác nhận nhập phần hợp lệ' }).click();
  await expect.poll(() => writes.length).toBe(1);
  expect(writes[0]).toMatchObject({ path: '/import-jobs/batch1/confirm', body: { expected_version: 7, staging_revision: 4, mapping_revision: 2, decision_revision: 3, validation_token: 'validated-exact-revisions', mode: 'valid_rows_only' } });
});
test('cancelled hash navigation retains draft; actor change drops drafts and removes write permission', async ({ page }) => {
  await setup(page); await paste(page, 'private-actor1-draft'); await page.getByRole('button', { name: 'Áp dụng vào nháp' }).click();
  await expect(page.getByRole('gridcell', { name: 'private-actor1-draft', exact: true })).toBeVisible();
  page.once('dialog', dialog => dialog.dismiss());
  await page.evaluate(() => { location.hash = '/accounting?page=2'; });
  await expect(page).toHaveURL(/#\/accounting$/);
  await expect(page.getByRole('gridcell', { name: 'private-actor1-draft', exact: true })).toBeVisible();
  await page.evaluate(() => { (window as any).__testSession.getState().login('actor2-token', { id: 'actor2', username: 'reader', role: 'operator', permissions: ['accounting.read'], version: 1 }); });
  await expect(page.getByRole('gridcell', { name: '001', exact: true })).toBeVisible();
  await expect(page.getByText('private-actor1-draft', { exact: true })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Thêm dòng', exact: true })).toBeDisabled();
  await expect(page.getByRole('button', { name: 'Tạo sổ', exact: true })).toBeDisabled();
});
test('native drag fill and explicit range fill preview only the loaded page', async ({ page }) => {
  const writes = await setup(page, false, true);
  const first = page.getByRole('gridcell', { name: '001', exact: true }); const second = page.getByRole('gridcell', { name: '002', exact: true });
  await first.click(); const handle = page.locator('.rdg-cell-drag-handle'); await expect(handle).toBeVisible();
  const start = await handle.boundingBox(); const end = await second.boundingBox();
  await page.mouse.move(start!.x + start!.width / 2, start!.y + start!.height / 2); await page.mouse.down();
  await page.mouse.move(end!.x + end!.width / 2, end!.y + end!.height / 2, { steps: 5 }); await page.mouse.up();
  const preview = page.getByRole('dialog', { name: 'Xem trước thay đổi vùng' }); await expect(preview).toBeVisible();
  expect(writes).toHaveLength(0); await preview.getByRole('button', { name: 'Hủy', exact: true }).click();
  await expect(second).toBeVisible();
  await first.click(); await second.click({ modifiers: ['Shift'] });
  await page.getByRole('button', { name: 'Điền vùng từ dòng đầu · xem trước' }).click();
  await preview.getByRole('button', { name: 'Áp dụng vào nháp' }).click();
  await expect(page.getByRole('gridcell', { name: '001', exact: true })).toHaveCount(2);
  expect(writes).toHaveLength(0);
});
test('inclusive business-date summary accepts one day and labels both endpoints', async ({ page }) => {
  await setup(page);
  await page.getByText('Tổng thu / chi theo đơn vị tiền', { exact: true }).click();
  await expect(page.getByText('Ngày nghiệp vụ theo Asia/Ho_Chi_Minh. Tính cả ngày đầu và ngày cuối; có thể chọn cùng một ngày. Nhập DD/MM/YYYY.', { exact: true })).toBeVisible();
  const singleDay = page.waitForRequest(request => { const url = new URL(request.url()); return url.pathname.endsWith('/books/book1/summary') && url.searchParams.get('from_on') === '2026-01-15' && url.searchParams.get('through_on') === '2026-01-15'; });
  await page.getByLabel('Từ ngày (bao gồm)', { exact: true }).fill('15/01/2026');
  await page.getByLabel('Đến hết ngày (bao gồm)', { exact: true }).fill('15/01/2026');
  await singleDay;
  await expect(page.getByText('Chọn đủ hai ngày hợp lệ DD/MM/YYYY; ngày bắt đầu không được sau ngày kết thúc.', { exact: true })).toHaveCount(0);
});
test('in-file duplicate pairs are displayed separately from published-book matches', async ({ page }) => {
  const writes = await setup(page);
  await page.getByRole('button', { name: 'Nhập Excel / CSV · mở job đã lưu' }).click();
  await page.getByRole('combobox', { name: 'Job import đã lưu' }).click(); await page.getByText('batch1 · READY_FOR_CONFIRM', { exact: false }).click();
  await page.getByRole('button', { name: 'Xem ứng viên trùng', exact: true }).click();
  const review = page.getByRole('dialog', { name: 'Ứng viên trùng · lựa chọn rõ ràng' });
  await expect(review.getByText('Ứng viên trong cùng tệp', { exact: true })).toBeVisible();
  await expect(review.getByText(/MATCH_IN_FILE/)).toBeVisible();
  await expect(review.getByText('Ứng viên trong sổ đã công bố', { exact: true })).toBeVisible();
  expect(writes).toHaveLength(0);
});
test('501-cell clipboard requires an explicit new CSV import and raw-byte upload, never a row JSON payload', async ({ page }) => {
  const writes = await setup(page); const text = Array.from({ length: 501 }, (_, index) => `CLIP-${index}`).join('\r\n');
  await paste(page, text);
  const choice = page.getByRole('button', { name: 'Đưa clipboard lớn vào lượt nhập mới', exact: true }); await expect(choice).toBeVisible();
  expect(writes).toHaveLength(0); await expect(page.getByRole('gridcell', { name: '001', exact: true })).toBeVisible();
  await choice.click(); const workspace = page.getByRole('dialog', { name: 'Nhập dữ liệu · Sổ tổng hợp' });
  await expect(workspace.getByText(/Tệp clipboard đã chuẩn bị:/)).toBeVisible(); expect(writes).toHaveLength(0);
  const profile = JSON.parse(await workspace.getByLabel('Profile import JSON').inputValue()); expect(profile).toMatchObject({ delimiter: '\t', header_row: 0, encoding: 'utf-8' });
  await workspace.getByRole('button', { name: 'Lưu gốc và tạo job', exact: true }).click();
  await expect(workspace.getByRole('grid', { name: 'Sổ kế toán theo ô' })).toBeVisible();
  await expect.poll(() => writes.length).toBe(2);
  expect(writes[0]).toEqual({ path: '/files', body: { raw: text, category: 'workbooks' } });
  expect(writes[1].path).toBe('/import-jobs'); expect(writes[1].body.profile).toMatchObject({ delimiter: '\t', header_row: 0, encoding: 'utf-8' });
  expect(Object.keys(writes[1].body).sort()).toEqual(['allow_duplicate_file', 'book_id', 'file_id', 'profile', 'request_key']);
  await expect(workspace.getByText('501 dòng theo bộ lọc · 1 dòng đã tải', { exact: true })).toBeVisible();
  await expect(workspace.getByText('Đã công bố vào sổ: 0', { exact: true })).toBeVisible();
  // A large paste in staging offers another NEW job; accepting does not patch
  // the existing stage or trigger an upload until its explicit create button.
  await workspace.getByRole('gridcell', { name: '001', exact: true }).click();
  await workspace.getByRole('grid').evaluate((node, value) => { const data = new DataTransfer(); data.setData('text/plain', value); node.dispatchEvent(new ClipboardEvent('paste', { bubbles: true, cancelable: true, clipboardData: data })); }, text);
  await workspace.getByRole('button', { name: 'Đưa clipboard lớn vào lượt nhập mới', exact: true }).click();
  expect(writes).toHaveLength(2); await workspace.getByRole('button', { name: 'Bỏ tệp clipboard', exact: true }).click();
  await expect(workspace.getByRole('button', { name: 'Lưu gốc và tạo job', exact: true })).toBeDisabled();
});
test('large clipboard cannot discard an existing dirty draft and prepared source clears on actor change', async ({ page }) => {
  const writes = await setup(page);
  await paste(page, 'bounded-first\nbounded-off-page'); await expect(page.getByText(/Vùng vượt trang đang tải/)).toBeVisible();
  await expect(page.getByRole('button', { name: 'Đưa clipboard lớn vào lượt nhập mới', exact: true })).toHaveCount(0);
  await paste(page, 'my-draft'); await page.getByRole('button', { name: 'Áp dụng vào nháp' }).click();
  await expect(page.getByRole('gridcell', { name: 'my-draft', exact: true })).toBeVisible();
  const text = 'x'.repeat(100001);
  await page.getByRole('grid').evaluate((node, value) => { const data = new DataTransfer(); data.setData('text/plain', value); node.dispatchEvent(new ClipboardEvent('paste', { bubbles: true, cancelable: true, clipboardData: data })); }, text);
  await expect(page.getByText('Lưu hoặc bỏ bản nháp hiện tại trước khi đưa clipboard lớn vào lượt nhập mới.', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Đưa clipboard lớn vào lượt nhập mới', exact: true })).toHaveCount(0);
  page.once('dialog', dialog => dialog.accept()); await page.getByRole('button', { name: 'Bỏ nháp', exact: true }).click();
  await paste(page, text); await page.getByRole('button', { name: 'Đưa clipboard lớn vào lượt nhập mới', exact: true }).click();
  await expect(page.getByText(/Tệp clipboard đã chuẩn bị:/)).toBeVisible(); expect(writes).toHaveLength(0);
  await page.evaluate(() => { (window as any).__testSession.getState().login('reader', { id: 'actor2', username: 'reader', role: 'operator', permissions: ['accounting.read'], version: 1 }); });
  await expect(page.getByRole('dialog', { name: 'Nhập dữ liệu · Sổ tổng hợp' })).toHaveCount(0);
  await expect(page.getByText(/Tệp clipboard đã chuẩn bị:/)).toHaveCount(0);
  expect(writes).toHaveLength(0);
});
test('invalid DateInput draft blocks automatic/manual summaries and cached preview while whole-book export remains usable', async ({ page }) => {
  const writes = await setup(page, false, false, true);
  const summaries: string[] = []; const comparisons: string[] = [];
  page.on('request', request => { const url = new URL(request.url()); if (url.pathname.endsWith('/books/book1/summary')) summaries.push(request.url()); if (url.pathname.endsWith('/import-jobs/batch1/summary')) comparisons.push(request.url()); });
  await page.getByText('Tổng thu / chi theo đơn vị tiền', { exact: true }).click();
  const from = page.getByLabel('Từ ngày (bao gồm)', { exact: true }); const through = page.getByLabel('Đến hết ngày (bao gồm)', { exact: true });
  const validPeriod = page.waitForResponse(response => { const url = new URL(response.url()); return url.pathname.endsWith('/books/book1/summary') && url.searchParams.get('from_on') === '2026-11-05' && url.searchParams.get('through_on') === '2026-11-06'; });
  await from.fill('05/11/2026'); await through.fill('06/11/2026'); await validPeriod;
  await expect(page.getByText('VND: thu 12.34 · chi 0.00', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Nhập Excel / CSV · mở job đã lưu' }).click();
  const workspace = page.getByRole('dialog', { name: 'Nhập dữ liệu · Sổ tổng hợp' });
  await workspace.getByRole('combobox', { name: 'Job import đã lưu' }).click(); await page.getByText('batch1 · READY_FOR_CONFIRM', { exact: false }).click();
  await workspace.getByText(/^Thu \/ chi trước và sau nhập dự kiến/).click();
  await expect(workspace.getByText(/Thu 20\.34/)).toBeVisible();
  await workspace.getByRole('button', { name: 'Đóng', exact: true }).click();
  const beforeSummary = summaries.length; const beforePreview = comparisons.length;
  await from.fill('31/02/2026'); await from.blur();
  await expect(from).toHaveValue('31/02/2026'); await expect(from).toHaveAttribute('aria-invalid', 'true');
  await expect(page.getByText('VND: thu 12.34 · chi 0.00', { exact: true })).toHaveCount(0);
  const refreshedBooks = page.waitForResponse(response => new URL(response.url()).pathname.endsWith('/accounting/books'));
  await page.getByRole('button', { name: 'Tải lại dữ liệu', exact: true }).click(); await refreshedBooks;
  expect(summaries).toHaveLength(beforeSummary);
  await page.getByRole('button', { name: 'Nhập Excel / CSV · mở job đã lưu' }).click();
  await workspace.getByText(/^Thu \/ chi trước và sau nhập dự kiến/).click();
  await expect(workspace.getByText('Chọn hai ngày hợp lệ DD/MM/YYYY trước khi xem dự kiến; ngày đầu không được sau ngày cuối.', { exact: true })).toBeVisible();
  await expect(workspace.getByText(/Thu 20\.34/)).toHaveCount(0); expect(comparisons).toHaveLength(beforePreview);
  await workspace.getByRole('button', { name: 'Đóng', exact: true }).click();
  await page.getByRole('button', { name: 'Xuất CSV', exact: true }).click();
  await expect.poll(() => writes.filter(write => write.path === '/books/book1/exports').length).toBe(1);
  expect(Object.keys(writes.find(write => write.path === '/books/book1/exports')!.body).sort()).toEqual(['format', 'request_key']);
  await expect(from).toHaveValue('31/02/2026');
  const corrected = page.waitForRequest(request => { const url = new URL(request.url()); return url.pathname.endsWith('/books/book1/summary') && url.searchParams.get('from_on') === '2026-11-01' && url.searchParams.get('through_on') === '2026-11-06'; });
  await from.fill('01/11/2026'); await corrected; await expect(from).toHaveValue('01/11/2026');
});
test('required and optional new-row dates retain invalid draft and never submit old ISO or implicit empty', async ({ page }) => {
  const writes = await setup(page, false, false, true);
  await page.getByRole('button', { name: 'Thêm dòng', exact: true }).click();
  const modal = page.getByRole('dialog', { name: 'Thêm dòng vào sổ' }); const save = modal.getByRole('button', { name: 'Xác nhận thêm dòng', exact: true });
  const day = modal.getByLabel('Dòng mới Ngày nghiệp vụ'); const due = modal.getByLabel('Dòng mới Hạn tùy chọn');
  await expect(save).toBeDisabled(); await day.fill('06/11/2026'); await due.fill('07/11/2026'); await expect(save).toBeEnabled();
  await due.fill('31/02/2026'); await due.blur(); await expect(due).toHaveValue('31/02/2026'); await expect(save).toBeDisabled();
  await expect(modal.getByText(/Hạn tùy chọn: ngày không hợp lệ/)).toBeVisible(); expect(writes).toHaveLength(0);
  await due.press('Enter'); expect(writes).toHaveLength(0);
  await due.fill('08/11/2026'); await save.click(); await expect.poll(() => writes.length).toBe(1);
  expect(writes[0]).toMatchObject({ path: '/books/book1/rows', body: { values: { day: '2026-11-06', due: '2026-11-08' } } });
  await page.getByRole('button', { name: 'Thêm dòng', exact: true }).click(); await day.fill('09/11/2026'); await due.fill('10/11/2026'); await due.fill('');
  await expect(save).toBeEnabled(); await due.fill('31/02/2026'); await expect(due).toHaveValue('31/02/2026'); await expect(save).toBeDisabled(); expect(writes).toHaveLength(1);
  await due.fill(''); await save.click();
  await expect.poll(() => writes.length).toBe(2); expect(writes[1].body.values).toMatchObject({ day: '2026-11-09', due: '' });
  await page.getByRole('button', { name: 'Thêm dòng', exact: true }).click(); await day.fill('31/02/2026');
  await expect(day).toHaveValue('31/02/2026'); await expect(save).toBeDisabled(); expect(writes).toHaveLength(2);
});
test('date filter builder, advanced JSON and direct URL all block invalid dates before rows network', async ({ page }) => {
  await setup(page, false, false, true); const rowRequests: string[] = [];
  page.on('request', request => { if (new URL(request.url()).pathname.endsWith('/books/book1/rows')) rowRequests.push(request.url()); });
  await page.getByText('Lọc toàn bộ sổ / xem dòng đã xóa', { exact: true }).click();
  await page.getByRole('combobox', { name: 'Cột lọc', exact: true }).click(); await page.locator('.ant-select-dropdown .ant-select-item-option-content').filter({ hasText: /^Ngày nghiệp vụ$/ }).click();
  const value = page.getByLabel('Giá trị lọc', { exact: true }); await value.fill('31/02/2026'); await value.blur();
  await expect(value).toHaveValue('31/02/2026'); await expect(page.getByRole('button', { name: 'Thêm điều kiện', exact: true })).toBeDisabled(); expect(rowRequests).toHaveLength(0);
  await value.fill('06/11/2026'); await page.getByRole('button', { name: 'Thêm điều kiện', exact: true }).click();
  await value.fill('31/02/2026'); await expect(value).toHaveValue('31/02/2026'); await expect(page.getByRole('button', { name: 'Áp dụng bộ lọc', exact: true })).toBeDisabled(); expect(rowRequests).toHaveLength(0);
  await value.fill('06/11/2026');
  await page.getByText('Nâng cao: JSON bộ lọc', { exact: true }).click();
  const invalid = JSON.stringify([{ column_id: 'day', op: 'eq', value: '31/02/2026' }]); const json = page.getByLabel('Bộ lọc sổ JSON');
  await json.fill(invalid); await page.getByRole('button', { name: 'Áp dụng bộ lọc', exact: true }).click();
  await expect(page.getByText(/Ngày nghiệp vụ: ngày lọc không hợp lệ/).first()).toBeVisible(); expect(rowRequests).toHaveLength(0); await expect(json).toHaveValue(invalid);
  await page.evaluate(filters => { location.hash = `/accounting?filters=${encodeURIComponent(filters)}`; }, invalid);
  await expect(page).toHaveURL(/filters=/); const refreshed = page.waitForResponse(response => new URL(response.url()).pathname.endsWith('/accounting/books'));
  await page.getByRole('button', { name: 'Tải lại dữ liệu', exact: true }).click(); await refreshed; expect(rowRequests).toHaveLength(0);
  const valid = JSON.stringify([{ column_id: 'day', op: 'eq', value: '2026-11-08' }]); await json.fill(valid);
  const requested = page.waitForRequest(request => { const url = new URL(request.url()); return url.pathname.endsWith('/books/book1/rows') && url.searchParams.get('filters') === valid; });
  await page.getByRole('button', { name: 'Áp dụng bộ lọc', exact: true }).click(); await requested;
  expect(JSON.parse(new URL(rowRequests.at(-1)!).searchParams.get('filters')!)[0].value).toBe('2026-11-08');
});
