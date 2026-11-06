import { test, expect, type Page } from "../../frontend/node_modules/@playwright/test/index.mjs";
import type { ContractDTO } from "../../frontend/src/features/contracts/types";
import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import { createHash, randomBytes } from "node:crypto";
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
  const recordQueries: URL[] = [];
  const sourceReads: string[] = [];
  const recordsWrites: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (/\/records\/(parties|weighings)$/.test(url.pathname)) recordQueries.push(url);
    if (url.pathname.includes("/contracts/sources/")) sourceReads.push(url.pathname);
    if (url.pathname.startsWith("/api/v1/records/") && !["GET", "OPTIONS"].includes(request.method())) recordsWrites.push(request.method());
  });
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
    const deniedOrigin = await fetch(`${api_base}/health`, { headers: { "X-App-Session": sessionToken, Origin: "http://127.0.0.1:1423" } });
    expect(deniedOrigin.status).toBe(403);
    expect(deniedOrigin.headers.get("access-control-allow-origin")).toBeNull();
    const allowedOrigin = await fetch(`${api_base}/health`, { headers: { "X-App-Session": sessionToken, Origin: "http://127.0.0.1:1422" } });
    expect(allowedOrigin.status).toBe(200);
    expect(allowedOrigin.headers.get("access-control-allow-origin")).toBe("http://127.0.0.1:1422");
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
    await expect(page.getByLabel("Ngày lập")).toHaveValue(/^\d{2}\/\d{2}\/\d{4}$/);
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
    for (const button of await page.getByRole("button", { name: "Mở lịch chọn ngày", exact: true }).all()) await expect(button).toBeDisabled();
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
    const partyPicker = page.getByRole("region", { name: "Tra cứu đối tác", exact: true });
    const weighingPicker = page.getByRole("region", { name: "Tra cứu phiếu cân", exact: true });
    await partyPicker.getByLabel("Tìm đối tác theo tên hoặc mã").fill("nguồn & Đắk");
    await partyPicker.getByRole("button", { name: "Tìm đối tác", exact: true }).click();
    await expect(partyPicker.getByRole("row")).toHaveCount(51);
    await expect(partyPicker.getByText("52 bản ghi", { exact: true })).toBeVisible();
    await partyPicker.getByRole("button", { name: "Page 2", exact: true }).click();
    await expect(partyPicker.getByRole("row")).toHaveCount(3);
    await partyPicker.getByRole("button", { name: /Chọn đối tác .*bb912ba5$/ }).click();
    await expect(page.getByRole("dialog")).toContainText("Địa chỉ bản ghi thứ hai");
    await page.getByRole("button", { name: "Giữ thông tin đang nhập", exact: true }).click();
    await expect(page.getByLabel("Tên đầy đủ").nth(1)).toHaveValue("Đối tác nhập thủ công");
    await partyPicker.getByRole("button", { name: /Chọn đối tác .*bb912ba4$/ }).click();
    await expect(page.getByRole("dialog")).toContainText("Đối tác nguồn & Đắk Lắk · v1");
    await expect(page.getByRole("dialog")).toContainText("Địa chỉ tổng hợp");
    await page.getByRole("button", { name: "Dùng thông tin nguồn" }).click();
    await expect(page.getByLabel("Tên đầy đủ").nth(1)).toHaveValue("Đối tác nguồn & Đắk Lắk · v1");
    await weighingPicker.getByLabel("Tìm phiếu cân theo tên hoặc mã").fill("CÂN ĐẮK LẮK &");
    await weighingPicker.getByRole("button", { name: "Tìm phiếu cân", exact: true }).click();
    await expect(weighingPicker.getByRole("row")).toHaveCount(51);
    await weighingPicker.getByRole("button", { name: "Page 2", exact: true }).click();
    await expect(weighingPicker.getByRole("row")).toHaveCount(3);
    await weighingPicker.getByRole("button", { name: /Chọn phiếu cân .*d8356386$/ }).click();
    await expect(page.getByRole("checkbox", { name: /Dòng 1: Cà phê cân bản ghi thứ hai/ })).toBeVisible();
    await weighingPicker.getByRole("button", { name: /Chọn phiếu cân .*d8356385$/ }).click();
    await page.getByRole("checkbox", { name: /Dòng 1: Cà phê cân tổng hợp/ }).check();
    await page.getByText("Tự điền từ dữ liệu đã lưu (tùy chọn)", { exact: true }).scrollIntoViewIfNeeded();
    await page.screenshot({ path: testInfo.outputPath("desktop-records-picker.png") });
    await partyPicker.screenshot({ path: testInfo.outputPath("party-source-picker.png") });
    await weighingPicker.screenshot({ path: testInfo.outputPath("weighing-source-picker.png") });
    await page.getByRole("button", { name: "Thêm các dòng đã chọn vào hợp đồng" }).click();
    await page.getByLabel("Đơn giá (VND/kg)").nth(1).fill("90000.05");
    await page.getByLabel("Số lượng hợp đồng (kg)").nth(1).fill("12.300");
    await page.getByLabel("Điều khoản bổ sung").fill("Điều khoản sửa lần hai: giữ snapshot lần đầu.");
    await page.getByRole("button", { name: "Lưu hợp đồng", exact: true }).click();
    await expect(page.getByText("Đã lưu hợp đồng HD-TONG-HOP-001 · phiên bản 2.", { exact: true })).toBeVisible();
    const linkedContract = await (await fetch(`${api_base}/contracts/${contractId}`, { headers })).json();
    expect(linkedContract.data.lines[1].source.id).toBe("7836b8e8-366a-4d09-9ffc-36b6d8356385");
    expect(linkedContract.data.source_refs.find((ref: { type: string }) => ref.type === "party").id).toBe("460b42cd-3b86-43b4-90f9-c811bb912ba4");
    for (const suffix of ["parties/460b42cd-3b86-43b4-90f9-c811bb912ba4", "parties/460b42cd-3b86-43b4-90f9-c811bb912ba5", "weighings/7836b8e8-366a-4d09-9ffc-36b6d8356385", "weighings/7836b8e8-366a-4d09-9ffc-36b6d8356386"])
      expect(sourceReads.some((read) => read.endsWith(suffix))).toBe(true);
    expect(recordQueries.every((url) => url.searchParams.get("page_size") === "50")).toBe(true);
    expect(recordQueries.some((url) => url.searchParams.get("page") === "2" && url.pathname.endsWith("/parties"))).toBe(true);
    expect(recordQueries.some((url) => url.searchParams.get("page") === "2" && url.pathname.endsWith("/weighings"))).toBe(true);
    expect(recordQueries.find((url) => url.pathname.endsWith("/parties"))!.searchParams.get("search")).toBe("nguồn & Đắk");
    expect(recordQueries.find((url) => url.pathname.endsWith("/parties"))!.href).toContain("%26");
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
    const attachmentResponse = page.waitForResponse((response) => response.url().startsWith(`${api_base}/contracts/${contractId}/attachments/`) && response.url().endsWith("/content"));
    const attachmentDownload = page.waitForEvent("download");
    await page.getByRole("button", { name: "Tải tệp gốc", exact: true }).click();
    const originalAttachment = await attachmentResponse;
    expect(originalAttachment.status()).toBe(200);
    expect(await originalAttachment.body()).toEqual(Buffer.from(pdfBytes));
    expect(originalAttachment.headers()["x-content-sha256"]).toBe(createHash("sha256").update(Buffer.from(pdfBytes)).digest("hex"));
    expect((await attachmentDownload).suggestedFilename()).toBe("scan-tong-hop.pdf");

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
    await page.getByLabel("Ngày đợt 1").fill("20/11/2026");
    await page.getByLabel("Số tiền đợt 1 (VND)").fill("100.00");
    await page.getByLabel("Ghi chú đợt 1").fill("Đợt một đã thỏa thuận");
    // Either a denied records module or an absent module leaves manual contracts usable.
    const sourceToggle = page.getByText("Tự điền từ dữ liệu đã lưu (tùy chọn)", { exact: true });
    if (!await partyPicker.isVisible()) await sourceToggle.click();
    for (const status of [403, 404]) {
      await fetch(`${api_base}/harness/records-mode/${status}`, { method: "POST", headers, body: "{}" });
      const partyFailure = page.waitForResponse((response) => new URL(response.url()).pathname.endsWith("/records/parties") && response.status() === status);
      await partyPicker.getByLabel("Tìm đối tác theo tên hoặc mã").fill(`nguồn ${status}`);
      await partyPicker.getByLabel("Tìm đối tác theo tên hoặc mã").press("Enter");
      await partyFailure;
      await expect(partyPicker.getByText("Chưa tra cứu được đối tác", { exact: true })).toBeVisible();
      const weighingFailure = page.waitForResponse((response) => new URL(response.url()).pathname.endsWith("/records/weighings") && response.status() === status);
      await weighingPicker.getByLabel("Tìm phiếu cân theo tên hoặc mã").fill(`cân ${status}`);
      await weighingPicker.getByLabel("Tìm phiếu cân theo tên hoặc mã").press("Enter");
      await weighingFailure;
      await expect(weighingPicker.getByText("Chưa tra cứu được phiếu cân", { exact: true })).toBeVisible();
      await expect(page.getByLabel("Tên đầy đủ").nth(1)).toHaveValue("Khách mua tổng hợp");
      await expect(page.getByRole("button", { name: "Lưu hợp đồng", exact: true })).toBeEnabled();
      await page.getByRole("button", { name: "Lưu hợp đồng", exact: true }).click();
      await expect(page.getByText(`Đã lưu hợp đồng HD-BAN-TONG-HOP-002 · phiên bản ${status === 403 ? 1 : 2}.`, { exact: true })).toBeVisible();
      if (status === 403) {
        await page.getByRole("button", { name: "Xuất Word + PDF" }).click();
        await expect(page.getByRole("button", { name: "Tải DOCX", exact: true })).toBeVisible();
        await expect(page.getByRole("button", { name: "Tải PDF", exact: true })).toBeVisible();
        await page.getByRole("tab", { name: "Nội dung hợp đồng" }).click();
        await page.getByLabel("Điều khoản bổ sung").fill("Nhập tay khi nguồn chưa truy cập được; tiếp tục thử khi module vắng mặt.");
      }
    }
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
    expect(salesVersions.total).toBe(2);
    expect(salesVersions.items.map((version: { contract_version: number }) => version.contract_version).sort()).toEqual([1, 2]);
    expect(salesVersions.items[0].snapshot.data.kind).toBe("sale");
    expect(salesVersions.items[0].snapshot.data.source_refs).toEqual([]);
    expect(salesVersions.items[0].snapshot.data.payment.method).toBe("mixed");
    expect(salesVersions.items[0].snapshot.data.payment.schedule[0].due_on).toBe("2026-11-20");
    expect(salesVersions.items[0].files.pdf.status).toBe("succeeded");

    // Superseded searches and malformed pages cannot replace the latest bounded results.
    await page.getByRole("tab", { name: "Nội dung hợp đồng" }).click();
    await fetch(`${api_base}/harness/records-mode/200`, { method: "POST", headers, body: "{}" });
    if (!await partyPicker.isVisible()) await sourceToggle.click();
    let releaseOld!: () => void, oldReady!: () => void;
    const oldGate = new Promise<void>((resolve) => { releaseOld = resolve; });
    const oldStarted = new Promise<void>((resolve) => { oldReady = resolve; });
    let releaseActor!: () => void, actorReady!: () => void;
    const actorGate = new Promise<void>((resolve) => { releaseActor = resolve; });
    const actorStarted = new Promise<void>((resolve) => { actorReady = resolve; });
    await page.route(`${api_base}/records/parties?**`, async (route) => {
      const query = new URL(route.request().url()).searchParams.get("search");
      if (query === "metadata lỗi") return route.fulfill({ json: { items: [], total: "52", page: 0, page_size: 500 } });
      if (query === "chờ cũ" || query === "actor cũ") {
        const response = await route.fetch();
        if (query === "chờ cũ") { oldReady(); await oldGate; }
        else { actorReady(); await actorGate; }
        await route.fulfill({ response }).catch(() => {});
      } else await route.continue();
    });
    await partyPicker.getByLabel("Tìm đối tác theo tên hoặc mã").fill("metadata lỗi");
    await partyPicker.getByLabel("Tìm đối tác theo tên hoặc mã").press("Enter");
    await expect(partyPicker.getByText("Chưa tra cứu được đối tác", { exact: true })).toBeVisible();
    await expect(partyPicker).toContainText("Danh sách nguồn không đúng giới hạn một trang");
    await partyPicker.getByLabel("Tìm đối tác theo tên hoặc mã").fill("chờ cũ");
    await partyPicker.getByLabel("Tìm đối tác theo tên hoặc mã").press("Enter");
    await oldStarted;
    await partyPicker.getByLabel("Tìm đối tác theo tên hoặc mã").fill("nguồn & Đắk");
    await partyPicker.getByLabel("Tìm đối tác theo tên hoặc mã").press("Enter");
    await expect(partyPicker.getByRole("row")).toHaveCount(51);
    const oldCompleted = page.waitForResponse((response) => new URL(response.url()).searchParams.get("search") === "chờ cũ").then((response) => response.finished());
    releaseOld();
    await oldCompleted;
    await page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    await expect(partyPicker.getByRole("row")).toHaveCount(51);
    await expect(partyPicker.getByText("52 bản ghi", { exact: true })).toBeVisible();

    // A second real local actor cannot receive A's delayed search or draft state.
    const createB = await fetch(`${api_base}/users`, { method: "POST", headers, body: JSON.stringify({ request_key: randomBytes(16).toString("hex"), username: "contractsoperator", password: "synthetic-contracts-b-password", role: "operator" }) });
    expect(createB.status).toBe(200);
    const authBResponse = await fetch(`${api_base}/auth/login`, { method: "POST", headers, body: JSON.stringify({ username: "contractsoperator", password: "synthetic-contracts-b-password" }) });
    expect(authBResponse.status).toBe(200);
    const authB = await authBResponse.json();
    await page.getByLabel("Số hợp đồng").fill("PRIVATE-UNSAVED-A");
    await partyPicker.getByLabel("Tìm đối tác theo tên hoặc mã").fill("actor cũ");
    await partyPicker.getByLabel("Tìm đối tác theo tên hoặc mã").press("Enter");
    await actorStarted;
    await page.evaluate(async (authB) => {
      const modulePath = "/frontend/src/shared/session.ts";
      const { useSession } = await import(modulePath);
      useSession.getState().login(authB.access_token, authB.user);
    }, authB);
    releaseActor();
    await expect(page.getByLabel("Số hợp đồng")).toHaveValue("");
    await page.getByText("Tự điền từ dữ liệu đã lưu (tùy chọn)", { exact: true }).click();
    await expect(partyPicker.getByRole("row")).toHaveCount(0);
    await expect(partyPicker.getByLabel("Tìm đối tác theo tên hoặc mã")).toHaveValue("");
    await expect(page.getByText("PRIVATE-UNSAVED-A")).toHaveCount(0);
    expect(recordsWrites).toEqual([]);
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

async function mountDateWorkspace(page: Page) {
  const apiBase = "http://127.0.0.1:19097/api/v1";
  const company = { type: "company", name: "Công ty ngày tổng hợp", address: null, tax_code: null, contacts: [], bank_details: [], representative: null };
  const state: { detail: ContractDTO; commands: { path: string; payload: any }[] } = {
    detail: {
      id: "bce08e7a-2d32-488d-a4cd-877418149b30", version: 1,
      data: {
        kind: "purchase", number: "HD-DATE", occurred_on: "2026-11-06", place: "Đắk Lắk", template_id: "be33fbce-4a0d-50eb-b203-895a24102ce1",
        company, counterparty: { ...company, name: "Đối tác ngày tổng hợp" },
        lines: [{ description: "Cà phê", quantity_kg: "1.000", unit_price: "100.00", gross_kg: null, tare_kg: null, net_kg: null, quantity_source: null, note: null, product_id: null, source: null, source_snapshot: null }],
        tax: { mode: "none", rate: null }, terms: { delivery: "", packaging: "", quality: "", deadline: "", responsibilities: "", additional: "" },
        payment: { method: "cash", description: "", receiving_account: null, due_on: "2026-11-20", deposit_amount: null, recorded_paid_amount: null, schedule: [{ due_on: "2026-11-25", amount: "100.00", note: "" }] }, source_refs: [],
      },
    }, commands: [],
  };
  await page.clock.setFixedTime(new Date("2026-11-07T08:00:00+07:00"));
  await page.route(`${apiBase}/**`, async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname.replace("/api/v1", "");
    const headers = { "Access-Control-Allow-Origin": "http://127.0.0.1:1422", "Access-Control-Allow-Headers": "Authorization,Content-Type,X-App-Session", "Access-Control-Allow-Methods": "GET,POST,PATCH,OPTIONS" };
    const fulfill = (json: unknown) => route.fulfill({ json, headers });
    if (request.method() === "OPTIONS") return route.fulfill({ status: 204, headers });
    if (request.method() !== "GET") {
      const payload = request.postDataJSON();
      state.commands.push({ path, payload });
      if (path === `/contracts/${state.detail.id}`) { state.detail = { ...state.detail, version: state.detail.version + 1, data: payload.data }; return fulfill(state.detail); }
      const document = { title: "Hợp đồng ngày tổng hợp", subtitle: "", fields: [], paragraphs: [], column_headers: [], rows: [] };
      if (path === "/contracts/preview") return fulfill({ document, totals: {} });
      return fulfill({ id: "633768c1-eed2-4c92-985b-ad1eb65d788b", contract_id: state.detail.id, contract_version: state.detail.version, snapshot_sha256: "synthetic-date-snapshot", snapshot: { document, totals: {}, data: state.detail.data }, files: {} });
    }
    if (path === "/contracts/templates") return fulfill({ items: [{ id: state.detail.data.template_id, kind: "purchase", version: 1, title: "Mẫu ngày tổng hợp" }] });
    if (path === "/contracts") return fulfill({ items: [state.detail], total: 1, page: 1, page_size: 20 });
    if (path === `/contracts/${state.detail.id}`) return fulfill(state.detail);
    return fulfill({ items: [], total: 0, page: 1, page_size: 20 });
  });
  await page.addInitScript((settings) => { (window as any).__CONTRACTS_BOOT__ = settings; }, { boot: { protocol_version: 1, api_base: apiBase, session_token: "synthetic-date-session-0123456789abcdef", data_root: "D:\\SyntheticContractDates" }, token: "synthetic-date-admin-token", user: { id: "date-admin", username: "dateadmin", role: "admin", permissions: ["*"], version: 1 } });
  await page.goto("/tests/contracts/browser.html");
  await page.getByRole("button", { name: /HD-DATE Mua/ }).click();
  await expect(page.getByLabel("Ngày lập")).toHaveValue("06/11/2026");
  return state;
}

test("contract date drafts retain invalid text, block requests, and send corrected ISO dates", async ({ page }) => {
  const state = await mountDateWorkspace(page);
  const occurred = page.getByLabel("Ngày lập");
  const due = page.getByLabel("Hạn thanh toán", { exact: true });
  const schedule = page.getByLabel("Ngày đợt 1");
  async function rejectsDraft(field: ReturnType<Page["getByLabel"]>, raw: string) {
    const before = state.commands.length;
    await field.fill(raw);
    await expect(field).toHaveAttribute("aria-invalid", "true");
    await page.getByRole("button", { name: "Lưu hợp đồng", exact: true }).click();
    await page.getByRole("button", { name: "Xem trước", exact: true }).click();
    await expect(page.getByText("Kiểm tra ngày trong hợp đồng trước khi lưu, xem trước hoặc xuất.", { exact: true })).toBeVisible();
    await expect(field).toHaveValue(raw);
    expect(state.commands).toHaveLength(before);
  }
  async function saveCorrected() {
    const before = state.commands.length;
    await page.getByRole("button", { name: "Lưu hợp đồng", exact: true }).click();
    await expect.poll(() => state.commands.length).toBe(before + 1);
    await expect(page.getByRole("button", { name: "Lưu hợp đồng", exact: true })).toBeDisabled();
    return state.commands.at(-1)!.payload.data;
  }
  for (const raw of ["31/02/2026", "20/11/", ""]) await rejectsDraft(occurred, raw);
  await occurred.fill("07/11/2026");
  expect((await saveCorrected()).occurred_on).toBe("2026-11-07");
  for (const raw of ["31/02/2026", "20/11/"]) await rejectsDraft(due, raw);
  await due.fill("21/11/2026");
  expect((await saveCorrected()).payment.due_on).toBe("2026-11-21");
  const dueField = page.locator(".contracts-field").filter({ has: due });
  await dueField.getByRole("button", { name: "Xóa", exact: true }).click();
  expect((await saveCorrected()).payment.due_on).toBeNull();
  await rejectsDraft(due, "31/02/2026");
  const beforeCalendar = state.commands.length;
  await dueField.getByRole("button", { name: "Mở lịch chọn ngày", exact: true }).click();
  await page.locator('[title="2026-11-22"]').click();
  await expect(due).toHaveValue("22/11/2026");
  expect(state.commands).toHaveLength(beforeCalendar);
  expect((await saveCorrected()).payment.due_on).toBe("2026-11-22");
  for (const raw of ["25/11/", "31/02/2026", ""]) await rejectsDraft(schedule, raw);
  await schedule.fill("30/11/2026");
  expect((await saveCorrected()).payment.schedule[0].due_on).toBe("2026-11-30");
  await page.getByRole("button", { name: "Xem trước", exact: true }).click();
  await expect.poll(() => state.commands.at(-1)!.path).toBe("/contracts/preview");
  expect(state.commands.at(-1)!.payload.data.occurred_on).toBe("2026-11-07");
});

test("current export validates persisted required, optional, schedule and copied-source dates", async ({ page }) => {
  const state = await mountDateWorkspace(page);
  const original = structuredClone(state.detail);
  const invalidCases: { message: string; mutate: (detail: ContractDTO) => void }[] = [
    { message: "Ngày lập", mutate: (detail) => { detail.data.occurred_on = "31/02/2026"; } },
    { message: "Hạn thanh toán", mutate: (detail) => { detail.data.payment.due_on = "20/11/"; } },
    { message: "Ngày đợt 1", mutate: (detail) => { detail.data.payment.schedule[0].due_on = ""; } },
    { message: "Ngày phiếu cân nguồn dòng 1", mutate: (detail) => { detail.data.lines[0].source = { type: "weighing", id: "7836b8e8-366a-4d09-9ffc-36b6d8356385", version: 1, line_index: 0, code: "CÂN-NGÀY", occurred_on: "2026-02-31" }; } },
  ];
  for (const { message, mutate } of invalidCases) {
    state.detail = structuredClone(original);
    mutate(state.detail);
    await page.getByRole("button", { name: /HD-DATE Mua/ }).click();
    const exportButton = page.getByRole("button", { name: "Xuất Word + PDF", exact: true });
    await expect(exportButton).toBeEnabled(); // pristine persisted data: dirty/disabled cannot protect this action.
    const before = state.commands.length;
    await exportButton.click();
    await expect(page.getByText("Kiểm tra ngày trong hợp đồng trước khi lưu, xem trước hoặc xuất.", { exact: true })).toBeVisible();
    await expect(page.locator(".ant-alert-error")).toContainText(message);
    expect(state.commands).toHaveLength(before);
  }
  state.detail = structuredClone(original);
  state.detail.data.payment.due_on = null;
  state.detail.data.lines[0].source = { type: "weighing", id: "7836b8e8-366a-4d09-9ffc-36b6d8356385", version: 1, line_index: 0, code: "CÂN-NGÀY", occurred_on: null };
  await page.getByRole("button", { name: /HD-DATE Mua/ }).click();
  await page.getByRole("button", { name: "Xuất Word + PDF", exact: true }).click();
  await expect.poll(() => state.commands.length).toBe(1);
  expect(state.commands[0].path).toMatch(/\/exports$/);
});
