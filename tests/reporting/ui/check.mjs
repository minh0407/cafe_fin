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
const output =
  process.env.REPORTING_QA_OUTPUT ||
  path.join(process.env.TEMP, "cafe-fin-reporting-qa");
await fs.mkdir(output, { recursive: true });
let timerFailed = false;
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
const exportFile = {
  id: "demo-summary-export",
  report_id: row.id,
  format: "pdf",
  file_id: "service-owned-file",
  sha256: "d".repeat(64),
  size: 24,
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
  if (
    resource ===
    "/reporting/reports/demo-report/exports/demo-summary-export/content"
  ) {
    await route.fulfill({
      status: 200,
      contentType: "application/pdf",
      body: "%PDF synthetic summary",
    });
    return;
  }
  if (resource === "/reporting/settings")
    result = {
      version: 0,
      oa_id: "",
      group_id: "",
      enabled: false,
      timezone: "Asia/Ho_Chi_Minh",
      send_at: null,
      attachments_enabled: false,
      auto_generate_daily: false,
      daily_book_ids: [],
      daily_export_formats: ["pdf", "xlsx", "txt"],
      scheduled_actor_id: "server-owned-synthetic-id",
      schedule_actor_status: "ACTIVE",
      scheduler_mode: "APP_RUNTIME",
      scheduler_limit: "Lịch backend không cần mở màn hình Báo cáo.",
      scheduler_status: {
        registered: true,
        state: "RUNNING",
        running: true,
        active: false,
        error_code: timerFailed ? "PERIODIC_TASK_FAILED" : null,
        last_error_code: "PERIODIC_TASK_FAILED",
        task_error_code: timerFailed ? "PERIODIC_TASK_FAILED" : null,
        runs: 5,
        failures: 1,
      },
      credential_store_available: false,
      credential_configured: false,
      sender_status: "UNCONFIGURED",
    };
  else if (resource === "/reporting/scheduler/tick") {
    timerFailed = !timerFailed;
    result = { job_id: "synthetic-manual-check" };
  } else if (resource === "/reporting/scheduler/daily-runs")
    result = {
      items: [
        {
          id: "missed-demo",
          business_on: "2026-11-05",
          state: "MISSED",
          phase: "capture",
          policy: "MISSED_NO_SNAPSHOT",
          report_id: null,
          outbox_id: null,
          attempts: 0,
          error_code: "MISSED_REQUIRES_MANUAL",
          config_version: 1,
        },
      ],
      total: 1,
      page: 1,
      page_size: 25,
    };
  else if (resource === "/reporting/reports")
    result = {
      items: [row],
      total: 26,
      page: Number(url.searchParams.get("page")),
      page_size: 25,
    };
  else if (resource === "/reporting/reports/demo-report/exports")
    result = exportFile;
  else if (resource === "/reporting/reports/preview") result = row;
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
  const firstDate = page.getByLabel("Từ ngày (VN)", { exact: true });
  const lastDate = page.getByLabel("Đến hết ngày (VN)", { exact: true });
  assert.match(await firstDate.inputValue(), /^\d{2}\/\d{2}\/\d{4}$/);
  await firstDate.fill("06/11/2026");
  await lastDate.fill("06/11/2026");
  const previewCount = () =>
    calls.filter((x) => x.resource === "/reporting/reports/preview").length;
  await page
    .getByRole("button", { name: "Mở lịch chọn ngày", exact: true })
    .first()
    .click();
  await page.getByText("Chọn ngày", { exact: true }).waitFor();
  assert.equal(previewCount(), 0);
  assert.equal(await firstDate.inputValue(), "06/11/2026");
  await lastDate.click();
  await firstDate.fill("31/02/2026");
  await page
    .getByRole("button", { name: "Xem trước báo cáo", exact: true })
    .click();
  await page
    .locator("#from_on_help")
    .getByText("Ngày không hợp lệ. Nhập DD/MM/YYYY.", { exact: true })
    .waitFor();
  assert.equal(await firstDate.inputValue(), "31/02/2026");
  assert.equal(previewCount(), 0);
  await firstDate.fill("05/11/2026");
  await lastDate.fill("07/");
  await page
    .getByRole("button", { name: "Xem trước báo cáo", exact: true })
    .click();
  await page
    .locator("#through_on_help")
    .getByText("Ngày không hợp lệ. Nhập DD/MM/YYYY.", { exact: true })
    .waitFor();
  assert.equal(await lastDate.inputValue(), "07/");
  assert.equal(previewCount(), 0);
  await lastDate.fill("");
  await page
    .getByRole("button", { name: "Xem trước báo cáo", exact: true })
    .click();
  await page.getByText("Nhập ngày cuối.", { exact: true }).waitFor();
  assert.equal(previewCount(), 0);
  await lastDate.fill("06/11/2026");
  await page
    .getByRole("button", { name: "Xem trước báo cáo", exact: true })
    .click();
  await page.getByText("Snapshot báo cáo", { exact: true }).waitFor();
  assert.equal(previewCount(), 1);
  const previewBody = JSON.parse(
    calls.findLast((x) => x.resource === "/reporting/reports/preview").body,
  );
  assert.equal(previewBody.from_on, "2026-11-05");
  assert.equal(previewBody.through_on, "2026-11-06");
  await page.getByRole("button", { name: "Close", exact: true }).click();
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
  const downloading = page.waitForEvent("download");
  await page.getByRole("button", { name: "Xuất PDF", exact: true }).click();
  const downloaded = await downloading;
  assert.equal(downloaded.suggestedFilename(), "CafeFin-tong-hop.pdf");
  assert(
    calls.some(
      (x) =>
        x.resource ===
        "/reporting/reports/demo-report/exports/demo-summary-export/content",
    ),
  );
  assert(!calls.some((x) => x.resource.startsWith("/files/")));
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
  await page.getByText("Bỏ lỡ; cần tạo thủ công", { exact: true }).waitFor();
  await page.getByText("Lịch nền: Đang chạy", { exact: true }).waitFor();
  await page.getByText(/Mã lỗi gần nhất: PERIODIC_TASK_FAILED/).waitFor();
  assert(!calls.some((x) => x.resource === "/reporting/scheduler/tick"));
  assert.equal(
    await page
      .getByLabel("Tự tạo và lưu báo cáo cuối ngày", { exact: true })
      .getAttribute("aria-checked"),
    "false",
  );
  await page
    .getByLabel("Tự tạo và lưu báo cáo cuối ngày", { exact: true })
    .click();
  await page
    .getByLabel(
      "Các sổ cho báo cáo tự động (mã cách bằng dấu phẩy, tối đa 100)",
      { exact: true },
    )
    .fill("cash, missing");
  await page.getByLabel("Giờ gửi", { exact: true }).fill("18:00");
  await page
    .getByRole("button", { name: "Yêu cầu kiểm tra lịch ngay", exact: true })
    .click();
  await page.getByText(/Lỗi hiện tại: PERIODIC_TASK_FAILED/).waitFor();
  assert.equal(
    await page.getByLabel("Giờ gửi", { exact: true }).inputValue(),
    "18:00",
  );
  await page
    .getByRole("button", { name: "Yêu cầu kiểm tra lịch ngay", exact: true })
    .click();
  await page
    .getByText(/Lỗi hiện tại: PERIODIC_TASK_FAILED/)
    .waitFor({ state: "hidden" });
  assert.equal(
    calls.filter((x) => x.resource === "/reporting/scheduler/tick").length,
    2,
  );
  await page.getByRole("button", { name: "Lưu cấu hình", exact: true }).click();
  await page.getByText("Đã lưu cấu hình.", { exact: true }).waitFor();
  const configWrite = calls.findLast(
    (x) => x.resource === "/reporting/settings" && x.method === "PUT",
  );
  const configBody = JSON.parse(configWrite.body);
  assert.equal(configBody.auto_generate_daily, true);
  assert.deepEqual(configBody.daily_book_ids, ["cash", "missing"]);
  assert.deepEqual(configBody.daily_export_formats, ["pdf", "xlsx", "txt"]);
  assert(!Object.hasOwn(configBody, "scheduled_actor_id"));
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
        "DD/MM/YYYY single-day defaults and inclusive end label",
        "calendar opens without submitting or changing the selected period",
        "invalid, partial and empty required dates block preview API",
        "corrected date posts new ISO inclusive bounds rather than stale date",
        "summary export downloads through authorized reporting route, no raw file URL",
        "unmarked legacy cannot enqueue",
        "snapshot exact kg/missing mapping",
        "v2 components and deposit subset labels",
        "UNKNOWN no retry",
        "reconcile remains unknown",
        "unconfigured credentials disabled",
        "connection check no send",
        "daily generation explicit opt-in, selected books/formats, no actor spoof",
        "missed day status visible",
        "actual timer status and sanitized current/last errors",
        "explicit manual check preserves configuration draft",
        "actor draft reset",
      ],
      screenshots: output,
    }),
  );
} catch (cause) {
  const failurePath = path.join(output, "reporting-ui-failure.png");
  await page.screenshot({
    path: failurePath,
    fullPage: true,
    animations: "disabled",
  });
  console.error(
    JSON.stringify({
      pageErrors: failures,
      buttons: await page.getByRole("button").allTextContents(),
      manualButton: await page
        .getByRole("button")
        .filter({ hasText: "Yêu cầu kiểm tra lịch ngay" })
        .ariaSnapshot({ timeout: 1000 })
        .catch(() => null),
      credentialButton: await page
        .getByRole("button")
        .filter({ hasText: "Lưu credential" })
        .ariaSnapshot({ timeout: 1000 })
        .catch(() => null),
      screenshot: failurePath,
    }),
  );
  throw cause;
} finally {
  await browser.close();
}
