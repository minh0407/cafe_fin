import { test, expect, type Page } from '../../../frontend/node_modules/@playwright/test';
const initial = { id: 'row1', version: 3, logical_row: 1, values: { code: '001', amount: '92233720368547758.07' }, issues: [] };
const book = { id: 'book1', name: 'Sổ tổng hợp', version: 1, schema_revision: 1, data_revision: 1, columns: [{ id: 'code', name: 'Mã', kind: 'text', editable: true }, { id: 'amount', name: 'Số tiền', kind: 'money', editable: true }], semantics: {} };
const batch = { id: 'batch1', book_id: 'book1', file_id: 'file1', state: 'READY_FOR_CONFIRM', version: 7, revision: 4, mapping_revision: 2, decision_revision: 3, validation_token: 'validated-exact-revisions', mapping: { code: 'A', amount: 'B' }, profile: {}, counts: { source_rows: 5, valid: 3, invalid: 1, potential_duplicates: 1, excluded: 0, published_rows: 0, staged_committed_rows: 0, pending: 5 } };
async function setup(page: Page, conflict = false, secondRow = false) {
  page.on('pageerror', error => console.error('Browser error:', error.message));
  page.on('console', message => { if (message.type() === 'error') console.error('Browser console:', message.text()); });
  const writes: { path: string; body: any }[] = []; let row = structuredClone(initial);
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
      const body = request.postDataJSON(); writes.push({ path, body });
      if (path === '/rows/row1') {
        if (conflict) return respond({ error: { code: 'VERSION_CONFLICT', message: 'Phiên bản mới đã được ghi.', field_errors: [] } }, 409);
        row = { ...row, version: 4, values: body.values }; return respond(row);
      }
      if (path === '/import-jobs/batch1/confirm') return respond({ ...batch, state: 'COMMITTING' });
      return respond(batch);
    }
    if (path === '/books') return respond({ items: [book], total: 1, page: 1, page_size: 200 });
    if (path === '/books/book1/rows') return respond({ items: [row, ...(secondRow ? [{ ...initial, id: 'row2', version: 1, logical_row: 2, values: { code: '002', amount: '1.00' } }] : [])], total: secondRow ? 2 : 1, page: 1, page_size: 200 });
    if (path === '/rows/row1') return respond({ ...initial, version: 4, values: { code: 'OTHER', amount: '11.00' } });
    if (path === '/books/book1/summary') return respond({ totals: {}, has_valid_money_mapping: false, validation_flags: ['MAPPING_REQUIRED'] });
    if (path === '/import-jobs') return respond({ items: [batch], total: 1, page: 1, page_size: 50 });
    if (path === '/import-jobs/batch1') return respond(batch);
    if (path === '/import-jobs/batch1/summary') return respond({ before: { totals: {}, has_valid_money_mapping: false }, new_batch: {}, after: {}, provisional: true });
    if (path === '/import-jobs/batch1/staging') return respond({ items: [{ row_id: 'stage1', revision: 1, source_sheet: 'Sheet1', source_row: 2, raw_values: { A: '001', B: '12.00' }, typed_values: { code: '001', amount: '12.00' }, edited_values: {}, issues: [], duplicate_count: 0, decision: null, imported: false }], total: 1, page: 1, page_size: 200 });
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
