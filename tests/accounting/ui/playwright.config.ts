import { defineConfig } from '../../../frontend/node_modules/@playwright/test';
import { HARNESS_DEV_COMMAND, HARNESS_ORIGIN } from './harness-origin';
export default defineConfig({
  testDir: '.', testMatch: ['drafts.spec.ts', 'workspace.spec.ts'], fullyParallel: false, workers: 1, retries: 0, reporter: 'list',
  outputDir: '../../../frontend/test-results/accounting',
  use: { baseURL: HARNESS_ORIGIN, browserName: 'chromium', viewport: { width: 1600, height: 1100 } },
  webServer: { command: HARNESS_DEV_COMMAND, cwd: '../../..', url: HARNESS_ORIGIN, reuseExistingServer: false },
});

