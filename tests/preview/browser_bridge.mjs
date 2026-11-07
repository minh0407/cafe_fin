// Synthetic browser-bridge contract probe. This intercepts bootstrap/health only;
// it does not exercise a running backend or prove Docker/Linux behavior.
// Start Vite separately with VITE_CAFE_FIN_BROWSER_PREVIEW=1 from frontend/,
// then run: node tests/preview/browser_bridge.mjs
// Keep port 1420 free of any other app. Do not run against real user data.
import assert from "node:assert/strict";
import { createRequire } from "node:module";

const requireFrontend = createRequire(new URL("../../frontend/package.json", import.meta.url));
const { chromium } = requireFrontend("@playwright/test");
const browser = await chromium.launch({ headless: true });
try {
  const page = await browser.newPage();
  const token = "synthetic_preview_session_012345678901234567890";
  let payload = {
    protocol_version: 1,
    api_base: "http://127.0.0.1:1420/api/v1",
    session_token: token,
    data_root: "/data",
  };
  let bootstrapCount = 0;
  await page.route("**/preview/bootstrap", (route) => {
    assert.equal(route.request().method(), "POST");
    assert.equal(route.request().headers()["x-preview-bootstrap"], "1");
    bootstrapCount += 1;
    return route.fulfill({ json: payload, headers: { "Cache-Control": "no-store" } });
  });
  await page.route("**/probe", (route) => route.fulfill({
    contentType: "text/html",
    body: "<!doctype html><html><body>probe</body></html>",
  }));
  await page.goto("http://127.0.0.1:1420/probe");
  const valid = await page.evaluate(async () => {
    const { desktop } = await import("/src/shared/api.ts");
    const status = await desktop.status();
    const boot = await desktop.start(false);
    const failures = [];
    for (const command of [
      () => desktop.chooseDataRoot(),
      () => desktop.restart(),
      () => desktop.attach(),
      () => desktop.maintenanceBegin("backup"),
      () => desktop.maintenanceSelect("synthetic", "destination"),
      () => desktop.maintenanceRun("synthetic", "synthetic"),
      () => desktop.maintenanceStatus("synthetic", "synthetic"),
      () => desktop.maintenanceActivate("synthetic", "synthetic"),
      () => desktop.openReports("synthetic"),
    ]) {
      try {
        await command();
        failures.push("unexpected success");
      } catch (error) {
        failures.push(error.code);
      }
    }
    return {
      status,
      // Check token/metadata in the browser; never return a credential to logs.
      tokenAccepted: boot.session_token === "synthetic_preview_session_012345678901234567890",
      maintenancePresent: "maintenance_protocol" in boot || "generation" in boot,
      failures,
      local: localStorage.length,
      session: sessionStorage.length,
      native: !!window.__TAURI_INTERNALS__,
    };
  });
  assert.deepEqual(valid.status, { data_root: "/data", running: true, runtime_state: "ACTIVE" });
  assert.equal(valid.tokenAccepted, true);
  assert.equal(valid.maintenancePresent, false);
  assert.deepEqual(valid.failures, Array(9).fill("PREVIEW_NATIVE_UNAVAILABLE"));
  assert.equal(valid.local, 0);
  assert.equal(valid.session, 0);
  assert.equal(valid.native, false);

  for (const patch of [
    { data_root: "/other" },
    { api_base: "http://evil.invalid/api/v1" },
    { maintenance_protocol: 1, generation: "forged" },
    { session_token: "short" },
  ]) {
    const original = payload;
    payload = { ...payload, ...patch };
    assert.equal(await page.evaluate(async () => {
      const { desktop } = await import("/src/shared/api.ts");
      try { await desktop.start(false); return false; }
      catch { return true; }
    }), true);
    payload = original;
  }

  await page.route("**/api/v1/health", (route) => {
    assert.equal(route.request().headers()["x-app-session"], token);
    return route.fulfill({ json: { status: "ok", protocol_version: 1, setup_required: true } });
  });
  await page.goto("http://127.0.0.1:1420/");
  await page.getByText("Bản xem thử Docker trên máy này", { exact: true }).waitFor();
  await page.getByText("Tạo tài khoản quản trị đầu tiên", { exact: true }).waitFor();
  assert.equal(await page.evaluate(() => localStorage.length + sessionStorage.length), 0);
  console.log(`PASS synthetic preview bridge: bootstrap headers/validation, 9 native rejections, memory-only credentials, no native shim, banner, health session header; bootstrap requests=${bootstrapCount}`);
} finally {
  await browser.close();
}
