import { expect, test, type Page } from "../../../frontend/node_modules/@playwright/test/index.mjs";
import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import { randomBytes, randomUUID } from "node:crypto";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { port } from "./settings.mjs";

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../..");
async function choose(page: Page, label: string, option: string) {
  await page.getByLabel(label, { exact: true }).click();
  await page.locator(".ant-select-dropdown:not(.ant-select-dropdown-hidden)").getByText(option, { exact: true }).click();
}

test("real daily boards auto-price purchase and sale, retain frozen edits, reject stale saves and negative stock", async ({ page }, info) => {
  test.setTimeout(180000);
  const root = await mkdtemp(path.join(tmpdir(), "cafe-fin-records-pricing-browser-"));
  let child: ChildProcessWithoutNullStreams | undefined;
  const browserErrors: string[] = [];
  page.on("pageerror", (error) => browserErrors.push(error.message));
  try {
    child = spawn(process.env.CAFE_FIN_RECORDS_TEST_PYTHON ?? path.join(repo, ".venv/Scripts/python.exe"), [path.join(repo, "tests/records/browser/server.py")], { cwd: path.join(repo, "backend"), windowsHide: true, env: { ...process.env, PYTHONUTF8: "1", PYTHONPATH: path.join(repo, "backend") }, stdio: "pipe" });
    const handshake = new Promise<{ api_base: string; session_token: string; data_root: string; protocol_version: number }>((resolve, reject) => {
      let output = "";
      const timer = setTimeout(() => reject(new Error("Records pricing server startup timeout")), 20000);
      child!.stdout.on("data", (chunk) => { output += String(chunk); if (output.includes("\n")) { clearTimeout(timer); try { resolve(JSON.parse(output.slice(0, output.indexOf("\n")))); } catch { reject(new Error("Invalid test startup receipt")); } } });
      child!.once("error", (error) => { clearTimeout(timer); reject(error); });
      child!.once("exit", () => { clearTimeout(timer); reject(new Error("Records pricing server exited before startup")); });
    });
    child.stdin.write(JSON.stringify({ data_root: root, session_token: randomBytes(32).toString("hex"), web_port: port }) + "\n");
    const boot = await handshake;
    const setup = await fetch(`${boot.api_base}/auth/setup`, { method: "POST", headers: { "X-App-Session": boot.session_token, "Content-Type": "application/json" }, body: JSON.stringify({ username: "pricing-browser", password: "pricing-synthetic-browser-password" }) });
    expect(setup.status).toBe(200);
    const auth = await setup.json();
    const headers = { "X-App-Session": boot.session_token, Authorization: `Bearer ${auth.access_token}`, "Content-Type": "application/json" };
    const get = async (endpoint: string) => {
      const response = await fetch(`${boot.api_base}/records/${endpoint}`, { headers });
      expect(response.status).toBe(200);
      return response.json();
    };
    const write = async (endpoint: string, body: Record<string, unknown>, method = "POST") => {
      const response = await fetch(`${boot.api_base}/records/${endpoint}`, { method, headers, body: JSON.stringify({ ...body, request_key: randomUUID() }) });
      expect(response.status).toBe(200);
      return response.json();
    };
    // Synthetic catalog prerequisites only. Pricing, orders and stock actions below use rendered UI.
    const product = await write("products", { code: "P-PRICE", name: "Cà phê kiểm thử bảng giá" });
    const warehouse = await write("products/warehouses", { code: "W-PRICE", name: "Kho kiểm thử giá" });
    const farm = await write("parties", { code: "F009", name: "Farm kiểm thử giá", profile_kind: "farm" });
    const company = await write("parties", { code: "COMP-PRICE", name: "Công ty kiểm thử giá", profile_kind: "customer_company", tax_code: "SYNTHETIC-PRICE-MST", representative: { name: "Liên hệ tổng hợp" } });
    const observed: { endpoint: string; method: string }[] = [];
    page.on("request", (request) => { if (request.url().startsWith(`${boot.api_base}/records/`)) observed.push({ endpoint: new URL(request.url()).pathname.slice("/api/v1/records/".length), method: request.method() }); });
    // The app permits 15s per API call; this waiter also starts before clicking.
    const responseFor = (endpoint: string, method = "POST", status = 200) => page.waitForResponse((response) => response.url() === `${boot.api_base}/records/${endpoint}` && response.request().method() === method && response.status() === status, { timeout: 20000 });
    await page.addInitScript((context) => { Object.assign(window, { recordsTest: context }); }, { boot, auth });
    await page.goto("/records-test#/records/prices");
    await expect(page.getByRole("heading", { name: "Bảng giá mua / nhập / bán", exact: true })).toBeVisible();
    await page.getByRole("button", { name: "Thêm bảng giá", exact: true }).click();
    await page.getByLabel("Ngày bảng giá", { exact: true }).fill("07/11/2026");
    await page.getByLabel("Giá Grade5 (VND/kg)", { exact: true }).fill("100.05");
    await page.getByRole("button", { name: "Xem trước giá", exact: true }).click();
    await expect(page.getByRole("cell", { name: "81,05", exact: true })).toBeVisible();
    const purchaseSaved = responseFor("price-boards");
    await page.getByRole("dialog", { name: "Thêm bảng giá", exact: true }).getByRole("button", { name: "Lưu dữ liệu", exact: true }).click();
    const purchase = await (await purchaseSaved).json();
    expect(purchase).toMatchObject({ price_kind: "purchase_fresh", product_id: null, pricing_method: "grade", grade5_price_vnd: "100.05" });
    await page.getByRole("dialog", { name: `Bảng giá · ${purchase.code}`, exact: true }).getByRole("button", { name: "Đóng", exact: true }).click();

    await page.getByRole("button", { name: "Thêm bảng giá", exact: true }).click();
    await choose(page, "Nhóm bảng giá", "Bán ra (giá cài riêng)");
    await page.getByLabel("Ngày bảng giá", { exact: true }).fill("07/11/2026");
    await choose(page, "Hàng hóa áp dụng (bắt buộc cho bán)", "P-PRICE — Cà phê kiểm thử bảng giá");
    await page.getByLabel("Giá cố định (VND/kg)", { exact: true }).fill("200.01");
    await page.getByRole("button", { name: "Xem trước giá", exact: true }).click();
    await expect(page.getByText("Giá cố định: 200,01 VND/kg", { exact: true })).toBeVisible();
    const saleBoardSaved = responseFor("price-boards");
    await page.getByRole("dialog", { name: "Thêm bảng giá", exact: true }).getByRole("button", { name: "Lưu dữ liệu", exact: true }).click();
    const saleBoard = await (await saleBoardSaved).json();
    expect(saleBoard).toMatchObject({ price_kind: "sale", product_id: product.id, pricing_method: "flat", flat_price_vnd: "200.01" });
    await expect(page.getByRole("dialog", { name: `Bảng giá · ${saleBoard.code}`, exact: true })).toBeVisible();

    await page.getByRole("dialog", { name: `Bảng giá · ${saleBoard.code}`, exact: true }).getByRole("button", { name: "Đóng", exact: true }).click();
    await page.getByRole("link", { name: "Đầu vào", exact: true }).click();
    await page.getByRole("button", { name: "Thêm mua vào", exact: true }).click();
    await page.getByLabel("Mã / số đơn", { exact: true }).fill("BUY-PRICE");
    await page.getByLabel("Ngày nghiệp vụ", { exact: true }).fill("07/11/2026");
    await choose(page, "Farm dòng 1", `${farm.code} — ${farm.name}`);
    await choose(page, "Hàng hóa (chọn trước khi ghi sổ kho)", "P-PRICE — Cà phê kiểm thử bảng giá");
    await page.getByLabel("Số kg", { exact: true }).fill("10.001");
    await expect(page.getByRole("dialog").getByRole("button", { name: "Lưu dữ liệu", exact: true })).toBeDisabled();
    await choose(page, "Grade", "3");
    await expect(page.getByLabel("Đơn giá (VND/kg)", { exact: true })).toHaveValue("81.05");
    await expect(page.getByLabel("Đơn giá (VND/kg)", { exact: true })).toHaveAttribute("readonly", "");
    const purchaseTradeSaved = responseFor("trades");
    await page.getByRole("dialog").getByRole("button", { name: "Lưu dữ liệu", exact: true }).click();
    const purchaseTrade = await (await purchaseTradeSaved).json();
    expect(purchaseTrade.lines[0]).toMatchObject({ pricing_mode: "daily", unit_price_vnd: "81.05", price_snapshot: { price_board_id: purchase.id, price_board_version: 1, grade: 3 } });
    await expect(page.getByRole("dialog", { name: "Chi tiết mua vào · BUY-PRICE", exact: true })).toBeVisible();

    async function startSale(code: string, quantity: string) {
      await page.goto("/records-test#/records/outbound");
      await page.getByRole("button", { name: "Thêm bán ra", exact: true }).click();
      await choose(page, "Chọn công ty khách hàng", `${company.code} — ${company.name}`);
      await page.getByRole("button", { name: "Tiếp tục nhập đơn bán", exact: true }).click();
      await page.getByLabel("Mã / số đơn", { exact: true }).fill(code);
      await page.getByLabel("Ngày nghiệp vụ", { exact: true }).fill("07/11/2026");
      await choose(page, "Hàng hóa", "P-PRICE — Cà phê kiểm thử bảng giá");
      await page.getByLabel("Số kg", { exact: true }).fill(quantity);
    }
    await startSale("SALE-PRICE", "3.001");
    // Flat SALE has no Grade requirement; only kg is entered after selecting company/product.
    await expect(page.getByLabel("Đơn giá (VND/kg)", { exact: true })).toHaveValue("200.01");
    await expect(page.getByText("Thành tiền dòng (VND): 600,23001", { exact: true })).toBeVisible();
    const saleSaved = responseFor("trades");
    await page.getByRole("dialog").getByRole("button", { name: "Lưu dữ liệu", exact: true }).click();
    const sale = await (await saleSaved).json();
    expect(sale.lines[0]).toMatchObject({ pricing_mode: "daily", grade: null, unit_price_vnd: "200.01", price_kind: "sale", price_snapshot: { price_board_id: saleBoard.id, price_board_version: 1 } });
    await expect(page.getByRole("dialog", { name: "Chi tiết bán ra · SALE-PRICE", exact: true })).toBeVisible();
    expect((await get("stock-movements")).total).toBe(0);

    await page.goto(`/records-test#/records/prices?selected=${saleBoard.id}`);
    await page.getByRole("button", { name: "Sửa bảng giá / ngừng áp dụng", exact: true }).click();
    await page.getByLabel("Giá cố định (VND/kg)", { exact: true }).fill("300.00");
    const boardUpdated = responseFor(`price-boards/${saleBoard.id}`, "PUT");
    await page.getByRole("dialog", { name: "Sửa bảng giá", exact: true }).getByRole("button", { name: "Lưu dữ liệu", exact: true }).click();
    const newerBoard = await (await boardUpdated).json();
    expect(newerBoard.version).toBe(2);
    await expect(page.getByRole("dialog", { name: "Sửa bảng giá", exact: true })).not.toBeVisible();
    await page.goto(`/records-test#/records/outbound?selected=${sale.id}`);
    await page.getByRole("button", { name: "Sửa đơn", exact: true }).click();
    await page.getByRole("button", { name: "Tiếp tục nhập đơn bán", exact: true }).click();
    await expect(page.getByLabel("Đơn giá (VND/kg)", { exact: true })).toHaveValue("200.01");
    const lookupsBeforeKg = observed.filter((request) => request.endpoint === "price-quote").length;
    await page.getByLabel("Số kg", { exact: true }).fill("4.001");
    await expect(page.getByText("Thành tiền dòng (VND): 800,24001", { exact: true })).toBeVisible();
    const saleUpdated = responseFor(`trades/${sale.id}`, "PUT");
    await page.getByRole("dialog", { name: "Sửa hồ sơ bán ra", exact: true }).getByRole("button", { name: "Lưu dữ liệu", exact: true }).click();
    const updated = await (await saleUpdated).json();
    expect(updated.lines[0].price_snapshot).toEqual(sale.lines[0].price_snapshot);
    expect(updated.lines[0]).toMatchObject({ quantity_kg: "4.001", unit_price_vnd: "200.01" });
    expect(observed.filter((request) => request.endpoint === "price-quote")).toHaveLength(lookupsBeforeKg);

    await page.getByRole("button", { name: "Tạo phiếu xuất kho nháp", exact: true }).click();
    const stockModal = page.getByRole("dialog", { name: "Phiếu kho liên kết đơn", exact: true });
    await stockModal.getByLabel("Mã / số phiếu", { exact: true }).fill("ISSUE-PRICE");
    await choose(page, "Vị trí / kho", `${warehouse.code} — ${warehouse.name}`);
    const stockSaved = responseFor("entries");
    await stockModal.getByRole("button", { name: "Lưu dữ liệu", exact: true }).click();
    const stock = await (await stockSaved).json();
    await page.getByRole("dialog", { name: "Chi tiết ISSUE-PRICE", exact: true }).getByRole("button", { name: "Đóng", exact: true }).click();
    await page.getByRole("row").filter({ has: page.getByRole("button", { name: "ISSUE-PRICE", exact: true }) }).getByRole("button", { name: "Ghi vào sổ kho", exact: true }).click();
    const blockedStock = responseFor(`entries/${stock.id}/post`, "POST", 409);
    await page.getByRole("button", { name: "Xác nhận", exact: true }).click();
    expect((await (await blockedStock).json()).error.code).toBe("STOCK_NEGATIVE");
    expect((await get("stock-movements")).total).toBe(0);
    expect((await get(`entries/${stock.id}`)).status).toBe("draft");

    await startSale("SALE-STALE", "1.001");
    await expect(page.getByLabel("Đơn giá (VND/kg)", { exact: true })).toHaveValue("300.00");
    // A separate real writer changes the board after the operator viewed this quote.
    const { id, version, created_at, created_by, updated_at, updated_by, recorded_at, deleted_at, order_key, ...editable } = newerBoard;
    void created_at; void created_by; void updated_at; void updated_by; void recorded_at; void deleted_at; void order_key;
    await write(`price-boards/${id}`, { ...editable, expected_version: version, flat_price_vnd: "400.00" }, "PUT");
    const staleSave = responseFor("trades", "POST", 409);
    await page.getByRole("dialog").getByRole("button", { name: "Lưu dữ liệu", exact: true }).click();
    expect((await (await staleSave).json()).error.code).toBe("PRICE_CHANGED");
    await expect(page.getByRole("dialog", { name: "Thêm hồ sơ bán ra", exact: true })).toBeVisible();
    expect((await get("trades")).total).toBe(2);
    await page.getByRole("button", { name: "Lấy lại giá mới", exact: true }).click();
    await expect(page.getByLabel("Đơn giá (VND/kg)", { exact: true })).toHaveValue("400.00");
    const refreshedSave = responseFor("trades");
    await page.getByRole("dialog").getByRole("button", { name: "Lưu dữ liệu", exact: true }).click();
    const refreshed = await (await refreshedSave).json();
    expect(refreshed.lines[0]).toMatchObject({ unit_price_vnd: "400.00", price_snapshot: { price_board_version: 3 } });
    expect(browserErrors).toEqual([]);
    await page.screenshot({ path: info.outputPath("pricing-real-api-frozen-source.png"), fullPage: true, animations: "disabled" });
    await info.attach("pricing-verification", { body: JSON.stringify({ mode: "real Chromium + React + authenticated HTTP + new SQLite WAL", purchase_grade3_vnd: "81.05", sale_configured_vnd: "200.01", retained_sale_price_vnd: updated.lines[0].unit_price_vnd, retained_board_version: updated.lines[0].price_snapshot.price_board_version, latest_board_version: 3, stale_save: "PRICE_CHANGED409", stock_guard: "STOCK_NEGATIVE409", no_api_mocks: true, native_tauri: "NOT RUN" }, null, 2), contentType: "application/json" });
  } finally {
    if (child && child.exitCode === null) {
      const exited = new Promise<void>((resolve) => child!.once("exit", () => resolve()));
      child.stdin.end("shutdown\n");
      await Promise.race([exited, new Promise((resolve) => setTimeout(resolve, 9000))]);
      if (child.exitCode === null) { child.kill(); await Promise.race([exited, new Promise((resolve) => setTimeout(resolve, 2000))]); }
    }
    const absolute = path.resolve(root);
    if (path.dirname(absolute) === path.resolve(tmpdir()) && path.basename(absolute).startsWith("cafe-fin-records-pricing-browser-")) await rm(absolute, { recursive: true, force: true, maxRetries: 3, retryDelay: 250 });
  }
});
