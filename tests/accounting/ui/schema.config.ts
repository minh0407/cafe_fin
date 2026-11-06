import { defineConfig } from '../../../frontend/node_modules/@playwright/test';
import { HARNESS_DEV_COMMAND, HARNESS_ORIGIN } from './harness-origin';
export default defineConfig({
  testDir: '.', testMatch: ['schema.spec.ts', 'schema-real.spec.ts'], workers: 1, retries: 0, reporter: 'list', timeout: 60000,
  outputDir: '../../../frontend/test-results/accounting-schema',
  use: { baseURL: HARNESS_ORIGIN, browserName: 'chromium', viewport: { width: 1600, height: 1100 }, actionTimeout: 10000 },
  webServer: { command: `${HARNESS_DEV_COMMAND} --config ../tests/accounting/ui/schema-vite.config.mts`, cwd: '../../..', url: HARNESS_ORIGIN, reuseExistingServer: false },
});
