import { test, expect, type Page } from "@playwright/test";
import type { BootSession, DesktopStatus, MaintenanceKind, MaintenanceResult, MaintenanceView } from "../src/shared/types";

interface Call { command: string; args: Record<string, unknown> }
interface NativeState {
  boot: BootSession; operation: MaintenanceView | null; calls: Call[]; usersReads: number;
  cancelPicker: boolean; status?: DesktopStatus;
  handler?: (call: Call) => Promise<{ value?: unknown; error?: string } | undefined>;
}
const sourceBoot: BootSession = { protocol_version: 1, api_base: "http://127.0.0.1:1420/api/v1", session_token: "synthetic-app-source", data_root: "D:\\SyntheticSource", maintenance_protocol: 1, generation: "source-generation", runtime_state: "ACTIVE", pending_transition: null };
function view(kind: MaintenanceKind, overrides: Partial<MaintenanceView> = {}): MaintenanceView {
  return { operation_id: "native-operation-1", kind, generation: "source-generation", phase: "SELECTING", recovery_required: false, runtime_state: "ACTIVE", destination_display: null, backup_source_display: null, ready: false, can_activate: false, ...overrides };
}
async function mount(page: Page, options: { boot?: BootSession; status?: DesktopStatus; operation?: MaintenanceView; handler?: NativeState["handler"]; failStart?: boolean } = {}) {
  const state: NativeState = { boot: structuredClone(options.boot ?? sourceBoot), operation: options.operation ?? null, calls: [], usersReads: 0, cancelPicker: false, status: options.status, handler: options.handler };
  await page.exposeFunction("maintenanceNative", async (command: string, args: Record<string, unknown> = {}) => {
    const call = { command, args }; state.calls.push(call);
    const override = await state.handler?.(call);
    if (override) { if (override.error) throw new Error(override.error); return override.value; }
    if (command === "desktop_status") return state.status ?? { data_root: state.boot.data_root, running: true, maintenance_protocol: state.boot.maintenance_protocol, generation: state.boot.generation, runtime_state: state.boot.runtime_state, pending_transition: state.operation ?? state.boot.pending_transition };
    if (command === "start_backend") { if (options.failStart) throw new Error("synthetic-start-held"); return state.boot; }
    if (command === "maintenance_begin") { state.operation = view(args.kind as MaintenanceKind); return state.operation; }
    if (command === "maintenance_select") {
      if (state.cancelPicker) return null;
      const op = state.operation!;
      if (args.purpose === "destination") op.destination_display = "D:\\OutputOnly-private-destination";
      else op.backup_source_display = "D:\\OutputOnly-private-backup";
      op.ready = !!op.destination_display && (op.kind !== "restore" || !!op.backup_source_display);
      return structuredClone(op);
    }
    if (command === "maintenance_run") {
      if (state.operation!.kind === "backup") {
        state.operation = { ...state.operation!, phase: "ACTIVE", runtime_state: "ACTIVE" };
        return { operation: state.operation, boot_session: null };
      }
      state.operation = { ...state.operation!, generation: "target-generation", runtime_state: "DORMANT", phase: "CANDIDATE_DORMANT", can_activate: true };
      state.boot = { ...state.boot, generation: "target-generation", session_token: "synthetic-app-target", data_root: "D:\\SyntheticTarget", runtime_state: "DORMANT", pending_transition: state.operation };
      return { operation: state.operation, boot_session: state.boot };
    }
    if (command === "maintenance_status") return { operation: state.operation, boot_session: null };
    if (command === "maintenance_activate") {
      state.operation = { ...state.operation!, runtime_state: "ACTIVE", phase: "ACTIVE", can_activate: false, recovery_required: false };
      return { operation: state.operation, boot_session: null };
    }
    if (command === "open_reports") return null;
    throw new Error(`unexpected-${command}`);
  });
  await page.addInitScript(() => {
    Object.defineProperty(window, "__TAURI_INTERNALS__", { value: {
      invoke: async (command: string, args: Record<string, unknown>) => {
        try { return await Reflect.get(window, "maintenanceNative")(command, args); }
        catch (error) { throw error instanceof Error ? error.message : error; }
      },
    } });
  });
  await page.route("**/api/v1/**", async (route) => {
    const path = new URL(route.request().url()).pathname.replace("/api/v1", "");
    if (path === "/health") return route.fulfill({ json: { status: "ok", protocol_version: 1, setup_required: false } });
    if (path === "/auth/login") {
      const username = route.request().postDataJSON().username;
      const role = username === "operator" ? "operator" : "admin";
      return route.fulfill({ json: { access_token: `synthetic-token-${username}`, user: { id: username, username, role, version: 1, permissions: role === "admin" ? ["core.manage", "reporting.read"] : ["reporting.read"] } } });
    }
    if (path === "/auth/logout") return route.fulfill({ status: 204 });
    if (path === "/users") { state.usersReads++; return route.fulfill({ json: { items: [], total: 0, page: 1, page_size: 50 } }); }
    return route.fulfill({ status: 404, json: { error: { code: "NOT_FOUND", message: "Synthetic route.", field_errors: [] }, request_id: "synthetic" } });
  });
  await page.goto("/#/settings");
  return state;
}
async function login(page: Page, username = "admin") {
  await expect(page.getByRole("button", { name: "Đăng nhập", exact: true })).toBeEnabled();
  await page.getByLabel("Tên đăng nhập", { exact: true }).fill(username);
  await page.getByLabel("Mật khẩu", { exact: true }).fill("synthetic-password");
  await page.getByRole("button", { name: "Đăng nhập", exact: true }).click();
  await expect(page.getByRole("button", { name: "Đăng xuất", exact: true })).toBeVisible();
}
async function store(page: Page) {
  return page.evaluate(async () => {
    const path = "/src/shared/session.ts";
    const state = (await import(path)).useSession.getState();
    return { boot: state.boot, token: state.token, actor: state.user?.username ?? null, generation: state.generation, maintenance: state.maintenance };
  });
}
async function switchActor(page: Page, username: string) {
  await page.evaluate(async (username) => {
    const path = "/src/shared/session.ts";
    const { useSession } = await import(path);
    useSession.getState().login(`synthetic-token-${username}`, { id: username, username, role: "admin", permissions: ["core.manage", "reporting.read"], version: 1 });
  }, username);
}
function deferred() { let resolve!: () => void; const promise = new Promise<void>((done) => { resolve = done; }); return { promise, resolve }; }

test("legacy or absent current capability never invokes maintenance; current Operator may open reports", async ({ page }) => {
  const state = await mount(page, { boot: { ...sourceBoot, maintenance_protocol: undefined, generation: undefined } });
  await login(page);
  await expect(page.getByText("Phiên desktop này chưa hỗ trợ quản lý dữ liệu. Các thao tác hiện không khả dụng.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Sao lưu", exact: true })).toHaveCount(0);
  expect(state.calls.filter((call) => call.command.startsWith("maintenance_") || call.command === "open_reports")).toEqual([]);
  await page.evaluate(async (boot) => { const path = "/src/shared/session.ts"; (await import(path)).useSession.getState().setBoot(boot); }, sourceBoot);
  await login(page, "operator");
  await page.getByRole("button", { name: "Mở thư mục báo cáo", exact: true }).click();
  await expect.poll(() => state.calls.filter((call) => call.command === "open_reports")).toEqual([{ command: "open_reports", args: { userToken: "synthetic-token-operator" } }]);
  await expect(page.getByRole("button", { name: "Sao lưu", exact: true })).toHaveCount(0);
});

test("cancelled native picker retains operation, restore requires both selections and only sends opaque ID/current token", async ({ page }) => {
  const state = await mount(page); await login(page);
  state.cancelPicker = true;
  await page.getByRole("button", { name: "Khôi phục bản sao lưu", exact: true }).click();
  await expect(page.getByText("Đã hủy chọn thư mục. Thao tác hiện tại được giữ nguyên.")).toBeVisible();
  await expect(page.getByRole("textbox", { name: /đường dẫn|thư mục/i })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Thực hiện", exact: true })).toBeDisabled();
  state.cancelPicker = false;
  await page.getByRole("button", { name: "Chọn nơi lưu", exact: true }).click();
  await expect(page.getByText("D:\\OutputOnly-private-destination", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Thực hiện", exact: true })).toBeDisabled();
  await page.getByRole("button", { name: "Chọn bản sao lưu", exact: true }).click();
  await expect(page.getByRole("button", { name: "Thực hiện", exact: true })).toBeEnabled();
  await switchActor(page, "other-admin");
  await page.getByRole("button", { name: "Thực hiện", exact: true }).click();
  await expect.poll(() => state.calls.find((call) => call.command === "maintenance_run")?.args).toEqual({ operationId: "native-operation-1", userToken: "synthetic-token-other-admin" });
  expect(state.calls.filter((call) => call.command === "maintenance_begin")).toHaveLength(1);
  const nativeArgs = JSON.stringify(state.calls.filter((call) => call.command.startsWith("maintenance_")).map((call) => call.args));
  expect(nativeArgs).not.toContain("OutputOnly"); expect(nativeArgs).not.toContain("source-generation"); expect(nativeArgs).not.toContain("SyntheticSource");
  await expect(page.getByRole("button", { name: "Đăng nhập", exact: true })).toBeVisible();
});

test("lost run ACK keeps the exact operation through route changes, status and explicit retry", async ({ page }) => {
  const state = await mount(page); await login(page);
  let runs = 0;
  state.handler = async (call) => {
    if (call.command === "maintenance_run" && ++runs === 1) return { error: "arbitrary-private-path-D:\\SECRET synthetic-token-secret" };
    if (call.command === "maintenance_status") return { value: { operation: { ...state.operation!, phase: "INTENT", runtime_state: "ACTIVE" }, boot_session: null } };
    return undefined;
  };
  await page.getByRole("button", { name: "Sao lưu", exact: true }).click();
  await page.getByRole("button", { name: "Thực hiện", exact: true }).click();
  await expect(page.getByText("Chưa rõ kết quả thao tác", { exact: true })).toBeVisible();
  await expect(page.getByText(/SECRET|synthetic-token-secret/)).toHaveCount(0);
  await page.evaluate(() => { location.hash = "/foundation"; });
  await page.evaluate(() => { location.hash = "/settings"; });
  await expect(page.getByRole("button", { name: "Thử lại cùng thao tác", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Thử lại cùng thao tác", exact: true }).click();
  await expect(page.getByText("Desktop đã xác nhận thao tác hoàn tất.", { exact: true })).toBeVisible();
  const calls = state.calls.filter((call) => call.command === "maintenance_run");
  expect(calls).toHaveLength(2); expect(calls[1].args).toEqual(calls[0].args);
  expect(state.calls.filter((call) => call.command === "maintenance_begin")).toHaveLength(1);
  expect((await store(page)).actor).toBe("admin");
  expect(await page.evaluate(() => [localStorage.length, sessionStorage.length])).toEqual([0, 0]);
});

test("unknown begin never begins again; bounded desktop status recovers its ID", async ({ page }) => {
  const state = await mount(page); await login(page);
  state.handler = async (call) => {
    if (call.command === "maintenance_begin") { state.operation = view("backup"); return { error: "lost-ack" }; }
    return undefined;
  };
  await page.getByRole("button", { name: "Sao lưu", exact: true }).click();
  await expect(page.getByText("Chưa xác nhận lựa chọn hoặc thao tác desktop. Không tạo yêu cầu mới; kiểm tra trạng thái desktop hoặc thao tác.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Sao lưu", exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "Kiểm tra trạng thái desktop", exact: true }).click();
  await page.getByRole("button", { name: "Kiểm tra trạng thái thao tác", exact: true }).click();
  await expect(page.getByRole("button", { name: "Chọn nơi lưu", exact: true })).toBeVisible();
  expect(state.calls.filter((call) => call.command === "maintenance_begin")).toHaveLength(1);
});

test("move same-port BootSession clears source actor/cache, target login remains dormant until confirmed activation", async ({ page }) => {
  const state = await mount(page); await login(page);
  await page.getByLabel("Tên đăng nhập mới", { exact: true }).fill("source-private-account-draft");
  await page.getByLabel("Mật khẩu ban đầu", { exact: true }).fill("synthetic-private-draft-password");
  const generation = (await store(page)).generation;
  await page.getByRole("button", { name: "Chuyển nơi lưu", exact: true }).click();
  await page.getByRole("button", { name: "Thực hiện", exact: true }).click();
  await expect(page.getByRole("button", { name: "Đăng nhập", exact: true })).toBeVisible();
  const dormant = await store(page);
  expect(dormant.actor).toBeNull(); expect(dormant.token).toBeNull();
  expect(dormant.boot).toMatchObject({ api_base: sourceBoot.api_base, runtime_state: "DORMANT", generation: "target-generation" });
  expect(dormant.generation).toBeGreaterThan(generation);
  const reads = state.usersReads;
  await login(page, "target-admin");
  await expect(page.getByRole("heading", { name: "Phục hồi dữ liệu trên máy", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Tài khoản nội bộ", exact: true })).toHaveCount(0);
  expect(state.usersReads).toBe(reads);
  const targetGeneration = (await store(page)).generation;
  await page.getByRole("button", { name: "Kích hoạt dữ liệu hiện tại", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Tài khoản nội bộ", exact: true })).toBeVisible();
  await expect(page.getByLabel("Tên đăng nhập mới", { exact: true })).toHaveValue("");
  await expect(page.getByLabel("Mật khẩu ban đầu", { exact: true })).toHaveValue("");
  const active = await store(page);
  expect(active.actor).toBe("target-admin"); expect(active.generation).toBe(targetGeneration);
  expect(active.boot).toMatchObject({ runtime_state: "ACTIVE", pending_transition: null });
  expect(state.calls.find((call) => call.command === "maintenance_activate")?.args).toEqual({ operationId: "native-operation-1", userToken: "synthetic-token-target-admin" });
});

test("Operator dormant login and native can_activate=false cannot activate or fetch accounts", async ({ page }) => {
  const operation = view("move", { phase: "CANDIDATE_DORMANT", runtime_state: "DORMANT", can_activate: false });
  const state = await mount(page, { boot: { ...sourceBoot, runtime_state: "DORMANT", pending_transition: operation }, operation });
  await login(page, "operator");
  await expect(page.getByText("Cần đăng nhập Admin của dữ liệu hiện tại để kiểm tra và kích hoạt.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Kích hoạt dữ liệu hiện tại", exact: true })).toHaveCount(0);
  expect(state.usersReads).toBe(0);
  await switchActor(page, "target-admin");
  await page.getByRole("button", { name: "Kiểm tra trạng thái thao tác", exact: true }).click();
  await expect(page.getByRole("button", { name: "Kích hoạt dữ liệu hiện tại", exact: true })).toBeDisabled();
  expect(state.calls.filter((call) => call.command === "maintenance_activate")).toEqual([]);
});

test("late picker and stale-generation status never replace the current operation", async ({ page }) => {
  const gate = deferred(); const started = deferred();
  const state = await mount(page); await login(page);
  state.handler = async (call) => {
    if (call.command === "maintenance_select") { started.resolve(); await gate.promise; return { value: view("backup", { destination_display: "OLD-PRIVATE-SELECTION", ready: true }) }; }
    return undefined;
  };
  await page.getByRole("button", { name: "Sao lưu", exact: true }).click();
  await started.promise;
  await switchActor(page, "other-admin"); gate.resolve();
  await expect(page.getByText("OLD-PRIVATE-SELECTION", { exact: true })).toHaveCount(0);
  state.handler = async (call) => call.command === "maintenance_status" ? { value: { operation: view("backup", { generation: "stale-generation", destination_display: "WRONG-CHILD" }), boot_session: null } } : undefined;
  await page.getByRole("button", { name: "Kiểm tra trạng thái thao tác", exact: true }).click();
  await expect(page.getByText("Phản hồi không khớp phiên dữ liệu hiện tại. Hãy kiểm tra trạng thái.")).toBeVisible();
  await expect(page.getByText("WRONG-CHILD", { exact: true })).toHaveCount(0);
});

test("late run cannot switch a new actor to the returned target BootSession", async ({ page }) => {
  const gate = deferred(); const started = deferred();
  const state = await mount(page); await login(page);
  state.handler = async (call) => {
    if (call.command !== "maintenance_run") return undefined;
    started.resolve(); await gate.promise;
    const operation = view("move", { generation: "late-target", runtime_state: "DORMANT", phase: "CANDIDATE_DORMANT", can_activate: true });
    return { value: { operation, boot_session: { ...sourceBoot, generation: "late-target", runtime_state: "DORMANT", pending_transition: operation } } satisfies MaintenanceResult };
  };
  await page.getByRole("button", { name: "Chuyển nơi lưu", exact: true }).click();
  await page.getByRole("button", { name: "Thực hiện", exact: true }).click(); await started.promise;
  await switchActor(page, "other-admin"); gate.resolve();
  await expect(page.getByText("other-admin", { exact: true })).toBeVisible();
  expect((await store(page)).boot?.generation).toBe("source-generation");
  expect((await store(page)).maintenance.uncertain).toBe(true);
});

test("held startup never exposes initialize/select/restart and no missing status abandons recovery", async ({ page }) => {
  const operation = view("move", { phase: "OLD_CLOSED", runtime_state: "FAILED_HELD", recovery_required: true });
  const state = await mount(page, { status: { data_root: sourceBoot.data_root, running: false, maintenance_protocol: 1, generation: "source-generation", runtime_state: "FAILED_HELD", pending_transition: operation }, failStart: true });
  await expect(page.getByText("Chuyển dữ liệu đang chờ phục hồi", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Chọn thư mục dữ liệu", exact: true })).toHaveCount(0);
  await expect(page.getByRole("checkbox")).toHaveCount(0);
  await expect(page.getByRole("button", { name: /khởi động|kết nối lại/i })).toHaveCount(0);
  state.status = { data_root: null, running: false };
  await page.getByRole("button", { name: "Kiểm tra trạng thái desktop", exact: true }).click();
  await expect(page.getByText("Chuyển dữ liệu đang chờ phục hồi", { exact: true })).toBeVisible();
  expect(state.calls.filter((call) => call.command === "restart_backend" || call.command === "choose_data_root")).toEqual([]);
});

test("activation lost ACK stays held; a later native proof updates metadata without changing actor", async ({ page }) => {
  const operation = view("move", { phase: "CANDIDATE_DORMANT", runtime_state: "DORMANT", can_activate: true });
  const state = await mount(page, { boot: { ...sourceBoot, runtime_state: "DORMANT", pending_transition: operation }, operation });
  await login(page); await page.getByRole("button", { name: "Kiểm tra trạng thái thao tác", exact: true }).click();
  state.handler = async (call) => call.command === "maintenance_activate" ? { error: "SHUTDOWN_FAILED: SECRET synthetic-token-private" } : undefined;
  await page.getByRole("button", { name: "Kích hoạt dữ liệu hiện tại", exact: true }).click();
  await expect(page.getByText("Chưa rõ kết quả thao tác", { exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Tài khoản nội bộ", exact: true })).toHaveCount(0);
  await expect(page.getByText(/SECRET|synthetic-token-private/)).toHaveCount(0);
  state.operation = { ...operation, phase: "ACTIVE", runtime_state: "ACTIVE", can_activate: false };
  await page.getByRole("button", { name: "Kiểm tra trạng thái thao tác", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Tài khoản nội bộ", exact: true })).toBeVisible();
  expect((await store(page)).actor).toBe("admin");
  expect(state.calls.filter((call) => call.command === "maintenance_activate")).toHaveLength(1);
});

test("mismatched operation cannot install a new BootSession or claim completion", async ({ page }) => {
  const state = await mount(page); await login(page);
  state.handler = async (call) => {
    if (call.command !== "maintenance_run") return undefined;
    const operation = view("move", { operation_id: "different-native-operation", generation: "wrong-target", runtime_state: "DORMANT", phase: "CANDIDATE_DORMANT" });
    return { value: { operation, boot_session: { ...sourceBoot, generation: "wrong-target", runtime_state: "DORMANT", pending_transition: operation } } };
  };
  await page.getByRole("button", { name: "Chuyển nơi lưu", exact: true }).click();
  await page.getByRole("button", { name: "Thực hiện", exact: true }).click();
  await expect(page.getByText("Phản hồi không khớp phiên dữ liệu hiện tại. Hãy kiểm tra trạng thái.")).toBeVisible();
  expect((await store(page)).boot?.generation).toBe("source-generation");
  expect((await store(page)).actor).toBe("admin");
  await expect(page.getByText("Desktop đã xác nhận thao tác hoàn tất.")).toHaveCount(0);
});

test("late activation response cannot unlock a different actor's dormant session", async ({ page }) => {
  const operation = view("restore", { phase: "CANDIDATE_DORMANT", runtime_state: "DORMANT", can_activate: true });
  const gate = deferred(); const started = deferred();
  const state = await mount(page, { boot: { ...sourceBoot, runtime_state: "DORMANT", pending_transition: operation }, operation });
  await login(page); await page.getByRole("button", { name: "Kiểm tra trạng thái thao tác", exact: true }).click();
  state.handler = async (call) => {
    if (call.command !== "maintenance_activate") return undefined;
    started.resolve(); await gate.promise;
    return { value: { operation: { ...operation, phase: "ACTIVE", runtime_state: "ACTIVE", can_activate: false }, boot_session: null } };
  };
  await page.getByRole("button", { name: "Kích hoạt dữ liệu hiện tại", exact: true }).click(); await started.promise;
  await switchActor(page, "next-target-admin"); gate.resolve();
  await expect(page.getByText("next-target-admin", { exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Tài khoản nội bộ", exact: true })).toHaveCount(0);
  expect((await store(page)).boot?.runtime_state).toBe("DORMANT");
});

test("unknown picker reply freezes previously ready selections until status confirms native labels", async ({ page }) => {
  const state = await mount(page); await login(page);
  await page.getByRole("button", { name: "Sao lưu", exact: true }).click();
  state.handler = async (call) => {
    if (call.command === "maintenance_select") {
      state.operation!.destination_display = "D:\\NativeSecondSelection";
      return { error: "lost-picker-response" };
    }
    return undefined;
  };
  await page.getByRole("button", { name: "Chọn nơi lưu", exact: true }).click();
  await expect(page.getByRole("button", { name: "Thực hiện", exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "Kiểm tra trạng thái thao tác", exact: true }).click();
  await expect(page.getByText("D:\\NativeSecondSelection", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Thực hiện", exact: true })).toBeEnabled();
  expect(state.calls.filter((call) => call.command === "maintenance_run")).toEqual([]);
});

test("known intermediate native status permits explicit continuation of only the same operation", async ({ page }) => {
  const state = await mount(page); await login(page);
  let attempts = 0;
  state.handler = async (call) => {
    if (call.command === "maintenance_run" && ++attempts === 1) {
      state.operation = { ...state.operation!, phase: "PREPARED", runtime_state: "PREPARED" };
      return { error: "lost-prepared-ack" };
    }
    return undefined;
  };
  await page.getByRole("button", { name: "Sao lưu", exact: true }).click();
  await page.getByRole("button", { name: "Thực hiện", exact: true }).click();
  await page.getByRole("button", { name: "Kiểm tra trạng thái thao tác", exact: true }).click();
  await expect(page.getByRole("button", { name: "Tiếp tục cùng thao tác", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Tiếp tục cùng thao tác", exact: true }).click();
  await expect(page.getByText("Desktop đã xác nhận thao tác hoàn tất.")).toBeVisible();
  const calls = state.calls.filter((call) => call.command === "maintenance_run");
  expect(calls).toHaveLength(2); expect(calls[1].args).toEqual(calls[0].args);
  expect(state.calls.filter((call) => call.command === "maintenance_begin")).toHaveLength(1);
});

test("unknown desktop startup status cannot enable root selection or initialization", async ({ page }) => {
  const state = await mount(page, { handler: async (call) => call.command === "desktop_status" ? { error: "unknown-journal-state" } : undefined });
  await expect(page.getByText("Chưa xác nhận được trạng thái desktop", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Chọn thư mục dữ liệu", exact: true })).toHaveCount(0);
  await expect(page.getByRole("checkbox")).toHaveCount(0);
  expect(state.calls.filter((call) => call.command === "start_backend")).toEqual([]);
});

test("an expired or logged-out actor can authenticate for status in a held same-child runtime", async ({ page }) => {
  const operation = view("move", { phase: "QUIESCED", runtime_state: "QUIESCED" });
  const state = await mount(page, { boot: { ...sourceBoot, runtime_state: "QUIESCED", pending_transition: operation }, operation });
  await login(page);
  await page.getByRole("button", { name: "Đăng xuất", exact: true }).click();
  await login(page, "recovery-admin");
  await page.getByRole("button", { name: "Kiểm tra trạng thái thao tác", exact: true }).click();
  expect(state.calls.find((call) => call.command === "maintenance_status")?.args).toEqual({ operationId: "native-operation-1", userToken: "synthetic-token-recovery-admin" });
  await expect(page.getByRole("heading", { name: "Tài khoản nội bộ", exact: true })).toHaveCount(0);
});

test("lost move ACK safely attaches to native current target without source credentials or restart", async ({ page }) => {
  const state = await mount(page); await login(page);
  state.handler = async (call) => {
    if (call.command !== "maintenance_run") return undefined;
    state.operation = { ...state.operation!, generation: "verified-target", runtime_state: "DORMANT", phase: "CANDIDATE_DORMANT", can_activate: true };
    state.boot = { ...sourceBoot, generation: "verified-target", session_token: "synthetic-app-target", runtime_state: "DORMANT", pending_transition: state.operation };
    return { error: "lost-target-boot-ack" };
  };
  await page.getByRole("button", { name: "Chuyển nơi lưu", exact: true }).click();
  await page.getByRole("button", { name: "Thực hiện", exact: true }).click();
  await expect(page.getByText("Chưa rõ kết quả thao tác", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Kiểm tra trạng thái desktop", exact: true }).click();
  await expect(page.getByText("Desktop đang giữ phiên dữ liệu khác. Kết nối phiên desktop hiện tại để đăng nhập lại; thao tác cũ vẫn được giữ.")).toBeVisible();
  await page.route("**/api/v1/health", (route) => route.request().headers()["x-app-session"] === sourceBoot.session_token ? route.abort("failed") : route.fallback());
  await page.getByRole("button", { name: "Đăng xuất", exact: true }).click();
  await expect(page.getByRole("button", { name: "Đăng nhập", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: /khởi động lại|kết nối lại/i })).toHaveCount(0);
  await page.getByRole("button", { name: "Kết nối phiên desktop hiện tại", exact: true }).click();
  await expect(page.getByRole("button", { name: "Đăng nhập", exact: true })).toBeVisible();
  expect((await store(page)).boot?.generation).toBe("verified-target");
  expect((await store(page)).actor).toBeNull();
  await login(page, "target-admin");
  await page.getByRole("button", { name: "Kiểm tra trạng thái thao tác", exact: true }).click();
  expect(state.calls.find((call) => call.command === "maintenance_status")?.args).toEqual({ operationId: "native-operation-1", userToken: "synthetic-token-target-admin" });
  expect(state.calls.filter((call) => call.command === "start_backend").map((call) => call.args)).toEqual([{ initialize: false }, { initialize: false }]);
  expect(state.calls.filter((call) => call.command === "restart_backend")).toEqual([]);
});

test("lost initial Start ACK can attach; refused attach never initializes, restarts or clears held state", async ({ page }) => {
  const operation = view("restore", { phase: "CANDIDATE_DORMANT", runtime_state: "DORMANT", can_activate: true });
  let starts = 0;
  const state = await mount(page, { boot: { ...sourceBoot, runtime_state: "DORMANT", pending_transition: operation }, operation,
    handler: async (call) => {
      if (call.command === "start_backend" && ++starts <= 2) return { error: starts === 1 ? "lost-first-start-ack" : "MAINTENANCE_RECOVERY_HELD: PRIVATE" };
      return undefined;
    },
  });
  await expect(page.getByText("Chuyển dữ liệu đang chờ phục hồi", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Kết nối phiên desktop hiện tại", exact: true }).click();
  await expect(page.getByText("Chưa xác minh được phiên dữ liệu đang giữ. Không khởi động lại hoặc chuyển về dữ liệu cũ.")).toBeVisible();
  await expect(page.getByRole("checkbox")).toHaveCount(0);
  expect((await store(page)).boot).toBeNull();
  await page.getByRole("button", { name: "Kết nối phiên desktop hiện tại", exact: true }).click();
  await expect(page.getByRole("button", { name: "Đăng nhập", exact: true })).toBeVisible();
  expect(state.calls.filter((call) => call.command === "start_backend").every((call) => call.args.initialize === false)).toBe(true);
  expect(state.calls.filter((call) => call.command === "restart_backend" || call.command === "choose_data_root")).toEqual([]);
});

test("late safe-attach BootSession cannot clear a newer actor", async ({ page }) => {
  const operation = view("move", { phase: "CANDIDATE_DORMANT", runtime_state: "DORMANT" });
  const gate = deferred(); const started = deferred(); let starts = 0;
  const state = await mount(page, { boot: { ...sourceBoot, runtime_state: "DORMANT", pending_transition: operation }, operation });
  await login(page);
  state.handler = async (call) => {
    if (call.command !== "start_backend" || ++starts !== 1) return undefined;
    started.resolve(); await gate.promise;
    return { value: { ...state.boot, generation: "late-attach-target" } };
  };
  await page.getByRole("button", { name: "Kết nối phiên desktop hiện tại", exact: true }).click(); await started.promise;
  await switchActor(page, "new-current-admin"); gate.resolve();
  await expect(page.getByText("new-current-admin", { exact: true })).toBeVisible();
  expect((await store(page)).boot?.generation).toBe("source-generation");
});
