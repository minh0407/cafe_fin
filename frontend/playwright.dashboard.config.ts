import { defineConfig } from "@playwright/test";
import base from "./playwright.config";
export default defineConfig({
  ...base,
  testMatch: "dashboard.spec.ts",
  use: { ...base.use, baseURL: "http://127.0.0.1:1434" },
  webServer: { command: "npm run dev -- --port 1434", env: { VITE_CAFE_FIN_PROOFS: "1" }, url: "http://127.0.0.1:1434", reuseExistingServer: false },
});
