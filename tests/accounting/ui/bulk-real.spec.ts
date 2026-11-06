import { test, expect } from '../../../frontend/node_modules/@playwright/test';
import { spawn, execFile, type ChildProcessWithoutNullStreams } from 'node:child_process';
import { createHash, randomBytes } from 'node:crypto';
import { createReadStream } from 'node:fs';
import { readFile, realpath, stat, writeFile } from 'node:fs/promises';
import { tmpdir, platform, release, arch, cpus, totalmem } from 'node:os';
import path from 'node:path';
import { performance } from 'node:perf_hooks';

const EXPECTED_ROWS = 1_000_000;
const PAGE_SIZE = 200;
interface Book { id: string; name: string; schema_revision: number; data_revision: number; columns: { id: string; name: string; editable?: boolean; kind: string }[] }
interface Row { id: string; version: number; logical_row: number; values: Record<string, string | null> }
interface RowPage { items: Row[]; total: number; page: number; page_size: number }

async function fileHash(filename: string) {
  const hash = createHash('sha256');
  for await (const chunk of createReadStream(filename)) hash.update(chunk);
  return hash.digest('hex');
}
function withinTemporaryPrefix(filename: string, tempRoot: string, prefix: string) {
  const relative = path.relative(tempRoot, filename);
  return !!relative && !path.isAbsolute(relative) && !relative.startsWith('..') && relative.split(path.sep)[0].toLowerCase().startsWith(prefix.toLowerCase());
}
async function windowsProcessMemory(ids: number[]) {
  if (process.platform !== 'win32') return { available: false, reason: 'Windows Get-Process counters unavailable on this platform' };
  const valid = ids.filter(id => Number.isSafeInteger(id) && id > 0);
  if (!valid.length) return { available: false, reason: 'No Chromium process IDs available' };
  // IDs come from CDP and are validated integers; no user text or credentials
  // enter this command. These counters are read-only and report processes only.
  const command = `Get-Process -Id @(${valid.join(',')}) -ErrorAction SilentlyContinue | ForEach-Object { [PSCustomObject]@{ pid=$_.Id; rss_bytes=$_.WorkingSet64; os_peak_rss_bytes=$_.PeakWorkingSet64; private_bytes=$_.PrivateMemorySize64 } } | ConvertTo-Json -Compress`;
  return new Promise<unknown>(resolve => execFile('powershell.exe', ['-NoProfile', '-NonInteractive', '-Command', command], { windowsHide: true, timeout: 15000 }, (error, stdout) => {
    if (error) return resolve({ available: false, reason: 'OS process counters could not be read' });
    try { const parsed = JSON.parse(stdout); resolve({ available: true, source: 'Windows Get-Process WorkingSet64/PeakWorkingSet64/PrivateMemorySize64', processes: Array.isArray(parsed) ? parsed : [parsed] }); }
    catch { resolve({ available: false, reason: 'OS process counter response unavailable' }); }
  }));
}

test('persisted million-row book keeps a bounded UI/cache with real high-page and full-data filtering', async ({ page, browser }) => {
  // No generation, credential reset, clone creation or source Runtime is allowed
  // here. Parent prepares a consistent isolated synthetic clone after CSV closes.
  expect(process.env.CAFE_FIN_BULK_READY, 'Run only after benchmark completion and clone preparation.').toBe('1');
  const required = (name: string) => { const value = process.env[name]; if (!value) throw new Error(`Supply ${name}; this harness never guesses credentials or book identity.`); return value; };
  const repository = path.resolve(__dirname, '../../..');
  const tempRoot = await realpath(tmpdir());
  const root = await realpath(required('CAFE_FIN_BULK_ROOT'));
  const resultFile = await realpath(required('CAFE_FIN_BULK_RESULT'));
  const bookId = required('CAFE_FIN_BULK_BOOK');
  const username = required('CAFE_FIN_BULK_USERNAME');
  const password = required('CAFE_FIN_BULK_PASSWORD');
  expect(withinTemporaryPrefix(root, tempRoot, 'cafe-fin-bulk-ui-'), 'ROOT must be an isolated Temp/cafe-fin-bulk-ui-*/ clone, never the original benchmark or operational data.').toBe(true);
  const completed = JSON.parse(await readFile(resultFile, 'utf8'));
  expect(completed.status).toBe('PASS');
  expect(completed.fixture?.rows).toBe(EXPECTED_ROWS);
  expect(completed.final_reconciliation?.published_rows).toBe(EXPECTED_ROWS);
  const sourceRoot = await realpath(String(completed.method?.data_root ?? ''));
  expect(withinTemporaryPrefix(sourceRoot, tempRoot, 'cafe-fin-frozen-20261106'), 'Source provenance must identify the frozen synthetic benchmark under Temp.').toBe(true);
  expect(root.toLowerCase()).not.toBe(sourceRoot.toLowerCase());
  const sourceDatabase = path.join(sourceRoot, 'database/cafe_fin.db');
  const sourceStatBefore = await stat(sourceDatabase);
  const cloneDatabase = await stat(path.join(root, 'database/cafe_fin.db'));
  expect(cloneDatabase.nlink, 'Clone DB must be an independent SQLite backup/copy, not a hard link.').toBe(1);
  expect(cloneDatabase.dev !== sourceStatBefore.dev || cloneDatabase.ino !== sourceStatBefore.ino, 'Clone DB must not share the source file identity.').toBe(true);
  const sourceHashBefore = await fileHash(sourceDatabase);
  const output = test.info().outputPath('bulk-real-metrics.json');
  const metrics: Record<string, any> = {
    status: 'RUNNING', expected_total_rows: EXPECTED_ROWS, requested_page_size: PAGE_SIZE,
    environment: { platform: platform(), release: release(), arch: arch(), cpu_model: cpus()[0]?.model, cpu_logical: cpus().length, physical_ram_bytes: totalmem(), node: process.version, browser: browser.version(), viewport: { width: 1600, height: 1100 } },
    data: { clone_root: root, source_result: resultFile, book_id: bookId, source_database_sha256_before: sourceHashBefore },
    direct_api: [], browser_row_responses: [], ui_snapshots: [], memory_samples: [], os_process_snapshots: [],
    method: {
      domain_mutations: false, http_api_mocking: false, native_bootstrap_only: true,
      sampling: 'CDP Runtime.getHeapUsage and Memory.getDOMCounters sampled every 250 ms while navigation runs; OS process counters at checkpoints',
      limits: ['JS heap is not renderer/browser/backend RSS.', 'Sampled JS-heap maximum is not an exact allocation high-water mark.', 'OS process RSS may include shared pages and must not be summed as unique memory.', 'CDP SystemInfo.getProcessInfo reports process identity/CPU time, not memory.', 'The login shell is publicly unmounted and its cache cleared before lane measurements.', 'This is a Vite development Chromium harness, not native Tauri/WebView2 or a release build.', 'API timings include actual loopback HTTP/body reading; no cold-disk-cache claim or speed threshold.'],
    },
  };
  let child: ChildProcessWithoutNullStreams | undefined;
  let sampler: ReturnType<typeof setInterval> | undefined;
  let sampling = false; let sampledMax = 0;
  const observations = new Set<Promise<void>>();
  const pageErrors: string[] = []; const domainWrites: string[] = [];
  try {
    const token = randomBytes(32).toString('hex');
    child = spawn(path.join(repository, '.venv/Scripts/python.exe'), [path.join(repository, 'tests/accounting/ui/serve.py')], { cwd: repository, windowsHide: true, env: { ...process.env, PYTHONUTF8: '1', PYTHONPATH: path.join(repository, 'backend') }, stdio: 'pipe' });
    const hello = new Promise<{ status: string; api_base: string }>((resolve, reject) => {
      let pending = ''; const timer = setTimeout(() => reject(new Error('Synthetic clone sidecar startup timed out.')), 20000);
      child!.once('error', () => { clearTimeout(timer); reject(new Error('Synthetic clone sidecar could not start.')); });
      child!.once('exit', () => { clearTimeout(timer); reject(new Error('Synthetic clone sidecar exited during startup; ensure the clone is closed.')); });
      child!.stdout.on('data', chunk => { pending += String(chunk); if (pending.includes('\n')) { clearTimeout(timer); try { resolve(JSON.parse(pending.slice(0, pending.indexOf('\n')))); } catch { reject(new Error('Invalid sidecar handshake.')); } } });
    });
    child.stdin.write(JSON.stringify({ protocol_version: 1, data_root: root, initialize: false, session_token: token, allowed_origin: 'http://127.0.0.1:1420' }) + '\n');
    const ready = await hello; expect(ready.status).toBe('ready');
    const boot = { protocol_version: 1, api_base: ready.api_base, session_token: token, data_root: root };
    await page.addInitScript(boot => { Object.assign(window, { __TAURI_INTERNALS__: { invoke: async (command: string) => { if (command === 'desktop_status') return { data_root: boot.data_root, running: true }; if (command === 'start_backend') return boot; throw new Error('Unexpected native operation in read-only bulk harness.'); } } }); }, boot);
    page.on('pageerror', error => pageErrors.push(error.message));
    page.on('request', request => { if (new URL(request.url()).pathname.startsWith('/api/v1/accounting/') && !['GET', 'OPTIONS'].includes(request.method())) domainWrites.push(`${request.method()} ${new URL(request.url()).pathname}`); });
    page.on('response', response => {
      if (response.request().method() !== 'GET') return;
      if (!new URL(response.url()).pathname.endsWith(`/accounting/books/${bookId}/rows`)) return;
      const observation = (async () => {
        const body = await response.body(); const data = JSON.parse(body.toString('utf8'));
        const requested = new URL(response.url()).searchParams;
        metrics.browser_row_responses.push({ status: response.status(), page: data.page, page_size: data.page_size, items: data.items?.length ?? 0, total: data.total, bytes: body.length, requested_page_size: Number(requested.get('page_size')), has_filter: requested.get('filters') !== '[]', has_search: !!requested.get('search') });
      })().catch(() => { metrics.cancelled_or_unreadable_row_responses = (metrics.cancelled_or_unreadable_row_responses ?? 0) + 1; });
      observations.add(observation); void observation.finally(() => observations.delete(observation));
    });
    await page.goto('/__accounting_bulk_harness#/foundation');
    await expect(page.getByRole('heading', { name: 'Đăng nhập local', exact: true })).toBeVisible();
    await page.getByLabel('Tên đăng nhập').fill(username); await page.getByLabel('Mật khẩu', { exact: true }).fill(password);
    await page.getByRole('button', { name: 'Đăng nhập', exact: true }).click();
    await expect(page.getByRole('menuitem', { name: 'Sổ kế toán', exact: true })).toBeVisible();
    const accessToken = await page.evaluate(async () => { const name = '/src/shared/session.ts'; const { useSession } = await import(name); return useSession.getState().token as string; });
    const headers = { 'X-App-Session': token, Authorization: `Bearer ${accessToken}`, Origin: 'http://127.0.0.1:1420' };
    const direct = async <T,>(endpoint: string, label: string): Promise<T> => {
      const start = performance.now(); const response = await fetch(`${ready.api_base}/accounting${endpoint}`, { headers, signal: AbortSignal.timeout(60000) });
      const body = await response.text(); const readMs = performance.now() - start;
      expect(response.status, label).toBe(200); const result = JSON.parse(body);
      metrics.direct_api.push({ label, elapsed_ms: readMs, response_bytes: Buffer.byteLength(body), total: result.total, returned_rows: result.items?.length, page: result.page });
      if (Array.isArray(result.items)) expect(result.items.length).toBeLessThanOrEqual(PAGE_SIZE);
      return result as T;
    };
    const book = await direct<Book>(`/books/${encodeURIComponent(bookId)}`, 'book_metadata');
    const codeId = process.env.CAFE_FIN_BULK_CODE_COLUMN ?? 'code';
    const codeColumn = book.columns.find(column => column.id === codeId);
    expect(codeColumn && codeColumn.editable !== false && codeColumn.kind !== 'formula', 'Choose the editable synthetic code column via CAFE_FIN_BULK_CODE_COLUMN.').toBeTruthy();
    const first = await direct<RowPage>(`/books/${bookId}/rows?page=1&page_size=${PAGE_SIZE}`, 'unfiltered_first_page_full_count');
    expect(first.total).toBe(EXPECTED_ROWS); expect(first.items.length).toBe(PAGE_SIZE);
    const lastPage = Math.ceil(EXPECTED_ROWS / PAGE_SIZE);
    const last = await direct<RowPage>(`/books/${bookId}/rows?page=${lastPage}&page_size=${PAGE_SIZE}`, 'unfiltered_high_offset_page_full_count');
    expect(last.total).toBe(EXPECTED_ROWS); expect(last.items.length).toBe(PAGE_SIZE);
    const targetCode = last.items.at(-1)!.values[codeId]; expect(typeof targetCode).toBe('string');
    const filter = JSON.stringify([{ column_id: codeId, op: 'eq', value: targetCode }]);
    const filtered = await direct<RowPage>(`/books/${bookId}/rows?${new URLSearchParams({ page: '1', page_size: String(PAGE_SIZE), filters: filter })}`, 'indexed_exact_filter_against_entire_million_rows');
    expect(filtered.total).toBeGreaterThan(0); expect(filtered.total).toBeLessThanOrEqual(PAGE_SIZE);
    await direct<RowPage>(`/books/${bookId}/rows?${new URLSearchParams({ page: '1', page_size: String(PAGE_SIZE), search: targetCode! })}`, 'server_search_against_entire_million_rows');

    const cdp = await page.context().newCDPSession(page); const browserCdp = await browser.newBrowserCDPSession();
    const sample = async (label: string) => {
      if (sampling) return; sampling = true;
      try { const [heap, dom] = await Promise.all([cdp.send('Runtime.getHeapUsage'), cdp.send('Memory.getDOMCounters')]); sampledMax = Math.max(sampledMax, heap.usedSize); metrics.memory_samples.push({ at_ms: performance.now(), label, ...heap, dom }); }
      catch { metrics.memory_sample_unavailable = true; } finally { sampling = false; }
    };
    const osSample = async (label: string) => { try { const processes = await browserCdp.send('SystemInfo.getProcessInfo'); metrics.os_process_snapshots.push({ label, identity_and_cpu: processes.processInfo, backend_pid: child?.pid, memory: await windowsProcessMemory([...processes.processInfo.map(item => item.id), ...(child?.pid ? [child.pid] : [])]) }); } catch { metrics.os_process_snapshots.push({ label, available: false }); } };
    sampler = setInterval(() => { void sample('interval'); }, 250);
    await sample('before_feature_mount');

    // No response interception: load the actual feature and exactly the dependency
    // URLs Vite compiled for it. Keeping provider/module identity equal avoids a
    // second React Query context while mounting without a product registry edit.
    await page.evaluate(async ({ bookId }) => {
      const featurePath = '/src/features/accounting/AccountingPage.tsx';
      const featureSource = await (await fetch(featurePath)).text(); const mainSource = await (await fetch('/src/app/main.tsx')).text();
      const dependency = (source: string, token: string) => { const urls = [...source.matchAll(/["']([^"']*\/node_modules\/\.vite\/deps\/[^"']+)["']/g)].map(match => match[1]); const found = urls.find(url => url.includes(token)); if (!found) throw new Error(`Vite dependency URL unavailable: ${token}`); return found; };
      const React = (await import(dependency(mainSource, '/react.js'))).default;
      const ReactDOM = await import(dependency(mainSource, '/react-dom_client.js'));
      const { QueryClient, QueryClientProvider } = await import(dependency(featureSource, '/@tanstack_react-query.js'));
      (window as any).__bulkShellRoot.unmount(); (window as any).__bulkShellCache.clear();
      history.replaceState(null, '', `${location.pathname}#/accounting?book=${encodeURIComponent(bookId)}`);
      const { AccountingPage } = await import(featurePath);
      const cache = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } } });
      const host = document.getElementById('root')!; host.id = 'bulk-lane-root';
      const root = (ReactDOM.createRoot ?? ReactDOM.default.createRoot)(host);
      root.render(React.createElement(QueryClientProvider, { client: cache }, React.createElement(AccountingPage)));
      Object.assign(window, { __bulkLaneCache: cache });
    }, { bookId });
    const lane = page.locator('#bulk-lane-root'); const grid = lane.getByRole('grid', { name: 'Sổ kế toán theo ô' });
    await expect(grid).toBeVisible(); await expect(lane.getByText(`${EXPECTED_ROWS} dòng theo bộ lọc · ${PAGE_SIZE} dòng đang tải`, { exact: true })).toBeVisible();
    const snapshot = async (label: string) => {
      await expect.poll(() => page.evaluate(() => { const cache = (window as any).__bulkLaneCache; return cache.getQueryCache().getAll().filter((query: any) => query.queryKey[2] === 'rows' && query.state.data).length; })).toBeLessThanOrEqual(1);
      const state = await page.evaluate(() => {
        const queries = (window as any).__bulkLaneCache.getQueryCache().getAll();
        const rowQueries = queries.filter((query: any) => query.queryKey[2] === 'rows' && query.state.data);
        const ui = document.getElementById('bulk-lane-root')!;
        return { query_count: queries.length, row_query_count: rowQueries.length, cached_rows: rowQueries.reduce((sum: number, query: any) => sum + query.state.data.items.length, 0), active_row_pages: rowQueries.map((query: any) => ({ page: query.state.data.page, total: query.state.data.total, rows: query.state.data.items.length })), dom_grid_rows: ui.querySelectorAll('[role="grid"] [role="row"]').length, ui_loaded_rows: Number(ui.innerText.match(/(\d+) dòng đang tải/)?.[1] ?? '-1') };
      });
      expect(state.cached_rows).toBeLessThanOrEqual(PAGE_SIZE); expect(state.ui_loaded_rows).toBeGreaterThanOrEqual(1); expect(state.ui_loaded_rows).toBeLessThanOrEqual(PAGE_SIZE); expect(state.dom_grid_rows).toBeLessThanOrEqual(PAGE_SIZE + 1);
      metrics.ui_snapshots.push({ label, ...state }); await sample(label);
    };
    await snapshot('first_page'); await osSample('first_page');
    const jump = async (target: number) => {
      const start = performance.now(); const jumper = lane.locator('.ant-pagination-options-quick-jumper input');
      await jumper.fill(String(target)); await jumper.press('Enter');
      await expect.poll(() => page.evaluate(() => { const queries = (window as any).__bulkLaneCache.getQueryCache().getAll(); return queries.find((query: any) => query.queryKey[2] === 'rows' && query.getObserversCount() > 0)?.state.data?.page; })).toBe(target);
      metrics.ui_snapshots.push({ label: `jump_${target}_latency`, elapsed_ms: performance.now() - start }); await snapshot(`page_${target}`);
    };
    for (const target of [2, Math.ceil(lastPage / 2), lastPage]) await jump(target);
    // Scroll only the loaded last page. Two pasted rows starting at its last row
    // must be rejected as a whole, rather than treating unloaded rows as empty.
    await grid.evaluate(node => { node.scrollTop = node.scrollHeight; });
    await grid.getByRole('gridcell', { name: targetCode!, exact: true }).click();
    await grid.evaluate(node => { const data = new DataTransfer(); data.setData('text/plain', 'bounded-draft\nunloaded-row'); node.dispatchEvent(new ClipboardEvent('paste', { bubbles: true, cancelable: true, clipboardData: data })); });
    await expect(lane.getByText(/Vùng vượt trang đang tải/)).toBeVisible();
    await expect(page.getByRole('dialog', { name: 'Xem trước thay đổi vùng' })).toHaveCount(0);
    await expect(lane.getByRole('button', { name: 'Lưu bản nháp', exact: true })).toBeDisabled();
    await grid.evaluate(node => { const data = new DataTransfer(); data.setData('text/plain', Array(501).fill('x').join('\t')); node.dispatchEvent(new ClipboardEvent('paste', { bubbles: true, cancelable: true, clipboardData: data })); });
    await expect(lane.getByText(/Chỉ dán tối đa 500 ô/)).toBeVisible();
    await lane.getByText('Lọc toàn bộ sổ / xem dòng đã xóa', { exact: true }).click();
    await lane.getByRole('combobox', { name: 'Cột lọc', exact: true }).click(); await page.getByRole('option', { name: codeColumn!.name, exact: true }).click();
    await lane.getByLabel('Giá trị lọc', { exact: true }).fill(targetCode!); await lane.getByRole('button', { name: 'Thêm điều kiện', exact: true }).click(); await lane.getByRole('button', { name: 'Áp dụng bộ lọc', exact: true }).click();
    await expect(lane.getByText(`${filtered.total} dòng theo bộ lọc · ${filtered.items.length} dòng đang tải`, { exact: true })).toBeVisible();
    await expect(grid.getByRole('gridcell', { name: targetCode!, exact: true }).first()).toBeVisible(); await snapshot('server_filtered_target_from_last_page');
    await lane.getByRole('button', { name: 'Bỏ bộ lọc', exact: true }).click(); await expect(lane.getByText(`${EXPECTED_ROWS} dòng theo bộ lọc · ${PAGE_SIZE} dòng đang tải`, { exact: true })).toBeVisible();
    await snapshot('filter_removed_first_page'); await osSample('after_navigation_and_filter');
    const after = await direct<Book>(`/books/${bookId}`, 'book_metadata_after_readonly_ui');
    expect(after.data_revision).toBe(book.data_revision); expect(after.schema_revision).toBe(book.schema_revision);
    const final = await direct<RowPage>(`/books/${bookId}/rows?page=${lastPage}&page_size=${PAGE_SIZE}`, 'last_page_after_readonly_ui');
    expect(final.total).toBe(EXPECTED_ROWS); expect(final.items).toEqual(last.items); expect(domainWrites).toEqual([]); expect(pageErrors).toEqual([]);
    await Promise.all([...observations]);
    expect(metrics.browser_row_responses.length).toBeGreaterThanOrEqual(5);
    for (const result of metrics.browser_row_responses) { expect(result.status).toBe(200); expect(result.items).toBeLessThanOrEqual(PAGE_SIZE); expect(result.requested_page_size).toBeLessThanOrEqual(PAGE_SIZE); }
    metrics.status = 'PASS'; metrics.domain_mutation_requests = domainWrites.length;
    await page.screenshot({ path: test.info().outputPath('bulk-real-ui.png'), fullPage: true });
  } catch (error) {
    metrics.status = 'FAIL'; metrics.failure = error instanceof Error ? error.message : 'Unknown test failure'; throw error;
  } finally {
    if (sampler) clearInterval(sampler);
    while (sampling) await new Promise(resolve => setTimeout(resolve, 10));
    metrics.sampled_peak_js_heap_used_bytes = sampledMax;
    metrics.sample_count = metrics.memory_samples.length;
    if (child && child.exitCode === null) { child.stdin.write('{"command":"shutdown"}\n'); child.stdin.end(); await new Promise<void>(resolve => { const timer = setTimeout(() => { child?.kill(); resolve(); }, 15000); child!.once('exit', () => { clearTimeout(timer); resolve(); }); }); }
    const sourceStatAfter = await stat(sourceDatabase); const sourceHashAfter = await fileHash(sourceDatabase);
    metrics.data.source_database_sha256_after = sourceHashAfter;
    metrics.data.source_database_unchanged = sourceHashAfter === sourceHashBefore && sourceStatAfter.size === sourceStatBefore.size && sourceStatAfter.mtimeMs === sourceStatBefore.mtimeMs;
    if (!metrics.data.source_database_unchanged) { metrics.status = 'FAIL'; metrics.failure = 'Original frozen benchmark DB changed during the UI run.'; }
    await writeFile(output, JSON.stringify(metrics, null, 2), 'utf8');
    await test.info().attach('bulk-real-metrics', { path: output, contentType: 'application/json' });
    expect(metrics.data.source_database_unchanged, 'Original frozen benchmark DB must remain byte/hash/mtime unchanged.').toBe(true);
    // Never delete, copy, repair, migrate, authenticate against or open a Runtime
    // on sourceRoot. The supplied clone is retained for parent inspection.
  }
});
