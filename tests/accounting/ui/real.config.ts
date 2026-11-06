import { defineConfig } from '../../../frontend/node_modules/@playwright/test';
import { HARNESS_DEV_COMMAND, HARNESS_ORIGIN } from './harness-origin';
export default defineConfig({
  testDir: '.', testMatch: 'real.spec.ts', workers: 1, retries: 0, reporter: 'list', timeout: 120000,
  outputDir: '../../../frontend/test-results/accounting-real',
  use: { baseURL: HARNESS_ORIGIN, browserName: 'chromium', viewport: { width: 1600, height: 1100 }, acceptDownloads: true, actionTimeout: 15000 },
  webServer: { command: HARNESS_DEV_COMMAND, cwd: '../../..', url: HARNESS_ORIGIN, reuseExistingServer: false },
});
