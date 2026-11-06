import { test, expect, type Page, type Route } from "@playwright/test";

type Role = "admin" | "operator";
interface Account { id: string; username: string; role: Role; version: number; active: boolean }
interface Command {
  path: string;
  method: string;
  raw: string;
  body: { username?: string; password?: string; role: Role; active?: boolean; expected_version?: number; request_key: string };
}
interface MockState {
  accounts: Account[];
  reads: URL[];
  commands: Command[];
  onList?: (route: Route, actor: string) => Promise<boolean>;
  onCommand?: (route: Route, command: Command) => Promise<boolean>;
}
const accountPage = (items: Account[], page = 1, total = items.length) => ({ items, total, page, page_size: 50 });
const errorResponse = (route: Route, code: string, status: number, fields: { field: string; code: string; message: string }[] = []) => route.fulfill({
  status, json: { error: { code, message: code === "VERSION_CONFLICT" ? "Bản ghi đã thay đổi." : "Kiểm tra lại tài khoản.", field_errors: fields, details: {} }, request_id: `synthetic-${code}` },
});

async function mountAccounts(page: Page, options: { role?: Role; onList?: MockState["onList"]; onCommand?: MockState["onCommand"] } = {}) {
  const state: MockState = {
    accounts: [
      { id: "A", username: "current-admin", role: "admin", version: 1, active: true },
      { id: "B", username: "backup-admin", role: "admin", version: 2, active: true },
      ...Array.from({ length: 51 }, (_, index) => ({ id: `operator-${index}`, username: `operator-${String(index).padStart(2, "0")}`, role: "operator" as const, version: 1, active: true })),
    ], reads: [], commands: [], onList: options.onList, onCommand: options.onCommand,
  };
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname.replace("/api/v1", "");
    if (path === "/auth/login") {
      const { username } = request.postDataJSON();
      const role: Role = username === "operator" ? "operator" : "admin";
      const id = username === "other-admin" ? "B" : role === "admin" ? "A" : "O";
      return route.fulfill({ json: { access_token: `synthetic-token-${id}`, user: { id, username, role, version: 1, permissions: role === "admin" ? ["core.manage"] : ["core.read"] } } });
    }
    if (path === "/users" && request.method() === "GET") {
      state.reads.push(url);
      if (await state.onList?.(route, request.headers().authorization ?? "")) return;
      const index = Number(url.searchParams.get("page"));
      const search = url.searchParams.get("search") ?? "";
      const role = url.searchParams.get("role");
      const active = url.searchParams.get("active");
      const matching = state.accounts.filter((item) => item.username.includes(search) && (!role || item.role === role) && (!active || String(item.active) === active));
      return route.fulfill({ json: accountPage(matching.slice((index - 1) * 50, index * 50), index, matching.length) });
    }
    if (request.method() === "POST" || request.method() === "PATCH") {
      const command: Command = { path, method: request.method(), raw: request.postData()!, body: request.postDataJSON() };
      state.commands.push(command);
      if (await state.onCommand?.(route, command)) return;
      if (path === "/users") {
        const result: Account = { id: `created-${state.accounts.length}`, username: command.body.username!, role: command.body.role, version: 1, active: true };
        state.accounts.push(result);
        return route.fulfill({ json: result });
      }
      const account = state.accounts.find((item) => path === `/users/${item.id}`)!;
      Object.assign(account, { role: command.body.role, active: command.body.active, version: account.version + 1 });
      return route.fulfill({ json: account });
    }
    return errorResponse(route, "NOT_FOUND", 404);
  });
  await page.route("**/local-accounts-test", (route) => route.fulfill({ contentType: "text/html", body: '<!doctype html><html><body><div id="root"></div></body></html>' }));
  await page.goto("/local-accounts-test");
  await page.evaluate(async (role) => {
    const refreshPath = "/@react-refresh";
    const refresh = (await import(refreshPath)).default;
    refresh.injectIntoGlobalHook(window);
    Reflect.set(window, "$RefreshReg$", () => {});
    Reflect.set(window, "$RefreshSig$", () => (type: unknown) => type);
    Reflect.set(window, "__vite_plugin_react_preamble_installed__", true);
    const reactPath = "/node_modules/.vite/deps/react.js";
    const rootPath = "/node_modules/.vite/deps/react-dom_client.js";
    const componentPath = "/src/app/LocalAccountsPage.tsx";
    const sessionPath = "/src/shared/session.ts";
    const apiPath = "/src/shared/api.ts";
    const React = (await import(reactPath)).default;
    const { createRoot } = (await import(rootPath)).default;
    const { LocalAccountsPage } = await import(componentPath);
    const { useSession } = await import(sessionPath);
    const { api } = await import(apiPath);
    useSession.getState().setBoot({ protocol_version: 1, api_base: `${location.origin}/api/v1`, session_token: "synthetic-account-app", data_root: "D:\\SyntheticAccounts" });
    createRoot(document.getElementById("root")!).render(React.createElement(LocalAccountsPage));
    const auth = await api("/auth/login", { method: "POST", body: JSON.stringify({ username: role === "operator" ? "operator" : "current-admin", password: "synthetic-login-password" }) }, false);
    useSession.getState().login(auth.access_token, auth.user);
  }, options.role ?? "admin");
  await expect(page.getByRole("heading", { name: "Tài khoản nội bộ", exact: true })).toBeVisible();
  return state;
}

async function choose(page: Page, label: string, option: string) {
  await page.getByLabel(label, { exact: true }).click();
  await page.locator(".ant-select-dropdown:visible").getByText(option, { exact: true }).click();
}
async function createInputs(page: Page, username: string, password = "  synthetic password  ") {
  await page.getByLabel("Tên đăng nhập mới", { exact: true }).fill(username);
  await page.getByLabel("Mật khẩu ban đầu", { exact: true }).fill(password);
}
async function loginAs(page: Page, username: string) {
  await page.evaluate(async (username) => {
    const sessionPath = "/src/shared/session.ts";
    const apiPath = "/src/shared/api.ts";
    const { useSession } = await import(sessionPath);
    const { api } = await import(apiPath);
    useSession.getState().logout();
    const auth = await api("/auth/login", { method: "POST", body: JSON.stringify({ username, password: "synthetic-login-password" }) }, false);
    useSession.getState().login(auth.access_token, auth.user);
  }, username);
}

test("operator is denied by the account component without fetching users", async ({ page }) => {
  const state = await mountAccounts(page, { role: "operator" });
  await expect(page.getByText("Chỉ Admin có quyền quản lý tài khoản nội bộ.", { exact: true })).toBeVisible();
  expect(state.reads).toEqual([]);
  expect(state.commands).toEqual([]);
  await expect(page.getByRole("button", { name: "Tạo tài khoản", exact: true })).toHaveCount(0);
});

test("admin list uses server paging, search, role and active filters", async ({ page }) => {
  const state = await mountAccounts(page);
  await expect(page.getByRole("cell", { name: "current-admin", exact: true })).toBeVisible();
  expect(state.reads[0].searchParams.get("page_size")).toBe("50");
  await page.locator(".ant-pagination-next").click();
  await expect(page.getByRole("cell", { name: "operator-50", exact: true })).toBeVisible();
  expect(state.reads.at(-1)!.searchParams.get("page")).toBe("2");
  await page.getByLabel("Tìm tài khoản", { exact: true }).fill("operator-05");
  await page.getByLabel("Tìm tài khoản", { exact: true }).press("Enter");
  await expect(page.getByRole("cell", { name: "operator-05", exact: true })).toBeVisible();
  expect(state.reads.at(-1)!.searchParams.get("page")).toBe("1");
  expect(state.reads.at(-1)!.searchParams.get("search")).toBe("operator-05");
  await choose(page, "Lọc vai trò tài khoản", "Nhân viên");
  await expect.poll(() => state.reads.at(-1)!.searchParams.get("role")).toBe("operator");
  await choose(page, "Lọc trạng thái tài khoản", "Đang hoạt động");
  await expect.poll(() => state.reads.at(-1)!.searchParams.get("active")).toBe("true");
});

test("create surfaces field errors, preserves password bytes, and edits use the displayed version", async ({ page }) => {
  const state = await mountAccounts(page);
  state.onCommand = async (route, command) => {
    if (command.path === "/users" && command.body.username === "invalid-user") {
      await errorResponse(route, "VALIDATION_ERROR", 422, [{ field: "body.username", code: "INVALID_FIELD", message: "Tên đăng nhập cần kiểm tra." }]);
      return true;
    }
    if (command.method === "PATCH" && command.body.expected_version === 1) {
      state.accounts.find((item) => command.path === `/users/${item.id}`)!.version = 2;
      await errorResponse(route, "VERSION_CONFLICT", 409);
      return true;
    }
    return false;
  };
  await createInputs(page, "invalid-user");
  await page.getByRole("button", { name: "Tạo tài khoản", exact: true }).click();
  await expect(page.getByText("Tên đăng nhập cần kiểm tra.").first()).toBeVisible();
  await expect(page.getByText("Mã yêu cầu: synthetic-VALIDATION_ERROR")).toBeVisible();
  await expect(page.getByLabel("Mật khẩu ban đầu", { exact: true })).toHaveValue("");
  await createInputs(page, "new-operator");
  await page.getByRole("button", { name: "Tạo tài khoản", exact: true }).click();
  await expect(page.getByText("Đã tạo tài khoản new-operator.", { exact: true })).toBeVisible();
  expect(state.commands[1].body).toMatchObject({ username: "new-operator", password: "  synthetic password  ", role: "operator" });
  expect(state.commands[1].body.request_key).not.toBe(state.commands[0].body.request_key);
  await expect(page.getByLabel("Mật khẩu ban đầu", { exact: true })).toHaveValue("");
  expect(await page.evaluate(() => [localStorage.length, sessionStorage.length])).toEqual([0, 0]);
  await page.getByLabel("Tìm tài khoản", { exact: true }).fill("new-operator");
  await page.getByLabel("Tìm tài khoản", { exact: true }).press("Enter");
  await page.getByRole("button", { name: "Sửa tài khoản new-operator", exact: true }).click();
  await choose(page, "Vai trò sửa tài khoản", "Admin");
  await page.getByRole("switch", { name: "Tài khoản đang hoạt động" }).click();
  await page.getByRole("button", { name: "Lưu tài khoản", exact: true }).click();
  await expect(page.getByRole("dialog")).toContainText("Tải lại danh sách rồi mở lại tài khoản trước khi sửa.");
  expect(state.commands.at(-1)!.body).toMatchObject({ expected_version: 1, role: "admin", active: false });
  await page.getByRole("button", { name: "Đóng", exact: true }).click();
  await page.getByRole("button", { name: "Tải lại danh sách", exact: true }).click();
  await page.getByRole("button", { name: "Sửa tài khoản new-operator", exact: true }).click();
  await expect(page.getByRole("dialog")).toContainText("Phiên bản 2.");
  await choose(page, "Vai trò sửa tài khoản", "Admin");
  await page.getByRole("switch", { name: "Tài khoản đang hoạt động" }).click();
  await page.getByRole("button", { name: "Lưu tài khoản", exact: true }).click();
  await expect(page.getByText("Đã cập nhật tài khoản new-operator.", { exact: true })).toBeVisible();
  expect(state.commands.at(-1)!.body).toMatchObject({ expected_version: 2, role: "admin", active: false });
  expect(state.accounts.find((item) => item.username === "new-operator")).toMatchObject({ version: 3, role: "admin", active: false });
});

test("uncertain create freezes its exact payload and key until explicit retry resolves", async ({ page }) => {
  const state = await mountAccounts(page);
  let created: Account;
  state.onCommand = async (route, command) => {
    if (state.commands.length === 1) {
      created = { id: "lost-response-account", username: command.body.username!, role: command.body.role, active: true, version: 1 };
      state.accounts.push(created);
      await route.abort("failed");
    } else {
      expect(command.raw).toBe(state.commands[0].raw);
      await route.fulfill({ json: created });
    }
    return true;
  };
  await createInputs(page, "retry-user");
  await page.getByRole("button", { name: "Tạo tài khoản", exact: true }).click();
  await expect(page.getByText("Chưa rõ kết quả yêu cầu", { exact: true })).toBeVisible();
  await expect(page.getByLabel("Tên đăng nhập mới", { exact: true })).toBeDisabled();
  await expect(page.getByRole("button", { name: "Tạo tài khoản", exact: true })).toBeDisabled();
  expect(state.commands).toHaveLength(1);
  await page.getByRole("button", { name: "Thử lại yêu cầu", exact: true }).click();
  await expect(page.getByText("Đã tạo tài khoản retry-user.", { exact: true })).toBeVisible();
  expect(state.commands).toHaveLength(2);
  expect(state.accounts.filter((item) => item.username === "retry-user")).toHaveLength(1);
  await expect(page.getByLabel("Mật khẩu ban đầu", { exact: true })).toHaveValue("");
});

test("uncertain edit retries the same target, version, role, status and request key", async ({ page }) => {
  const state = await mountAccounts(page);
  let result: Account;
  state.onCommand = async (route, command) => {
    if (state.commands.length === 1) {
      const target = state.accounts.find((item) => command.path === `/users/${item.id}`)!;
      result = { ...target, role: command.body.role, active: command.body.active!, version: target.version + 1 };
      Object.assign(target, result);
      await route.abort("failed");
    } else {
      expect(command.raw).toBe(state.commands[0].raw);
      expect(command.path).toBe(state.commands[0].path);
      await route.fulfill({ json: result });
    }
    return true;
  };
  await page.getByRole("button", { name: "Sửa tài khoản backup-admin", exact: true }).click();
  await choose(page, "Vai trò sửa tài khoản", "Nhân viên");
  await page.getByRole("switch", { name: "Tài khoản đang hoạt động" }).click();
  await page.getByRole("button", { name: "Lưu tài khoản", exact: true }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByText("Chưa rõ kết quả yêu cầu", { exact: true })).toBeVisible();
  await expect(page.getByLabel("Vai trò sửa tài khoản", { exact: true })).toBeDisabled();
  await expect(dialog.getByRole("button", { name: "Đóng", exact: true })).toBeDisabled();
  expect(state.commands[0].body).toMatchObject({ expected_version: 2, role: "operator", active: false });
  await dialog.getByRole("button", { name: "Thử lại yêu cầu", exact: true }).click();
  await expect(page.getByText("Đã cập nhật tài khoản backup-admin.", { exact: true })).toBeVisible();
  expect(state.commands).toHaveLength(2);
  expect(state.accounts.find((item) => item.id === "B")).toMatchObject({ version: 3, role: "operator", active: false });
});

test("late account lists cannot replace the next actor's list", async ({ page }) => {
  let release!: () => void;
  let started!: () => void;
  let finished!: () => void;
  const gate = new Promise<void>((resolve) => { release = resolve; });
  const held = new Promise<void>((resolve) => { started = resolve; });
  const done = new Promise<void>((resolve) => { finished = resolve; });
  await mountAccounts(page, { onList: async (route, actor) => {
    if (actor === "Bearer synthetic-token-A") {
      started(); await gate;
      await route.fulfill({ json: accountPage([{ id: "old", username: "old-private-list", role: "admin", active: true, version: 1 }]) }).catch(() => {});
      finished(); return true;
    }
    await route.fulfill({ json: accountPage([{ id: "new", username: "new-actor-list", role: "admin", active: true, version: 1 }]) });
    return true;
  } });
  await held;
  await loginAs(page, "other-admin");
  await expect(page.getByRole("cell", { name: "new-actor-list", exact: true })).toBeVisible();
  release(); await done;
  await expect(page.getByText("old-private-list", { exact: true })).toHaveCount(0);
  await expect(page.getByRole("cell", { name: "new-actor-list", exact: true })).toBeVisible();
});

test("a command response after session change cannot show success or log out the new actor", async ({ page }) => {
  let release!: () => void;
  let started!: () => void;
  let finished!: () => void;
  const gate = new Promise<void>((resolve) => { release = resolve; });
  const held = new Promise<void>((resolve) => { started = resolve; });
  const done = new Promise<void>((resolve) => { finished = resolve; });
  const state = await mountAccounts(page, { onCommand: async (route, command) => {
    started(); await gate;
    await route.fulfill({ json: { id: "old-created", username: command.body.username, role: command.body.role, version: 1, active: true } }).catch(() => {});
    finished(); return true;
  } });
  await createInputs(page, "old-private-create");
  await page.getByRole("button", { name: "Tạo tài khoản", exact: true }).click();
  await held;
  await loginAs(page, "operator");
  release(); await done;
  await expect(page.getByText("Chỉ Admin có quyền quản lý tài khoản nội bộ.", { exact: true })).toBeVisible();
  await expect(page.getByText("Đã tạo tài khoản old-private-create.", { exact: true })).toHaveCount(0);
  expect(state.commands).toHaveLength(1);
  const actor = await page.evaluate(async () => {
    const module = "/src/shared/session.ts";
    return (await import(module)).useSession.getState().user?.id;
  });
  expect(actor).toBe("O");
});

test("successful current-user edits clear the local session for a fresh login", async ({ page }) => {
  const state = await mountAccounts(page);
  await page.getByRole("button", { name: "Sửa tài khoản current-admin", exact: true }).click();
  await choose(page, "Vai trò sửa tài khoản", "Nhân viên");
  await page.getByRole("switch", { name: "Tài khoản đang hoạt động" }).click();
  await page.getByRole("button", { name: "Lưu tài khoản", exact: true }).click();
  await expect(page.getByText("Chỉ Admin có quyền quản lý tài khoản nội bộ.", { exact: true })).toBeVisible();
  expect(state.commands.at(-1)!.body).toMatchObject({ expected_version: 1, role: "operator", active: false });
  const session = await page.evaluate(async () => {
    const module = "/src/shared/session.ts";
    const store = (await import(module)).useSession.getState();
    return { token: store.token, user: store.user };
  });
  expect(session).toEqual({ token: null, user: null });
});
