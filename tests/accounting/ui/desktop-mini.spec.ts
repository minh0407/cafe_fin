import { test, expect, type Locator } from '../../../frontend/node_modules/@playwright/test';
import { spawn, execFileSync, type ChildProcessWithoutNullStreams } from 'node:child_process';
import { createHash, randomBytes } from 'node:crypto';
import { mkdtemp, readFile, stat, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { encodeTSV } from '../../../frontend/src/features/accounting/drafts';
import type { Batch, Book, StageRow, Values } from '../../../frontend/src/features/accounting/types';
import { HARNESS_ORIGIN } from './harness-origin';

const BASELINE = 'eab8c96b851f039de515083189f4301cc09437c0';
const sha = (bytes: Buffer) => createHash('sha256').update(bytes).digest('hex');
const recordPath = (value: string | { path: string }) => typeof value === 'string' ? value : value.path;
async function jsonLines<T>(filename: string | { path: string }): Promise<T[]> { return (await readFile(recordPath(filename), 'utf8')).split(/\r?\n/).filter(Boolean).map(line => JSON.parse(line) as T); }
function deferred() { let resolve!: () => void; const promise = new Promise<void>(done => { resolve = done; }); return { promise, resolve }; }
async function paste(grid: Locator, text: string) { await grid.evaluate((node, text) => { const clipboardData = new DataTransfer(); clipboardData.setData('text/plain', text); node.dispatchEvent(new ClipboardEvent('paste', { bubbles: true, cancelable: true, clipboardData })); }, text); }

test('source desktop mini1000: sheet/header, bounded preview edits, duplicates, partial/resume/repair and immutable original', async ({ page }) => {
  const repository = path.resolve(__dirname, '../../..');
  const git = (args: string[]) => execFileSync('git', args, { cwd: repository, encoding: 'utf8', windowsHide: true }).trim();
  const harnessHead = git(['rev-parse', 'HEAD']);
  const productPaths = ['backend', 'frontend/src', 'desktop'];
  // Tests/docs may be committed after the approved product source. Require its
  // ancestry and unchanged, clean product paths rather than pinning harness HEAD.
  git(['merge-base', '--is-ancestor', BASELINE, harnessHead]);
  expect(git(['diff', '--no-ext-diff', '--name-only', BASELINE, '--', ...productPaths]), 'Product paths must still match the approved baseline.').toBe('');
  expect(git(['status', '--porcelain=v1', '--untracked-files=all', '--', ...productPaths]), 'Product paths must have no staged, unstaged or untracked changes.').toBe('');
  const manifestPath = process.env.CAFE_FIN_MINI_MANIFEST;
  expect(manifestPath, 'Generate the synthetic1000 fixture kit and supply CAFE_FIN_MINI_MANIFEST.').toBeTruthy();
  const manifest = JSON.parse(await readFile(manifestPath!, 'utf8'));
  const format = process.env.CAFE_FIN_MINI_FORMAT ?? 'xlsm'; expect(['xlsx', 'xlsm']).toContain(format);
  const fixture = manifest.files[format]; const source = recordPath(fixture); const sourceBefore = await readFile(source); const sourceStat = await stat(source);
  expect(sourceBefore.length).toBe(fixture.bytes); expect(sha(sourceBefore)).toBe(fixture.sha256);
  expect(fixture.profile).toMatchObject({ sheet_id: '2', header_row: 3 });
  const scenario = fixture.scenarios.skip_first_duplicate;
  expect(scenario).toMatchObject({ duplicate_source_row: 5, first_published: 982, final_published: 999, excluded: 1 });
  const expectedIssues = await jsonLines<{ source_sheet: string; source_row: number; cell: string; code: string; severity: string }>(fixture.issue_jsonl);
  const repairs = await jsonLines<{ source_sheet: string; source_row: number; values: Values }>(fixture.repair_jsonl);
  expect(repairs).toHaveLength(17);
  const python = process.env.CAFE_FIN_MINI_PYTHON ?? path.join(repository, '.venv/Scripts/python.exe');
  const root = await mkdtemp(path.join(tmpdir(), 'cafe-fin-desktop-mini-data-'));
  const token = randomBytes(32).toString('hex'); const password = `Synthetic-mini-${randomBytes(24).toString('base64url')}`;
  const evidence: Record<string, any> = { status: 'RUNNING', scope: 'source Vite/Chromium + real source Python HTTP backend; NOT native/packaged/clean-client', baseline: BASELINE, product_baseline: BASELINE, harness_head: harnessHead, product_paths: productPaths, product_guard: { baseline_is_ancestor: true, baseline_diff_empty: true, worktree_clean: true }, market_network: '0', fixture_manifest: manifestPath, format, source_sha256: fixture.sha256, source_bytes: sourceBefore.length, synthetic_data_root: root, checkpoints: [], staging_responses: [], page_errors: [], non_loopback_browser_requests: [], unknown_ack: {}, native_gui: 'NOT RUN: no approved05 artifact provided to this driver', limitations: ['A1000-row case is not a bulk benchmark.', 'Native invokes only bootstrap the source App; this does not test Tauri/WebView2, installer, tray, startup, native lifecycle or offline client.', 'Clipboard coverage dispatches browser copy/paste events through the actual grid handlers; OS clipboard integration remains native NOT RUN.', 'Controlled interruption uses the real cancel API immediately after an accepted confirm; it is not a process-crash or power-loss test.', 'Pending-chunk visibility is claimed only if a nonzero pending checkpoint is actually observed.'] };
  let child: ChildProcessWithoutNullStreams | undefined; const releaseAck = deferred(); const intercepted = deferred();
  page.on('pageerror', error => evidence.page_errors.push(error.message));
  page.on('request', request => { const url = new URL(request.url()); if (['http:', 'https:'].includes(url.protocol) && !['127.0.0.1', 'localhost'].includes(url.hostname)) evidence.non_loopback_browser_requests.push(url.origin); });
  page.on('response', async response => { if (response.request().method() === 'GET' && /\/accounting\/import-jobs\/[^/]+\/staging$/.test(new URL(response.url()).pathname)) { try { const data = await response.json(); evidence.staging_responses.push({ status: response.status(), total: data.total, page: data.page, items: data.items?.length }); } catch { /* navigation may cancel a response */ } } });
  try {
    child = spawn(python, [path.join(repository, 'tests/accounting/ui/serve.py')], { cwd: repository, windowsHide: true, stdio: 'pipe', env: { ...process.env, PYTHONUTF8: '1', PYTHONPATH: path.join(repository, 'backend'), CAFE_FIN_MARKET_NETWORK: '0' } });
    const hello = new Promise<{ status: string; api_base: string }>((resolve, reject) => {
      let output = ''; const timer = setTimeout(() => reject(new Error('Mini sidecar startup timeout.')), 20000);
      child!.once('error', reject); child!.once('exit', () => { clearTimeout(timer); reject(new Error('Mini sidecar exited during bootstrap.')); });
      child!.stdout.on('data', chunk => { output += String(chunk); if (output.includes('\n')) { clearTimeout(timer); resolve(JSON.parse(output.slice(0, output.indexOf('\n')))); } });
    });
    child.stdin.write(JSON.stringify({ protocol_version: 1, data_root: root, initialize: true, session_token: token, allowed_origin: HARNESS_ORIGIN }) + '\n');
    const ready = await hello; expect(ready.status).toBe('ready');
    const initialHeaders = { 'X-App-Session': token, 'Content-Type': 'application/json', Origin: HARNESS_ORIGIN };
    const setup = await fetch(`${ready.api_base}/auth/setup`, { method: 'POST', headers: initialHeaders, body: JSON.stringify({ username: 'desktop_mini_synthetic', password }) }); expect(setup.status).toBe(200); const auth = await setup.json();
    const headers = { ...initialHeaders, Authorization: `Bearer ${auth.access_token}` };
    const api = async (endpoint: string, method = 'GET', body?: object) => { const response = await fetch(`${ready.api_base}/accounting${endpoint}`, { method, headers, ...(body ? { body: JSON.stringify(body) } : {}), signal: AbortSignal.timeout(30000) }); expect(response.status, `${method} ${endpoint}`).toBe(200); return response.json(); };
    const book: Book = await api('/books', 'POST', { ...manifest.book, request_key: randomBytes(16).toString('hex') });
    const boot = { protocol_version: 1, api_base: ready.api_base, session_token: token, data_root: root };
    // Only native bootstrap is substituted. Registry, App, login and accounting UI
    // are production source modules; no entry-module or API response replacement.
    await page.addInitScript(boot => { Object.assign(window, { __TAURI_INTERNALS__: { invoke: async (command: string) => { if (command === 'desktop_status') return { data_root: boot.data_root, running: true, runtime_state: 'ACTIVE' }; if (command === 'start_backend') return boot; throw new Error(`Unexpected native command: ${command}`); } } }); }, boot);
    await page.goto(`/#/accounting?book=${encodeURIComponent(book.id)}`);
    await page.getByLabel('Tên đăng nhập').fill('desktop_mini_synthetic'); await page.getByLabel('Mật khẩu', { exact: true }).fill(password); await page.getByRole('button', { name: 'Đăng nhập', exact: true }).click();
    await expect(page.getByRole('grid', { name: 'Sổ kế toán theo ô' })).toBeVisible();
    await page.getByRole('button', { name: 'Nhập Excel / CSV · mở job đã lưu', exact: true }).click();
    const workspace = page.getByRole('dialog', { name: `Nhập dữ liệu · ${book.name}`, exact: true });
    const initialProfile = { ...fixture.profile, sheet_id: '1', header_row: 1 }; delete initialProfile.start_row; delete initialProfile.end_row;
    await workspace.getByLabel('Profile import JSON').fill(JSON.stringify(initialProfile)); await workspace.getByLabel('Tệp import').setInputFiles(source);
    const uploadedResponse = page.waitForResponse(response => response.request().method() === 'POST' && new URL(response.url()).pathname.endsWith('/accounting/import-jobs'));
    await workspace.getByRole('button', { name: 'Lưu gốc và tạo job', exact: true }).click(); const uploaded: Batch = await (await uploadedResponse).json();
    await expect.poll(async () => (await api(`/import-jobs/${uploaded.id}`)).state).toBe('READY_FOR_MAPPING');
    await workspace.getByText('Sheet, profile và mapping cột', { exact: true }).click();
    await workspace.getByRole('combobox', { name: 'Sheet nguồn', exact: true }).click(); await page.locator('.ant-select-dropdown:visible').getByText('Sổ cà phê', { exact: true }).click();
    await workspace.getByText('Dòng header', { exact: true }).locator('input').fill('3');
    await workspace.getByText('Bắt đầu', { exact: true }).locator('input').fill('4');
    for (const column of book.columns) await workspace.getByLabel(`Mapping ${column.name}`, { exact: true }).fill(fixture.mapping[column.id]);
    expect(JSON.parse(await workspace.getByLabel('Profile mapping JSON').inputValue())).toMatchObject({ sheet_id: '2', header_row: 3, start_row: 4 });
    await workspace.getByRole('button', { name: 'Lưu mapping / profile · làm mới validation', exact: true }).click();
    await expect.poll(async () => (await api(`/import-jobs/${uploaded.id}`)).state).toBe('READY_FOR_MAPPING');
    await expect.poll(async () => (await api(`/import-jobs/${uploaded.id}/staging?page_size=200`)).total).toBe(1000);
    await expect(workspace.getByText('1000 dòng theo bộ lọc · 200 dòng đã tải', { exact: true })).toBeVisible();
    const grid = workspace.getByRole('grid');
    const gridRow = (sourceRow: number) => grid.getByRole('row').filter({ has: page.getByRole('gridcell', { name: `2!${sourceRow}`, exact: true }) });
    const amountCell = gridRow(6).getByRole('gridcell').nth(3);
    await amountCell.dblclick(); const editor = grid.getByRole('textbox'); await editor.fill('123.45'); await editor.press('Enter');
    page.once('dialog', dialog => dialog.accept()); await workspace.getByRole('button', { name: 'Lưu bản nháp', exact: true }).click();
    await expect.poll(async () => (await api(`/import-jobs/${uploaded.id}/staging?page_size=200`)).items.find((row: StageRow) => row.source_row === 6).edited_values.amount).toBe('123.45');
    const stageBefore = await api(`/import-jobs/${uploaded.id}/staging?page_size=200`); const sourceRow6: StageRow = stageBefore.items.find((row: StageRow) => row.source_row === 6);
    await gridRow(6).getByRole('gridcell').nth(1).click(); await gridRow(6).getByRole('gridcell').nth(3).click({ modifiers: ['Shift'] });
    const copied = await grid.evaluate(node => { const clipboardData = new DataTransfer(); node.dispatchEvent(new ClipboardEvent('copy', { bubbles: true, cancelable: true, clipboardData })); return clipboardData.getData('text/plain'); });
    const projected = (id: string) => sourceRow6.edited_values?.[id] ?? sourceRow6.typed_values?.[id] ?? sourceRow6.raw_values[fixture.mapping[id]] ?? '';
    expect(copied).toBe(encodeTSV([[projected('code'), projected('day'), '123.45']]));
    await gridRow(6).getByRole('gridcell').nth(3).click(); await paste(grid, '124.45'); await page.getByRole('dialog', { name: 'Xem trước thay đổi vùng' }).getByRole('button', { name: 'Áp dụng vào nháp', exact: true }).click();
    page.once('dialog', dialog => dialog.accept()); await workspace.getByRole('button', { name: 'Lưu bản nháp', exact: true }).click();
    await expect.poll(async () => (await api(`/import-jobs/${uploaded.id}/staging?page_size=200`)).items.find((row: StageRow) => row.source_row === 6).edited_values.amount).toBe('124.45');
    console.log('Mini source UI: non-first sheet/header mapped;200-row preview, inline edit and TSV copy/paste patches confirmed.');
    await workspace.getByRole('button', { name: 'Validate toàn bộ', exact: true }).click(); await expect.poll(async () => (await api(`/import-jobs/${uploaded.id}`)).state).toBe('READY_FOR_CONFIRM');
    let batch: Batch = await api(`/import-jobs/${uploaded.id}`); expect(batch.counts).toMatchObject({ source_rows: 1000, invalid: 17, valid: 983, potential_duplicates: 20, published_rows: 0 });
    const actualIssues = await api(`/import-jobs/${uploaded.id}/issues?page_size=100`);
    for (const issue of expectedIssues) expect(actualIssues.items).toEqual(expect.arrayContaining([expect.objectContaining({ source_sheet: issue.source_sheet, source_row: issue.source_row, cell: issue.cell, code: issue.code })]));
    await workspace.getByRole('button', { name: 'Danh sách lỗi toàn job', exact: true }).click(); const issueModal = page.getByRole('dialog', { name: 'Lỗi theo tọa độ nguồn', exact: true });
    const issue = expectedIssues.find(value => value.severity === 'error')!; await expect(issueModal.getByRole('button', { name: `${issue.source_sheet}!${issue.cell}`, exact: true }).first()).toBeVisible();
    await page.screenshot({ path: test.info().outputPath('mini-issue-coordinates.png'), fullPage: true });
    await issueModal.getByRole('button', { name: 'Đóng', exact: true }).click();
    await workspace.getByRole('button', { name: 'Xem ứng viên trùng', exact: true }).click(); const duplicateModal = page.getByRole('dialog', { name: 'Ứng viên trùng · lựa chọn rõ ràng', exact: true });
    await duplicateModal.getByRole('row').filter({ hasText: 'Dòng nguồn: 5 ·' }).getByRole('button', { name: 'Loại', exact: true }).click();
    await expect.poll(async () => (await api(`/import-jobs/${uploaded.id}/staging?page_size=200`)).items.find((row: StageRow) => row.source_row === 5).decision).toBe('skip');
    await duplicateModal.getByRole('row').filter({ hasText: 'Dòng nguồn: 4 ·' }).getByRole('button', { name: 'Giữ', exact: true }).click();
    await expect.poll(async () => (await api(`/import-jobs/${uploaded.id}/staging?page_size=200`)).items.find((row: StageRow) => row.source_row === 4).decision).toBe('keep');
    await duplicateModal.getByRole('button', { name: 'Đóng', exact: true }).click();
    page.once('dialog', dialog => dialog.accept()); await workspace.getByRole('button', { name: 'Giữ nghi trùng chưa có quyết định', exact: true }).click();
    await expect.poll(async () => (await api(`/import-jobs/${uploaded.id}`)).counts.excluded).toBe(1);
    batch = await api(`/import-jobs/${uploaded.id}`); if (!batch.validation_token) { await workspace.getByRole('button', { name: 'Validate toàn bộ', exact: true }).click(); await expect.poll(async () => (await api(`/import-jobs/${uploaded.id}`)).state).toBe('READY_FOR_CONFIRM'); }
    const firstCommand: { body?: object } = {};
    await page.route(`**/api/v1/accounting/import-jobs/${uploaded.id}/confirm`, async route => {
      if (firstCommand.body) return route.continue();
      firstCommand.body = route.request().postDataJSON(); const response = await route.fetch(); expect(response.status()).toBe(200);
      const accepted = await response.json(); const cancelled = await api(`/import-jobs/${uploaded.id}/cancel`, 'POST', { request_key: randomBytes(16).toString('hex') });
      evidence.unknown_ack = { actual_server_accepted: true, accepted_state: accepted.state, cancel_state: cancelled.state, pending_at_cancel: cancelled.counts.staged_committed_rows, published_at_cancel: cancelled.counts.published_rows };
      intercepted.resolve(); await releaseAck.promise; await route.abort('failed');
    });
    page.once('dialog', dialog => dialog.accept()); await workspace.getByRole('button', { name: 'Xác nhận nhập phần hợp lệ', exact: true }).click(); await intercepted.promise;
    expect((await api(`/books/${book.id}/rows?page_size=200`)).total).toBe(0);
    evidence.pending_chunk_visibility_observed = evidence.unknown_ack.pending_at_cancel > 0;
    releaseAck.resolve(); await expect(workspace.getByText(/Chưa xác nhận thao tác đã được lưu/)).toBeVisible();
    const replay = await api(`/import-jobs/${uploaded.id}/confirm`, 'POST', firstCommand.body); evidence.unknown_ack.exact_confirm_replayed_via_real_api = true; expect(replay.counts.published_rows).toBe(0);
    await workspace.getByRole('button', { name: 'Tải trạng thái', exact: true }).click(); await expect(workspace.getByRole('button', { name: 'Tiếp tục job', exact: true })).toBeEnabled();
    await workspace.getByRole('button', { name: 'Tiếp tục job', exact: true }).click();
    const visibility: number[] = [];
    await expect.poll(async () => { const rows = await api(`/books/${book.id}/rows?page_size=200`); visibility.push(rows.total); expect([0, scenario.first_published]).toContain(rows.total); return rows.total; }, { timeout: 30000 }).toBe(scenario.first_published);
    evidence.checkpoints.push({ phase: 'resumed_partial_publication', total: scenario.first_published, observed_totals: visibility });
    await workspace.getByRole('button', { name: 'Tải trạng thái', exact: true }).click(); await expect(workspace.getByText('Đã công bố vào sổ: 982', { exact: true })).toBeVisible(); await expect(workspace.getByText('Lỗi: 17', { exact: true })).toBeVisible();
    await workspace.getByRole('button', { name: 'Đóng', exact: true }).click(); await page.getByRole('button', { name: 'Nhập Excel / CSV · mở job đã lưu', exact: true }).click();
    await workspace.getByRole('combobox', { name: 'Lọc staging', exact: true }).click(); await page.locator('.ant-select-dropdown:visible').getByText('Lỗi', { exact: true }).click();
    await expect(workspace.getByText('17 dòng theo bộ lọc · 17 dòng đã tải', { exact: true })).toBeVisible();
    const invalidPage = await api(`/import-jobs/${uploaded.id}/staging?page_size=200&status=invalid`); const repairByRow = new Map(repairs.map(repair => [repair.source_row, repair.values]));
    const matrix = invalidPage.items.map((row: StageRow) => { const repair = repairByRow.get(row.source_row); expect(repair).toBeTruthy(); return book.columns.map(column => { if (repair && Object.hasOwn(repair, column.id)) return repair[column.id]; if (Object.hasOwn(row.edited_values ?? {}, column.id)) return row.edited_values[column.id]; return row.typed_values?.[column.id] ?? row.raw_values[fixture.mapping[column.id]] ?? ''; }); });
    expect(matrix.length * book.columns.length).toBeLessThanOrEqual(500);
    const firstInvalid = invalidPage.items[0] as StageRow; await gridRow(firstInvalid.source_row).getByRole('gridcell').nth(1).click(); await paste(grid, encodeTSV(matrix));
    await page.getByRole('dialog', { name: 'Xem trước thay đổi vùng', exact: true }).getByRole('button', { name: 'Áp dụng vào nháp', exact: true }).click();
    page.once('dialog', dialog => dialog.accept()); await workspace.getByRole('button', { name: 'Lưu bản nháp', exact: true }).click();
    await workspace.getByRole('button', { name: 'Validate toàn bộ', exact: true }).click(); await expect.poll(async () => (await api(`/import-jobs/${uploaded.id}`)).state).toBe('READY_FOR_CONFIRM');
    expect((await api(`/import-jobs/${uploaded.id}`)).counts.invalid).toBe(0);
    page.once('dialog', dialog => dialog.accept()); await workspace.getByRole('button', { name: 'Xác nhận nhập phần hợp lệ', exact: true }).click();
    await expect.poll(async () => (await api(`/import-jobs/${uploaded.id}`)).counts.published_rows, { timeout: 30000 }).toBe(scenario.final_published);
    const finalBatch: Batch = await api(`/import-jobs/${uploaded.id}`); expect(finalBatch.counts).toMatchObject({ published_rows: 999, excluded: 1, invalid: 0 }); expect((await api(`/books/${book.id}/rows?page_size=200`)).total).toBe(999);
    await workspace.getByRole('button', { name: 'Tải trạng thái', exact: true }).click();
    const originalDownload = page.waitForEvent('download'); await workspace.getByRole('button', { name: 'Tải tệp gốc nguyên bản', exact: true }).click(); const downloaded = await originalDownload;
    expect(sha(await readFile((await downloaded.path())!))).toBe(fixture.sha256);
    expect(sha(await readFile(source))).toBe(fixture.sha256); expect((await stat(source)).mtimeMs).toBe(sourceStat.mtimeMs);
    const imported = await api(`/import-jobs/${uploaded.id}/staging?page_size=200&status=imported`); expect(imported.total).toBe(999); expect(imported.items.every((row: StageRow) => row.imported)).toBe(true);
    const excluded = await api(`/import-jobs/${uploaded.id}/staging?page_size=200&status=excluded`); expect(excluded.total).toBe(1); expect(excluded.items[0]).toMatchObject({ source_row: 5, imported: false });
    for (const response of evidence.staging_responses) { expect(response.items).toBeLessThanOrEqual(200); expect(response.status).toBe(200); }
    expect(evidence.page_errors).toEqual([]); expect(evidence.non_loopback_browser_requests).toEqual([]);
    Object.assign(evidence, { status: 'PASS', batch_id: uploaded.id, book_id: book.id, final_counts: finalBatch.counts, original_download_sha256: fixture.sha256, original_unchanged: true, copy_paste: 'actual grid handlers; bounded preview then versioned patch', edited_source_row: 6, edited_amount: '124.45' });
    await page.screenshot({ path: test.info().outputPath('mini-final.png'), fullPage: true });
    await workspace.getByRole('button', { name: 'Đóng', exact: true }).click();
    await page.getByRole('button', { name: 'Tải lại dữ liệu', exact: true }).click();
    await expect(page.getByText('999 dòng theo bộ lọc · 200 dòng đang tải', { exact: true })).toBeVisible();
    evidence.final_ledger_visible_total = 999; evidence.final_ledger_loaded_rows = 200;
    await page.screenshot({ path: test.info().outputPath('mini-ledger-published.png'), fullPage: true });
    console.log('Mini source UI: keep/skip, cancelled unpublished state, exact unknown-ACK replay, UI resume,982 partial +17 repairs→999/excluded1 and original SHA confirmed.');
  } catch (error) { evidence.status = 'FAIL'; evidence.failure = error instanceof Error ? error.message : 'Unknown failure'; await page.screenshot({ path: test.info().outputPath('mini-failure.png'), fullPage: true }).catch(() => {}); throw error;
  } finally {
    releaseAck.resolve();
    if (child && child.exitCode === null) { child.stdin.write('{"command":"shutdown"}\n'); child.stdin.end(); await new Promise<void>(resolve => { const timer = setTimeout(() => { child?.kill(); resolve(); }, 10000); child!.once('exit', () => { clearTimeout(timer); resolve(); }); }); }
    evidence.source_file_sha256_after = sha(await readFile(source)); evidence.source_file_unchanged = evidence.source_file_sha256_after === fixture.sha256;
    if (!evidence.source_file_unchanged) { evidence.status = 'FAIL'; evidence.failure = 'Original synthetic fixture changed during the mini UI run.'; }
    const output = test.info().outputPath('desktop-mini-evidence.json'); await writeFile(output, JSON.stringify(evidence, null, 2)); await test.info().attach('desktop-mini-evidence', { path: output, contentType: 'application/json' });
    expect(evidence.source_file_unchanged).toBe(true);
    // Retain this isolated synthetic root for parent inspection; never touch an
    // operational root, old worktree, Docker data or prior benchmark source.
  }
});
