import path from "node:path";
import os from "node:os";
import { createRequire } from "node:module";
const root = path.resolve(__dirname, "../../..");
const frontendRequire = createRequire(path.join(root, "frontend/package.json"));
const { defineConfig } = frontendRequire("@playwright/test");

export default defineConfig({
  testDir: __dirname,
  testMatch: "smoke.spec.ts",
  workers: 1,
  fullyParallel: false,
  retries: 0,
  timeout: 180000,
  reporter: "list",
  outputDir: path.join(
    os.tmpdir(),
    `cafe-fin-reporting-playwright-${process.pid}`,
  ),
  webServer: {
    command:
      "node frontend/node_modules/vite/bin/vite.js --config tests/reporting/ui/vite.config.mjs",
    cwd: root,
    url: "http://127.0.0.1:1431",
    reuseExistingServer: false,
    timeout: 30000,
  },
});
