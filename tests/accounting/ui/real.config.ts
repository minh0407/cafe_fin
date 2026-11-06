import { defineConfig } from '../../../frontend/node_modules/@playwright/test';
export default defineConfig({
  testDir: '.', testMatch: 'real.spec.ts', workers: 1, retries: 0, reporter: 'list', timeout: 120000,
  outputDir: '../../../frontend/test-results/accounting-real',
  use: { baseURL: 'http://127.0.0.1:1420', browserName: 'chromium', viewport: { width: 1600, height: 1100 }, acceptDownloads: true, actionTimeout: 15000 },
  webServer: { command: 'npm --prefix frontend run dev', cwd: '../../..', url: 'http://127.0.0.1:1420', reuseExistingServer: false },
});
