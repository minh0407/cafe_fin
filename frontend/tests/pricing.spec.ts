import { test, expect, type Page, type Route } from "@playwright/test";

// Synthetic browser contract tests; the real SQLite/API suite verifies authority.
type Row = Record<string, any>;
const farmId = "11111111-1111-4111-8111-111111111111";
const productId = "33333333-3333-4333-8333-333333333333";
const otherProduct = "33333333-3333-4333-8333-333333333334";
const boardId = "77777777-7777-4777-8777-777777777777";
const tradeId = "44444444-4444-4444-8444-444444444444";
const companyId = "22222222-2222-4222-8222-222222222222";
const entity = (id: string, code: string, extra: Row = {}) => ({ id, code, name: code, active: true, version: 1, deleted_at: null, created_at: "2026-11-07T03:00:00Z", updated_at: "2026-11-07T03:00:00Z", created_by: "synthetic", updated_by: "synthetic", ...extra });
const quote = (query: URLSearchParams, extra: Row = {}) => ({ price_board_id: boardId, price_board_version: 1, price_kind: query.get("price_kind"), price_date: query.get("price_date"), product_id: query.get("product_id") || null, grade: query.has("grade") ? Number(query.get("grade")) : null, unit_price_vnd: "100.01", formula_version: 1, ...extra });
const board = () => entity(boardId, "GIA-TU-SINH", { price_date: "2026-11-07", price_kind: "sale", product_id: productId, pricing_method: "flat", flat_price_vnd: "100.01", grade5_price_vnd: null });
function oldTrade(daily = true): Row {
  const snapshot = quote(new URLSearchParams({ price_kind: "sale", price_date: "2026-11-07", product_id: productId, grade: "3" }));
  return entity(tradeId, "BAN-CU", { direction: "outbound", occurred_on: "2026-11-07", occurred_at: "2026-11-07T08:00:00+07:00", physical_actor: "Người giao tổng hợp", party_id: companyId, vehicle_plate: "SYNTH-01", weighing_id: null, status: "recorded", note: "Ghi chú giữ lại", lines: [{ farm_id: farmId, product_id: productId, quantity_kg: "1.001", unit_price_vnd: "100.01", bag_count: 2, grade: 3, note: "Ghi chú dòng giữ lại", ...(daily ? { pricing_mode: "daily", price_kind: "sale", price_date: "2026-11-07", price_snapshot: snapshot } : {}) }] });
}
async function fixture(page: Page) {
  const requests: { path: string; method: string; body: Row | null; query: URLSearchParams }[] = [];
  const boards: Row[] = [];
  await page.route("**/api/v1/records/**", async (route) => {
    const req = route.request(), url = new URL(req.url()), path = url.pathname.split("/records/")[1];
    const body = req.postData() ? req.postDataJSON() : null;
    requests.push({ path, method: req.method(), body, query: url.searchParams });
    if (path === "price-quote") { await route.fulfill({ json: quote(url.searchParams) }); return; }
    if (path === "price-board-preview") { await route.fulfill({ json: { pricing_method: body.pricing_method, flat_price_vnd: body.flat_price_vnd, grade_prices: [5, 4, 3, 2, 1].map((grade, index) => ({ grade, unit_price_vnd: ["100.01", "90.01", "81.01", "72.91", "65.62"][index] })), formula_version: 1 } }); return; }
    const [resource, id, action] = path.split("/");
    const parties = [entity(farmId, "AB12", { profile_kind: "farm" }), entity(companyId, "CT01", { profile_kind: "customer_company", tax_code: "SYNTH-MST", representative: { name: "Liên hệ tổng hợp" } })];
    const rows = resource === "parties" ? parties : resource === "products" ? [entity(productId, "CF01"), entity(otherProduct, "CF02")] : resource === "price-boards" ? boards : [];
    if (req.method() === "GET") {
      if (action === "history") { await route.fulfill({ json: { items: [{ version: rows[0].version, action: "update", recorded_at: "2026-11-07T03:00:00Z", data: rows[0] }], total: 1 } }); return; }
      if (id) { await route.fulfill({ json: rows.find((row) => row.id === id) ?? entity(id, "SOURCE") }); return; }
      await route.fulfill({ json: { items: rows, total: rows.length, page: 1, page_size: 25 } }); return;
    }
    if (resource === "price-boards") {
      if (req.method() === "POST" && !id) boards.push(entity(boardId, "GIA-TU-SINH", body));
      else if (req.method() === "PUT") Object.assign(boards[0], body, { version: boards[0].version + 1 });
      else if (req.method() === "DELETE") Object.assign(boards[0], { deleted_at: "2026-11-07T04:00:00Z", version: boards[0].version + 1 });
      else if (action === "restore") Object.assign(boards[0], { deleted_at: null, version: boards[0].version + 1 });
      await route.fulfill({ json: boards[0] }); return;
    }
    await route.fulfill({ json: entity(tradeId, body.code, body) });
  });
  return { requests, boards, quotes: () => requests.filter((r) => r.path === "price-quote"), writes: () => requests.filter((r) => r.path.startsWith("trades") && r.method !== "GET") };
}
async function mount(page: Page, component: "TradeEditor" | "PricesPage", props: Row = {}) {
  await page.goto("about:blank");
  await page.route("**/pricing-harness", (route) => route.fulfill({ contentType: "text/html", body: '<html><body><div id="root"></div></body></html>' }));
  await page.goto(`/pricing-harness#/records/${component === "PricesPage" ? "prices" : "outbound"}`);
  await page.evaluate(async ({ component, props }) => {
    const refreshPath = "/@react-refresh", refresh = (await import(refreshPath)).default;
    refresh.injectIntoGlobalHook(window); Reflect.set(window, "$RefreshReg$", () => {}); Reflect.set(window, "$RefreshSig$", () => (type: unknown) => type); Reflect.set(window, "__vite_plugin_react_preamble_installed__", true);
    const path = `/src/features/records/${component}.tsx`, source = await (await fetch(path)).text();
    const queryPath = source.match(/["'](\/node_modules\/\.vite\/deps\/@tanstack_react-query\.js(?:\?[^"']*)?)["']/)?.[1];
    if (!queryPath) throw new Error("React Query module unavailable");
    const reactPath = "/node_modules/.vite/deps/react.js", domPath = "/node_modules/.vite/deps/react-dom_client.js", sessionPath = "/src/shared/session.ts";
    const React = (await import(reactPath)).default, { createRoot } = (await import(domPath)).default;
    const { QueryClient, QueryClientProvider } = await import(queryPath), { useSession } = await import(sessionPath), module = await import(path);
    useSession.getState().setBoot({ protocol_version: 1, api_base: `${location.origin}/api/v1`, session_token: "synthetic", data_root: "D:\\Synthetic" });
    useSession.getState().login("synthetic", { id: "synthetic", username: "synthetic", role: "admin", permissions: ["*"] });
    createRoot(document.getElementById("root")!).render(React.createElement(QueryClientProvider, { client: new QueryClient() }, React.createElement(module[component], { ...props, onClose: () => {}, onSaved: (result: unknown) => Reflect.set(window, "__savedPricing", result) })));
  }, { component, props });
}
async function choose(page: Page, label: string, text: string, nth = 0) { await page.getByLabel(label, { exact: true }).nth(nth).click(); await page.locator(".ant-select-dropdown:visible .ant-select-item-option-content").filter({ hasText: text }).first().click(); }
async function newOutbound(page: Page) {
  await mount(page, "TradeEditor", { direction: "outbound" });
  await choose(page, "Chọn công ty khách hàng", "CT01"); await page.getByRole("button", { name: "Tiếp tục nhập đơn bán" }).click();
  await page.getByLabel("Mã / số đơn").fill("BAN-MOI"); await choose(page, "Hàng hóa", "CF01"); await page.getByLabel("Số kg", { exact: true }).fill("1.001");
}
async function saved(page: Page) { await expect.poll(() => page.evaluate(() => Reflect.get(window, "__savedPricing"))).toBeTruthy(); }

test("grade preview is server supplied with five steps; code/name are generated and form resets", async ({ page }) => {
  const state = await fixture(page); await mount(page, "PricesPage"); await page.getByRole("button", { name: "Thêm bảng giá", exact: true }).click();
  await page.getByLabel("Giá Grade5 (VND/kg)").fill("100.01"); await page.getByRole("button", { name: "Xem trước giá" }).click();
  await expect(page.getByRole("cell", { name: "65,62", exact: true })).toBeVisible(); await expect(page.getByRole("cell", { name: "90,01", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Lưu dữ liệu" }).click(); await expect(page.getByText("Bảng giá · GIA-TU-SINH", { exact: true })).toBeVisible();
  const body = state.requests.find((r) => r.path === "price-boards" && r.method === "POST")!.body!;
  expect(body).toMatchObject({ price_kind: "purchase_fresh", product_id: null, grade5_price_vnd: "100.01", flat_price_vnd: null }); expect(body).not.toHaveProperty("code"); expect(body).not.toHaveProperty("name");
  await page.locator(".ant-drawer-close").click(); await page.getByRole("button", { name: "Thêm bảng giá", exact: true }).click(); await expect(page.getByLabel("Giá Grade5 (VND/kg)")).toHaveValue("");
});
test("price page filters are paged and departing navigation is never overwritten", async ({ page }) => {
  const state = await fixture(page); await mount(page, "PricesPage"); await choose(page, "Lọc nhóm giá", "Bán ra"); await page.getByLabel("Lọc ngày bảng giá", { exact: true }).fill("07/11/2026");
  await expect.poll(() => state.requests.filter((r) => r.path === "price-boards").some((r) => JSON.parse(r.query.get("filters") || "{}").price_date === "2026-11-07")).toBe(true);
  const request = state.requests.filter((r) => r.path === "price-boards").at(-1)!; expect(request.query.get("page_size")).toBe("25"); expect(JSON.parse(request.query.get("filters")!)).toMatchObject({ price_kind: "sale", price_date: "2026-11-07" });
  await page.getByRole("link", { name: "Đầu vào", exact: true }).click(); await expect(page).toHaveURL(/#\/records\/inbound$/);
  // The harness keeps the outgoing page mounted to expose any later rewrite.
  await page.getByLabel("Tìm bảng giá").fill("outgoing"); await expect(page).toHaveURL(/#\/records\/inbound$/);
});
test("sale preset is independent, product required; scope/version/history/delete/restore are retained", async ({ page }) => {
  const state = await fixture(page); await mount(page, "PricesPage"); await page.getByRole("button", { name: "Thêm bảng giá", exact: true }).click();
  await choose(page, "Nhóm bảng giá", "Bán ra"); await expect(page.getByLabel("Giá cố định (VND/kg)")).toBeVisible(); await page.getByLabel("Giá cố định (VND/kg)").fill("100.01");
  await page.getByRole("button", { name: "Lưu dữ liệu" }).click(); expect(state.boards).toHaveLength(0); await choose(page, "Hàng hóa áp dụng (bắt buộc cho bán)", "CF01"); await page.getByRole("button", { name: "Lưu dữ liệu" }).click();
  await page.getByRole("button", { name: "Sửa bảng giá / ngừng áp dụng" }).click(); await expect(page.getByLabel("Ngày bảng giá", { exact: true })).toBeDisabled(); await expect(page.getByLabel("Nhóm bảng giá", { exact: true })).toBeDisabled(); await expect(page.getByLabel("Hàng hóa áp dụng (bắt buộc cho bán)")).toBeDisabled();
  await page.getByLabel("Đang áp dụng", { exact: true }).uncheck(); await page.getByRole("button", { name: "Lưu dữ liệu" }).click();
  await expect.poll(() => state.boards[0].version).toBe(2); await page.getByRole("button", { name: "Xem lịch sử" }).click(); await page.getByRole("button", { name: "Xem bản 2" }).click(); await expect(page.getByText("Bản lịch sử 2", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Xóa mềm", exact: true }).click(); await page.getByRole("button", { name: "Xóa mềm", exact: true }).last().click(); await page.getByRole("button", { name: "Khôi phục" }).click();
  await expect.poll(() => state.requests.find((r) => r.path.endsWith("/restore"))?.body?.expected_version).toBe(3);
});
test("new outbound uses sale automatically, readonly price and exact BigInt total from kg alone", async ({ page }) => {
  const state = await fixture(page); await newOutbound(page); await expect(page.getByLabel("Đơn giá (VND/kg)")).toHaveValue("100.01"); await expect(page.getByLabel("Đơn giá (VND/kg)")).toHaveAttribute("readonly", "");
  await expect(page.getByText("Thành tiền dòng (VND): 100,11001", { exact: true })).toBeVisible();
  await page.getByLabel("Số kg", { exact: true }).fill("9007199254740.999"); await expect(page.getByText("Thành tiền dòng (VND): 900.809.997.466.647,30999", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Lưu dữ liệu" }).click(); await saved(page); expect(state.writes()[0].body!.lines[0]).toMatchObject({ pricing_mode: "daily", price_kind: "sale", unit_price_vnd: "100.01", price_snapshot: { price_kind: "sale" } }); expect(state.quotes()).toHaveLength(1);
});
test("inbound defaults purchase fresh and requires Grade only when quote says so", async ({ page }) => {
  const state = await fixture(page);
  await page.route("**/api/v1/records/price-quote?**", async (route) => { const q = new URL(route.request().url()).searchParams; if (!q.has("grade")) await route.fulfill({ status: 422, json: { error: { code: "PRICE_GRADE_REQUIRED", message: "Bảng giá này cần chọn Grade.", field_errors: [] } } }); else await route.fulfill({ json: quote(q, { unit_price_vnd: "90.01" }) }); });
  await mount(page, "TradeEditor", { direction: "inbound" }); await expect(page.getByText("Bảng giá này cần chọn Grade.", { exact: true })).toBeVisible(); await expect(page.getByRole("button", { name: "Lưu dữ liệu" })).toBeDisabled();
  await choose(page, "Farm dòng 1", "AB12"); await choose(page, "Grade", "4"); await page.getByLabel("Mã / số đơn").fill("MUA-MOI"); await page.getByLabel("Số kg", { exact: true }).fill("2.001"); await expect(page.getByLabel("Đơn giá (VND/kg)")).toHaveValue("90.01"); await page.getByRole("button", { name: "Lưu dữ liệu" }).click(); await saved(page);
  expect(state.writes()[0].body!.lines[0]).toMatchObject({ price_kind: "purchase_fresh", product_id: null, grade: 4, price_snapshot: { price_kind: "purchase_fresh", grade: 4 } });
});
test("missing price blocks save and inline configuration retains trade draft/session", async ({ page }) => {
  await fixture(page); await page.route("**/api/v1/records/price-quote?**", (route) => route.fulfill({ status: 404, json: { error: { code: "PRICE_NOT_FOUND", message: "Chưa có bảng giá đúng ngày.", field_errors: [] } } }));
  await newOutbound(page); await expect(page.getByText("Chưa có bảng giá đúng ngày.", { exact: true })).toBeVisible(); await expect(page.getByRole("button", { name: "Lưu dữ liệu" })).toBeDisabled();
  await page.getByRole("button", { name: "Thiết lập bảng giá cho dòng này" }).click(); const boardDialog = page.getByRole("dialog", { name: "Thêm bảng giá", exact: true }); await expect(boardDialog.getByLabel("Giá cố định (VND/kg)")).toBeVisible(); await expect(boardDialog.getByLabel("Hàng hóa áp dụng (bắt buộc cho bán)")).toBeVisible(); await boardDialog.getByRole("button", { name: "Đóng", exact: true }).click(); await expect(page.getByLabel("Mã / số đơn")).toHaveValue("BAN-MOI"); await expect(page.getByLabel("Số kg", { exact: true })).toHaveValue("1.001");
});
test("saved daily snapshot survives kg edit without quote; hidden allowed metadata is preserved", async ({ page }) => {
  const state = await fixture(page), initial = oldTrade(); await mount(page, "TradeEditor", { direction: "outbound", initial }); await page.getByRole("button", { name: "Tiếp tục nhập đơn bán" }).click();
  await page.getByLabel("Số kg", { exact: true }).fill("2.001"); await expect(page.getByText("Thành tiền dòng (VND): 200,12001", { exact: true })).toBeVisible(); await page.getByRole("button", { name: "Lưu dữ liệu" }).click(); await saved(page);
  expect(state.quotes()).toHaveLength(0); expect(state.writes()[0].body).toMatchObject({ expected_version: 1, occurred_at: initial.occurred_at, physical_actor: initial.physical_actor, vehicle_plate: initial.vehicle_plate, note: initial.note, lines: [{ farm_id: farmId, bag_count: 2, grade: 3, note: initial.lines[0].note, price_snapshot: initial.lines[0].price_snapshot }] }); expect(state.writes()[0].body).not.toHaveProperty("created_by");
});
test("old manual data stays manual; explicit refresh alone replaces a saved daily quote", async ({ page }) => {
  const state = await fixture(page); await mount(page, "TradeEditor", { direction: "outbound", initial: oldTrade(false) }); await page.getByRole("button", { name: "Tiếp tục nhập đơn bán" }).click(); await expect(page.getByText("Giá nhập tay / dữ liệu cũ: giá đã ghi được giữ nguyên khi sửa kg.", { exact: true })).toBeVisible(); await page.getByLabel("Đơn giá (VND/kg)").fill("123.45"); await page.getByRole("button", { name: "Lưu dữ liệu" }).click(); await saved(page); expect(state.quotes()).toHaveLength(0); expect(state.writes()[0].body!.lines[0].pricing_mode).toBe("manual");
  await mount(page, "TradeEditor", { direction: "outbound", initial: oldTrade() }); await page.getByRole("button", { name: "Tiếp tục nhập đơn bán" }).click(); await page.route("**/api/v1/records/price-quote?**", (route) => route.fulfill({ json: quote(new URL(route.request().url()).searchParams, { price_board_version: 2, unit_price_vnd: "200.02" }) })); await page.getByRole("button", { name: "Lấy lại giá mới" }).click(); await expect(page.getByLabel("Đơn giá (VND/kg)")).toHaveValue("200.02"); await expect(page.getByText(/Nguồn:.*bản 2/)).toBeVisible();
});
test("changed criteria clears price immediately; slower quote cannot overwrite newer Grade or date", async ({ page }) => {
  await fixture(page); let pending: Route | undefined;
  await page.route("**/api/v1/records/price-quote?**", async (route) => { const q = new URL(route.request().url()).searchParams; if (!q.has("grade")) pending = route; else await route.fulfill({ json: quote(q, { unit_price_vnd: "81.01" }) }); });
  await newOutbound(page); await expect.poll(() => !!pending).toBe(true); await expect(page.getByRole("button", { name: "Lưu dữ liệu" })).toBeDisabled(); await choose(page, "Grade", "3"); await expect(page.getByLabel("Đơn giá (VND/kg)")).toHaveValue("81.01");
  await pending!.fulfill({ json: quote(new URL(pending!.request().url()).searchParams, { unit_price_vnd: "999.99" }) }); await expect(page.getByLabel("Đơn giá (VND/kg)")).toHaveValue("81.01");
  await page.getByLabel("Ngày nghiệp vụ", { exact: true }).fill("08/11/2026"); await expect(page.getByText(/Nguồn:.*08\/11\/2026/)).toBeVisible(); await expect(page.getByLabel("Đơn giá (VND/kg)")).toHaveValue("81.01");
});
test("removed row quote never writes into surviving row", async ({ page }) => {
  await fixture(page); let pending: Route | undefined;
  await page.route("**/api/v1/records/price-quote?**", async (route) => { const q = new URL(route.request().url()).searchParams; if (q.get("product_id") === otherProduct) pending = route; else await route.fulfill({ json: quote(q) }); });
  await newOutbound(page); await expect(page.getByLabel("Đơn giá (VND/kg)")).toHaveValue("100.01"); await page.getByRole("button", { name: "Thêm dòng hàng" }).click(); await choose(page, "Hàng hóa", "CF02", 1); await expect.poll(() => !!pending).toBe(true); await page.getByRole("button", { name: "Bỏ dòng", exact: true }).nth(1).click();
  await pending!.fulfill({ json: quote(new URL(pending!.request().url()).searchParams, { unit_price_vnd: "999.99" }) }); await expect(page.getByLabel("Đơn giá (VND/kg)")).toHaveCount(1); await expect(page.getByLabel("Đơn giá (VND/kg)")).toHaveValue("100.01");
});
test("removed first row cannot overwrite a frozen surviving row with identical criteria", async ({ page }) => {
  await fixture(page); let pending: Route | undefined;
  await page.route("**/api/v1/records/price-quote?**", (route) => { pending = route; });
  const initial = oldTrade(); initial.lines = [{ ...initial.lines[0], price_snapshot: null, unit_price_vnd: null }, initial.lines[0]];
  await mount(page, "TradeEditor", { direction: "outbound", initial }); await page.getByRole("button", { name: "Tiếp tục nhập đơn bán" }).click(); await expect.poll(() => !!pending).toBe(true);
  await page.getByRole("button", { name: "Bỏ dòng", exact: true }).first().click(); await pending!.fulfill({ json: quote(new URL(pending!.request().url()).searchParams, { unit_price_vnd: "999.99", price_board_version: 2 }) });
  await expect(page.getByLabel("Đơn giá (VND/kg)")).toHaveCount(1); await expect(page.getByLabel("Đơn giá (VND/kg)")).toHaveValue("100.01"); await expect(page.getByText(/Nguồn:.*bản 1/)).toBeVisible();
});
test("PRICE_CHANGED keeps the seen price until explicit refresh and new confirmation", async ({ page }) => {
  await fixture(page); const attempts: Row[] = [];
  await page.route("**/api/v1/records/trades", async (route) => { const body = route.request().postDataJSON(); attempts.push(body); if (attempts.length === 1) await route.fulfill({ status: 409, json: { error: { code: "PRICE_CHANGED", message: "Bảng giá đã thay đổi. Lấy lại giá mới rồi xác nhận.", field_errors: [] } } }); else await route.fulfill({ json: entity(tradeId, body.code, body) }); });
  await newOutbound(page); await expect(page.getByLabel("Đơn giá (VND/kg)")).toHaveValue("100.01"); await page.getByRole("button", { name: "Lưu dữ liệu" }).click(); await expect(page.getByText("Bảng giá đã thay đổi. Lấy lại giá mới rồi xác nhận.", { exact: true })).toBeVisible(); await expect(page.getByLabel("Đơn giá (VND/kg)")).toHaveValue("100.01");
  await page.route("**/api/v1/records/price-quote?**", (route) => route.fulfill({ json: quote(new URL(route.request().url()).searchParams, { price_board_version: 2, unit_price_vnd: "200.02" }) })); await page.getByRole("button", { name: "Lấy lại giá mới" }).click(); await expect(page.getByLabel("Đơn giá (VND/kg)")).toHaveValue("200.02"); await page.getByRole("button", { name: "Lưu dữ liệu" }).click(); await saved(page); expect(attempts[1].request_key).not.toBe(attempts[0].request_key); expect(attempts[1].lines[0].price_snapshot.price_board_version).toBe(2);
});
for (const status of [200, 500]) test(`unknown trade save ${status} freezes prices/form and retry reuses exact body and key`, async ({ page }) => {
  const state = await fixture(page), attempts: Row[] = []; let first = true;
  await page.route("**/api/v1/records/trades", async (route) => { const body = route.request().postDataJSON(); attempts.push(body); if (first) { first = false; await route.fulfill({ status, body: "{", contentType: "application/json" }); } else await route.fulfill({ json: entity(tradeId, body.code, body) }); });
  await newOutbound(page); await expect(page.getByLabel("Đơn giá (VND/kg)")).toHaveValue("100.01"); await page.getByRole("button", { name: "Lưu dữ liệu" }).click(); await expect(page.getByRole("button", { name: "Kiểm tra lại cùng yêu cầu" })).toBeVisible(); await expect(page.getByLabel("Số kg", { exact: true })).toBeDisabled(); await expect(page.getByRole("button", { name: "Lấy lại giá mới" })).toBeDisabled(); await expect(page.getByRole("button", { name: "Đóng", exact: true })).toBeDisabled(); await expect(page.getByRole("button", { name: "Thêm dòng hàng" })).toBeDisabled();
  await page.getByRole("button", { name: "Kiểm tra lại cùng yêu cầu" }).click(); await saved(page); expect(attempts).toHaveLength(2); expect(attempts[1]).toEqual(attempts[0]); expect(state.quotes()).toHaveLength(1);
});
test("session replacement discards a pending quote and disables writing", async ({ page }) => {
  await fixture(page); let pending: Route | undefined;
  await page.route("**/api/v1/records/price-quote?**", (route) => { pending = route; }); await newOutbound(page); await expect.poll(() => !!pending).toBe(true);
  await page.evaluate(async () => { const path = "/src/shared/session.ts", { useSession } = await import(path); useSession.getState().logout(); }); await pending!.fulfill({ json: quote(new URL(pending!.request().url()).searchParams) }).catch(() => {}); await expect(page.getByLabel("Đơn giá (VND/kg)")).toHaveValue(""); await expect(page.getByRole("button", { name: "Lưu dữ liệu" })).toBeDisabled();
});
