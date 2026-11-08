import { defineConfig } from '../../../frontend/node_modules/@playwright/test';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { HARNESS_DEV_COMMAND, HARNESS_ORIGIN } from './harness-origin';

const output = path.resolve(process.env.CAFE_FIN_MINI_OUTPUT ?? path.join(tmpdir(), `cafe-fin-desktop-mini-ui-${Date.now()}`));
// Playwright clears outputDir. Restrict it to a dedicated direct Temp child so
// a mistyped environment path cannot erase a workspace or operational root.
if (path.dirname(output).toLowerCase() !== path.resolve(tmpdir()).toLowerCase() || !path.basename(output).startsWith('cafe-fin-desktop-mini-ui-')) throw new Error('CAFE_FIN_MINI_OUTPUT must be a dedicated Temp/cafe-fin-desktop-mini-ui-* directory.');

// Source UI evidence only. This config never selects/launches a packaged binary.
export default defineConfig({
  testDir: '.', testMatch: 'desktop-mini.spec.ts', workers: 1, retries: 0, reporter: 'list',
  timeout: 180000, expect: { timeout: 15000 },
  outputDir: output,
  use: { baseURL: HARNESS_ORIGIN, browserName: 'chromium', viewport: { width: 1700, height: 1200 }, acceptDownloads: true, actionTimeout: 15000, trace: 'off' },
  webServer: { command: HARNESS_DEV_COMMAND, cwd: '../../..', url: HARNESS_ORIGIN, reuseExistingServer: false },
});
