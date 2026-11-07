import { test, expect, type Page } from "@playwright/test";

// All parties and documents are synthetic. These UI contract tests deliberately
// do not claim to verify SQLite/ledger transactions; integration runs do that.
const farmId = "11111111-1111-4111-8111-111111111111";
const companyId = "22222222-2222-4222-8222-222222222222";
const productId = "33333333-3333-4333-8333-333333333333";
const tradeId = "44444444-4444-4444-8444-444444444444";
const paymentId = "55555555-5555-4555-8555-555555555555";
const entryId = "66666666-6666-4666-8666-666666666666";
type Row = Record<string, any>;
function entity(id: string, code: string, extra: Row = {}): Row { return { id, code, version: 1, active: true, deleted_at: null, created_at: "2026-11-07T03:00:00Z", updated_at: "2026-11-07T03:00:00Z", created_by: "synthetic", updated_by: "synthetic", ...extra }; }
function farm(): Row { return entity(farmId, "AB12", { name: "Farm tổng hợp", type: "person", roles: ["supplier"], contacts: [], bank_details: [], profile_kind: "farm", farm: { owner_name: "Chủ Farm tổng hợp", owner_id_card: "SYNTHETIC-ID", plots: [], surveys: [] } }); }
function company(complete = true): Row { return entity(companyId, "CT01", { name: "Công ty tổng hợp", type: "organization", roles: ["customer"], profile_kind: "customer_company", tax_code: complete ? "SYNTHETIC-MST" : null, representative: complete ? { name: "Liên hệ tổng hợp" } : null, contacts: [], bank_details: [] }); }
function trade(direction: "inbound" | "outbound" = "outbound"): Row { return entity(tradeId, direction === "inbound" ? "MUA-01" : "BAN-01", { direction, occurred_on: "2026-11-07", status: "recorded", party_id: direction === "outbound" ? companyId : null, lines: [{ farm_id: direction === "inbound" ? farmId : null, product_id: productId, quantity_kg: "1.001", unit_price_vnd: "100.01", bag_count: 2, grade: 3 }] }); }

async function fixtures(page: Page, initial: Record<string, Row[]> = {}) {
  const data: Record<string, Row[]> = { parties: [farm(), company()], products: [entity(productId, "CF01", { name: "Cà phê tổng hợp" })], entries: [], trades: [], "trade-payments": [], ...initial };
  const requests: { method: string; resource: string; path: string; query: URLSearchParams; body: Row | null }[] = [];
  await page.route("**/api/v1/records/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname.split("/records/")[1];
    const [resource, id, action] = path.split("/");
    const body = request.postData() ? request.postDataJSON() : null;
    requests.push({ method: request.method(), resource, path, query: url.searchParams, body });
    const rows = data[resource] ?? [];
    if (request.method() === "GET") {
      if (action === "history") { const value = rows.find((row) => row.id === id)!; await route.fulfill({ json: { items: [{ version: value.version, action: "create", recorded_at: value.created_at, data: value }], total: 1, page: 1, page_size: 20 } }); return; }
      if (id) { const value = rows.find((row) => row.id === id); await route.fulfill(value ? { json: value } : { status: 404, json: { error: { code: "NOT_FOUND", message: "Không tìm thấy hồ sơ.", field_errors: [] } } }); return; }
      const filters = JSON.parse(url.searchParams.get("filters") ?? "{}");
      const search = url.searchParams.get("search") ?? "";
      const filtered = rows.filter((row) => (filters.include_deleted || !row.deleted_at) && (!filters.profile_kind || row.profile_kind === filters.profile_kind) && (!filters.direction || row.direction === filters.direction) && (!filters.trade_id || row.trade_id === filters.trade_id) && (!filters.status || row.status === filters.status) && (!filters.from_on || row.occurred_on >= filters.from_on) && (!filters.through_on || row.occurred_on <= filters.through_on) && (!search || `${row.code} ${row.name}`.includes(search)));
      const current = Number(url.searchParams.get("page") ?? "1"); const size = Number(url.searchParams.get("page_size") ?? "25");
      await route.fulfill({ json: { items: filtered.slice((current - 1) * size, current * size), total: filtered.length, page: current, page_size: size } }); return;
    }
    if (request.method() === "POST" && !id) {
      if (resource === "parties" && rows.some((row) => row.code === body.code)) { await route.fulfill({ status: 409, json: { error: { code: "DUPLICATE_CODE", message: "Mã đã tồn tại.", field_errors: [{ field: "code", code: "DUPLICATE_CODE", message: "Mã đã tồn tại." }] } } }); return; }
      const newId = resource === "parties" ? (body.profile_kind === "farm" ? farmId : companyId) : resource === "trades" ? tradeId : resource === "entries" ? entryId : paymentId;
      const result = entity(newId, body.code, body); delete result.request_key; delete result.expected_version;
      data[resource] = [...rows, result]; await route.fulfill({ json: result }); return;
    }
    const value = rows.find((row) => row.id === id)!;
    if (request.method() === "PUT") { Object.assign(value, body, { version: value.version + 1 }); delete value.request_key; delete value.expected_version; }
    else if (request.method() === "DELETE") { value.deleted_at = "2026-11-07T04:00:00Z"; value.version++; }
    else if (action === "restore") { value.deleted_at = null; value.version++; }
    await route.fulfill({ json: value });
  });
  return { data, requests };
}

async function mount(page: Page, component: "FarmsPage" | "CustomersPage" | "InboundPage" | "OutboundPage", query = "", write = true) {
  await page.goto("about:blank");
  await page.route("**/crm-harness", (route) => route.fulfill({ contentType: "text/html", body: '<!doctype html><html><body><div id="root"></div></body></html>' }));
  const route = { FarmsPage: "farms", CustomersPage: "customers", InboundPage: "inbound", OutboundPage: "outbound" }[component];
  await page.goto(`/crm-harness#/records/${route}${query}`);
  await page.evaluate(async ({ component, write }) => {
    const refreshPath = "/@react-refresh"; const refresh = (await import(refreshPath)).default;
    refresh.injectIntoGlobalHook(window); Reflect.set(window, "$RefreshReg$", () => {}); Reflect.set(window, "$RefreshSig$", () => (type: unknown) => type); Reflect.set(window, "__vite_plugin_react_preamble_installed__", true);
    const modulePath = `/src/features/records/${component === "FarmsPage" || component === "CustomersPage" ? "PartyCatalog" : "TradePage"}.tsx`;
    const source = await (await fetch(modulePath)).text();
    const queryPath = source.match(/["'](\/node_modules\/\.vite\/deps\/@tanstack_react-query\.js(?:\?[^"']*)?)["']/)?.[1];
    if (!queryPath) throw new Error("React Query module unavailable");
    const reactPath = "/node_modules/.vite/deps/react.js"; const rootPath = "/node_modules/.vite/deps/react-dom_client.js";
    const sessionPath = "/src/shared/session.ts";
    const React = (await import(reactPath)).default; const { createRoot } = (await import(rootPath)).default;
    const { QueryClient, QueryClientProvider } = await import(queryPath); const { useSession } = await import(sessionPath);
    useSession.getState().setBoot({ protocol_version: 1, api_base: `${location.origin}/api/v1`, session_token: "synthetic", data_root: "D:\\Synthetic" });
    useSession.getState().login("synthetic", { id: "synthetic", username: "synthetic", version: 1, role: "operator", permissions: write ? ["records.read", "records.write"] : ["records.read"] });
    const module = await import(modulePath);
    createRoot(document.getElementById("root")!).render(React.createElement(QueryClientProvider, { client: new QueryClient({ defaultOptions: { queries: { retry: false } } }) }, React.createElement(module[component])));
  }, { component, write });
  await expect(page.getByRole("heading", { level: 2 })).toBeVisible();
}

async function choose(page: Page, label: string, text: string) {
  await page.getByLabel(label, { exact: true }).click();
  await page.locator(".ant-select-item-option-content").filter({ hasText: text }).first().click();
}

test("farm form writes owner, area, plot and survey; code remains immutable and duplicates stay visible", async ({ page }) => {
  const state = await fixtures(page, { parties: [] }); await mount(page, "FarmsPage");
  await page.getByRole("button", { name: "Thêm Farm", exact: true }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Mã Farm (4 ký tự)").fill("ab12");
  await dialog.getByLabel("Tên Farm", { exact: true }).fill("Farm tổng hợp");
  await dialog.getByLabel("Tên chủ Farm").fill("Chủ Farm tổng hợp");
  await dialog.getByLabel("CCCD / giấy tờ chủ Farm").fill("SYNTHETIC-ID");
  await dialog.getByLabel("Mã vùng chính thức").fill("SYNTH-AREA");
  await dialog.getByRole("button", { name: "Thêm lô trồng" }).click();
  await dialog.getByLabel("Diện tích (ha)").fill("12.345");
  await dialog.getByRole("button", { name: "Thêm khảo sát" }).click();
  await dialog.getByLabel("Năm mùa vụ").fill("2026"); await choose(page, "Grade khảo sát", "3");
  await dialog.getByLabel("Tỷ lệ chín (%)").fill("85.125");
  await dialog.getByRole("button", { name: "Lưu dữ liệu" }).click();
  await expect(page.getByText("Chi tiết AB12", { exact: true })).toBeVisible();
  const saved = state.requests.find((item) => item.method === "POST")!.body!;
  expect(saved.code).toBe("AB12"); expect(saved.farm.plots[0].area_ha).toBe("12.345"); expect(saved.farm.surveys[0]).toMatchObject({ season_year: 2026, grade: 3, ripeness_pct: "85.125" }); expect(saved.representative.name).toBe("Chủ Farm tổng hợp");
  await page.getByRole("button", { name: "Sửa dữ liệu", exact: true }).click();
  await expect(page.getByLabel("Mã Farm (4 ký tự)")).toBeDisabled();
  await page.getByRole("dialog").getByRole("button", { name: "Đóng", exact: true }).click();
  await page.locator(".ant-drawer-close").click();
  await page.getByRole("button", { name: "Thêm Farm", exact: true }).click();
  await page.getByLabel("Mã Farm (4 ký tự)").fill("AB12"); await page.getByLabel("Tên Farm", { exact: true }).fill("Trùng tổng hợp");
  await page.getByRole("dialog").getByRole("button", { name: "Lưu dữ liệu" }).click();
  await expect(page.getByRole("dialog").getByText("Mã đã tồn tại.", { exact: true }).first()).toBeVisible();
});

test("company catalog uses explicit fields and outbound requires MST and contact before order", async ({ page }) => {
  const state = await fixtures(page, { parties: [] }); await mount(page, "CustomersPage");
  await page.getByRole("button", { name: "Thêm Công ty khách hàng", exact: true }).click();
  await page.getByLabel("Mã công ty").fill("CT01"); await page.getByLabel("Tên công ty", { exact: true }).fill("Công ty tổng hợp");
  await page.getByLabel("Giấy phép kinh doanh").fill("SYNTH-LICENSE");
  await page.getByRole("dialog").getByRole("button", { name: "Lưu dữ liệu" }).click();
  await expect(page.getByText("Chi tiết CT01", { exact: true })).toBeVisible();
  expect(state.data.parties[0].business_license).toBe("SYNTH-LICENSE");
  await mount(page, "OutboundPage"); await page.getByRole("button", { name: "Thêm bán ra" }).click();
  await choose(page, "Chọn công ty khách hàng", "CT01");
  await expect(page.getByRole("button", { name: "Tiếp tục nhập đơn bán" })).toBeDisabled();
  await expect(page.getByLabel("Mã / số đơn")).toHaveCount(0);
  await page.getByRole("button", { name: "Hoàn tất thông tin công ty" }).click();
  const companyDialog = page.getByRole("dialog").filter({ has: page.getByLabel("Mã công ty") });
  await companyDialog.getByLabel("Mã số thuế", { exact: true }).fill("SYNTHETIC-MST"); await companyDialog.getByLabel("Người liên hệ / đại diện").fill("Liên hệ tổng hợp");
  await companyDialog.getByRole("button", { name: "Lưu dữ liệu" }).click();
  await page.getByRole("button", { name: "Tiếp tục nhập đơn bán" }).click();
  await page.getByLabel("Mã / số đơn").fill("BAN-01"); await choose(page, "Hàng hóa", "CF01");
  await page.getByLabel("Số kg", { exact: true }).fill("1.001"); await page.getByLabel("Đơn giá (VND/kg)").fill("100.01");
  await page.getByRole("dialog").getByRole("button", { name: "Lưu dữ liệu" }).click();
  await expect(page.getByText("Chi tiết bán ra · BAN-01", { exact: true })).toBeVisible();
  const created = state.requests.find((item) => item.method === "POST" && item.resource === "trades")!.body!;
  expect(created).toMatchObject({ direction: "outbound", party_id: companyId, lines: [{ product_id: productId, quantity_kg: "1.001", unit_price_vnd: "100.01" }] });
  expect(state.requests.some((item) => item.method === "POST" && item.resource === "entries")).toBe(false);
  await expect(page.getByText("100,11001", { exact: true }).first()).toBeVisible();
});

test("inbound records farm, bags, grade, vehicle; linked stock starts as a draft", async ({ page }) => {
  const state = await fixtures(page); await mount(page, "InboundPage");
  await page.getByRole("button", { name: "Thêm mua vào" }).click();
  await page.getByLabel("Mã / số đơn").fill("MUA-01"); await page.getByLabel("Biển xe", { exact: true }).fill("SYNTH-01");
  await choose(page, "Farm dòng 1", "AB12"); await choose(page, "Hàng hóa (chọn trước khi ghi sổ kho)", "CF01");
  await page.getByLabel("Số kg", { exact: true }).fill("12.125"); await page.getByLabel("Số bao", { exact: true }).fill("3"); await choose(page, "Grade", "4");
  await page.getByRole("dialog").getByRole("button", { name: "Lưu dữ liệu" }).click();
  await expect(page.getByText("Chi tiết mua vào · MUA-01", { exact: true })).toBeVisible();
  expect(state.data.trades[0]).toMatchObject({ direction: "inbound", vehicle_plate: "SYNTH-01", lines: [{ farm_id: farmId, quantity_kg: "12.125", bag_count: 3, grade: 4 }] });
  await page.getByRole("button", { name: "Tạo phiếu nhập kho nháp" }).click();
  await expect(page.getByLabel("Loại phiếu hàng")).toBeDisabled(); await expect(page.getByLabel("Trạng thái dữ liệu")).toBeDisabled();
  await page.getByLabel("Mã / số phiếu").fill("NHAP-01");
  await page.getByRole("dialog").getByRole("button", { name: "Lưu dữ liệu" }).click();
  await expect(page.getByText("Chi tiết NHAP-01", { exact: true })).toBeVisible();
  expect(state.requests.find((item) => item.method === "POST" && item.resource === "entries")!.body).toMatchObject({ trade_id: tradeId, entry_type: "receipt", status: "draft" });
});

test("direction/date/search/page/selection survive URL and details are fetched independently", async ({ page }) => {
  const state = await fixtures(page, { trades: [trade(), ...Array.from({ length: 26 }, (_, index) => ({ ...trade(), id: `synthetic-${index}`, code: `BAN-${index + 2}` }))] });
  await mount(page, "OutboundPage", `?from_on=2026-11-01&through_on=2026-11-30&search=BAN&sort=code&page=2&selected=${tradeId}`);
  await expect(page.getByText("Chi tiết bán ra · BAN-01", { exact: true })).toBeVisible();
  expect(state.requests.some((item) => item.path === `trades/${tradeId}` && item.method === "GET")).toBe(true);
  const list = state.requests.find((item) => item.resource === "trades" && item.query.has("filters"))!;
  expect(JSON.parse(list.query.get("filters")!)).toMatchObject({ direction: "outbound", from_on: "2026-11-01", through_on: "2026-11-30" }); expect(list.query.get("page")).toBe("2"); expect(list.query.get("search")).toBe("BAN");
  expect(page.url()).toContain(`selected=${tradeId}`);
  await page.locator(".ant-drawer-close").click();
  await page.getByLabel("Từ ngày", { exact: true }).fill("31/02/2026");
  await expect(page.getByText("Nhập ngày theo DD/MM/YYYY; ngày đầu không được sau ngày cuối.", { exact: true })).toBeVisible();
  expect(page.url()).not.toContain("31%2F02");
});

for (const failure of ["invalid-body", "generic-500"] as const) test(`payment ${failure} retry preserves request key and decimal text; version/history/delete/restore controls work`, async ({ page }) => {
  const state = await fixtures(page, { trades: [trade()] });
  const attempts: Row[] = []; let first = true;
  await page.route("**/api/v1/records/trade-payments", async (route) => {
    if (route.request().method() !== "POST") { await route.fallback(); return; }
    const body = route.request().postDataJSON(); attempts.push(body);
    const payment = entity(paymentId, body.code, body); delete payment.request_key;
    state.data["trade-payments"] = [payment];
    if (first) { first = false; await route.fulfill({ status: failure === "generic-500" ? 500 : 200, contentType: "application/json", body: "{" }); return; }
    await route.fulfill({ json: payment });
  });
  await mount(page, "OutboundPage", `?selected=${tradeId}`);
  await page.getByRole("button", { name: "Ghi thu thực tế" }).click();
  await page.getByLabel("Mã chứng từ thu/chi").fill("THU-01"); await page.getByLabel("Số tiền thực tế (VND)").fill("90071992547409.99");
  await page.getByRole("dialog").getByRole("button", { name: "Lưu dữ liệu" }).click();
  await expect(page.getByText(failure === "generic-500" ? "Không thể hoàn thành thao tác." : "Không đọc được phản hồi từ dữ liệu local. Chưa xác nhận thao tác đã hoàn tất; kiểm tra lại trước khi gửi lại.", { exact: true })).toBeVisible();
  await expect(page.getByLabel("Số tiền thực tế (VND)")).toBeDisabled();
  await expect(page.getByRole("dialog").getByRole("button", { name: "Đóng", exact: true })).toBeDisabled();
  await page.getByRole("button", { name: "Kiểm tra lại cùng yêu cầu" }).click();
  await expect(page.getByText("Chứng từ THU-01", { exact: true })).toBeVisible();
  expect(attempts).toHaveLength(2); expect(attempts[0].request_key).toBe(attempts[1].request_key); expect(attempts[0].amount_vnd).toBe("90071992547409.99"); expect(attempts[0].party_id).toBe(companyId);
  const details = page.getByRole("dialog", { name: "Chứng từ THU-01", exact: true });
  await details.getByRole("button", { name: "Xem lịch sử" }).click(); await details.getByRole("button", { name: "Xem bản 1" }).click(); await expect(details.getByText("Bản lịch sử 1", { exact: true })).toBeVisible();
  await details.getByRole("button", { name: "Sửa thu/chi" }).click();
  const edit = page.getByRole("dialog").filter({ has: page.getByLabel("Mã chứng từ thu/chi") });
  await edit.getByLabel("Số tiền thực tế (VND)").fill("123.45"); await edit.getByRole("button", { name: "Lưu dữ liệu" }).click();
  await expect.poll(() => state.requests.find((item) => item.method === "PUT" && item.resource === "trade-payments")?.body?.expected_version).toBe(1);
  await details.getByRole("button", { name: "Xóa mềm", exact: true }).click(); await page.getByRole("button", { name: "Xóa mềm", exact: true }).last().click();
  await details.getByRole("button", { name: "Khôi phục", exact: true }).click();
  await expect.poll(() => state.requests.find((item) => item.path.endsWith("/restore"))?.body?.expected_version).toBe(3);
});

test("stock posting conflict stays visible and read-only users have no write controls", async ({ page }) => {
  const entry = entity(entryId, "XUAT-01", { trade_id: tradeId, occurred_on: "2026-11-07", entry_type: "issue", status: "draft", lines: [] });
  const state = await fixtures(page, { trades: [trade()], entries: [entry] });
  await page.route(`**/api/v1/records/entries/${entryId}/post`, (route) => route.fulfill({ status: 409, json: { error: { code: "NEGATIVE_STOCK", message: "Không đủ tồn ở ngày 07/11/2026; phiếu liên quan XUAT-01.", field_errors: [] } } }));
  await mount(page, "OutboundPage", `?selected=${tradeId}`);
  await page.getByRole("button", { name: "Ghi vào sổ kho", exact: true }).click(); await page.getByRole("button", { name: "Xác nhận", exact: true }).click();
  await expect(page.getByText("Không đủ tồn ở ngày 07/11/2026; phiếu liên quan XUAT-01.", { exact: true })).toBeVisible(); expect(state.data.entries[0].status).toBe("draft");
  await mount(page, "OutboundPage", `?selected=${tradeId}`, false);
  await expect(page.getByRole("button", { name: "Thêm bán ra" })).toHaveCount(0); await expect(page.getByRole("button", { name: "Ghi thu thực tế" })).toHaveCount(0); await expect(page.getByRole("button", { name: "Tạo phiếu xuất kho nháp" })).toHaveCount(0);
});

test("corrections retain hidden metadata and allow the unchanged inactive historical company", async ({ page }) => {
  const buyer = { ...company(), active: false, contacts: [{ kind: "phone", value: "SYNTHETIC-PHONE", label: "Liên hệ giữ nguyên" }], representative: { name: "Liên hệ tổng hợp", authorization_reference: "SYNTH-AUTH" } };
  const order: Row = { ...trade(), occurred_at: "2026-11-07T08:00:00+07:00", physical_actor: "Người giao tổng hợp" };
  order.lines[0].farm_id = farmId;
  const payment = entity(paymentId, "THU-CU", { trade_id: tradeId, occurred_on: "2026-11-07", occurred_at: "2026-11-07T09:00:00+07:00", physical_actor: "Người thu tổng hợp", party_id: companyId, amount_vnd: "12.34", method: "cash", reference: "SYNTH-REF" });
  const state = await fixtures(page, { parties: [farm(), buyer], trades: [order], "trade-payments": [payment] });
  await mount(page, "OutboundPage", `?selected=${tradeId}`);
  await page.getByRole("button", { name: "Sửa đơn", exact: true }).click();
  await page.getByRole("button", { name: "Tiếp tục nhập đơn bán" }).click();
  await page.getByLabel("Số kg", { exact: true }).fill("2.001");
  await page.getByRole("dialog").getByRole("button", { name: "Lưu dữ liệu" }).click();
  await expect.poll(() => state.requests.find((item) => item.resource === "trades" && item.method === "PUT")?.body).toMatchObject({ occurred_at: order.occurred_at, physical_actor: order.physical_actor, lines: [{ farm_id: farmId }] });
  await page.getByRole("button", { name: "THU-CU", exact: true }).click();
  await page.getByRole("button", { name: "Sửa thu/chi", exact: true }).click();
  const edit = page.getByRole("dialog").filter({ has: page.getByLabel("Mã chứng từ thu/chi") });
  await edit.getByLabel("Số tiền thực tế (VND)").fill("23.45"); await edit.getByRole("button", { name: "Lưu dữ liệu" }).click();
  await expect.poll(() => state.requests.find((item) => item.resource === "trade-payments" && item.method === "PUT")?.body).toMatchObject({ occurred_at: payment.occurred_at, physical_actor: payment.physical_actor, reference: "SYNTH-REF" });
  await mount(page, "CustomersPage", `?selected=${companyId}`);
  await page.getByRole("button", { name: "Sửa dữ liệu", exact: true }).click();
  await page.getByLabel("Tên công ty", { exact: true }).fill("Công ty tổng hợp sửa");
  await page.getByRole("dialog").getByRole("button", { name: "Lưu dữ liệu" }).click();
  await expect.poll(() => state.requests.find((item) => item.resource === "parties" && item.method === "PUT")?.body).toMatchObject({ contacts: [{ label: "Liên hệ giữ nguyên" }], representative: { authorization_reference: "SYNTH-AUTH" } });
  const exact = await page.evaluate(async () => { const path = "/src/features/records/commerceTypes.ts"; const { orderValue } = await import(path); return orderValue([{ quantity_kg: "9007199254740.999", unit_price_vnd: "123.45", bag_count: 0 }]); });
  expect(exact).toBe("1111938747997776.32655");
});
