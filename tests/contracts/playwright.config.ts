import { defineConfig } from "../../frontend/node_modules/@playwright/test/index.mjs";
import path from "node:path";
import { fileURLToPath } from "node:url";
const repository = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
export default defineConfig({
  testDir: ".",
  testMatch: "browser.spec.ts",
  workers: 1,
  retries: 0,
  use: { baseURL: "http://127.0.0.1:1422", browserName: "chromium", viewport: { width: 1600, height: 1050 }, actionTimeout: 15000, trace: "retain-on-failure" },
  webServer: { command: "node frontend/node_modules/vite/bin/vite.js --config tests/contracts/vite.config.mjs", cwd: repository, url: "http://127.0.0.1:1422/tests/contracts/browser.html", reuseExistingServer: false },
  reporter: "list",
});
