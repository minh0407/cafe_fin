import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";
import assert from "node:assert/strict";
const root = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "../../..",
);
const require = createRequire(path.join(root, "frontend/package.json"));
const { chromium } = require("@playwright/test");
const browser = await chromium.launch({ headless: true });
process.on("message", (message) => {
  if (message?.type === "reporting-ui-cancel") void browser.close();
});
const manualLabel = "Sổ kế toán cho báo cáo";
const dailyLabel = "Sổ kế toán cho lịch tự động";
const row = {
  id: "picker-report",
  version: 1,
  state: "SAVED",
  from_on: "2026-11-06",
  through_on: "2026-11-06",
  sha256: "a".repeat(64),
};
const snapshot = {
  notice: "Chỉ tổng hợp dữ liệu đã nhập",
  cutoff: "2026-11-06T11:00:00Z",
  source_sha256: "b".repeat(64),
  consistency: "atomic_read_snapshot",
  period: {
    from_on: row.from_on,
    through_on: row.through_on,
    from: "2026-11-05T17:00:00Z",
    to: "2026-11-06T17:00:00Z",
    timezone: "Asia/Ho_Chi_Minh",
    date_range_contract: "inclusive_business_dates_v1",
    timestamp_range_contract: "half_open_utc",
  },
  sources: { inventory: { items: [] }, books: [] },
  warnings: [],
};
const settings = {
  version: 0,
  provider: "telegram",
  bot_id: null,
  bot_verified_at: null,
  chat_id: "",
  enabled: false,
  timezone: "Asia/Ho_Chi_Minh",
  send_at: null,
  attachments_enabled: false,
  auto_generate_daily: false,
  daily_book_ids: ["saved-remote"],
  daily_export_formats: ["txt"],
  credential_store_available: false,
  credential_configured: false,
  sender_status: "UNCONFIGURED",
};
async function scenario(
  unavailable = false,
  resolvedSelection = false,
  restored = false,
) {
  let currentSettings = structuredClone(settings);
  if (restored)
    Object.assign(currentSettings, {
      bot_id: "123456",
      bot_verified_at: null,
      chat_id: "-1001234567890",
      send_at: "18:00",
      restore_review_required: true,
      credential_configured: null,
      sender_status: "RESTORE_SUSPENDED",
    });
  const page = await browser.newPage({
    viewport: { width: 1440, height: 1300 },
  });
  const calls = [],
    errors = [];
  let releaseDetail,
    releasePage,
    holdOldPage = false;
  const detailGate = new Promise((resolve) => {
    releaseDetail = resolve;
  });
  const pageGate = new Promise((resolve) => {
    releasePage = resolve;
  });
  page.on("pageerror", (error) => errors.push(error.message));
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const resource = url.pathname.replace("/api/v1", "");
    const nextActor =
      request.headers().authorization === "Bearer synthetic-next";
    calls.push({
      resource,
      query: url.search,
      method: request.method(),
      body: request.postData(),
      nextActor,
    });
    let result = {};
    if (resource === "/accounting/books") {
      if (unavailable) {
        await route.fulfill({
          status: 404,
          json: {
            error: {
              code: "ACCOUNTING_UNAVAILABLE",
              message: "Kế toán chưa sẵn sàng.",
            },
          },
        });
        return;
      }
      assert.equal(url.searchParams.get("page_size"), "50");
      assert(!url.searchParams.has("search"));
      if (holdOldPage && !nextActor) await pageGate;
      const current = Number(url.searchParams.get("page"));
      const books = nextActor
        ? [{ id: "next-book", name: "Sổ người dùng mới" }]
        : Array.from({ length: 50 }, (_, index) => ({
            id: `book-${(current - 1) * 50 + index + 1}`,
            name:
              index === 0
                ? current === 1
                  ? "Sổ <quỹ & tiền>"
                  : `Sổ trang ${current}`
                : `Sổ ${current}-${index + 1}`,
          }));
      result = {
        items: books,
        total: nextActor ? 1 : 150,
        page: current,
        page_size: 50,
      };
    } else if (resource === "/accounting/books/saved-remote") {
      await detailGate;
      result = {
        id: "saved-remote",
        name: resolvedSelection ? "Sổ đã lưu ngoài trang" : "STALE_SAVED_NAME",
      };
    } else if (resource === "/reporting/settings") {
      if (request.method() === "PUT") {
        currentSettings = {
          ...currentSettings,
          ...JSON.parse(request.postData()),
          version: currentSettings.version + 1,
        };
        if (currentSettings.enabled)
          currentSettings.restore_review_required = false;
      }
      result = currentSettings;
    } else if (resource === "/reporting/reports/preview") result = row;
    else if (resource === "/reporting/reports/picker-report")
      result = { ...row, snapshot, short_message: "Bản tổng hợp", exports: [] };
    else if (resource === "/reporting/reports")
      result = { items: [row], total: 1, page: 1, page_size: 25 };
    else if (resource === "/reporting/deliveries")
      result = {
        items: ["UNKNOWN", "FAILED"].map((state) => ({
          id: "restore-" + state,
          report_id: row.id,
          version: 2,
          provider: "telegram",
          chat_id: "-1001234567890",
          destination: "-1001234567890",
          state,
          attempts: 0,
          error_code: "RESTORE_REVIEW_REQUIRED",
        })),
        total: 2, page: 1, page_size: 25,
      };
    else if (resource.endsWith("/daily-runs"))
      result = { items: [], total: 0, page: 1, page_size: 25 };
    try {
      await route.fulfill({ status: 200, json: result });
    } catch {
      /* Actor switch may abort the old request. */
    }
  });
  await page.goto("http://127.0.0.1:1431");
  await page.getByText("Xem bản 1", { exact: true }).waitFor();
  const picker = page.getByRole("group", {
    name: `${manualLabel} — danh sách sổ`,
    exact: true,
  });
  const combo = picker.getByRole("combobox", {
    name: manualLabel,
    exact: true,
  });
  if (resolvedSelection) {
    releaseDetail();
    await page
      .getByRole("tab", { name: "Cấu hình Admin", exact: true })
      .click();
    const daily = page.getByRole("group", {
      name: `${dailyLabel} — danh sách sổ`,
      exact: true,
    });
    await daily.getByText("Sổ đã lưu ngoài trang", { exact: true }).waitFor();
    await daily.getByTitle("2", { exact: true }).click();
    await daily.getByText("Sổ đã lưu ngoài trang", { exact: true }).waitFor();
    await page
      .getByRole("button", { name: "Lưu cấu hình", exact: true })
      .click();
    await page.getByText("Đã lưu cấu hình.", { exact: true }).waitFor();
    assert.deepEqual(
      JSON.parse(
        calls.find(
          (call) =>
            call.resource === "/reporting/settings" && call.method === "PUT",
        ).body,
      ).daily_book_ids,
      ["saved-remote"],
    );
    assert.equal(
      calls.filter((call) => call.resource === "/accounting/books/saved-remote")
        .length,
      1,
    );
    assert.deepEqual(errors, []);
    releasePage();
    await page.close();
    return;
  }
  if (unavailable) {
    await picker
      .getByText("Chưa tải được sổ Kế toán", { exact: true })
      .waitFor();
    await page
      .getByRole("button", { name: "Xem trước báo cáo", exact: true })
      .click();
    await page.getByText("Snapshot báo cáo", { exact: true }).waitFor();
    assert.deepEqual(
      JSON.parse(calls.find((call) => call.resource.endsWith("/preview")).body)
        .book_ids,
      [],
    );
    if (restored) {
      const banner = page.getByText(
        "Đã khôi phục dữ liệu — lịch và gửi Telegram đang tạm dừng",
        { exact: true },
      );
      await banner.waitFor();
      assert(await page.getByRole("button", {
        name: "Xếp gửi bản tổng hợp này", exact: true,
      }).isDisabled());
      await page.getByRole("button", { name: "Close", exact: true }).click();
      await page.getByRole("tab", { name: "Lượt gửi", exact: true }).click();
      for (const name of ["Thử lại", "Đối chiếu"])
        assert(await page.getByRole("button", { name, exact: true }).isDisabled());
      await page.getByRole("tab", { name: "Cấu hình Admin", exact: true }).click();
      assert(await page.getByRole("button", {
        name: "Kiểm tra kết nối", exact: true,
      }).isDisabled());
      if (process.env.REPORTING_QA_OUTPUT)
        await page.screenshot({
          path: path.join(process.env.REPORTING_QA_OUTPUT, "reporting-restore-review.png"),
          fullPage: true,
        });
      const enabled = page.locator("#enabled");
      assert.equal(await enabled.getAttribute("aria-checked"), "false");
      await enabled.click();
      await page.getByRole("button", { name: "Lưu cấu hình", exact: true }).click();
      await banner.waitFor({ state: "hidden" });
      const saved = JSON.parse(calls.find(
        (call) => call.resource === "/reporting/settings" && call.method === "PUT",
      ).body);
      assert.equal(saved.enabled, true);
      assert(!("restore_review_required" in saved) && !("restore_review" in saved));
      assert(!calls.some((call) =>
        /credentials|connection-check|scheduler\/tick|\/deliveries$/.test(call.resource)
        && call.method !== "GET",
      ));
    }
  } else {
    await combo.click();
    await page
      .getByRole("option", { name: "Sổ <quỹ & tiền>", exact: true })
      .click();
    await combo.press("Escape");
    assert.equal(await page.locator("quỹ").count(), 0);
    await picker.getByTitle("2", { exact: true }).click();
    await combo.click();
    await page.getByRole("option", { name: "Sổ trang 2", exact: true }).click();
    await combo.press("Escape");
    assert.match(await picker.innerText(), /Sổ <quỹ & tiền>/);
    assert.match(await picker.innerText(), /Sổ trang 2/);
    assert.deepEqual(
      calls
        .filter((call) => call.resource === "/accounting/books")
        .map((call) => call.query),
      ["?page=1&page_size=50", "?page=2&page_size=50"],
    );
    await page
      .getByRole("button", { name: "Xem trước báo cáo", exact: true })
      .click();
    await page.getByText("Snapshot báo cáo", { exact: true }).waitFor();
    assert.deepEqual(
      JSON.parse(calls.find((call) => call.resource.endsWith("/preview")).body)
        .book_ids,
      ["book-1", "book-51"],
    );
    await page.getByRole("button", { name: "Close", exact: true }).click();
    await page
      .getByRole("tab", { name: "Cấu hình Admin", exact: true })
      .click();
    const daily = page.getByRole("group", {
      name: `${dailyLabel} — danh sách sổ`,
      exact: true,
    });
    await page.waitForFunction(
      () => !!document.querySelector("#daily_book_ids"),
    );
    await daily
      .getByText("Sổ đã chọn 1 (chưa đọc được tên)", { exact: true })
      .waitFor();
    // Wait for real selected-ID lookup, then remove before it returns.
    const lookupDeadline = Date.now() + 5000;
    while (
      Date.now() < lookupDeadline &&
      !calls.some((call) => call.resource === "/accounting/books/saved-remote")
    )
      await page.waitForTimeout(10);
    assert(
      calls.some((call) => call.resource === "/accounting/books/saved-remote"),
    );
    await daily.locator(".ant-select-selection-item-remove").click();
    releaseDetail();
    const dailyCombo = daily.getByRole("combobox", {
      name: dailyLabel,
      exact: true,
    });
    await dailyCombo.click();
    await page
      .getByRole("option", { name: "Sổ <quỹ & tiền>", exact: true })
      .click();
    await dailyCombo.press("Escape");
    await page
      .getByRole("button", { name: "Lưu cấu hình", exact: true })
      .click();
    await page.getByText("Đã lưu cấu hình.", { exact: true }).waitFor();
    assert.deepEqual(
      JSON.parse(
        calls.find(
          (call) =>
            call.resource === "/reporting/settings" && call.method === "PUT",
        ).body,
      ).daily_book_ids,
      ["book-1"],
    );
    assert.equal(
      await page.getByText("STALE_SAVED_NAME", { exact: true }).count(),
      0,
    );
    holdOldPage = true;
    await picker
      .getByRole("button", { name: "Tải lại danh sách sổ", exact: true })
      .click();
    await page.evaluate(() => window.reportingQA.switchActor());
    releasePage();
    const fresh = page.getByRole("group", {
      name: `${manualLabel} — danh sách sổ`,
      exact: true,
    });
    await fresh
      .getByRole("combobox", { name: manualLabel, exact: true })
      .click();
    await page
      .getByRole("option", { name: "Sổ người dùng mới", exact: true })
      .waitFor();
    assert.equal(
      await page.getByText("Sổ <quỹ & tiền>", { exact: true }).count(),
      0,
    );
    assert.equal(
      await page.getByText("STALE_SAVED_NAME", { exact: true }).count(),
      0,
    );
    assert.match(await fresh.innerText(), /Đã chọn 0\/100/);
  }
  releaseDetail();
  releasePage();
  assert.deepEqual(errors, []);
  await page.close();
}
try {
  await scenario();
  await scenario(true);
  await scenario(false, true);
  await scenario(true, false, true);
  console.log(
    JSON.stringify({
      status: "PASS",
      cases: [
        "bounded 50-row pages, no server-search fiction",
        "names and IDs retained across pages",
        "escaped book label",
        "preview ID-array payload",
        "selected-ID detail lookup",
        "stale removed-selection response ignored",
        "schedule ID-array payload",
        "actor switch discards stale page/names",
        "accounting unavailable still permits inventory-only preview",
        "restored off-page selection resolves name and retains ID across page change",
        "restore banner preserves inventory-only local preview",
        "restore hold disables enqueue, retry, reconcile and connection check",
        "explicit settings enable clears banner without client-authored guard metadata",
        "restore review makes no credential, transport or scheduler request",
      ],
    }),
  );
} finally {
  await browser.close();
  if (process.connected) process.disconnect();
}
