import { test, expect } from "../../frontend/node_modules/@playwright/test/index.mjs";
import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import { randomBytes } from "node:crypto";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

test("real contracts UI preserves exported snapshots, exact retries, sources and attachments", async ({ page }, testInfo) => {
  test.setTimeout(120000);
  const repository = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
  const root = await mkdtemp(path.join(tmpdir(), "cafe-fin-contracts-browser-"));
  const sessionToken = randomBytes(32).toString("hex");
  let child: ChildProcessWithoutNullStreams | undefined;
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  try {
    child = spawn(path.join(repository, ".venv/Scripts/python.exe"), [path.join(repository, "tests/contracts/browser-server.py")], {
      cwd: repository, windowsHide: true, env: { ...process.env, PYTHONPATH: path.join(repository, "backend"), PYTHONUTF8: "1" }, stdio: "pipe",
    });
    let stderr = "";
    child.stderr.on("data", (chunk) => { stderr += String(chunk); });
    const hello = new Promise<{ api_base: string }>((resolve, reject) => {
      let output = "";
      const timer = setTimeout(() => reject(new Error(`Runtime startup timeout: ${stderr}`)), 20000);
      child!.once("error", (error) => { clearTimeout(timer); reject(error); });
      child!.once("exit", () => { clearTimeout(timer); reject(new Error(`Runtime exited: ${stderr}`)); });
      child!.stdout.on("data", (chunk) => { output += String(chunk); if (output.includes("\n")) { clearTimeout(timer); try { resolve(JSON.parse(output.split("\n")[0])); } catch (error) { reject(error); } } });
    });
    child.stdin.write(JSON.stringify({ data_root: root, session_token: sessionToken }) + "\n");
    const { api_base } = await hello;
    const setup = await fetch(`${api_base}/auth/setup`, { method: "POST", headers: { "X-App-Session": sessionToken, "Content-Type": "application/json" }, body: JSON.stringify({ username: "contractsadmin", password: "synthetic-contracts-password" }) });
    expect(setup.status).toBe(200);
    const auth = await setup.json();
    const headers = { "X-App-Session": sessionToken, Authorization: `Bearer ${auth.access_token}`, "Content-Type": "application/json" };
    await page.addInitScript((boot) => { (window as any).__CONTRACTS_BOOT__ = boot; }, { boot: { protocol_version: 1, api_base, session_token: sessionToken, data_root: root }, token: auth.access_token, user: auth.user });
    await page.goto("/tests/contracts/browser.html");
    await expect(page.getByRole("heading", { name: "Hợp đồng mua và bán" })).toBeVisible();
    await page.getByLabel("Số hợp đồng").fill("HD-TONG-HOP-001");
    await page.getByLabel("Số hợp đồng").focus();
    await page.keyboard.press("Tab");
    await expect(page.getByLabel("Ngày lập")).toBeFocused();
    await page.getByLabel("Nơi lập").fill("Buôn Ma Thuột");
    await page.getByLabel("Tên đầy đủ").nth(0).fill("Công ty tổng hợp Cafe Fin");
    await page.getByLabel("Tên đầy đủ").nth(1).fill("Đối tác nhập thủ công");
    await page.getByLabel("Hàng hóa / mô tả").fill("Cà phê nhân tổng hợp");
    await page.getByLabel("Số lượng hợp đồng (kg)").fill("1234.567");
    await page.getByLabel("Đơn giá (VND/kg)").fill("100000.01");
    await page.getByLabel("Giao nhận", { exact: true }).fill("Giao tại kho tổng hợp, chia làm hai lần.");
    await page.getByLabel("Điều khoản bổ sung").fill("Điều khoản lần đầu: hai bên đối chiếu khối lượng khi giao.\nGiữ nguyên chữ Việt.");
    await page.getByLabel("Nội dung và thỏa thuận thanh toán").fill("Thanh toán trong bảy ngày theo thông tin người nhập.");
    await page.getByLabel("Tiền đặt cọc đã ghi (VND)").fill("123.45");
    await page.getByRole("heading", { name: "Hợp đồng mua và bán" }).scrollIntoViewIfNeeded();
    await page.screenshot({ path: testInfo.outputPath("desktop-editor.png") });

    // Lose the first HTTP response after the real backend committed; exact retry must return its receipt.
    const createPayloads: string[] = [];
    let loseResponse = true;
    await page.route(`${api_base}/contracts`, async (route) => {
      if (route.request().method() !== "POST") return route.continue();
      createPayloads.push(route.request().postData()!);
      if (loseResponse) { loseResponse = false; await route.fetch(); await route.abort("connectionfailed"); }
      else await route.continue();
    });
    await page.getByRole("button", { name: "Lưu hợp đồng", exact: true }).click();
    await expect(page.getByText("Chưa xác nhận thao tác đã hoàn tất", { exact: true })).toBeVisible();
    await expect(page.getByLabel("Số hợp đồng")).toBeDisabled();
    await expect(page.getByRole("combobox", { name: "Loại hợp đồng", exact: true })).toBeDisabled();
    await page.getByRole("button", { name: "Thử lại yêu cầu đã gửi" }).click();
    await expect(page.getByText("Đã lưu hợp đồng HD-TONG-HOP-001 · phiên bản 1.", { exact: true })).toBeVisible();
    expect(createPayloads).toHaveLength(2);
    expect(createPayloads[0]).toBe(createPayloads[1]);
    const firstList = await (await fetch(`${api_base}/contracts`, { headers })).json();
    expect(firstList.total).toBe(1);
    const contractId = firstList.items[0].id;

    await page.getByRole("button", { name: "Xem trước", exact: true }).click();
    await expect(page.getByText("Số liệu được tính từ dữ liệu hợp đồng", { exact: true })).toBeVisible();
    await expect(page.getByText("Chưa xác định thuế; tổng thanh toán chưa được kết luận.")).toBeVisible();
    await expect(page.locator(".contracts-paper")).toContainText("Điều khoản lần đầu");
    await expect(page.getByRole("button", { name: "Xem trước", exact: true })).toBeEnabled();
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.screenshot({ path: testInfo.outputPath("desktop-preview.png"), fullPage: true });
    await page.getByRole("button", { name: "Xuất Word + PDF" }).click();
    await expect(page.getByRole("button", { name: "Tải DOCX", exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "Tải PDF", exact: true })).toBeVisible();
    const oldVersion = (await (await fetch(`${api_base}/contracts/${contractId}/versions`, { headers })).json()).items[0];
    const downloadPromise = page.waitForEvent("download");
    await page.getByRole("button", { name: "Tải DOCX", exact: true }).click();
    const downloaded = await downloadPromise;
    expect(downloaded.suggestedFilename()).toMatch(/\.docx$/);

    await page.getByRole("tab", { name: "Nội dung hợp đồng" }).click();
    await page.getByText("Tự điền từ dữ liệu đã lưu (tùy chọn)", { exact: true }).click();
    await page.getByLabel("ID đối tác nguồn").fill("460b42cd-3b86-43b4-90f9-c811bb912ba4");
    await page.getByRole("button", { name: "Lấy thông tin đối tác" }).click();
    await expect(page.getByRole("dialog")).toContainText("Đối tác nguồn phiên bản 1");
    await page.getByRole("button", { name: "Dùng thông tin nguồn" }).click();
    await expect(page.getByLabel("Tên đầy đủ").nth(1)).toHaveValue("Đối tác nguồn phiên bản 1");
    await page.getByLabel("ID phiếu cân nguồn").fill("7836b8e8-366a-4d09-9ffc-36b6d8356385");
    await page.getByRole("button", { name: "Xem dòng phiếu cân" }).click();
    await page.getByRole("checkbox", { name: /Dòng 1: Cà phê cân tổng hợp/ }).check();
    await page.getByRole("button", { name: "Thêm các dòng đã chọn vào hợp đồng" }).click();
    await page.getByLabel("Đơn giá (VND/kg)").nth(1).fill("90000.05");
    await page.getByLabel("Số lượng hợp đồng (kg)").nth(1).fill("12.300");
    await page.getByLabel("Điều khoản bổ sung").fill("Điều khoản sửa lần hai: giữ snapshot lần đầu.");
    await page.getByRole("button", { name: "Lưu hợp đồng", exact: true }).click();
    await expect(page.getByText("Đã lưu hợp đồng HD-TONG-HOP-001 · phiên bản 2.", { exact: true })).toBeVisible();
    expect((await (await fetch(`${api_base}/contracts/sources/weighings/7836b8e8-366a-4d09-9ffc-36b6d8356385`, { headers })).json()).lines[0].net_kg).toBe("12.345");
    await fetch(`${api_base}/harness/source-revision`, { method: "POST", headers, body: "{}" });

    await page.getByRole("tab", { name: /Bản đã xuất/ }).click();
    await page.getByRole("button", { name: "Xem bản này" }).click();
    await expect(page.locator(".contracts-paper")).toContainText("Điều khoản lần đầu");
    await expect(page.locator(".contracts-paper")).not.toContainText("Điều khoản sửa lần hai");
    const reopened = await (await fetch(`${api_base}/contracts/${contractId}/versions/${oldVersion.id}`, { headers })).json();
    expect(reopened.snapshot_sha256).toBe(oldVersion.snapshot_sha256);
    expect(reopened.files.docx.sha256).toBe(oldVersion.files.docx.sha256);
    expect(reopened.files.pdf.sha256).toBe(oldVersion.files.pdf.sha256);

    await page.getByRole("tab", { name: /Tệp đính kèm/ }).click();
    const pdfBytes = await (await fetch(`${api_base}/contracts/${contractId}/versions/${oldVersion.id}/files/pdf`, { headers })).arrayBuffer();
    await page.getByLabel("Chọn tệp", { exact: true }).setInputFiles({ name: "scan-tong-hop.pdf", mimeType: "application/pdf", buffer: Buffer.from(pdfBytes) });
    await page.getByLabel("Ghi chú tệp").fill("Chứng từ thử tùy chọn.");
    await page.getByRole("button", { name: "Lưu tệp đính kèm" }).click();
    await expect(page.getByText("Đã lưu tệp đính kèm và tình trạng do bạn ghi.", { exact: true })).toBeVisible();
    await expect(page.getByRole("cell", { name: "Chứng từ thử tùy chọn." })).toBeVisible();

    // Manual sale remains independent; a failed PDF must keep the actual DOCX usable.
    await page.getByRole("button", { name: "Lập hợp đồng mới" }).click();
    await page.locator(".ant-select").filter({ has: page.getByRole("combobox", { name: "Loại hợp đồng", exact: true }) }).click();
    await page.locator(".ant-select-dropdown:not(.ant-select-dropdown-hidden)").getByText("Bán ra", { exact: true }).click();
    await page.getByLabel("Số hợp đồng").fill("HD-BAN-TONG-HOP-002");
    await page.getByLabel("Nơi lập").fill("Đắk Lắk");
    await page.getByLabel("Tên đầy đủ").nth(0).fill("Công ty bán tổng hợp");
    await page.getByLabel("Tên đầy đủ").nth(1).fill("Khách mua tổng hợp");
    await page.getByLabel("Hàng hóa / mô tả").fill("Cà phê bán nhập tay");
    await page.getByLabel("Số lượng hợp đồng (kg)").fill("2.001");
    await page.getByLabel("Đơn giá (VND/kg)").fill("123.45");
    await page.locator(".ant-select").filter({ has: page.getByRole("combobox", { name: "Cách ghi thuế", exact: true }) }).click();
    await page.locator(".ant-select-dropdown:not(.ant-select-dropdown-hidden)").getByText("Đơn giá chưa bao gồm thuế", { exact: true }).click();
    await page.getByLabel("Thuế suất (%)").fill("10.00");
    await page.locator(".ant-select").filter({ has: page.getByRole("combobox", { name: "Phương thức thanh toán", exact: true }) }).click();
    await page.locator(".ant-select-dropdown:not(.ant-select-dropdown-hidden)").getByText("Kết hợp", { exact: true }).click();
    await page.getByLabel("Nội dung và thỏa thuận thanh toán").fill("Kết hợp tiền mặt và chuyển khoản, do hai bên thỏa thuận.");
    await page.getByRole("button", { name: "Thêm đợt thanh toán" }).click();
    await page.getByLabel("Ngày đợt 1").fill("2026-11-20");
    await page.getByLabel("Số tiền đợt 1 (VND)").fill("100.00");
    await page.getByLabel("Ghi chú đợt 1").fill("Đợt một đã thỏa thuận");
    await page.getByRole("button", { name: "Lưu hợp đồng", exact: true }).click();
    await expect(page.getByText("Đã lưu hợp đồng HD-BAN-TONG-HOP-002 · phiên bản 1.", { exact: true })).toBeVisible();
    await fetch(`${api_base}/harness/toggle-pdf-failure`, { method: "POST", headers, body: "{}" });
    await page.getByRole("button", { name: "Xuất Word + PDF" }).click();
    await expect(page.getByRole("button", { name: "Tải DOCX", exact: true })).toBeVisible();
    await expect(page.getByText(/SYNTHETIC_PDF_FAILURE:/)).toBeVisible();
    await expect(page.getByRole("button", { name: "Tải PDF", exact: true })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Tải DOCX", exact: true })).toBeEnabled();
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.screenshot({ path: testInfo.outputPath("desktop-independent-files.png"), fullPage: true });
    await fetch(`${api_base}/harness/toggle-pdf-failure`, { method: "POST", headers, body: "{}" });
    await page.getByRole("button", { name: "Thử tạo PDF từ bản này", exact: true }).click();
    await expect(page.getByRole("button", { name: "Tải PDF", exact: true })).toBeVisible();
    const salesList = await (await fetch(`${api_base}/contracts?search=HD-BAN-TONG-HOP-002`, { headers })).json();
    const salesVersions = await (await fetch(`${api_base}/contracts/${salesList.items[0].id}/versions`, { headers })).json();
    expect(salesVersions.total).toBe(1);
    expect(salesVersions.items[0].snapshot.data.kind).toBe("sale");
    expect(salesVersions.items[0].snapshot.data.payment.method).toBe("mixed");
    expect(salesVersions.items[0].files.pdf.status).toBe("succeeded");

    // A new actor generation drops the private draft and any local output state.
    await page.getByRole("tab", { name: "Nội dung hợp đồng" }).click();
    await page.getByLabel("Số hợp đồng").fill("PRIVATE-UNSAVED-A");
    await page.evaluate(async () => {
      const modulePath = "/frontend/src/shared/session.ts";
      const { useSession } = await import(modulePath);
      useSession.getState().logout();
    });
    await expect(page.getByLabel("Số hợp đồng")).toHaveCount(0);
    await expect(page.getByText("Đăng nhập để mở hợp đồng.", { exact: true })).toBeVisible();
    await expect(page.getByText("PRIVATE-UNSAVED-A")).toHaveCount(0);
    expect(errors).toEqual([]);
  } finally {
    if (child) {
      child.stdin.end("shutdown\n");
      await new Promise<void>((resolve) => { if (child!.exitCode !== null) return resolve(); child!.once("exit", () => resolve()); setTimeout(() => { child!.kill(); resolve(); }, 10000); });
    }
    await rm(root, { recursive: true, force: true });
  }
});
