import { expect, type Page } from '../../../frontend/node_modules/@playwright/test';
import type { Book } from '../../../frontend/src/features/accounting/types';
export const schemaBook: Book = { id: 'book-schema', name: 'Sổ schema synthetic', version: 3, schema_revision: 3, data_revision: 1, columns: [{ id: 'code', name: 'Mã', kind: 'text', editable: true }], semantics: {} };
export const schemaUser = { id: 'schema-admin', username: 'schema_admin', role: 'admin', permissions: ['*'], version: 1 };
export function gate() { let release!: () => void; const promise = new Promise<void>(resolve => { release = resolve; }); return { promise, release }; }
export async function submitSchema(page: Page) {
  const submit = page.getByRole('dialog').locator('.ant-modal-footer button').last();
  // AntD can retain an exiting loading-icon node in the accessible name after
  // loading=false. Check the actual button state, then use its stable footer.
  await expect(submit).not.toHaveClass(/ant-btn-loading/);
  await submit.click();
}
export async function mountSchema(page: Page, options: { book?: Book; advanceOnSaved?: boolean; boot?: object; token?: string; user?: object } = {}) {
  await page.goto('/__accounting_schema_harness');
  await expect.poll(() => page.evaluate(() => typeof (window as any).__schemaMount)).toBe('function');
  await page.evaluate(options => (window as any).__schemaMount({ boot: { protocol_version: 1, api_base: location.origin + '/api/v1', session_token: 'synthetic-session', data_root: 'synthetic' }, token: 'synthetic', user: { id: 'schema-admin', username: 'schema_admin', role: 'admin', permissions: ['*'], version: 1 }, ...options }), options);
  await expect(page.getByRole('dialog')).toBeVisible();
}
export async function prepareSchema(page: Page, create = true) {
  if (create) { await page.getByLabel('Tên sổ', { exact: true }).fill('Synthetic ACK A'); await page.getByRole('button', { name: 'Thêm cột', exact: true }).click(); }
  await page.getByLabel('Tên cột 1', { exact: true }).fill('Mã ACK A');
  await page.getByLabel('Giá trị chiều thu', { exact: true }).fill('thu');
  await page.getByLabel('Giá trị chiều chi', { exact: true }).fill('chi');
  // Advanced JSON is deliberately collapsed until requested.
  await expect(page.getByLabel('Ngữ nghĩa sổ JSON')).toBeHidden();
  await page.getByText('Ngữ nghĩa nâng cao: JSON (ID cột ổn định)', { exact: true }).click();
}
export async function schemaLocked(page: Page) {
  const modal = page.getByRole('dialog');
  await expect(page.getByLabel('Tên sổ', { exact: true })).toBeDisabled();
  for (const control of await modal.locator('input, textarea').all()) await expect(control).toBeDisabled();
  await expect(modal.getByRole('button', { name: 'Thêm cột', exact: true })).toBeDisabled();
  await expect(modal.getByRole('button', { name: 'Bỏ cột', exact: true })).toBeDisabled();
  await expect(modal.getByRole('button', { name: '↑', exact: true })).toBeDisabled();
  await expect(modal.locator('.ant-modal-footer button').first()).toBeDisabled();
  await expect(modal.locator('.ant-modal-close')).toHaveCount(0);
  // Even synthetic DOM events or a second immediate submission cannot alter the
  // frozen state or start a second command while the first response is pending.
  await page.getByLabel('Tên cột 1', { exact: true }).evaluate(node => {
    const input = node as HTMLInputElement; const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!;
    setter.call(input, 'Mã ACK B'); input.dispatchEvent(new Event('input', { bubbles: true }));
  });
  await page.keyboard.press('Escape'); await expect(modal).toBeVisible();
}
