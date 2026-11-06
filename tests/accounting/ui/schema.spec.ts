import { test, expect } from '../../../frontend/node_modules/@playwright/test';
import { gate, mountSchema, prepareSchema, schemaBook, schemaLocked, schemaUser, submitSchema } from './schema-fixture';

for (const mode of ['create', 'patch'] as const) test(`${mode}: uncertain command locks every editor control and retries the exact body/key/version`, async ({ page }) => {
  const received = gate(); const ack = gate(); const writes: { method: string; path: string; body: string }[] = [];
  await page.route('**/api/v1/accounting/**', async route => {
    writes.push({ method: route.request().method(), path: new URL(route.request().url()).pathname, body: route.request().postData()! });
    if (writes.length === 1) { received.release(); await ack.promise; return route.abort('failed'); }
    const payload = JSON.parse(writes[0].body);
    await route.fulfill({ json: { ...schemaBook, name: payload.name ?? schemaBook.name, columns: payload.columns, semantics: payload.semantics } });
  });
  await mountSchema(page, { book: mode === 'patch' ? schemaBook : undefined }); await prepareSchema(page, mode === 'create');
  await submitSchema(page); await received.promise;
  await schemaLocked(page);
  await page.getByRole('dialog').locator('.ant-modal-footer button').last().evaluate(node => (node as HTMLElement).click());
  expect(writes).toHaveLength(1); ack.release();
  await expect(page.getByText('Chưa xác nhận cấu hình đã lưu.', { exact: true })).toBeVisible(); await schemaLocked(page);
  if (mode === 'patch') await page.evaluate(book => (window as any).__schemaSetBook(book), { ...schemaBook, version: 99, columns: [] });
  await submitSchema(page);
  await expect(page.getByLabel('Saved callbacks')).toHaveText('1'); await expect(page.getByLabel('Closed callbacks')).toHaveText('1');
  expect(writes).toHaveLength(2); expect(writes[1]).toEqual(writes[0]);
  expect(JSON.parse(writes[0].body)).toMatchObject({ columns: [{ name: 'Mã ACK A' }], semantics: { income_value: 'thu', expense_value: 'chi' } });
  expect(JSON.parse(writes[0].body).expected_version).toBe(mode === 'patch' ? 3 : undefined);
});

for (const code of ['VALIDATION_ERROR', 'VERSION_CONFLICT']) test(`${code}: definitive rejection unlocks editing and a changed payload gets a fresh key`, async ({ page }) => {
  const writes: any[] = [];
  await page.route('**/api/v1/accounting/**', async route => {
    writes.push(route.request().postDataJSON());
    if (writes.length === 1) return route.fulfill({ status: code === 'VALIDATION_ERROR' ? 422 : 409, json: { error: { code, message: 'Synthetic definitive rejection', field_errors: [] } } });
    await route.fulfill({ json: schemaBook });
  });
  await mountSchema(page, { book: schemaBook }); await prepareSchema(page, false);
  await submitSchema(page);
  await expect(page.getByText('Synthetic definitive rejection', { exact: true })).toBeVisible();
  await expect(page.getByLabel('Tên cột 1', { exact: true })).toBeEnabled(); await expect(page.getByRole('button', { name: 'Thêm cột', exact: true })).toBeEnabled();
  await page.getByLabel('Tên cột 1', { exact: true }).fill('Mã corrected');
  await submitSchema(page); await expect(page.getByLabel('Saved callbacks')).toHaveText('1');
  expect(writes[1].request_key).not.toBe(writes[0].request_key); expect(writes[1].columns[0].name).toBe('Mã corrected');
});

test('local JSON rejection never freezes a command and unknown server failure stays uncertain', async ({ page }) => {
  let writes = 0;
  await page.route('**/api/v1/accounting/**', route => { writes++; return route.fulfill({ status: 500, json: { error: { code: 'INTERNAL_ERROR', message: 'Synthetic unknown outcome' } } }); });
  await mountSchema(page); await prepareSchema(page);
  await page.getByLabel('Ngữ nghĩa sổ JSON').fill('[]'); await submitSchema(page);
  await expect(page.getByText('Ngữ nghĩa phải là một object JSON.', { exact: true })).toBeVisible(); expect(writes).toBe(0);
  await expect(page.getByLabel('Tên sổ', { exact: true })).toBeEnabled(); await page.getByLabel('Ngữ nghĩa sổ JSON').fill('{}');
  await submitSchema(page); await expect(page.getByText('Chưa xác nhận cấu hình đã lưu.', { exact: true })).toBeVisible(); await schemaLocked(page);
});

for (const change of ['generation', 'open-epoch'] as const) test(`${change}: late success cannot save/close or leak the old payload into the new editor`, async ({ page }) => {
  const received = gate(); const ack = gate(); const writes: any[] = [];
  await page.route('**/api/v1/accounting/**', async route => {
    writes.push(route.request().postDataJSON());
    if (writes.length === 1) { received.release(); await ack.promise; }
    await route.fulfill({ json: schemaBook }).catch(() => {});
  });
  await mountSchema(page); await prepareSchema(page); await submitSchema(page); await received.promise;
  if (change === 'generation') {
    await page.evaluate(user => (window as any).__schemaSession.getState().login('new-synthetic-token', user), { ...schemaUser, id: 'actor-new' });
    await expect(page.getByRole('dialog')).toBeHidden();
    await expect(page.locator('input[aria-label="Tên sổ"]')).toHaveCount(0);
    await expect(page.locator('input[aria-label="Tên cột 1"]')).toHaveCount(0);
    await page.evaluate(() => (window as any).__schemaClose());
    await page.evaluate(() => (window as any).__schemaOpen()); await expect(page.getByRole('dialog')).toBeVisible();
  } else {
    await page.evaluate(() => (window as any).__schemaClose()); await expect(page.getByRole('dialog')).toBeHidden();
    await page.evaluate(() => (window as any).__schemaOpen()); await expect(page.getByRole('dialog')).toBeVisible();
  }
  await page.getByLabel('Tên sổ', { exact: true }).fill('New scope'); ack.release();
  await page.waitForTimeout(150);
  await expect(page.getByLabel('Saved callbacks')).toHaveText('0'); await expect(page.getByLabel('Closed callbacks')).toHaveText('0'); await expect(page.getByLabel('Tên sổ', { exact: true })).toHaveValue('New scope');
  await submitSchema(page); await expect(page.getByLabel('Saved callbacks')).toHaveText('1');
  expect(writes).toHaveLength(2); expect(writes[1].name).toBe('New scope'); expect(writes[1].columns).toEqual([]); expect(writes[1].semantics).toEqual({}); expect(writes[1].request_key).not.toBe(writes[0].request_key);
});

test('session change inside onSaved suppresses the following old onClose callback', async ({ page }) => {
  await page.route('**/api/v1/accounting/**', route => route.fulfill({ json: schemaBook }));
  await mountSchema(page, { advanceOnSaved: true }); await prepareSchema(page); await submitSchema(page);
  await expect(page.getByLabel('Saved callbacks')).toHaveText('1'); await expect(page.getByLabel('Closed callbacks')).toHaveText('0'); await expect(page.getByRole('dialog')).toBeHidden();
});

test('actor reset during uncertain PATCH retires the old target and payload until a new open epoch', async ({ page }) => {
  const writes: any[] = [];
  await page.route('**/api/v1/accounting/**', async route => {
    writes.push({ path: new URL(route.request().url()).pathname, body: route.request().postDataJSON() });
    if (writes.length === 1) return route.abort('failed');
    await route.fulfill({ json: schemaBook });
  });
  await mountSchema(page, { book: schemaBook }); await prepareSchema(page, false);
  await submitSchema(page); await expect(page.getByText('Chưa xác nhận cấu hình đã lưu.', { exact: true })).toBeVisible();
  await page.evaluate(user => (window as any).__schemaSession.getState().login('new-synthetic-token', user), { ...schemaUser, id: 'actor-new' });
  await expect(page.getByRole('dialog')).toBeHidden(); await expect(page.locator('input[aria-label="Tên sổ"]')).toHaveCount(0);
  await expect(page.getByLabel('Saved callbacks')).toHaveText('0'); await expect(page.getByLabel('Closed callbacks')).toHaveText('0');
  await page.evaluate(() => (window as any).__schemaClose()); await page.evaluate(() => (window as any).__schemaOpen());
  await expect(page.getByRole('dialog', { name: 'Tạo sổ độc lập', exact: true })).toBeVisible();
  await page.getByLabel('Tên sổ', { exact: true }).fill('New actor book'); await submitSchema(page);
  await expect(page.getByLabel('Saved callbacks')).toHaveText('1'); expect(writes[1].path).toBe('/api/v1/accounting/books');
  expect(writes[1].body).toMatchObject({ name: 'New actor book', columns: [], semantics: {} }); expect(writes[1].body.expected_version).toBeUndefined(); expect(writes[1].body.request_key).not.toBe(writes[0].body.request_key);
});
