import { defineConfig } from '../../../frontend/node_modules/@playwright/test';
import bulk from './bulk-real.config';
export default defineConfig({ ...bulk, testMatch: 'bulk-bootstrap-smoke.spec.ts', timeout: 60000, outputDir: '../../../frontend/test-results/accounting-bulk-bootstrap', use: { ...bulk.use, trace: 'retain-on-failure' } });
