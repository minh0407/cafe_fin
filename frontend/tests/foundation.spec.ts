import { test, expect, type Page } from "@playwright/test";

async function mockNativeAndApi(page: Page, existing = true) {
  await page.addInitScript(
    ({ existing }) => {
      const calls: unknown[] = [];
      Object.assign(window, {
        __nativeCalls: calls,
        __TAURI_INTERNALS__: {
          invoke: async (command: string, args: unknown) => {
            calls.push({ command, args });
            if (command === "desktop_status")
              return {
                data_root: existing ? "D:\\Dữ liệu Cafe Fin" : null,
                running: false,
              };
            if (command === "choose_data_root") return "D:\\Dữ liệu Cafe Fin";
            if (command === "start_backend" || command === "restart_backend")
              return {
                protocol_version: 1,
                api_base: "http://127.0.0.1:19099/api/v1",
                session_token: "synthetic-app-session",
                data_root: "D:\\Dữ liệu Cafe Fin",
              };
            throw new Error("Unexpected native command");
          },
        },
      });
    },
    { existing },
  );
  await page.route("http://127.0.0.1:19099/api/v1/**", async (route) => {
    const request = route.request();
    const headers = {
      "Access-Control-Allow-Origin": "http://127.0.0.1:1420",
      "Access-Control-Allow-Headers":
        "X-App-Session,Authorization,Content-Type",
      "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
    };
    if (request.method() === "OPTIONS") {
      await route.fulfill({ status: 204, headers });
      return;
    }
    expect(request.headers()["x-app-session"]).toBe("synthetic-app-session");
    const url = new URL(request.url());
    if (url.pathname.endsWith("/health")) {
      await route.fulfill({
        json: { status: "ok", protocol_version: 1, setup_required: false },
        headers,
      });
      return;
    }
    if (url.pathname.endsWith("/auth/login")) {
      await route.fulfill({
        json: {
          access_token: "synthetic-user-token",
          user: {
            id: "synthetic-user",
            username: "admin",
            role: "admin",
            permissions: ["*"],
          },
        },
        headers,
      });
      return;
    }
    if (url.pathname.endsWith("/auth/logout")) {
      await route.fulfill({ status: 204, headers });
      return;
    }
    if (url.pathname.endsWith("/spikes/grid")) {
      expect(request.headers().authorization).toBe(
        "Bearer synthetic-user-token",
      );
      const pageIndex = Number(url.searchParams.get("page"));
      const items = Array.from({ length: 500 }, (_, index) => {
        const row = (pageIndex - 1) * 500 + index + 1;
        return {
          id: `row-${row}`,
          source_sheet: "Tổng hợp",
          source_row: row + 1,
          code: String(row).padStart(6, "0"),
          description: `Cà phê Đắk Lắk ${row}`,
          occurred_on: "2026-11-06",
          amount: "92233720368547758.07",
          formula: "=SUM(A1:A2)",
          issues:
            index === 0
              ? [
                  {
                    sheet: "Tổng hợp",
                    row: row + 1,
                    column: "amount",
                    cell: `D${row + 1}`,
                    code: "EXAMPLE",
                    message: "Lỗi tổng hợp thử nghiệm",
                  },
                ]
              : [],
        };
      });
      await route.fulfill({
        json: { items, total: 1000000, page: pageIndex, page_size: 500 },
        headers,
      });
      return;
    }
    await route.fulfill({
      status: 404,
      json: {
        error: {
          code: "NOT_FOUND",
          message: "Không tìm thấy.",
          field_errors: [],
        },
        request_id: "synthetic-request",
      },
      headers,
    });
  });
}
async function login(page: Page) {
  await page.goto("/");
  await page.getByLabel("Tên đăng nhập").fill("admin");
  await page.getByLabel("Mật khẩu", { exact: true }).fill("synthetic-password");
  await page.getByRole("button", { name: "Đăng nhập", exact: true }).click();
  await expect(
    page.getByRole("menuitem", { name: "Bản thử bảng tính" }),
  ).toBeVisible();
}
test("React 19 grid edits exact strings, limits rendered rows, maps issues and pages on server", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await mockNativeAndApi(page);
  await login(page);
  await page.getByRole("menuitem", { name: "Bản thử bảng tính" }).click();
  await expect(page.getByTestId("loaded-rows")).toHaveText("Đang giữ 500 dòng");
  const grid = page.getByRole("grid", { name: "Grid projection" });
  expect(await grid.getByRole("row").count()).toBeLessThan(40);
  await expect(grid.getByText("000001", { exact: true })).toBeVisible();
  await expect(
    page.locator('[title="Tổng hợp!D2: Lỗi tổng hợp thử nghiệm"]'),
  ).toBeVisible();
  await grid.getByText("000001", { exact: true }).dblclick();
  const editor = grid.getByRole("textbox");
  await editor.fill("00000000000000000001");
  await editor.press("Enter");
  await expect(
    grid.getByText("00000000000000000001", { exact: true }),
  ).toBeVisible();
  await expect(
    page.getByText("Bản nháp chưa lưu", { exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Bỏ bản nháp" }).click();
  await page.getByRole("listitem", { name: "2", exact: true }).click();
  await expect(grid.getByText("000501", { exact: true })).toBeVisible();
  await expect(
    grid.getByText("92233720368547758.07", { exact: true }).first(),
  ).toBeVisible();
  const stored = await page.evaluate(() => ({
    local: { ...localStorage },
    session: { ...sessionStorage },
  }));
  expect(JSON.stringify(stored)).not.toContain("synthetic-app-session");
  expect(JSON.stringify(stored)).not.toContain("synthetic-user-token");
  expect(errors).toEqual([]);
});
test("first-run wizard requires explicit initialization and uses only native selected root", async ({
  page,
}) => {
  await mockNativeAndApi(page, false);
  await page.goto("/");
  await expect(
    page.getByRole("button", { name: "Mở dữ liệu local" }),
  ).toBeDisabled();
  await page.getByRole("button", { name: "Chọn thư mục dữ liệu" }).click();
  await expect(page.getByRole("checkbox")).not.toBeChecked();
  await page.getByRole("checkbox").check();
  await page.getByRole("button", { name: "Mở dữ liệu local" }).click();
  await expect(page.getByLabel("Tên đăng nhập")).toBeVisible();
  const calls = await page.evaluate(
    () =>
      (
        window as unknown as {
          __nativeCalls: { command: string; args?: unknown }[];
        }
      ).__nativeCalls,
  );
  expect(calls.find((call) => call.command === "start_backend")?.args).toEqual({
    initialize: true,
  });
});
test("backend loss is visible and does not report successful local save", async ({
  page,
}) => {
  await mockNativeAndApi(page);
  await login(page);
  await page.route("http://127.0.0.1:19099/api/v1/health", (route) =>
    route.abort(),
  );
  await expect(page.getByText(/Mất kết nối dữ liệu local/).first()).toBeVisible(
    { timeout: 10000 },
  );
  await expect(
    page.getByRole("button", { name: "Khởi động lại kết nối" }),
  ).toBeVisible();
});
test("paste keeps leading zeros and Unicode in bounded drafts, refuses an oversized range", async ({
  page,
}) => {
  await mockNativeAndApi(page);
  await login(page);
  await page.getByRole("menuitem", { name: "Bản thử bảng tính" }).click();
  const cell = page
    .getByRole("grid", { name: "Grid projection" })
    .getByText("000001", { exact: true });
  await cell.click();
  await cell.evaluate((element) => {
    const clipboard = new DataTransfer();
    clipboard.setData(
      "text/plain",
      "00000009\tCà phê Việt Nam\n00000010\tĐắk Lắk",
    );
    element.dispatchEvent(
      new ClipboardEvent("paste", {
        bubbles: true,
        cancelable: true,
        clipboardData: clipboard,
      }),
    );
  });
  await expect(page.getByText("00000009", { exact: true })).toBeVisible();
  await expect(
    page.getByText("Cà phê Việt Nam", { exact: true }),
  ).toBeVisible();
  await expect(page.getByText("00000010", { exact: true })).toBeVisible();
  await page.getByText("00000009", { exact: true }).evaluate((element) => {
    const clipboard = new DataTransfer();
    clipboard.setData(
      "text/plain",
      Array.from({ length: 501 }, () => "x").join("\n"),
    );
    element.dispatchEvent(
      new ClipboardEvent("paste", {
        bubbles: true,
        cancelable: true,
        clipboardData: clipboard,
      }),
    );
  });
  await expect(
    page.getByText(
      "Chỉ dán tối đa 500 ô vào vùng chỉnh sửa trong trang hiện tại.",
    ),
  ).toBeVisible();
  await expect(page.getByText("00000009", { exact: true })).toBeVisible();
  await expect(page.getByTestId("loaded-rows")).toHaveText("Đang giữ 500 dòng");
});
