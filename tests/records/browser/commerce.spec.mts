import { expect, test, type Locator, type Page } from "../../../frontend/node_modules/@playwright/test/index.mjs";
import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import { randomBytes } from "node:crypto";
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
async function saveModal(modal: Locator) {
  await modal.getByRole("button", { name: "Lưu dữ liệu", exact: true }).click();
}

test("real API farm purchase and company sale keep draft stock, shipment limits and actual payments separate", async ({ page }, info) => {
  test.setTimeout(180000);
  const root = await mkdtemp(path.join(tmpdir(), "cafe-fin-records-commerce-browser-"));
  let child: ChildProcessWithoutNullStreams | undefined;
  const browserErrors: string[] = [];
  page.on("pageerror", (error) => browserErrors.push(error.message));
  try {
    child = spawn(process.env.CAFE_FIN_RECORDS_TEST_PYTHON ?? path.join(repo, ".venv/Scripts/python.exe"), [path.join(repo, "tests/records/browser/server.py")], { cwd: path.join(repo, "backend"), windowsHide: true, env: { ...process.env, PYTHONUTF8: "1", PYTHONPATH: path.join(repo, "backend") }, stdio: "pipe" });
    const handshake = new Promise<{ api_base: string; session_token: string; data_root: string; protocol_version: number }>((resolve, reject) => {
      let output = "";
      const timer = setTimeout(() => reject(new Error("Records commerce server startup timeout")), 20000);
      child!.stdout.on("data", (chunk) => { output += String(chunk); if (output.includes("\n")) { clearTimeout(timer); try { resolve(JSON.parse(output.slice(0, output.indexOf("\n")))); } catch { reject(new Error("Invalid test startup receipt")); } } });
      child!.once("error", (error) => { clearTimeout(timer); reject(error); });
      child!.once("exit", () => { clearTimeout(timer); reject(new Error("Records commerce server exited before startup")); });
    });
    child.stdin.write(JSON.stringify({ data_root: root, session_token: randomBytes(32).toString("hex"), web_port: port }) + "\n");
    const boot = await handshake;
    const setup = await fetch(`${boot.api_base}/auth/setup`, { method: "POST", headers: { "X-App-Session": boot.session_token, "Content-Type": "application/json" }, body: JSON.stringify({ username: "commerce-browser", password: "commerce-synthetic-browser-password" }) });
    expect(setup.status).toBe(200);
    const auth = await setup.json();
    const headers = { "X-App-Session": boot.session_token, Authorization: `Bearer ${auth.access_token}` };
    const get = async (endpoint: string) => {
      const response = await fetch(`${boot.api_base}/records/${endpoint}`, { headers });
      expect(response.status).toBe(200);
      return response.json();
    };
    const writes: { endpoint: string; method: string; body: Record<string, unknown> }[] = [];
    page.on("request", (request) => {
      if (request.url().startsWith(`${boot.api_base}/records/`) && ["POST", "PUT", "DELETE"].includes(request.method())) writes.push({ endpoint: new URL(request.url()).pathname.slice("/api/v1/records/".length), method: request.method(), body: request.postDataJSON() });
    });
    const writeResponse = (endpoint: string, status = 200, method = "POST") => page.waitForResponse((response) => response.url() === `${boot.api_base}/records/${endpoint}` && response.request().method() === method && response.status() === status);
    await page.addInitScript((context) => { Object.assign(window, { recordsTest: context }); }, { boot, auth });
    await page.goto("/records-test#/records");
    // Setup catalogs through the rendered legacy tool; every business write uses UI.
    for (const master of [{ tab: "Vị trí / kho", code: "W-COM", name: "Kho tổng hợp thương mại" }, { tab: "Hàng hóa", code: "P-COM", name: "Cà phê tổng hợp thương mại" }]) {
      await page.getByRole("tab", { name: master.tab, exact: true }).click();
      await page.getByRole("button", { name: "Thêm mới", exact: true }).click();
      await page.getByLabel("Mã / số phiếu", { exact: true }).fill(master.code);
      await page.getByLabel("Tên", { exact: true }).fill(master.name);
      await saveModal(page.getByRole("dialog"));
      await expect(page.getByText(`Đã lưu ${master.code}`, { exact: true })).toBeVisible();
      await page.getByRole("dialog").getByRole("button", { name: "Đóng", exact: true }).click();
    }
    await page.goto("/records-test#/records/farms");
    await expect(page.getByRole("heading", { name: "Farm", exact: true })).toBeVisible();
    await page.getByRole("button", { name: "Thêm Farm", exact: true }).click();
    await page.getByLabel("Mã Farm (4 ký tự)", { exact: true }).fill("00a1");
    await page.getByLabel("Tên Farm", { exact: true }).fill("Farm tổng hợp 00A1");
    await page.getByLabel("Tên chủ Farm", { exact: true }).fill("Chủ Farm tổng hợp");
    await page.getByRole("button", { name: "Thêm lô trồng", exact: true }).click();
    await page.getByLabel("Diện tích (ha)", { exact: true }).fill("1.234");
    // An unnamed plot remains optional; no synthetic plot code is invented by UI.
    const farmSaved = writeResponse("parties");
    await saveModal(page.getByRole("dialog"));
    const farm = await (await farmSaved).json();
    expect(farm.code).toBe("00A1");
    expect(farm.farm.plots[0]).toMatchObject({ plot_code: null, area_ha: "1.234" });
    await expect(page.getByText("Chi tiết 00A1", { exact: true })).toBeVisible();
    await page.getByRole("dialog", { name: "Chi tiết 00A1", exact: true }).getByRole("button", { name: "Đóng", exact: true }).click();

    await page.getByRole("link", { name: "Đầu vào", exact: true }).click();
    await page.getByRole("button", { name: "Thêm mua vào", exact: true }).click();
    await page.getByLabel("Mã / số đơn", { exact: true }).fill("BUY-COM");
    await page.getByLabel("Ngày nghiệp vụ", { exact: true }).fill("07/11/2026");
    await choose(page, "Farm dòng 1", "00A1 — Farm tổng hợp 00A1");
    await choose(page, "Hàng hóa (chọn trước khi ghi sổ kho)", "P-COM — Cà phê tổng hợp thương mại");
    await page.getByLabel("Số kg", { exact: true }).fill("10.001");
    await page.getByLabel("Đơn giá (VND/kg)", { exact: true }).fill("100.25");
    const inboundSaved = writeResponse("trades");
    await saveModal(page.getByRole("dialog"));
    const inbound = await (await inboundSaved).json();
    expect(inbound.direction).toBe("inbound");
    expect(inbound.lines[0].farm_id).toBe(farm.id);
    expect((await get("stock-movements")).total).toBe(0);
    await expect(page.getByText("Chi tiết mua vào · BUY-COM", { exact: true })).toBeVisible();

    async function stockDraft(code: string, quantity: string, incoming: boolean) {
      await page.getByRole("button", { name: incoming ? "Tạo phiếu nhập kho nháp" : "Tạo phiếu xuất kho nháp", exact: true }).click();
      const modal = page.getByRole("dialog", { name: "Phiếu kho liên kết đơn", exact: true });
      await modal.getByLabel("Mã / số phiếu", { exact: true }).fill(code);
      await choose(page, "Vị trí / kho", "W-COM — Kho tổng hợp thương mại");
      await modal.getByLabel("Số kg", { exact: true }).fill(quantity);
      const saved = writeResponse("entries");
      await saveModal(modal);
      const entry = await (await saved).json();
      expect(entry.status).toBe("draft");
      await page.getByRole("dialog", { name: `Chi tiết ${code}`, exact: true }).getByRole("button", { name: "Đóng", exact: true }).click();
      return entry;
    }
    async function postStock(code: string, id: string, status = 200) {
      const row = page.getByRole("row").filter({ has: page.getByRole("button", { name: code, exact: true }) });
      await row.getByRole("button", { name: "Ghi vào sổ kho", exact: true }).click();
      const response = writeResponse(`entries/${id}/post`, status);
      await page.getByRole("button", { name: "Xác nhận", exact: true }).click();
      return (await response).json();
    }
    const receipt = await stockDraft("RECEIPT-COM", "10.001", true);
    expect(receipt.trade_id).toBe(inbound.id);
    expect((await get("stock-movements")).total).toBe(0);
    await postStock(receipt.code, receipt.id);
    await expect(page.getByRole("row").filter({ has: page.getByRole("button", { name: receipt.code, exact: true }) }).getByText("Đã ghi sổ", { exact: true })).toBeVisible();
    expect((await get("stock-movements")).total).toBe(1);
    const excess = await stockDraft("RECEIPT-OVER", "0.001", true);
    const rejected = await postStock(excess.code, excess.id, 409);
    expect(rejected.error.code).toBe("TRADE_CONFLICT");
    await expect(page.getByRole("alert").filter({ hasText: "Tổng kg giao nhận vượt" })).toBeVisible();
    expect((await get(`entries/${excess.id}`)).status).toBe("draft");
    expect((await get("stock-movements")).total).toBe(1);
    await page.screenshot({ path: info.outputPath("commerce-real-api-cap-error.png"), fullPage: true, animations: "disabled" });
    await page.getByRole("dialog", { name: "Chi tiết mua vào · BUY-COM", exact: true }).getByRole("button", { name: "Đóng", exact: true }).click();

    await page.getByRole("link", { name: "Công ty khách hàng", exact: true }).click();
    await page.getByRole("button", { name: "Thêm Công ty khách hàng", exact: true }).click();
    await page.getByLabel("Mã công ty", { exact: true }).fill("COMP-COM");
    await page.getByLabel("Tên công ty", { exact: true }).fill("Công ty tổng hợp thương mại");
    const incompleteSaved = writeResponse("parties");
    await saveModal(page.getByRole("dialog"));
    const incomplete = await (await incompleteSaved).json();
    expect(incomplete.tax_code).toBeNull();
    await page.getByRole("dialog", { name: "Chi tiết COMP-COM", exact: true }).getByRole("button", { name: "Đóng", exact: true }).click();
    await page.getByRole("link", { name: "Đầu ra", exact: true }).click();
    await page.getByRole("button", { name: "Thêm bán ra", exact: true }).click();
    await choose(page, "Chọn công ty khách hàng", "COMP-COM — Công ty tổng hợp thương mại");
    await expect(page.getByRole("button", { name: "Tiếp tục nhập đơn bán", exact: true })).toBeDisabled();
    await expect(page.getByLabel("Mã / số đơn", { exact: true })).toHaveCount(0);
    expect(writes.filter((request) => request.endpoint === "trades")).toHaveLength(1);
    await page.getByRole("button", { name: "Hoàn tất thông tin công ty", exact: true }).click();
    const companyModal = page.getByRole("dialog", { name: "Sửa công ty khách hàng", exact: true });
    await companyModal.getByLabel("Mã số thuế", { exact: true }).fill("SYNTHETIC-MST");
    await companyModal.getByLabel("Người liên hệ / đại diện", { exact: true }).fill("Liên hệ tổng hợp");
    const companySaved = writeResponse(`parties/${incomplete.id}`, 200, "PUT");
    await saveModal(companyModal);
    const company = await (await companySaved).json();
    await expect(page.getByRole("button", { name: "Tiếp tục nhập đơn bán", exact: true })).toBeEnabled();
    await page.getByRole("button", { name: "Tiếp tục nhập đơn bán", exact: true }).click();
    await page.getByLabel("Mã / số đơn", { exact: true }).fill("SALE-COM");
    await page.getByLabel("Ngày nghiệp vụ", { exact: true }).fill("07/11/2026");
    await choose(page, "Hàng hóa", "P-COM — Cà phê tổng hợp thương mại");
    await page.getByLabel("Số kg", { exact: true }).fill("3.001");
    await page.getByLabel("Đơn giá (VND/kg)", { exact: true }).fill("200.01");
    const outboundSaved = writeResponse("trades");
    await saveModal(page.getByRole("dialog"));
    const outbound = await (await outboundSaved).json();
    expect(outbound).toMatchObject({ direction: "outbound", party_id: company.id });
    expect((await get("stock-movements")).total).toBe(1);
    const issue = await stockDraft("ISSUE-COM", "3.001", false);
    expect(issue).toMatchObject({ trade_id: outbound.id, party_id: company.id, entry_type: "issue" });
    await postStock(issue.code, issue.id);
    expect((await get("stock-balances?from_on=2026-11-07&through_on=2026-11-07")).items[0].closing_kg).toBe("7.000");
    await page.getByRole("button", { name: "Ghi thu thực tế", exact: true }).click();
    await page.getByLabel("Mã chứng từ thu/chi", { exact: true }).fill("PAY-COM");
    await page.getByLabel("Ngày thu/chi", { exact: true }).fill("07/11/2026");
    await page.getByLabel("Số tiền thực tế (VND)", { exact: true }).fill("123.45");
    const paymentSaved = writeResponse("trade-payments");
    await saveModal(page.getByRole("dialog", { name: "Ghi thu thực tế", exact: true }));
    const payment = await (await paymentSaved).json();
    expect(payment).toMatchObject({ amount_vnd: "123.45", party_id: company.id, trade_id: outbound.id });
    const dashboard = await get("records-dashboard?from_on=2026-11-07&through_on=2026-11-07");
    expect(dashboard.period).toMatchObject({ inbound_kg: "10.001", outbound_kg: "3.001", cash_in_vnd: "123.45", cash_out_vnd: "0.00", sales_order_value_vnd: "600.23001" });
    expect(dashboard.inventory.items[0].closing_kg).toBe("7.000");
    expect(writes.find((request) => request.endpoint === "trades" && request.body.direction === "inbound")?.body.lines).toEqual([expect.objectContaining({ farm_id: farm.id, quantity_kg: "10.001", unit_price_vnd: "100.25" })]);
    expect(writes.filter((request) => request.endpoint === "trade-payments")).toHaveLength(1);
    expect(browserErrors).toEqual([]);
    await info.attach("commerce-verification", { body: JSON.stringify({ mode: "real Chromium + rendered React + HTTP + new file-backed SQLite WAL", farm_code: farm.code, purchase_id: inbound.id, sale_id: outbound.id, payment_vnd: payment.amount_vnd, closing_kg: "7.000", cap_rejection: rejected.error.code, no_api_mocks: true, native_tauri: "NOT RUN" }, null, 2), contentType: "application/json" });
  } finally {
    if (child && child.exitCode === null) {
      const exited = new Promise<void>((resolve) => child!.once("exit", () => resolve()));
      child.stdin.end("shutdown\n");
      await Promise.race([exited, new Promise((resolve) => setTimeout(resolve, 9000))]);
      if (child.exitCode === null) { child.kill(); await Promise.race([exited, new Promise((resolve) => setTimeout(resolve, 2000))]); }
    }
    const absolute = path.resolve(root);
    if (path.dirname(absolute) === path.resolve(tmpdir()) && path.basename(absolute).startsWith("cafe-fin-records-commerce-browser-")) await rm(absolute, { recursive: true, force: true, maxRetries: 3, retryDelay: 250 });
  }
});
