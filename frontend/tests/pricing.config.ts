import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: ".", testMatch: ["pricing.spec.ts", "crm-parity.spec.ts"], fullyParallel: false, retries: 0,
  use: { baseURL: "http://127.0.0.1:1436", browserName: "chromium", viewport: { width: 1440, height: 1100 } },
  webServer: { command: "npm run dev -- --port 1436", url: "http://127.0.0.1:1436", reuseExistingServer: false, env: { VITE_CAFE_FIN_PROOFS: "1" } },
  reporter: "list",
});
