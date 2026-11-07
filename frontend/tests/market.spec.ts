import { test, expect, type Page, type Route } from "@playwright/test";

// Contract fixtures are synthetic. A real source fetch is verified separately.
const source = "https://banggianongsan.com/bang-gia-ca-phe/";
const boardId = "77777777-7777-4777-8777-777777777777";
type Row = Record<string, any>;
const status = (extra: Row = {}): Row => ({ price_date: "2026-11-07", today: "2026-11-07", enabled: true, settings_version: 3, network_available: true, status: "WAITING_SOURCE", source_url: source, board_id: null, board_version: null, attempts: 0, last_checked_at: null, next_attempt_at: null, detail: null, snapshot: null, ...extra });
const snapshot = () => ({ source_url: source, source_date: "2026-11-07", price_vnd_per_kg: "100000.01", fetched_at: "2026-11-07T03:00:00Z", region: "Gia Lai", product: "ROBUSTA_GREEN_BEAN", unit: "VND/kg", parser_version: "1", html_sha256: "a".repeat(64), board_id: boardId, board_version: 1 });
const applied = () => status({ status: "APPLIED", board_id: boardId, board_version: 1, attempts: 1, last_checked_at: "2026-11-07T03:00:00Z", snapshot: snapshot() });
const board = () => ({ id: boardId, code: "GIA-NHAN-XO", name: "Giá nhập nhân xô tổng hợp", active: true, version: 1, deleted_at: null, price_date: "2026-11-07", price_kind: "purchase_processed", product_id: null, pricing_method: "grade", flat_price_vnd: null, grade5_price_vnd: "100000.01", note: "" });
async function fixture(page: Page, initial = status()) {
  let current = initial;
  const calls: { path: string; method: string; body: Row | null; query: URLSearchParams }[] = [];
  await page.route("**/api/v1/records/**", async (route) => {
    const req = route.request(), url = new URL(req.url()), path = url.pathname.split("/records/")[1], body = req.postData() ? req.postDataJSON() : null;
    calls.push({ path, method: req.method(), body, query: url.searchParams });
    if (path === "market/processed") { await route.fulfill({ json: { ...current, price_date: url.searchParams.get("price_date") || current.price_date } }); return; }
    if (path === "market/processed/settings") { current = status({ ...current, enabled: body.enabled, settings_version: current.settings_version + 1 }); await route.fulfill({ json: current }); return; }
    if (path === "market/processed/check") { current = status({ ...current, status: "BLOCKED", attempts: 1, last_checked_at: "2026-11-07T03:00:00Z", next_attempt_at: "2099-11-07T04:00:00Z", detail: "Nguồn công khai trả HTTP 403." }); await route.fulfill({ json: current }); return; }
    if (path === "price-board-preview") { await route.fulfill({ json: { pricing_method: "grade", flat_price_vnd: null, grade_prices: [5, 4, 3, 2, 1].map((grade, i) => ({ grade, unit_price_vnd: ["100000.01", "90000.01", "81000.01", "72900.01", "65610.01"][i] })), formula_version: 1 } }); return; }
    if (path.endsWith("/history")) { await route.fulfill({ json: { items: [{ version: 1, action: "create", recorded_at: "2026-11-07T03:00:00Z", data: board() }], total: 1 } }); return; }
    if (path === `price-boards/${boardId}`) { await route.fulfill({ json: board() }); return; }
    await route.fulfill({ json: { items: path === "price-boards" ? [board()] : [], total: path === "price-boards" ? 1 : 0, page: 1, page_size: 25 } });
  });
  return { calls, setStatus: (value: Row) => { current = value; }, writes: () => calls.filter((c) => c.method !== "GET" && c.path.startsWith("market/")) };
}
async function mount(page: Page, readOnly = false) {
  await page.route("**/market-harness", (route) => route.fulfill({ contentType: "text/html", body: '<html><body><div id="root"></div></body></html>' }));
  await page.goto("/market-harness#/records/prices");
  await page.evaluate(async (readOnly) => {
    const refreshPath = "/@react-refresh", refresh = (await import(refreshPath)).default;
    refresh.injectIntoGlobalHook(window); Reflect.set(window, "$RefreshReg$", () => {}); Reflect.set(window, "$RefreshSig$", () => (type: unknown) => type); Reflect.set(window, "__vite_plugin_react_preamble_installed__", true);
    const path = "/src/features/records/PricesPage.tsx", source = await (await fetch(path)).text();
    const queryPath = source.match(/["'](\/node_modules\/\.vite\/deps\/@tanstack_react-query\.js(?:\?[^"']*)?)["']/)?.[1];
    if (!queryPath) throw new Error("React Query unavailable");
    const reactPath = "/node_modules/.vite/deps/react.js", domPath = "/node_modules/.vite/deps/react-dom_client.js", sessionPath = "/src/shared/session.ts";
    const React = (await import(reactPath)).default, { createRoot } = (await import(domPath)).default;
    const { QueryClient, QueryClientProvider } = await import(queryPath), { useSession } = await import(sessionPath), module = await import(path);
    useSession.getState().setBoot({ protocol_version: 1, api_base: `${location.origin}/api/v1`, session_token: "synthetic", data_root: "D:\\Synthetic" });
    useSession.getState().login("synthetic", { id: "synthetic", username: "synthetic", role: readOnly ? "operator" : "admin", permissions: readOnly ? ["records.read"] : ["*"] });
    createRoot(document.getElementById("root")!).render(React.createElement(QueryClientProvider, { client: new QueryClient() }, React.createElement(module.PricesPage)));
  }, readOnly);
}
const card = (page: Page) => page.locator(".ant-card").filter({ hasText: "Tự động giá nhập nhân xô Robusta Gia Lai" });
const check = (page: Page) => page.getByRole("button", { name: "Kiểm tra nguồn ngay", exact: true });

test("applied source has exact date, fixed safe link, server five Grades and readonly board with history", async ({ page }) => {
  const state = await fixture(page, applied()); await mount(page);
  await expect(card(page).getByText("Đã áp dụng giá đúng ngày", { exact: true })).toBeVisible();
  await expect(card(page).getByRole("link")).toHaveAttribute("href", source);
  await expect(card(page).getByText("Grade5 đã áp dụng: 100.000,01 VND/kg", { exact: true })).toBeVisible();
  await expect(card(page).getByRole("cell", { name: "65.610,01", exact: true })).toBeVisible();
  await expect(card(page).getByRole("cell", { name: /^[1-5]$/, exact: true })).toHaveCount(5);
  await expect(card(page).getByText(/Giá quả tươi tiếp tục nhập tay, không quy đổi/)).toBeVisible();
  await expect(check(page)).toBeDisabled();
  await page.getByRole("button", { name: "Xem bảng giá tự động", exact: true }).click();
  const drawer = page.getByRole("dialog"); await expect(drawer.getByText("Bảng giá tự động chỉ đọc", { exact: true })).toBeVisible();
  await expect(drawer.getByRole("button", { name: "Sửa bảng giá / ngừng áp dụng", exact: true })).toHaveCount(0); await expect(drawer.getByRole("button", { name: "Xóa mềm", exact: true })).toHaveCount(0);
  await drawer.getByRole("button", { name: "Xem lịch sử", exact: true }).click(); await drawer.getByRole("button", { name: "Xem bản 1", exact: true }).click(); await expect(drawer.getByText("Bản lịch sử 1", { exact: true })).toBeVisible();
  expect(state.calls.find((c) => c.path === "price-board-preview")?.body).toEqual({ pricing_method: "grade", flat_price_vnd: null, grade5_price_vnd: "100000.01" });
  expect(state.writes()).toHaveLength(0);
});
for (const [code, title] of [["BLOCKED", "Nguồn đang chặn truy cập"], ["STALE_SOURCE", "Giá nguồn đã cũ, chưa áp dụng"], ["MISSING_SOURCE_DATE", "Nguồn thiếu ngày công bố"], ["NETWORK_DISABLED", "Mạng lấy giá đang bị tắt trên máy này"]]) test(`${code} is honest and never supplies a zero price or success`, async ({ page }) => {
  await fixture(page, status({ status: code, network_available: code !== "NETWORK_DISABLED", detail: "Chưa xác nhận được giá đúng ngày." })); await mount(page);
  await expect(card(page).getByText(title, { exact: true })).toBeVisible(); await expect(card(page).getByText("Chưa xác nhận", { exact: true })).toBeVisible();
  await expect(card(page).getByText(/Grade5 đã áp dụng|Đã áp dụng giá đúng ngày/)).toHaveCount(0); await expect(card(page).getByRole("columnheader", { name: "VND/kg", exact: true })).toHaveCount(0);
  if (code === "NETWORK_DISABLED") await expect(check(page)).toBeDisabled();
});
test("existing manual board retains edit, stop, delete and history controls", async ({ page }) => {
  await fixture(page, status({ status: "EXISTING_BOARD", board_id: boardId, board_version: 1 })); await mount(page); await page.getByRole("button", { name: "Xem bảng giá đã có", exact: true }).click();
  const drawer = page.getByRole("dialog"); await expect(drawer.getByRole("button", { name: "Sửa bảng giá / ngừng áp dụng", exact: true })).toBeVisible(); await expect(drawer.getByRole("button", { name: "Xóa mềm", exact: true })).toBeVisible(); await expect(drawer.getByRole("button", { name: "Xem lịch sử", exact: true })).toBeVisible();
  await drawer.getByRole("button", { name: "Sửa bảng giá / ngừng áp dụng", exact: true }).click(); await expect(page.getByRole("dialog", { name: "Sửa bảng giá", exact: true }).getByLabel("Đang áp dụng", { exact: true })).toBeEnabled();
});
test("APPLIED for a different board never locks a manual product board", async ({ page }) => {
  const otherId = "77777777-7777-4777-8777-777777777778";
  await fixture(page, applied()); await page.route(`**/api/v1/records/price-boards/${otherId}`, (route) => route.fulfill({ json: { ...board(), id: otherId, code: "GIA-RIENG" } })); await mount(page);
  await page.evaluate((id) => { location.hash = `#/records/prices?selected=${id}`; }, otherId);
  await expect(page.getByRole("dialog").getByRole("button", { name: "Sửa bảng giá / ngừng áp dụng", exact: true })).toBeVisible();
});
test("check-now respects server cooldown and applied board prevents another check", async ({ page }) => {
  const state = await fixture(page); await mount(page); await expect(check(page)).toBeEnabled(); await check(page).click();
  await expect(card(page).getByText("Nguồn đang chặn truy cập", { exact: true })).toBeVisible(); await expect(check(page)).toBeDisabled(); await expect(card(page).getByText("Đang chờ đến lượt kiểm tra tiếp theo.", { exact: true })).toBeVisible();
  expect(state.writes()).toHaveLength(1); expect(state.writes()[0].body).toEqual({ request_key: expect.any(String) });
  state.setStatus(applied()); await page.getByRole("button", { name: "Tải lại trạng thái giá tự động", exact: true }).click(); await expect(card(page).getByText("Đã áp dụng giá đúng ngày", { exact: true })).toBeVisible(); await expect(check(page)).toBeDisabled(); expect(state.writes()).toHaveLength(1);
});
for (const kind of ["settings", "check"] as const) for (const response of [200, 500]) test(`unknown ${kind} ${response} freezes and retries exact key, version and body only on explicit action`, async ({ page }) => {
  await fixture(page); const bodies: Row[] = []; let first = true;
  await page.route(`**/api/v1/records/market/processed/${kind}`, async (route) => { const body = route.request().postDataJSON(); bodies.push(body); if (first) { first = false; await route.fulfill({ status: response, contentType: "application/json", body: "{" }); } else await route.fulfill({ json: status({ enabled: kind === "settings" ? false : true, settings_version: 4 }) }); });
  await mount(page); if (kind === "settings") await page.getByRole("switch", { name: "Tự động lấy giá nhân xô", exact: true }).click(); else await check(page).click();
  const retry = page.getByRole("button", { name: "Kiểm tra lại cùng yêu cầu giá tự động", exact: true }); await expect(retry).toBeVisible(); await expect(check(page)).toBeDisabled(); await expect(page.getByRole("switch", { name: "Tự động lấy giá nhân xô", exact: true })).toBeDisabled();
  // Status refresh cannot acknowledge or unlock an uncertain mutation.
  await page.getByRole("button", { name: "Tải lại trạng thái giá tự động", exact: true }).click(); await expect(retry).toBeVisible(); expect(bodies).toHaveLength(1);
  await retry.click(); await expect(retry).toHaveCount(0); expect(bodies).toHaveLength(2); expect(bodies[1]).toEqual(bodies[0]); if (kind === "settings") expect(bodies[0]).toEqual({ request_key: expect.any(String), expected_version: 3, enabled: false });
});
test("successful toggle uses latest version and disabled setting blocks check-now", async ({ page }) => {
  const state = await fixture(page); await mount(page); const toggle = page.getByRole("switch", { name: "Tự động lấy giá nhân xô", exact: true }); await toggle.click(); await expect(toggle).not.toBeChecked(); await expect(toggle).toBeEnabled(); await expect(check(page)).toBeDisabled();
  await toggle.click(); await expect(toggle).toBeChecked(); expect(state.writes().map((c) => c.body?.expected_version)).toEqual([3, 4]); expect(state.writes()[0].body?.request_key).not.toBe(state.writes()[1].body?.request_key);
});
test("read-only user cannot toggle or fetch and page remains readable", async ({ page }) => {
  const state = await fixture(page, applied()); await mount(page, true); await expect(card(page).getByText("Đã áp dụng giá đúng ngày", { exact: true })).toBeVisible(); await expect(page.getByRole("switch", { name: "Tự động lấy giá nhân xô", exact: true })).toBeDisabled(); await expect(check(page)).toBeDisabled(); expect(state.writes()).toHaveLength(0);
});
test("session replacement discards late status and pending toggle acknowledgement", async ({ page }) => {
  await fixture(page); let pending: Route | undefined;
  await page.route("**/api/v1/records/market/processed/settings", (route) => { pending = route; });
  await mount(page); await page.getByRole("switch", { name: "Tự động lấy giá nhân xô", exact: true }).click(); await expect.poll(() => !!pending).toBe(true);
  await page.evaluate(async () => { const path = "/src/shared/session.ts", { useSession } = await import(path); useSession.getState().logout(); });
  await pending!.fulfill({ json: applied() }).catch(() => {}); await expect(card(page).getByText("Đã áp dụng giá đúng ngày", { exact: true })).toHaveCount(0); await expect(check(page)).toHaveCount(0);
});
test("30 second status polling is bounded and stops after leaving the tab; list remains paged", async ({ page }) => {
  const state = await fixture(page); await page.clock.install(); await mount(page); await expect(check(page)).toBeEnabled();
  const before = state.calls.filter((c) => c.path === "market/processed").length; await page.clock.fastForward(30001); await expect.poll(() => state.calls.filter((c) => c.path === "market/processed").length).toBe(before + 1);
  await page.getByRole("link", { name: "Đầu vào", exact: true }).click(); const departed = state.calls.filter((c) => c.path === "market/processed").length; await page.clock.fastForward(90000); expect(state.calls.filter((c) => c.path === "market/processed")).toHaveLength(departed);
  expect(state.calls.filter((c) => c.path === "price-boards").every((c) => c.query.get("page_size") === "25")).toBe(true); expect(state.writes()).toHaveLength(0);
});
test("malformed success with foreign source never becomes applied and remains uncertain", async ({ page }) => {
  await fixture(page); await page.route("**/api/v1/records/market/processed/check", (route) => route.fulfill({ json: { ...applied(), source_url: "javascript:alert(1)" } })); await mount(page); await check(page).click();
  await expect(page.getByRole("button", { name: "Kiểm tra lại cùng yêu cầu giá tự động", exact: true })).toBeVisible(); await expect(card(page).getByText("Đã áp dụng giá đúng ngày", { exact: true })).toHaveCount(0); await expect(card(page).getByRole("link")).toHaveAttribute("href", source);
});
