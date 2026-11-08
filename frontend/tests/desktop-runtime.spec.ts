import { test, expect, type Page } from "@playwright/test";

interface Call {
  command: string;
  args: Record<string, unknown>;
}
async function mount(
  page: Page,
  options: {
    setup?: boolean;
    held?: boolean;
    healthError?: boolean;
    manual?: boolean;
    handler?: (call: Call) => Promise<unknown>;
  } = {},
) {
  const calls: Call[] = [];
  let enabled = false;
  let setup = options.setup ?? false;
  const boot = {
    protocol_version: 1,
    api_base: "http://127.0.0.1:1420/api/v1",
    session_token: "synthetic-runtime-session",
    data_root: "D:\\Synthetic",
    maintenance_protocol: 1,
    generation: "native-generation",
    runtime_state: options.held ? "DORMANT" : "ACTIVE",
    pending_transition: options.held
      ? {
          operation_id: "synthetic-operation",
          kind: "restore",
          phase: "CANDIDATE_DORMANT",
          recovery_required: true,
        }
      : null,
  };
  await page.exposeFunction(
    "runtimeNative",
    async (command: string, args: Record<string, unknown> = {}) => {
      const call = { command, args };
      calls.push(call);
      if (
        options.handler &&
        (command === "set_desktop_startup" ||
          command === "desktop_runtime_status")
      )
        return options.handler(call);
      if (command === "desktop_status")
        return {
          data_root: options.manual ? null : boot.data_root,
          running: false,
          runtime_state: "ACTIVE",
          pending_transition: null,
        };
      if (command === "start_backend") return boot;
      if (command === "choose_data_root") return boot.data_root;
      if (command === "desktop_runtime_status")
        return { startup_enabled: enabled, startup_supported: true };
      if (command === "set_desktop_startup") {
        enabled = args.enabled as boolean;
        return { startup_enabled: enabled, startup_supported: true };
      }
      if (command === "desktop_background_ready") return null;
      throw new Error(`unexpected-${command}`);
    },
  );
  await page.addInitScript(() => {
    Object.defineProperty(window, "__TAURI_INTERNALS__", {
      value: {
        invoke: async (command: string, args: Record<string, unknown>) => {
          try {
            return await Reflect.get(window, "runtimeNative")(command, args);
          } catch (error) {
            throw error instanceof Error ? error.message : error;
          }
        },
      },
    });
  });
  await page.route("**/api/v1/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/health"))
      return options.healthError
        ? route.fulfill({
            status: 503,
            json: {
              error: {
                code: "STORAGE_UNAVAILABLE",
                message: "Dữ liệu chưa sẵn sàng.",
                field_errors: [],
              },
              request_id: "synthetic",
            },
          })
        : route.fulfill({
            json: { status: "ok", protocol_version: 1, setup_required: setup },
          });
    if (path.endsWith("/auth/login") || path.endsWith("/auth/setup")) {
      setup = false;
      return route.fulfill({
        json: {
          access_token: "synthetic-user-token",
          user: {
            id: "admin",
            username: "admin",
            role: "admin",
            version: 1,
            permissions: ["*"],
          },
        },
      });
    }
    return route.fulfill({
      json: { items: [], total: 0, page: 1, page_size: 50 },
    });
  });
  await page.goto("/#/settings");
  return calls;
}
async function painted(page: Page) {
  await page.evaluate(
    () =>
      new Promise((resolve) =>
        requestAnimationFrame(() => requestAnimationFrame(() => resolve(null))),
      ),
  );
}

test("startup setting reads on demand, toggles only by user and remains available after login", async ({
  page,
}) => {
  const calls = await mount(page);
  await expect(page.getByLabel("Tên đăng nhập", { exact: true })).toBeVisible();
  expect(
    calls.filter(
      (call) =>
        call.command === "desktop_runtime_status" ||
        call.command === "set_desktop_startup",
    ),
  ).toHaveLength(0);
  await page
    .getByRole("button", { name: "Cài đặt chạy nền" })
    .click();
  const toggle = page.getByRole("switch", { name: "Tự mở cùng Windows" });
  await expect(toggle).toBeEnabled();
  await expect(toggle).not.toBeChecked();
  await toggle.click();
  await expect(toggle).toBeChecked();
  await toggle.click();
  await expect(toggle).not.toBeChecked();
  expect(
    calls
      .filter((call) => call.command === "set_desktop_startup")
      .map((call) => call.args),
  ).toEqual([{ enabled: true }, { enabled: false }]);
  await page.getByRole("button", { name: "Đóng cài đặt" }).click();
  await page.getByLabel("Tên đăng nhập", { exact: true }).fill("admin");
  await page.getByLabel("Mật khẩu", { exact: true }).fill("synthetic-password");
  await page.getByRole("button", { name: "Đăng nhập", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Đăng xuất", exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Cài đặt chạy nền" })
    .click();
  await expect(toggle).toBeEnabled();
  await expect(toggle).not.toBeChecked();
  await expect(
    page.getByText(/Máy ngủ hoặc tắt thì lịch không chạy/),
  ).toBeVisible();
  await painted(page);
  expect(
    calls.filter((call) => call.command === "desktop_background_ready"),
  ).toHaveLength(1);
});

for (const outcome of ["success", "failure"] as const)
  test(`old toggle ${outcome} cannot update settings or show feedback in a replacement session`, async ({
    page,
  }) => {
    let release!: () => void;
    let started!: () => void;
    const pending = new Promise<void>((resolve) => {
      release = resolve;
    });
    const called = new Promise<void>((resolve) => {
      started = resolve;
    });
    let reads = 0;
    await mount(page, {
      handler: async (call) => {
        if (call.command === "desktop_runtime_status") {
          reads += 1;
          return { startup_enabled: false, startup_supported: true };
        }
        started();
        await pending;
        if (outcome === "success")
          return { startup_enabled: true, startup_supported: true };
        throw new Error(
          "STARTUP_CONFLICT: PRIVATE synthetic token C:\\private-path",
        );
      },
    });
    try {
      await page
        .getByRole("button", { name: "Cài đặt chạy nền" })
        .click();
      const toggle = page.getByRole("switch", { name: "Tự mở cùng Windows" });
      await expect(toggle).toBeEnabled();
      await toggle.click();
      await called;
      await page.evaluate(async () => {
        const path = "/src/shared/session.ts";
        const { useSession } = await import(path);
        useSession.getState().login("synthetic-B", {
          id: "B",
          username: "B",
          role: "admin",
          version: 1,
          permissions: ["*"],
        });
      });
      await expect.poll(() => reads).toBeGreaterThan(1);
      release();
      await painted(page);
      await expect(toggle).toBeEnabled();
      await expect(toggle).not.toBeChecked();
      await expect(
        page.getByText(/Cấu hình khởi động hiện tại không khớp/),
      ).toHaveCount(0);
      await expect(
        page.getByText(/PRIVATE|private-path|synthetic token/),
      ).toHaveCount(0);
    } finally {
      release();
    }
  });

test("browser-only settings explain the limitation without invoking native commands", async ({
  page,
}) => {
  await page.goto("/tests/desktop-runtime.html");
  await page
    .getByRole("button", { name: "Cài đặt chạy nền" })
    .click();
  await expect(page.getByText("Chỉ có trong ứng dụng Windows")).toBeVisible();
  await expect(page.getByRole("switch")).toHaveCount(0);
  expect(await page.evaluate(() => "__TAURI_INTERNALS__" in window)).toBe(
    false,
  );
});

for (const variant of ["setup", "held", "health-error", "manual"] as const) {
  test(`startup keeps a ${variant} bootstrap visible`, async ({ page }) => {
    const calls = await mount(page, {
      setup: variant === "setup",
      held: variant === "held",
      healthError: variant === "health-error",
      manual: variant === "manual",
    });
    if (variant === "manual") {
      await page
        .getByRole("button", { name: "Chọn thư mục dữ liệu", exact: true })
        .click();
      await page.getByRole("button", { name: /Mở dữ liệu local$/ }).click();
    }
    if (variant === "health-error")
      await expect(page.getByText("Dữ liệu chưa sẵn sàng.")).toBeVisible();
    else
      await expect(
        page.getByLabel("Tên đăng nhập", { exact: true }),
      ).toBeVisible();
    if (variant === "setup") {
      await page.getByLabel("Tên đăng nhập", { exact: true }).fill("admin");
      await page
        .getByLabel("Mật khẩu", { exact: true })
        .fill("synthetic-password");
      await page
        .getByRole("button", { name: "Tạo quản trị và đăng nhập", exact: true })
        .click();
      await expect(
        page.getByRole("button", { name: "Đăng xuất", exact: true }),
      ).toBeVisible();
    }
    await painted(page);
    expect(
      calls.filter((call) => call.command === "desktop_background_ready"),
    ).toHaveLength(0);
    expect(
      calls.filter((call) => call.command === "set_desktop_startup"),
    ).toHaveLength(0);
  });
}

test("native startup errors and malformed status are sanitized", async ({
  page,
}) => {
  await page.route("**/runtime-api-test", (route) =>
    route.fulfill({
      contentType: "text/html",
      body: "<!doctype html><html><body></body></html>",
    }),
  );
  await page.goto("/runtime-api-test");
  const results = await page.evaluate(async () => {
    const path = "/src/shared/api.ts";
    const { desktop } = await import(path);
    const results = [];
    for (const code of [
      "STARTUP_CONFLICT",
      "STARTUP_UNAVAILABLE",
      "STARTUP_COMMAND_INVALID",
      "UNKNOWN_PRIVATE_CODE",
      "malformed",
    ]) {
      Object.assign(window, {
        __TAURI_INTERNALS__: {
          invoke: async () => {
            if (code === "malformed")
              return { startup_enabled: "false", startup_supported: true };
            throw `${code}: PRIVATE token C:\\private-path`;
          },
        },
      });
      try {
        await desktop.runtimeStatus();
      } catch (error) {
        results.push({
          code: (error as { code: string }).code,
          message: (error as Error).message,
        });
      }
    }
    return results;
  });
  expect(results.map((value) => value.code)).toEqual([
    "STARTUP_CONFLICT",
    "STARTUP_UNAVAILABLE",
    "STARTUP_COMMAND_INVALID",
    "NATIVE_RESULT_UNKNOWN",
    "STARTUP_UNAVAILABLE",
  ]);
  for (const result of results)
    expect(result.message).not.toMatch(/PRIVATE|token|private-path/);
});
