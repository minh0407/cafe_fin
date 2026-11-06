import { defineConfig } from "../../../frontend/node_modules/@playwright/test/index.mjs";
import path from "node:path";
import { fileURLToPath } from "node:url";
const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../..");
export default defineConfig({
  testDir: ".",
  testMatch: "*.spec.mts",
  fullyParallel: false,
  retries: 0,
  workers: 1,
  timeout: 90000,
  outputDir: path.join(repo, "frontend/test-results/records"),
  use: { baseURL: "http://tauri.localhost", browserName: "chromium", locale: "vi-VN", actionTimeout: 10000, viewport: { width: 1480, height: 1100 }, screenshot: "only-on-failure" },
  webServer: { command: "node frontend/node_modules/vite/bin/vite.js --config tests/records/browser/vite.config.mts --configLoader native", cwd: repo, url: "http://127.0.0.1", reuseExistingServer: false },
  reporter: "list",
});
