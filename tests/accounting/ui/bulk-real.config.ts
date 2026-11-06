import { defineConfig } from '../../../frontend/node_modules/@playwright/test';
import { HARNESS_DEV_COMMAND, HARNESS_ORIGIN } from './harness-origin';

// Opt-in, AFTER the source benchmark is closed. This configuration never reuses
// another lane's Vite listener and never starts or resets benchmark generation.
export default defineConfig({
  testDir: '.', testMatch: 'bulk-real.spec.ts', workers: 1, retries: 0,
  timeout: 240000, expect: { timeout: 30000 }, reporter: 'list',
  outputDir: '../../../frontend/test-results/accounting-bulk-real',
  use: {
    baseURL: HARNESS_ORIGIN, browserName: 'chromium',
    viewport: { width: 1600, height: 1100 }, actionTimeout: 30000,
    launchOptions: { args: ['--enable-precise-memory-info'] },
  },
  webServer: {
    command: `${HARNESS_DEV_COMMAND} --config ../tests/accounting/ui/bulk-vite.config.mts`, cwd: '../../..',
    url: HARNESS_ORIGIN, reuseExistingServer: false,
  },
});
