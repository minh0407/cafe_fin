import { defineConfig } from '../../../frontend/node_modules/@playwright/test';
import { HARNESS_DEV_COMMAND, HARNESS_ORIGIN } from './harness-origin';

// Run approved shared consumer cases on the lane's port, without editing shared config.
export default defineConfig({
  testDir: '../../../frontend/tests', testMatch: 'date-input.spec.ts',
  workers: 1, retries: 0, reporter: 'list',
  outputDir: '../../../frontend/test-results/accounting-shared-date',
  use: { baseURL: HARNESS_ORIGIN, browserName: 'chromium', viewport: { width: 1440, height: 1000 } },
  webServer: { command: HARNESS_DEV_COMMAND, cwd: '../../..', url: HARNESS_ORIGIN, reuseExistingServer: false },
});
