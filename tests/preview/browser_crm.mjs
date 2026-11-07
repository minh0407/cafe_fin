// Read-only UI smoke against the disposable project verified by docker_smoke.py.
// Credentials arrive through stdin, stay in memory, and never reach diagnostics.
import { createRequire } from "node:module";
const requireFrontend = createRequire(new URL("../../frontend/package.json", import.meta.url));
const { chromium, expect } = requireFrontend("@playwright/test");
let browser;
let stage = "INPUT";
try {
  let input = "";
  for await (const chunk of process.stdin) input += chunk;
  const context = JSON.parse(input);
  if (!/^cafe-fin-preview-smoke(?:-[a-z0-9-]{1,32})?$/.test(context.project)) throw new Error();
  browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1480, height: 1100 } });
  let pageErrors = 0;
  page.on("pageerror", () => { pageErrors += 1; });
  stage = "LOGIN_FORM";
  await page.goto("http://127.0.0.1:1420");
  await page.getByLabel("Tên đăng nhập", { exact: true }).fill(context.username);
  await page.getByLabel("Mật khẩu", { exact: true }).fill(context.password);
  await page.getByRole("button", { name: "Đăng nhập", exact: true }).click();
  stage = "DASHBOARD";
  await expect(page.getByRole("heading", { name: "Tổng quan kinh doanh", exact: true })).toBeVisible();
  await page.getByLabel("Tổng quan từ ngày", { exact: true }).fill("06/11/2026");
  await page.getByLabel("Tổng quan đến ngày", { exact: true }).fill("06/11/2026");
  await page.getByRole("button", { name: "Xem tổng quan", exact: true }).click();
  stage = "DASHBOARD_TOTAL";
  await expect(page.getByRole("link", { name: "45,67", exact: true })).toBeVisible();
  for (const [route, heading] of [["farms", "Farm"], ["customers", "Công ty khách hàng"], ["prices", "Bảng giá"], ["inbound", "Đầu vào"], ["outbound", "Đầu ra"]]) {
    stage = `NAV_${route}`;
    await page.goto(`http://127.0.0.1:1420/#/records/${route}`);
    await expect(page.getByRole("heading", { name: new RegExp(heading) }).first()).toBeVisible();
    if (route === "prices") {
      await expect(page.getByText("Tự động giá nhập nhân xô Robusta Gia Lai", { exact: true })).toBeVisible();
      await expect(page.getByRole("switch", { name: "Tự động lấy giá nhân xô", exact: true })).toBeVisible();
    }
  }
  await page.goto(`http://127.0.0.1:1420/#/records/outbound?selected=${context.outbound_id}`);
  stage = "TRADE_DETAIL";
  // Route selection is additionally exercised by the real API records browser suite.
  await expect(page.getByText("TEST-COMPANY — Synthetic customer company", { exact: true }).first()).toBeVisible();
  stage = "LINKED_STOCK_DETAIL";
  await expect(page.getByRole("heading", { name: "Nhập / xuất kho đã liên kết", exact: true })).toBeVisible();
  if (context.priced_outbound_id) {
    stage = "FROZEN_PRICE_EDITOR";
    let quoteRequests = 0;
    page.on("request", (request) => { if (new URL(request.url()).pathname.endsWith("/records/price-quote")) quoteRequests += 1; });
    await page.goto(`http://127.0.0.1:1420/#/records/outbound?selected=${context.priced_outbound_id}`);
    await page.getByRole("button", { name: "Sửa đơn", exact: true }).click();
    await page.getByRole("button", { name: "Tiếp tục nhập đơn bán", exact: true }).click();
    await expect(page.getByLabel("Đơn giá (VND/kg)", { exact: true })).toHaveValue("150.01");
    await expect(page.getByLabel("Đơn giá (VND/kg)", { exact: true })).toHaveAttribute("readonly", "");
    await page.getByLabel("Số kg", { exact: true }).fill("3.501");
    await expect(page.getByText("Thành tiền dòng (VND): 525,18501", { exact: true })).toBeVisible();
    if (quoteRequests !== 0) throw new Error();
  }
  stage = "PAGE_ERRORS";
  if (pageErrors !== 0) throw new Error();
  console.log("PASS DOCKER_PRODUCTION_BROWSER_CRM_NAVIGATION");
} catch {
  console.error(`FAIL DOCKER_PRODUCTION_BROWSER_CRM_NAVIGATION_${stage}`);
  process.exitCode = 1;
} finally {
  await browser?.close();
}
