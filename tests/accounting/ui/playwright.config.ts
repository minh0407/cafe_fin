import { defineConfig } from '../../../frontend/node_modules/@playwright/test';
export default defineConfig({
  testDir: '.', testIgnore: 'real.spec.ts', fullyParallel: false, workers: 1, retries: 0, reporter: 'list',
  outputDir: '../../../frontend/test-results/accounting',
  use: { baseURL: 'http://127.0.0.1:1447', browserName: 'chromium', viewport: { width: 1600, height: 1100 } },
  webServer: { command: 'npm --prefix frontend run dev -- --port 1447', cwd: '../../..', url: 'http://127.0.0.1:1447', reuseExistingServer: false },
});

