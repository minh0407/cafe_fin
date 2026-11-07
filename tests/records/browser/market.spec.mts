import { expect, test, type Page } from "../../../frontend/node_modules/@playwright/test/index.mjs";
import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import { randomBytes, randomUUID } from "node:crypto";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { port } from "./settings.mjs";

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../..");
const source = "https://banggianongsan.com/bang-gia-ca-phe/";
const card = (page: Page) => page.locator(".ant-card").filter({ hasText: "Tự động giá nhập nhân xô Robusta Gia Lai" });
const toggle = (page: Page) => page.getByRole("switch", { name: "Tự động lấy giá nhân xô", exact: true });
const check = (page: Page) => page.getByRole("button", { name: "Kiểm tra nguồn ngay", exact: true });
async function withMarket(page: Page, mode: "fresh" | "blocked", run: (host: any) => Promise<void>) {
  const root = await mkdtemp(path.join(tmpdir(), "cafe-fin-records-market-browser-"));
  const key = randomBytes(32).toString("hex");
  let child: ChildProcessWithoutNullStreams | undefined;
  try {
    child = spawn(process.env.CAFE_FIN_RECORDS_TEST_PYTHON ?? path.join(repo, ".venv/Scripts/python.exe"), [path.join(repo, "tests/records/browser/server.py")], { cwd: path.join(repo, "backend"), windowsHide: true, env: { ...process.env, CAFE_FIN_RECORDS_TEST_MARKET: "1", PYTHONUTF8: "1", PYTHONPATH: path.join(repo, "backend") }, stdio: "pipe" });
    const handshake = new Promise<any>((resolve, reject) => {
      let output = "", errors = "";
      const timer = setTimeout(() => reject(new Error(`Market test startup timed out: ${errors}`)), 20000);
      child!.stdout.on("data", (chunk) => { output += String(chunk); if (output.includes("\n")) { clearTimeout(timer); try { resolve(JSON.parse(output.slice(0, output.indexOf("\n")))); } catch { reject(new Error("Invalid market startup receipt")); } } });
      child!.stderr.on("data", (chunk) => { errors += String(chunk); });
      child!.once("error", (error) => { clearTimeout(timer); reject(error); });
      child!.once("exit", () => { clearTimeout(timer); reject(new Error(`Market test exited before startup: ${errors}`)); });
    });
    child.stdin.write(JSON.stringify({ data_root: root, session_token: randomBytes(32).toString("hex"), web_port: port, market_mode: mode, market_control_key: key }) + "\n");
    const boot = await handshake;
    const setup = await fetch(`${boot.api_base}/auth/setup`, { method: "POST", headers: { "X-App-Session": boot.session_token, "Content-Type": "application/json" }, body: JSON.stringify({ username: "market-browser", password: "market-synthetic-browser-password" }) });
    expect(setup.status).toBe(200);
    const auth = await setup.json();
    const headers = { "X-App-Session": boot.session_token, Authorization: `Bearer ${auth.access_token}`, "Content-Type": "application/json" };
    const request = async (endpoint: string, body?: Record<string, unknown>, method = "POST") => {
      const response = await fetch(`${boot.api_base}/${endpoint}`, { headers, method: body ? method : "GET", ...(body ? { body: JSON.stringify(body) } : {}) });
      expect(response.status, `${endpoint} HTTP ${response.status}`).toBe(200);
      return response.json();
    };
    const get = (endpoint: string) => request(`records/${endpoint}`);
    const write = (endpoint: string, body: Record<string, unknown>, method = "POST") => request(`records/${endpoint}`, { ...body, request_key: randomUUID() }, method);
    const control = (action = "stats", extra: Record<string, unknown> = {}) => request("__records_test_market", { control_key: key, action, ...extra });
    const denied = await fetch(`${boot.api_base}/__records_test_market`, { method: "POST", headers, body: JSON.stringify({ control_key: "wrong", action: "stats" }) });
    expect(denied.status).toBe(403);
    const browserErrors: string[] = [];
    page.on("pageerror", (error) => browserErrors.push(error.message));
    const checkPosts: string[] = [];
    page.on("request", (request) => { if (request.url() === `${boot.api_base}/records/market/processed/check` && request.method() === "POST") checkPosts.push(request.postData()!); });
    await page.addInitScript((context) => { Object.assign(window, { recordsTest: context }); }, { boot, auth });
    await run({ boot, get, write, control, checkPosts });
    expect(browserErrors).toEqual([]);
  } finally {
    if (child && child.exitCode === null) {
      const exited = new Promise<void>((resolve) => child!.once("exit", () => resolve()));
      child.stdin.end("shutdown\n");
      await Promise.race([exited, new Promise((resolve) => setTimeout(resolve, 9000))]);
      if (child.exitCode === null) { child.kill(); await Promise.race([exited, new Promise((resolve) => setTimeout(resolve, 2000))]); }
    }
    const absolute = path.resolve(root);
    if (path.dirname(absolute) === path.resolve(tmpdir()) && path.basename(absolute).startsWith("cafe-fin-records-market-browser-")) await rm(absolute, { recursive: true, force: true, maxRetries: 3, retryDelay: 250 });
  }
}

test("real API timer applies current-day market evidence once; UI toggles versions and protects automatic board while saved trade stays frozen", async ({ page }, info) => {
  test.setTimeout(60000);
  await withMarket(page, "fresh", async ({ get, write, control, checkPosts }) => {
    const initial = await get("market/processed"), day = initial.today;
    // Create a previously saved trade from an independent product-specific board.
    const product = await write("products", { code: "MKT-P", name: "Nhân xô kiểm thử" });
    const farm = await write("parties", { code: "MK01", name: "Farm kiểm thử thị trường", profile_kind: "farm" });
    const manual = await write("price-boards", { price_date: day, price_kind: "purchase_processed", product_id: product.id, pricing_method: "grade", grade5_price_vnd: "203000.00" });
    const quote = await get(`price-quote?${new URLSearchParams({ price_date: day, price_kind: "purchase_processed", product_id: product.id, grade: "5" })}`);
    const trade = await write("trades", { code: "MKT-FROZEN", direction: "inbound", occurred_on: day, lines: [{ farm_id: farm.id, product_id: product.id, quantity_kg: "1.000", grade: 5, pricing_mode: "daily", price_kind: "purchase_processed", price_date: day, unit_price_vnd: quote.unit_price_vnd, price_snapshot: quote }] });
    expect(trade.lines[0].price_snapshot.price_board_id).toBe(manual.id);
    await page.goto("/records-test#/records/prices");
    await expect.poll(async () => (await get("market/processed")).status, { timeout: 18000 }).toBe("APPLIED");
    await page.getByRole("button", { name: "Tải lại trạng thái giá tự động", exact: true }).click();
    await expect(card(page).getByText("Đã áp dụng giá đúng ngày", { exact: true })).toBeVisible();
    await expect(card(page).getByText("Grade5 đã áp dụng: 103.000,00 VND/kg", { exact: true })).toBeVisible();
    await expect(card(page).getByRole("cell", { name: "67.578,30", exact: true })).toBeVisible();
    await expect(card(page).getByRole("link")).toHaveAttribute("href", source);
    const applied = await get("market/processed");
    expect(applied.snapshot).toMatchObject({ source_url: source, source_date: day, price_vnd_per_kg: "103000.00", region: "Gia Lai", product: "ROBUSTA_GREEN_BEAN", unit: "VND/kg", board_id: applied.board_id });
    expect((await control()).fetch_count).toBe(1); expect(checkPosts).toHaveLength(0);
    const originalVersion = applied.settings_version;
    await toggle(page).click(); await expect(toggle(page)).not.toBeChecked(); await expect(toggle(page)).toBeEnabled();
    expect((await get("market/processed")).settings_version).toBe(originalVersion + 1);
    await toggle(page).click(); await expect(toggle(page)).toBeChecked(); await expect(toggle(page)).toBeEnabled();
    expect((await get("market/processed")).settings_version).toBe(originalVersion + 2);
    await page.getByRole("button", { name: "Xem bảng giá tự động", exact: true }).click();
    const drawer = page.getByRole("dialog"); await expect(drawer.getByText("Bảng giá tự động chỉ đọc", { exact: true })).toBeVisible();
    await expect(drawer.getByRole("button", { name: "Sửa bảng giá / ngừng áp dụng", exact: true })).toHaveCount(0); await expect(drawer.getByRole("button", { name: "Xóa mềm", exact: true })).toHaveCount(0);
    await expect.poll(async () => (await control()).periodic.runs["records.market"], { timeout: 15000 }).toBeGreaterThanOrEqual(2);
    expect((await control()).fetch_count).toBe(1);
    expect(await get(`trades/${trade.id}`)).toEqual(trade);
    expect((await get(`price-boards/${manual.id}`)).grade5_price_vnd).toBe("203000.00");
    expect((await get("stock-movements")).total).toBe(0);
    await info.attach("market-real-api-proof", { body: JSON.stringify({ source: "synthetic current-day HTML only at test transport boundary", actual_api: true, sqlite: "new file-backed WAL", automatic_timer_runs: (await control()).periodic.runs["records.market"], fetch_count: 1, check_posts_from_browser: checkPosts.length, source_date: day, settings_version: originalVersion + 2, frozen_trade_unchanged: true, no_http_route_mocks: true }), contentType: "application/json" });
  });
});

test("real API blocked then stale source never invents an applied price; cooldown is respected and existing manual board remains editable", async ({ page }, info) => {
  test.setTimeout(60000);
  await withMarket(page, "blocked", async ({ get, write, control, checkPosts }) => {
    await page.goto("/records-test#/records/prices");
    await expect.poll(async () => (await get("market/processed")).status, { timeout: 18000 }).toBe("BLOCKED");
    await page.getByRole("button", { name: "Tải lại trạng thái giá tự động", exact: true }).click();
    await expect(card(page).getByText("Nguồn đang chặn truy cập", { exact: true })).toBeVisible(); await expect(check(page)).toBeDisabled();
    const blocked = await get("market/processed"); expect(blocked.snapshot).toBeNull(); expect(blocked.board_id).toBeNull(); expect(blocked.attempts).toBe(1); expect((await control()).fetch_count).toBe(1);
    await control("source", { mode: "stale", expire_cooldown: true });
    await page.getByRole("button", { name: "Tải lại trạng thái giá tự động", exact: true }).click(); await expect(check(page)).toBeEnabled(); await check(page).click();
    await expect(card(page).getByText("Giá nguồn đã cũ, chưa áp dụng", { exact: true })).toBeVisible(); await expect(check(page)).toBeDisabled();
    await expect(card(page).getByText(/Grade5 đã áp dụng|Đã áp dụng giá đúng ngày/)).toHaveCount(0);
    const stale = await get("market/processed"); expect(stale.snapshot).toBeNull(); expect(stale.board_id).toBeNull(); expect(stale.attempts).toBe(2); expect((await control()).fetch_count).toBe(2); expect(checkPosts).toHaveLength(1);
    const previous = new Date(`${stale.today}T00:00:00Z`); previous.setUTCDate(previous.getUTCDate() - 1);
    const manual = await write("price-boards", { price_date: previous.toISOString().slice(0, 10), price_kind: "purchase_processed", pricing_method: "grade", grade5_price_vnd: "113000.00" });
    expect((await get(`market/processed?price_date=${manual.price_date}`)).status).toBe("EXISTING_BOARD");
    await page.goto(`/records-test#/records/prices?selected=${manual.id}`);
    await page.getByRole("button", { name: "Sửa bảng giá / ngừng áp dụng", exact: true }).click();
    const editor = page.getByRole("dialog", { name: "Sửa bảng giá", exact: true }); await editor.getByLabel("Giá Grade5 (VND/kg)", { exact: true }).fill("114000.00"); await editor.getByRole("button", { name: "Lưu dữ liệu", exact: true }).click();
    await expect(editor).not.toBeVisible();
    expect(await get(`price-boards/${manual.id}`)).toMatchObject({ version: 2, grade5_price_vnd: "114000.00" });
    expect((await control()).fetch_count).toBe(2);
    await info.attach("market-real-api-rejections", { body: JSON.stringify({ actual_api: true, no_http_route_mocks: true, fixture_source_modes: ["blocked challenge HTML", "yesterday dated HTML"], statuses: [blocked.status, stale.status], fetch_count: 2, board_created_for_rejected_source: false, manual_existing_board_edit_version: 2 }), contentType: "application/json" });
  });
});
