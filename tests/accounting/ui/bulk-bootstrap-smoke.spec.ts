import { test, expect } from '../../../frontend/node_modules/@playwright/test';
import { spawn, type ChildProcessWithoutNullStreams } from 'node:child_process';
import { randomBytes } from 'node:crypto';
import { writeFile } from 'node:fs/promises';
import path from 'node:path';
import { HARNESS_ORIGIN } from './harness-origin';

test('test-only bulk bootstrap mounts real login before measurement', async ({ page }) => {
  const root = process.env.CAFE_FIN_BULK_ROOT;
  expect(root, 'Supply the already verified independent synthetic clone.').toContain('cafe-fin-bulk-ui-');
  const repository = path.resolve(__dirname, '../../..'); const token = randomBytes(32).toString('hex');
  const logs: { type: string; text: string }[] = []; let child: ChildProcessWithoutNullStreams | undefined;
  page.on('console', entry => logs.push({ type: entry.type(), text: entry.text() }));
  page.on('pageerror', error => { logs.push({ type: 'pageerror', text: error.message }); console.log(`Bootstrap pageerror: ${error.message}`); });
  try {
    child = spawn(path.join(repository, '.venv/Scripts/python.exe'), [path.join(repository, 'tests/accounting/ui/serve.py')], { cwd: repository, windowsHide: true, env: { ...process.env, PYTHONUTF8: '1', PYTHONPATH: path.join(repository, 'backend') }, stdio: 'pipe' });
    const hello = new Promise<{ status: string; api_base: string }>((resolve, reject) => {
      let text = ''; const timer = setTimeout(() => reject(new Error('Clone sidecar startup timeout.')), 20000);
      child!.once('error', reject); child!.once('exit', () => { clearTimeout(timer); reject(new Error('Clone sidecar exited.')); });
      child!.stdout.on('data', chunk => { text += String(chunk); if (text.includes('\n')) { clearTimeout(timer); resolve(JSON.parse(text.slice(0, text.indexOf('\n')))); } });
    });
    child.stdin.write(JSON.stringify({ protocol_version: 1, data_root: root, initialize: false, session_token: token, allowed_origin: HARNESS_ORIGIN }) + '\n');
    const ready = await hello; expect(ready.status).toBe('ready');
    await page.addInitScript(boot => { Object.assign(window, { __TAURI_INTERNALS__: { invoke: async (command: string) => { if (command === 'desktop_status') return { data_root: boot.data_root, running: true }; if (command === 'start_backend') return boot; throw new Error('Unexpected native bootstrap command.'); } } }); }, { protocol_version: 1, data_root: root!, session_token: token, api_base: ready.api_base });
    await page.goto('/__accounting_bulk_harness#/foundation');
    await expect(page.getByText('Đăng nhập local', { exact: true })).toBeVisible();
  } finally {
    await page.screenshot({ path: test.info().outputPath('bootstrap.png'), fullPage: true });
    await writeFile(test.info().outputPath('browser-console.json'), JSON.stringify(logs, null, 2));
    if (child && child.exitCode === null) { child.stdin.write('{"command":"shutdown"}\n'); child.stdin.end(); await new Promise<void>(resolve => { const timer = setTimeout(() => { child?.kill(); resolve(); }, 10000); child!.once('exit', () => { clearTimeout(timer); resolve(); }); }); }
  }
});
