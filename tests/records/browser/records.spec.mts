import { expect, test, type Page } from "../../../frontend/node_modules/@playwright/test/index.mjs";
import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { randomBytes } from "node:crypto";

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../..");
async function select(page: Page, label: string, option: string) {
  await page.getByLabel(label, { exact: true }).click();
  await page.locator(".ant-select-dropdown:not(.ant-select-dropdown-hidden)").getByText(option, { exact: true }).click();
}
async function save(page: Page, code: string) {
  await page.getByRole("button", { name: "Lưu dữ liệu", exact: true }).click();
  await expect(page.getByRole("dialog").getByText(`Đã lưu ${code}`, { exact: true })).toBeVisible();
}
async function closeDetail(page: Page) {
  await page.getByRole("dialog").getByRole("button", { name: "Đóng", exact: true }).click();
}

test("desktop real-API records flow, immutable weighing history and stock rejection", async ({ page }, info) => {
  const root = await mkdtemp(path.join(tmpdir(), "cafe-fin-records-browser-"));
  let child: ChildProcessWithoutNullStreams | undefined;
  const browserErrors: string[] = [];
  page.on("pageerror", (error) => browserErrors.push(error.message));
  try {
    child = spawn(path.join(repo, ".venv/Scripts/python.exe"), [path.join(repo, "tests/records/browser/server.py")], { cwd: path.join(repo, "backend"), windowsHide: true, env: { ...process.env, PYTHONUTF8: "1", PYTHONPATH: path.join(repo, "backend") }, stdio: "pipe" });
    const handshake = new Promise<{ api_base: string; session_token: string; data_root: string; protocol_version: number }>((resolve, reject) => {
      let output = "";
      const timer = setTimeout(() => reject(new Error("Records server startup timeout")), 20000);
      child!.stdout.on("data", (chunk) => { output += String(chunk); if (output.includes("\n")) { clearTimeout(timer); try { resolve(JSON.parse(output.slice(0, output.indexOf("\n")))); } catch { reject(new Error("Invalid test startup receipt")); } } });
      child!.once("error", (error) => { clearTimeout(timer); reject(error); });
      child!.once("exit", () => { clearTimeout(timer); reject(new Error("Records server exited before startup")); });
    });
    child.stdin.write(JSON.stringify({ data_root: root, session_token: randomBytes(32).toString("hex") }) + "\n");
    const boot = await handshake;
    const setup = await fetch(`${boot.api_base}/auth/setup`, { method: "POST", headers: { "X-App-Session": boot.session_token, "Content-Type": "application/json" }, body: JSON.stringify({ username: "records-browser", password: "records-synthetic-browser-password" }) });
    expect(setup.status).toBe(200);
    const auth = await setup.json();
    const headers = { "X-App-Session": boot.session_token, Authorization: `Bearer ${auth.access_token}` };
    const get = async (endpoint: string) => {
      const response = await fetch(`${boot.api_base}/records/${endpoint}`, { headers });
      expect(response.status).toBe(200);
      return response.json();
    };
    await page.addInitScript((context) => { Object.assign(window, { recordsTest: context }); }, { boot, auth });
    await page.goto("/records-test#/records");
    await expect(page.getByRole("heading", { name: "Ghi nhận cà phê" })).toBeVisible();

    // All business mutations use the actual React controls and actual HTTP handlers.
    for (const master of [{ tab: "Đối tác", code: "DT-UI", name: "Đối tác tổng hợp" }, { tab: "Vị trí / kho", code: "KHO-UI", name: "Kho tổng hợp" }, { tab: "Hàng hóa", code: "CP-UI", name: "Cà phê tổng hợp" }]) {
      await page.getByRole("tab", { name: master.tab, exact: true }).click();
      await page.getByRole("button", { name: "Thêm mới", exact: true }).click();
      await page.getByLabel("Mã / số phiếu", { exact: true }).fill(master.code);
      await page.getByLabel("Tên", { exact: true }).fill(master.name);
      if (master.tab === "Đối tác") { await select(page, "Vai trò (có thể chọn nhiều)", "Khách mua"); await page.keyboard.press("Escape"); }
      await save(page, master.code); await closeDetail(page);
    }
    await page.getByRole("tab", { name: "Phiếu cân tay", exact: true }).click();
    await page.getByRole("button", { name: "Thêm mới", exact: true }).click();
    await page.getByLabel("Mã / số phiếu", { exact: true }).fill("CAN-UI");
    await select(page, "Đối tác (tùy chọn)", "DT-UI — Đối tác tổng hợp");
    await select(page, "Hàng hóa (tùy chọn)", "CP-UI — Cà phê tổng hợp");
    await page.getByLabel("Kg tịnh trực tiếp", { exact: true }).fill("100.125");
    await page.getByLabel("Kg tịnh trực tiếp", { exact: true }).press("Control+Enter");
    await expect(page.getByRole("dialog").getByText("Đã lưu CAN-UI", { exact: true })).toBeVisible();
    const weighing = (await get("weighings")).items[0];
    expect(weighing.lines[0]).toMatchObject({ gross_kg: null, tare_kg: null, net_kg: "100.125", quantity_source: "direct_net" });
    const balancePath = `stock-balances?from_on=${weighing.occurred_on}&through_on=${weighing.occurred_on}`;
    expect((await get(balancePath)).items).toEqual([]);
    await page.getByRole("button", { name: "Lập phiếu nhập từ cân", exact: true }).click();
    await page.getByLabel("Mã / số phiếu", { exact: true }).fill("PN-UI");
    await select(page, "Trạng thái dữ liệu", "Đã ghi — cập nhật sổ kho khi lưu");
    await select(page, "Vị trí / kho", "KHO-UI — Kho tổng hợp");
    await expect(page.getByLabel("Số kg", { exact: true })).toHaveValue("100.125");
    await save(page, "PN-UI"); await closeDetail(page);

    async function issue(code: string, quantity: string) {
      await page.getByRole("button", { name: "Thêm mới", exact: true }).click();
      await page.getByLabel("Mã / số phiếu", { exact: true }).fill(code);
      await select(page, "Loại phiếu hàng", "Xuất hàng");
      await select(page, "Trạng thái dữ liệu", "Đã ghi — cập nhật sổ kho khi lưu");
      await select(page, "Hàng hóa", "CP-UI — Cà phê tổng hợp");
      await select(page, "Vị trí / kho", "KHO-UI — Kho tổng hợp");
      await page.getByLabel("Số kg", { exact: true }).fill(quantity);
    }
    await issue("PX-UI", "10.001"); await save(page, "PX-UI"); await closeDetail(page);
    await page.getByRole("tab", { name: "Tổng hợp tồn", exact: true }).click();
    await expect(page.getByRole("cell", { name: "90,124", exact: true })).toBeVisible();
    const inventoryV2 = await get(balancePath);
    expect(inventoryV2.items[0].closing_kg).toBe("90.124");
    expect(inventoryV2.breakdown_version).toBe(1);
    expect(inventoryV2.movement_breakdown).toEqual([{
      product_id: weighing.lines[0].product_id,
      warehouse_id: inventoryV2.items[0].warehouse_id,
      purchased_kg: "100.125",
      sold_kg: "10.001",
      production_input_kg: "0.000",
      production_output_kg: "0.000",
      transfer_in_kg: "0.000",
      transfer_out_kg: "0.000",
      adjustment_in_kg: "0.000",
      adjustment_out_kg: "0.000",
    }]);
    const classification = page.getByRole("region", { name: "Phân loại biến động kho" });
    for (const label of ["Mua vào", "Bán ra", "Nguyên liệu tiêu thụ", "Thành phẩm thu được", "Chuyển vào", "Chuyển ra", "Điều chỉnh tăng", "Điều chỉnh giảm"]) {
      await expect(classification.getByRole("columnheader", { name: label, exact: true })).toBeVisible();
    }
    await expect(classification.getByRole("cell", { name: "100,125", exact: true })).toBeVisible();
    await expect(classification.getByRole("cell", { name: "10,001", exact: true })).toBeVisible();
    await expect(page.locator(".ant-spin-blur")).toHaveCount(0);
    await expect(page.getByRole("tab", { name: "Tổng hợp tồn", exact: true })).toHaveAttribute("aria-selected", "true");
    await page.screenshot({ path: info.outputPath("records-real-api-inventory.png"), fullPage: true, animations: "disabled" });
    await page.getByRole("tab", { name: "Phiếu hàng", exact: true }).click();
    await issue("PX-OVERDRAW", "1000.000");
    await page.getByRole("button", { name: "Lưu dữ liệu", exact: true }).click();
    await expect(page.getByRole("alert").filter({ hasText: /tồn|Tồn/ }).first()).toBeVisible();
    expect((await get("entries")).total).toBe(2);
    expect((await get(balancePath)).items[0].closing_kg).toBe("90.124");
    await page.getByRole("dialog").locator(".ant-modal-footer").getByRole("button", { name: "Đóng", exact: true }).click();
    await page.getByRole("tab", { name: "Phiếu cân tay", exact: true }).click();
    await page.getByRole("row").filter({ hasText: "CAN-UI" }).getByRole("button", { name: "Sửa", exact: true }).click();
    await page.getByLabel("Kg tịnh trực tiếp", { exact: true }).fill("101.125");
    await save(page, "CAN-UI");
    await page.getByRole("button", { name: "Xem lịch sử", exact: true }).click();
    await expect(page.getByRole("button", { name: "Xem bản 2", exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "Xem bản 1", exact: true })).toBeVisible();
    expect((await get(balancePath)).items[0].closing_kg).toBe("90.124");
    await closeDetail(page);
    // Repeated HTTP conflict keeps the request key. Changing the payload gets a new key.
    // No response or domain API is mocked, intercepted or replaced.
    await page.getByRole("tab", { name: "Phiếu hàng", exact: true }).click();
    await page.getByRole("button", { name: "Thêm mới", exact: true }).click();
    await page.getByLabel("Mã / số phiếu", { exact: true }).fill("PN-UI");
    await select(page, "Liên kết phiếu cân (tùy chọn)", "CAN-UI");
    const writes: Record<string, unknown>[] = [];
    page.on("request", (request) => { if (request.method() === "POST" && request.url() === `${boot.api_base}/records/entries`) { writes.push(request.postDataJSON()); console.log("Retry proof request", writes.length); } });
    page.on("response", (response) => { if (response.request().method() === "POST" && response.url() === `${boot.api_base}/records/entries`) console.log("Retry proof response", response.status()); });
    const conflict = () => page.waitForResponse((response) => response.url() === `${boot.api_base}/records/entries` && response.request().method() === "POST" && response.status() === 409, { timeout: 10000 });
    const firstConflict = conflict();
    await page.getByRole("button", { name: "Lưu dữ liệu", exact: true }).click();
    await firstConflict;
    await expect(page.getByRole("alert").filter({ hasText: "Mã hồ sơ đã tồn tại" })).toBeVisible();
    await expect(page.locator(".ant-modal-footer .ant-btn-loading")).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Lưu dữ liệu", exact: true })).toHaveAttribute("aria-busy", "false");
    const secondConflict = conflict();
    await page.getByRole("button", { name: "Lưu dữ liệu", exact: true }).click();
    await secondConflict;
    await expect(page.locator(".ant-modal-footer .ant-btn-loading")).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Lưu dữ liệu", exact: true })).toHaveAttribute("aria-busy", "false");
    expect(writes).toHaveLength(2);
    expect(writes[0].request_key).toBe(writes[1].request_key);
    await page.getByLabel("Mã / số phiếu", { exact: true }).fill("PN-DRAFT-RETRY");
    await save(page, "PN-DRAFT-RETRY");
    expect(writes).toHaveLength(3);
    expect(writes[2].request_key).not.toBe(writes[1].request_key);
    expect(writes[2].weighing_id).toBe(weighing.id);
    expect(writes[2].lines).toEqual([{ direction: "in", product_id: null, warehouse_id: null, quantity_kg: null }]);
    expect((await get(balancePath)).items[0].closing_kg).toBe("90.124");
    expect(browserErrors).toEqual([]);
    await info.attach("verification", { body: JSON.stringify({ mode: "real Chromium + React + HTTP + file-backed SQLite WAL", received_kg: "100.125", issued_kg: "10.001", closing_kg: "90.124", weighing_stock_effect: "none", overdraw: "rejected atomically", immutable_weighing_revisions: 2, native_tauri: "NOT RUN" }, null, 2), contentType: "application/json" });
  } finally {
    if (child && child.exitCode === null) {
      const exited = new Promise<void>((resolve) => child!.once("exit", () => resolve()));
      child.stdin.end("shutdown\n");
      await Promise.race([exited, new Promise((resolve) => setTimeout(resolve, 9000))]);
      if (child.exitCode === null) { child.kill(); await Promise.race([exited, new Promise((resolve) => setTimeout(resolve, 2000))]); }
    }
    const absolute = path.resolve(root);
    if (path.dirname(absolute) === path.resolve(tmpdir()) && path.basename(absolute).startsWith("cafe-fin-records-browser-")) await rm(absolute, { recursive: true, force: true, maxRetries: 3, retryDelay: 250 });
  }
});
