import { expect, test, type Page } from "@playwright/test";

function summary() {
  return {
    coverage: "entered_records_only", cutoff: "2026-11-07T03:00:00Z", from_on: "2026-11-02", through_on: "2026-11-07",
    counts: { farms: 3, farm_surveys: 7, customer_companies: 2, inbound_trades: 4, outbound_trades: 5 },
    inventory: { items: [{ product_id: "p", warehouse_id: "w", closing_kg: "9007199254740993.125" }, { product_id: "p2", warehouse_id: "w", closing_kg: "0.001" }], validation_flags: [] },
    period: { inbound_kg: "15.125", outbound_kg: "2.000", cash_in_vnd: "9007199254740993.12", cash_out_vnd: "1000.50", sales_order_value_vnd: "15125.00125", unpriced_sales_orders: 1 },
    daily: [{ occurred_on: "2026-11-07", inbound_kg: "15.125", outbound_kg: "2.000", cash_in_vnd: "9007199254740993.12", cash_out_vnd: "1000.50", sales_order_value_vnd: "15125.00125", unpriced_sales_orders: 1 }],
  };
}
async function mount(page: Page) {
  const reads: URL[] = [];
  let fail = false;
  await page.route("**/api/v1/records/records-dashboard?**", (route) => {
    reads.push(new URL(route.request().url()));
    return fail ? route.fulfill({ status: 503, json: { error: { code: "BUSY", message: "Chưa đọc được dữ liệu tổng quan.", field_errors: [], details: {} } } }) : route.fulfill({ json: summary() });
  });
  await page.route("**/dashboard-harness", (route) => route.fulfill({ contentType: "text/html", body: '<!doctype html><html><body><div id="root"></div></body></html>' }));
  await page.goto("/dashboard-harness#/records/dashboard?from_on=2026-11-02&through_on=2026-11-07");
  await page.evaluate(async () => {
    const refreshPath = "/@react-refresh";
    const refresh = (await import(refreshPath)).default;
    refresh.injectIntoGlobalHook(window);
    Reflect.set(window, "$RefreshReg$", () => {});
    Reflect.set(window, "$RefreshSig$", () => (type: unknown) => type);
    Reflect.set(window, "__vite_plugin_react_preamble_installed__", true);
    const harness = "/tests/dashboard-harness.tsx";
    (await import(harness)).mountDashboard();
  });
  await expect(page.getByRole("heading", { name: "Tổng quan kinh doanh" })).toBeVisible();
  await expect(page.getByText("Tồn kho cuối kỳ", { exact: true })).toBeVisible();
  return { reads, fail: () => { fail = true; } };
}

test("dashboard preserves exact large values, separates sources and links to the selected flow", async ({ page }) => {
  await mount(page);
  await expect(page.getByRole("link", { name: "9.007.199.254.740.993,126" })).toBeVisible();
  await expect(page.getByRole("link", { name: "9.007.199.254.740.993,12", exact: true })).toBeVisible();
  await expect(page.getByText("15.125,00125 đ", { exact: true })).toBeVisible();
  await expect(page.getByText(/1 đơn chưa đủ giá/)).toBeVisible();
  await expect(page.getByRole("link", { name: "5", exact: true })).toHaveAttribute("href", "#/records/outbound?from_on=2026-11-02&through_on=2026-11-07");
  await expect(page.getByRole("img", { name: "Xu hướng kg nhập và xuất theo ngày" })).toBeVisible();
  await expect(page.getByRole("columnheader", { name: "Thu khách hàng (đ)" })).toBeVisible();
});

test("invalid or oversized date drafts do not reach the API; valid dates become URL state", async ({ page }) => {
  const state = await mount(page);
  const count = state.reads.length;
  await page.getByLabel("Tổng quan từ ngày", { exact: true }).fill("31/02/2026");
  await page.getByRole("button", { name: "Xem tổng quan", exact: true }).click();
  await expect(page.getByText("Nhập đủ ngày hợp lệ; ngày đầu không được sau ngày cuối.")).toBeVisible();
  expect(state.reads.length).toBe(count);
  await page.getByLabel("Tổng quan từ ngày", { exact: true }).fill("01/01/2020");
  await page.getByRole("button", { name: "Xem tổng quan", exact: true }).click();
  await expect(page.getByText("Chọn khoảng không quá 366 ngày.")).toBeVisible();
  expect(state.reads.length).toBe(count);
  await page.getByLabel("Tổng quan từ ngày", { exact: true }).fill("07/11/2026");
  await page.getByRole("button", { name: "Xem tổng quan", exact: true }).click();
  await expect.poll(() => state.reads.at(-1)?.searchParams.get("from_on")).toBe("2026-11-07");
  await expect(page).toHaveURL(/from_on=2026-11-07&through_on=2026-11-07/);
});

test("refresh failure hides cached totals and displays an error instead of zero", async ({ page }) => {
  const state = await mount(page);
  state.fail();
  await page.getByRole("button", { name: "Làm mới", exact: true }).click();
  await expect(page.getByText("Chưa đọc được dữ liệu tổng quan.", { exact: true })).toBeVisible();
  await expect(page.getByText("Tồn kho cuối kỳ", { exact: true })).toHaveCount(0);
  await expect(page.getByText(/Chưa có số liệu đã xác minh/)).toBeVisible();
});
