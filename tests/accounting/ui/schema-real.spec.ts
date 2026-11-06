import { test, expect } from '../../../frontend/node_modules/@playwright/test';
import { spawn, type ChildProcessWithoutNullStreams } from 'node:child_process';
import { randomBytes } from 'node:crypto';
import { mkdtemp, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import type { Book } from '../../../frontend/src/features/accounting/types';
import { gate, mountSchema, prepareSchema, schemaLocked, submitSchema } from './schema-fixture';
import { HARNESS_ORIGIN } from './harness-origin';

for (const mode of ['create', 'patch'] as const) test(`real ${mode}: commit then lost ACK replays exactly once without another book/schema revision`, async ({ page }) => {
  const repository = path.resolve(__dirname, '../../..'); const root = await mkdtemp(path.join(tmpdir(), 'cafe-fin-schema-retry-'));
  const token = randomBytes(32).toString('hex'); let child: ChildProcessWithoutNullStreams | undefined;
  const ack = gate(); const committed = gate(); const writes: { method: string; path: string; body: string }[] = []; const evidence: Record<string, unknown> = { mode, real_backend: true, lost_ack_after_real_success: false };
  try {
    child = spawn(path.join(repository, '.venv/Scripts/python.exe'), [path.join(repository, 'tests/accounting/ui/serve.py')], { cwd: repository, windowsHide: true, env: { ...process.env, PYTHONUTF8: '1', PYTHONPATH: path.join(repository, 'backend') }, stdio: 'pipe' });
    const hello = new Promise<{ status: string; api_base: string }>((resolve, reject) => {
      let output = ''; const timer = setTimeout(() => reject(new Error('Synthetic schema sidecar startup timeout.')), 20000);
      child!.once('error', reject); child!.once('exit', () => { clearTimeout(timer); reject(new Error('Synthetic schema sidecar exited.')); });
      child!.stdout.on('data', chunk => { output += String(chunk); if (output.includes('\n')) { clearTimeout(timer); resolve(JSON.parse(output.slice(0, output.indexOf('\n')))); } });
    });
    child.stdin.write(JSON.stringify({ protocol_version: 1, data_root: root, initialize: true, session_token: token, allowed_origin: HARNESS_ORIGIN }) + '\n');
    const ready = await hello; expect(ready.status).toBe('ready');
    const setup = await fetch(`${ready.api_base}/auth/setup`, { method: 'POST', headers: { 'X-App-Session': token, 'Content-Type': 'application/json', Origin: HARNESS_ORIGIN }, body: JSON.stringify({ username: 'schema_synthetic', password: 'Synthetic-schema-only-2026' }) });
    expect(setup.status).toBe(200); const auth = await setup.json();
    const headers = { 'X-App-Session': token, Authorization: `Bearer ${auth.access_token}`, 'Content-Type': 'application/json', Origin: HARNESS_ORIGIN };
    const api = async (endpoint: string, body?: object) => { const response = await fetch(`${ready.api_base}/accounting${endpoint}`, { headers, ...(body ? { method: 'POST', body: JSON.stringify(body) } : {}) }); expect(response.status).toBe(200); return response.json(); };
    const initialBook: Book | undefined = mode === 'patch' ? await api('/books', { name: 'Synthetic schema seed', columns: [{ id: 'code', name: 'Mã seed', kind: 'text', editable: true }], semantics: {}, request_key: randomBytes(16).toString('hex') }) : undefined;
    const endpoint = initialBook ? `/books/${initialBook.id}/schema` : '/books';
    // Forward to the REAL server first. Only the acknowledgement is dropped;
    // no synthetic API response or commit result is substituted.
    await page.route(`**/api/v1/accounting${endpoint}`, async route => {
      writes.push({ method: route.request().method(), path: new URL(route.request().url()).pathname, body: route.request().postData()! });
      const response = await route.fetch(); expect(response.status()).toBe(200);
      if (writes.length === 1) { evidence.lost_ack_after_real_success = true; committed.release(); await ack.promise; return route.abort('failed'); }
      await route.fulfill({ response });
    });
    await mountSchema(page, { book: initialBook, boot: { protocol_version: 1, api_base: ready.api_base, session_token: token, data_root: root }, token: auth.access_token, user: auth.user });
    await prepareSchema(page, mode === 'create'); await submitSchema(page); await committed.promise;
    const before = await api('/books'); expect(before.total).toBe(1);
    const committedBook = before.items[0] as Book; expect(committedBook.schema_revision).toBe(mode === 'patch' ? initialBook!.schema_revision + 1 : 1);
    await schemaLocked(page); await page.getByRole('dialog').locator('.ant-modal-footer button').last().evaluate(node => (node as HTMLElement).click()); expect(writes).toHaveLength(1);
    ack.release(); await expect(page.getByText('Chưa xác nhận cấu hình đã lưu.', { exact: true })).toBeVisible(); await schemaLocked(page);
    await submitSchema(page);
    await expect(page.getByLabel('Saved callbacks')).toHaveText('1'); await expect(page.getByLabel('Closed callbacks')).toHaveText('1');
    const after = await api('/books'); expect(after.total).toBe(1); expect(after.items[0]).toEqual(committedBook);
    expect(writes).toHaveLength(2); expect(writes[1]).toEqual(writes[0]);
    const body = JSON.parse(writes[0].body); expect(body.columns[0].name).toBe('Mã ACK A'); expect(body.semantics).toMatchObject({ income_value: 'thu', expense_value: 'chi' });
    expect(body.expected_version).toBe(initialBook?.version);
    Object.assign(evidence, { status: 'PASS', writes, before: { books: before.total, version: committedBook.version, schema_revision: committedBook.schema_revision }, after: { books: after.total, version: after.items[0].version, schema_revision: after.items[0].schema_revision }, saved_callbacks: 1, closed_callbacks: 1 });
    await page.screenshot({ path: test.info().outputPath('schema-real-confirmed.png'), fullPage: true });
  } finally {
    ack.release();
    if (child && child.exitCode === null) { child.stdin.write('{"command":"shutdown"}\n'); child.stdin.end(); await new Promise<void>(resolve => { const timer = setTimeout(() => { child?.kill(); resolve(); }, 10000); child!.once('exit', () => { clearTimeout(timer); resolve(); }); }); }
    await writeFile(test.info().outputPath('schema-real-evidence.json'), JSON.stringify(evidence, null, 2));
    await test.info().attach('schema-real-evidence', { path: test.info().outputPath('schema-real-evidence.json'), contentType: 'application/json' });
    // Synthetic credentials/data only; this test never touches benchmark roots.
    expect(path.dirname(path.resolve(root)).toLowerCase()).toBe(path.resolve(tmpdir()).toLowerCase());
    expect(path.basename(root).startsWith('cafe-fin-schema-retry-')).toBe(true);
    await rm(root, { recursive: true, force: true });
  }
});
