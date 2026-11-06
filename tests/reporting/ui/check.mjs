import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";
import fs from "node:fs/promises";
import assert from "node:assert/strict";
const root = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "../../..",
);
const require = createRequire(path.join(root, "frontend/package.json"));
const { chromium } = require("@playwright/test");
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 1080 } });
const failures = [];
page.on("pageerror", (error) => failures.push(error.message));
const calls = [];
const row = {
  id: "demo-report",
  version: 1,
  from_on: "2026-11-06",
  through_on: "2026-11-06",
  state: "SAVED",
  sha256: "a".repeat(64),
  reason: "Dữ liệu tổng hợp kiểm thử",
  created_at: "2026-11-06T10:00:00Z",
  saved_at: "2026-11-06T10:01:00Z",
};
const snapshot = {
  notice: "Chỉ tổng hợp dữ liệu đã nhập",
  cutoff: "2026-11-06T10:00:00Z",
  source_sha256: "b".repeat(64),
  consistency: "atomic_read_snapshot",
  period: {
    date_range_contract: "inclusive_business_dates_v1",
    timestamp_range_contract: "half_open_utc",
    from_on: row.from_on,
    through_on: row.through_on,
    from: "2026-11-05T17:00:00Z",
    to: "2026-11-06T17:00:00Z",
    timezone: "Asia/Ho_Chi_Minh",
  },
  sources: {
    inventory: {
      items: [
        {
          warehouse_id: "Kho tổng hợp",
          product_id: "Robusta tổng hợp",
          opening_kg: "20.000",
          received_kg: "10.500",
          issued_kg: "5.250",
          closing_kg: "25.250",
        },
      ],
    },
    books: [
      {
        book_id: "Sổ demo",
        has_valid_money_mapping: false,
        metrics: [],
        validation_flags: [],
      },
    ],
  },
  warnings: ["PRODUCTION_BREAKDOWN_UNAVAILABLE", "MONEY_DATA_INCOMPLETE"],
};
const delivery = {
  id: "demo-delivery",
  report_id: row.id,
  destination: "nhom-tong-hop",
  oa_id: "demo-oa",
  state: "UNKNOWN",
  phase: "text",
  version: 3,
  attempts: 1,
  message_id: null,
  file_message_id: null,
  error_code: "ZALO_NETWORK_ERROR",
  created_at: row.created_at,
};
await page.route("**/api/v1/**", async (route) => {
  const url = new URL(route.request().url());
  const resource = url.pathname.replace("/api/v1", "");
  calls.push({
    resource,
    query: url.search,
    method: route.request().method(),
    body: route.request().postData(),
  });
  let result = {};
  if (resource === "/reporting/settings")
    result = {
      version: 0,
      oa_id: "",
      group_id: "",
      enabled: false,
      timezone: "Asia/Ho_Chi_Minh",
      send_at: null,
      attachments_enabled: false,
      credential_store_available: false,
      credential_configured: false,
      sender_status: "UNCONFIGURED",
    };
  else if (resource === "/reporting/reports")
    result = {
      items: [row],
      total: 26,
      page: Number(url.searchParams.get("page")),
      page_size: 25,
    };
  else if (resource === "/reporting/reports/demo-report")
    result = {
      ...row,
      snapshot,
      short_message:
        "Cafe Fin 2026-11-06 - bản 1\nChỉ tổng hợp dữ liệu đã nhập",
      exports: [],
    };
  else if (resource === "/reporting/deliveries")
    result = { items: [delivery], total: 1, page: 1, page_size: 25 };
  else if (resource.endsWith("/reconcile")) result = delivery;
  else if (resource === "/reporting/connection-check")
    result = { state: "UNCONFIGURED", code: "ZALO_UNCONFIGURED" };
  await route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify(result),
  });
});
try {
  await page.goto("http://127.0.0.1:1431");
  await page.getByText("Xem bản 1", { exact: true }).waitFor();
  assert.equal(
    await page.getByLabel("Từ ngày (VN)", { exact: true }).inputValue(),
    await page.getByLabel("Đến hết ngày (VN)", { exact: true }).inputValue(),
  );
  await page.getByTitle("2", { exact: true }).click();
  await page.waitForFunction(() =>
    location.search.includes("reporting_page=2"),
  );
  assert(calls.some((x) => x.query.includes("page=2")));
  await page.getByText("Xem bản 1", { exact: true }).click();
  await page.getByText("Snapshot báo cáo", { exact: true }).waitFor();
  await page.getByText(/2026-11-06 đến hết 2026-11-06/).waitFor();
  await page.getByText("Chưa đủ dữ liệu tiền", { exact: true }).waitFor();
  await page.getByText("25,250", { exact: true }).waitFor();
  assert(await page.getByRole("button", { name: "Xuất PDF" }).isVisible());
  const output =
    process.env.REPORTING_QA_OUTPUT ||
    path.join(process.env.TEMP, "cafe-fin-reporting-qa");
  await fs.mkdir(output, { recursive: true });
  await page.waitForFunction(
    () =>
      getComputedStyle(document.querySelector(".ant-modal")).opacity === "1",
  );
  await page.screenshot({
    path: path.join(output, "reporting-snapshot.png"),
    fullPage: true,
    animations: "disabled",
  });
  await page.getByRole("button", { name: "Close", exact: true }).click();
  snapshot.sources.inventory.movement_breakdown = [
    {
      warehouse_id: "Kho tổng hợp",
      product_id: "Robusta tổng hợp",
      purchased_kg: "5.500",
      sold_kg: "2.250",
      production_input_kg: "1.000",
      production_output_kg: "3.000",
      transfer_in_kg: "2.000",
      transfer_out_kg: "2.000",
      adjustment_in_kg: "0.000",
      adjustment_out_kg: "0.000",
    },
  ];
  snapshot.sources.books.unshift({
    book_id: "Tiền tổng hợp",
    has_valid_money_mapping: true,
    metrics: [
      {
        key: "cot-A",
        meaning: "cash_receipts",
        amount_vnd: "1234567890.01",
        mapping_revision: 2,
      },
      {
        key: "cot-B",
        meaning: "cash_receipt_deposits",
        amount_vnd: "100.00",
        mapping_revision: 2,
      },
    ],
    validation_flags: [],
  });
  snapshot.warnings = ["MONEY_DATA_INCOMPLETE"];
  await page.setViewportSize({ width: 1440, height: 1500 });
  await page.getByText("Xem bản 1", { exact: true }).click();
  await page
    .getByText(
      "Các thành phần nằm trong nhập/xuất tổng; không cộng thêm vào tồn.",
      { exact: true },
    )
    .waitFor();
  await page.getByText(/Tổng thu tiền: 1.234.567.890,01/).waitFor();
  await page.getByText(/Cọc thu \(trong tổng thu\): 100,00/).waitFor();
  await page.waitForFunction(
    () =>
      getComputedStyle(document.querySelector(".ant-modal")).opacity === "1",
  );
  await page.screenshot({
    path: path.join(output, "reporting-v2-snapshot.png"),
    fullPage: true,
    animations: "disabled",
  });
  await page.getByRole("button", { name: "Close", exact: true }).click();
  await page.setViewportSize({ width: 1440, height: 1080 });
  await page.getByRole("tab", { name: "Lượt gửi", exact: true }).click();
  await page.getByRole("button", { name: "Đối chiếu", exact: true }).waitFor();
  assert.equal(
    await page.getByRole("button", { name: "Thử lại", exact: true }).count(),
    0,
  );
  await page.getByRole("button", { name: "Đối chiếu", exact: true }).click();
  await page.getByText(/Đã yêu cầu đối chiếu/).waitFor();
  await page.screenshot({
    path: path.join(output, "reporting-deliveries.png"),
    fullPage: true,
    animations: "disabled",
  });
  await page.getByRole("tab", { name: "Cấu hình Admin", exact: true }).click();
  await page.getByText("UNCONFIGURED", { exact: true }).waitFor();
  assert(
    await page
      .getByRole("button", { name: "Lưu credential", exact: true })
      .isDisabled(),
  );
  await page
    .getByRole("button", { name: "Kiểm tra kết nối", exact: true })
    .click();
  await page.getByText(/Chưa gửi tin/).waitFor();
  assert(
    !calls.some(
      (x) => x.resource.endsWith("/deliveries") && x.method === "POST",
    ),
  );
  await page.screenshot({
    path: path.join(output, "reporting-settings.png"),
    fullPage: true,
    animations: "disabled",
  });
  delete snapshot.period.date_range_contract;
  delete snapshot.period.timestamp_range_contract;
  await page.getByRole("tab", { name: "Báo cáo", exact: true }).click();
  await page.getByText("Xem bản 1", { exact: true }).click();
  await page.getByText(/Kỳ cũ chưa định danh cách chọn ngày/).waitFor();
  assert(
    await page
      .getByRole("button", { name: "Xếp gửi bản tổng hợp này", exact: true })
      .isDisabled(),
  );
  await page.getByRole("button", { name: "Close", exact: true }).click();
  // Actor change clears in-memory detail and Admin-only credentials UI.
  await page.evaluate(() => window.reportingQA.logout());
  assert.equal(
    await page
      .getByRole("tab", { name: "Cấu hình Admin", exact: true })
      .count(),
    0,
  );
  assert.deepEqual(failures, []);
  console.log(
    JSON.stringify({
      status: "PASS",
      cases: [
        "paging URL+server",
        "single-day defaults and inclusive end label",
        "unmarked legacy cannot enqueue",
        "snapshot exact kg/missing mapping",
        "v2 components and deposit subset labels",
        "UNKNOWN no retry",
        "reconcile remains unknown",
        "unconfigured credentials disabled",
        "connection check no send",
        "actor draft reset",
      ],
      screenshots: output,
    }),
  );
} finally {
  await browser.close();
}
