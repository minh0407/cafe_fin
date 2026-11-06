import { test, expect } from "@playwright/test";
import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import { createHash, randomBytes } from "node:crypto";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

// Only native invoke is stubbed. HTTP, CORS, local auth, grid and files use a real sidecar.
test("real sidecar API integrates auth, original uploads, paged grid and verified document downloads", async ({
  page,
}) => {
  test.skip(
    process.env.CAFE_FIN_REAL_API !== "1",
    "Opt in with CAFE_FIN_REAL_API=1 and the locked Python .venv.",
  );
  test.setTimeout(60000);
  const repository = path.resolve(
    path.dirname(fileURLToPath(import.meta.url)),
    "../..",
  );
  const root = await mkdtemp(path.join(tmpdir(), "cafe-fin-ui-real-"));
  const token = randomBytes(32).toString("hex");
  let child: ChildProcessWithoutNullStreams | undefined;
  try {
    child = spawn(
      path.join(repository, ".venv/Scripts/python.exe"),
      ["-m", "cafe_fin"],
      {
        cwd: path.join(repository, "backend"),
        windowsHide: true,
        env: { ...process.env, PYTHONUTF8: "1" },
        stdio: "pipe",
      },
    );
    const handshake = new Promise<{ status: string; api_base: string }>(
      (resolve, reject) => {
        let output = "";
        const timer = setTimeout(
          () => reject(new Error("Sidecar startup timed out.")),
          20000,
        );
        child!.once("error", () => {
          clearTimeout(timer);
          reject(new Error("Sidecar could not launch."));
        });
        child!.stdout.on("data", (chunk) => {
          output += String(chunk);
          if (output.includes("\n")) {
            clearTimeout(timer);
            try {
              resolve(JSON.parse(output.slice(0, output.indexOf("\n"))));
            } catch {
              reject(new Error("Invalid sidecar handshake."));
            }
          }
        });
        child!.once("exit", () => {
          clearTimeout(timer);
          reject(new Error("Sidecar exited during startup."));
        });
      },
    );
    child.stdin.write(
      JSON.stringify({
        protocol_version: 1,
        session_token: token,
        data_root: root,
        initialize: true,
        allowed_origin: "http://127.0.0.1:1420",
      }) + "\n",
    );
    const hello = await handshake;
    expect(hello.status).toBe("ready");
    const boot = {
      protocol_version: 1,
      api_base: hello.api_base,
      session_token: token,
      data_root: root,
    };
    await expect
      .poll(
        async () => {
          try {
            return (
              await fetch(`${boot.api_base}/health`, {
                headers: { "X-App-Session": token },
              })
            ).status;
          } catch {
            return 0;
          }
        },
        { timeout: 15000 },
      )
      .toBe(200);
    await page.addInitScript((boot) => {
      Object.assign(window, {
        __TAURI_INTERNALS__: {
          invoke: async (command: string) => {
            if (command === "desktop_status")
              return { data_root: boot.data_root, running: true };
            if (command === "start_backend") return boot;
            throw new Error("Unexpected native command in integration test.");
          },
        },
      });
    }, boot);
    await page.goto("/");
    await expect(
      page.getByText("Tạo tài khoản quản trị đầu tiên", { exact: true }),
    ).toBeVisible();
    await page.getByLabel("Tên đăng nhập").fill("integration");
    await page
      .getByLabel("Mật khẩu", { exact: true })
      .fill("synthetic-password-2026");
    await page
      .getByRole("button", { name: "Tạo quản trị và đăng nhập" })
      .click();
    await expect(
      page.getByRole("menuitem", { name: "Bản thử bảng tính" }),
    ).toBeVisible();
    let uploadRequests = 0;
    page.on("request", (request) => {
      if (
        request.method() === "POST" &&
        new URL(request.url()).pathname === "/api/v1/files"
      )
        uploadRequests += 1;
    });
    const upload = await page.evaluate(async () => {
      const modulePath = "/src/shared/api.ts";
      const sessionPath = "/src/shared/session.ts";
      const { api, uploadOriginal } = await import(modulePath);
      const { useSession } = await import(sessionPath);
      const content = new Uint8Array(2 * 1024 ** 2 + 257);
      for (let index = 0; index < content.length; index += 1)
        content[index] = (index * 31 + 7) % 256;
      // Opaque synthetic bytes with a ZIP marker, deliberately not parsed as a workbook.
      content.set(
        new TextEncoder().encode(
          "PK\u0003\u0004Cafe Fin harmless synthetic XLSM marker",
        ),
      );
      async function digest(bytes: ArrayBuffer) {
        return [...new Uint8Array(await crypto.subtle.digest("SHA-256", bytes))]
          .map((value) => value.toString(16).padStart(2, "0"))
          .join("");
      }
      const originalName = "Sổ kế toán thử 0001.xlsm";
      const file = new File([content], originalName, {
        type: "application/vnd.ms-excel.sheet.macroenabled.12",
      });
      const first = await uploadOriginal(
        file,
        "workbooks",
        "real-original-upload-001",
      );
      const replay = await uploadOriginal(
        file,
        "workbooks",
        "real-original-upload-001",
      );
      const metadata = await api(`/files/${first.id}`);
      const downloaded = await api(
        `/files/${first.id}/content`,
        {},
        true,
        "blob",
      );
      const downloadedBytes = await downloaded.arrayBuffer();
      content[content.length - 1] ^= 1;
      let conflictCode = "";
      try {
        await uploadOriginal(
          new File([content], originalName, { type: file.type }),
          "workbooks",
          "real-original-upload-001",
        );
      } catch (error) {
        conflictCode = (error as { code: string }).code;
      }
      content[content.length - 1] ^= 1;
      const session = useSession.getState();
      const storage = JSON.stringify({
        local: { ...localStorage },
        session: { ...sessionStorage },
      });
      return {
        first,
        replay,
        metadata,
        originalName,
        sourceHash: await digest(content.buffer),
        downloadedHash: await digest(downloadedBytes),
        downloadedSize: downloadedBytes.byteLength,
        conflictCode,
        credentialsPersisted:
          storage.includes(session.boot.session_token) ||
          storage.includes(session.token),
      };
    });
    expect(upload.first).toEqual(upload.replay);
    expect(upload.metadata).toEqual(upload.first);
    expect(upload.first.category).toBe("workbooks");
    expect(upload.first.original_name).toBe(upload.originalName);
    expect(upload.first.size).toBeGreaterThan(2 * 1024 ** 2);
    expect(upload.first.size).toBe(upload.downloadedSize);
    expect(upload.first.sha256).toBe(upload.sourceHash);
    expect(upload.downloadedHash).toBe(upload.sourceHash);
    expect(upload.conflictCode).toBe("IDEMPOTENCY_CONFLICT");
    expect(upload.credentialsPersisted).toBe(false);
    expect(uploadRequests).toBe(3); // Two explicit same-key calls, one deliberate conflict; no automatic retry.
    const response = page.waitForResponse(
      (item) =>
        item.url().endsWith("/spikes/documents") &&
        item.request().method() === "POST",
    );
    await page.getByRole("button", { name: "Tạo mẫu Word / PDF" }).click();
    const outputs = (await (await response).json()) as {
      documents: { format: string; sha256: string }[];
      errors: unknown[];
    };
    expect(outputs.errors).toEqual([]);
    expect(outputs.documents.map((item) => item.format).sort()).toEqual([
      "docx",
      "pdf",
    ]);
    for (const document of outputs.documents) {
      const pending = page.waitForEvent("download");
      await page
        .getByRole("button", { name: `Tải ${document.format}`, exact: true })
        .click();
      const download = await pending;
      const stream = await download.createReadStream();
      if (!stream) throw new Error("Document stream missing.");
      const pieces: Buffer[] = [];
      for await (const chunk of stream) pieces.push(Buffer.from(chunk));
      const bytes = Buffer.concat(pieces);
      expect(createHash("sha256").update(bytes).digest("hex")).toBe(
        document.sha256,
      );
      expect(
        bytes.subarray(0, document.format === "pdf" ? 4 : 2).toString(),
      ).toBe(document.format === "pdf" ? "%PDF" : "PK");
    }
    const sourceResponse = page.waitForResponse(
      (item) =>
        item.url().includes("/spikes/grid?page=1&") &&
        item.request().method() === "GET",
    );
    await page.getByRole("menuitem", { name: "Bản thử bảng tính" }).click();
    const source = (await (await sourceResponse).json()) as {
      source_file_id: string;
      source_sha256: string;
      projection_note: string;
      items: {
        issues: {
          sheet: string;
          cell: string;
          code: string;
          message: string;
        }[];
      }[];
    };
    expect(source.source_file_id).toBeTruthy();
    expect(source.source_sha256).toMatch(/^[a-f0-9]{64}$/);
    expect(source.projection_note).toContain("10.000");
    const issue = source.items[0].issues.find((item) => item.cell === "D2");
    expect(issue?.code).toBe("EXACT_TEXT_AMOUNT");
    await expect(page.getByTestId("loaded-rows")).toHaveText(
      "Đang giữ 500 dòng",
    );
    const grid = page.getByRole("grid", { name: "Grid projection" });
    await expect(grid.getByText("00000001", { exact: true })).toBeVisible();
    await expect(
      page.locator(".cell-issue").filter({ hasText: "92233720368547758.07" }),
    ).toHaveAttribute(
      "title",
      `${issue!.sheet}!${issue!.cell}: ${issue!.message}`,
    );
    expect(await grid.getByRole("row").count()).toBeLessThan(40);
    await page.getByRole("listitem", { name: "2", exact: true }).click();
    await expect(grid.getByText("00000501", { exact: true })).toBeVisible();
    const recordsResponse = page.waitForResponse((item) =>
      item.url().includes("/api/v1/records/parties?") && item.request().method() === "GET");
    await page.getByRole("menuitem", { name: "Ghi nhận cà phê", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Ghi nhận cà phê" })).toBeVisible();
    expect((await recordsResponse).status()).toBe(200);
    await expect(page.getByRole("tab", { name: "Phiếu cân tay", exact: true })).toBeVisible();
    await page.getByRole("button", { name: "Đăng xuất", exact: true }).click();
    await expect(
      page.getByRole("button", { name: "Đăng nhập", exact: true }),
    ).toBeVisible();
  } finally {
    if (child && child.exitCode === null) {
      const exited = new Promise<void>((resolve) =>
        child!.once("exit", () => resolve()),
      );
      child.stdin.end('{"command":"shutdown"}\n');
      await Promise.race([
        exited,
        new Promise((resolve) => setTimeout(resolve, 8000)),
      ]);
      if (child.exitCode === null) {
        child.kill();
        await Promise.race([
          exited,
          new Promise((resolve) => setTimeout(resolve, 2000)),
        ]);
      }
    }
    const resolved = path.resolve(root);
    if (
      path.dirname(resolved) === path.resolve(tmpdir()) &&
      path.basename(resolved).startsWith("cafe-fin-ui-real-")
    ) {
      await rm(resolved, {
        recursive: true,
        force: true,
        maxRetries: 3,
        retryDelay: 250,
      });
    }
  }
});
