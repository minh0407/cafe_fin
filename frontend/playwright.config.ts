import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: "./tests",
  fullyParallel: true,
  retries: 0,
  use: {
    baseURL: "http://127.0.0.1:1420",
    browserName: "chromium",
    viewport: { width: 1440, height: 1000 },
  },
  webServer: {
    command: "npm run dev",
    env: { VITE_CAFE_FIN_PROOFS: "1" },
    url: "http://127.0.0.1:1420",
    reuseExistingServer: false,
  },
  reporter: "list",
});
