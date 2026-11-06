import { test, expect } from "@playwright/test";
import { createHash } from "node:crypto";

test("opaque original upload preserves bytes, Unicode filename and memory credentials", async ({
  page,
}) => {
  const content = Buffer.from([0, 255, 80, 75, 1, 2, 128, 10]);
  const name = "Sổ thử 001.xlsm";
  const metadata = {
    id: "synthetic-file-id",
    sha256: createHash("sha256").update(content).digest("hex"),
    size: content.length,
    category: "workbooks",
    original_name: name,
    media_type: "application/octet-stream",
    created_at: "2026-11-06T13:00:00Z",
  };
  let uploads = 0;
  await page.addInitScript(() => {
    Object.assign(window, {
      __TAURI_INTERNALS__: {
        invoke: async () => ({ data_root: null, running: false }),
      },
    });
  });
  await page.route("http://127.0.0.1:19098/api/v1/**", async (route) => {
    const request = route.request();
    const headers = {
      "Access-Control-Allow-Origin": "http://127.0.0.1:1420",
      "Access-Control-Allow-Headers":
        "Content-Type,Authorization,X-App-Session,X-File-Name,X-Request-Key",
      "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
    };
    if (request.method() === "OPTIONS") {
      await route.fulfill({ status: 204, headers });
      return;
    }
    if (request.method() === "POST") {
      uploads += 1;
      expect(new URL(request.url()).pathname).toBe("/api/v1/files");
      expect(new URL(request.url()).search).toBe("?category=workbooks");
      expect(request.headers()["x-app-session"]).toBe(
        "synthetic-upload-app-session",
      );
      expect(request.headers().authorization).toBe(
        "Bearer synthetic-upload-user-token",
      );
      expect(request.headers()["x-file-name"]).toBe(encodeURIComponent(name));
      expect(request.headers()["x-request-key"]).toBe("upload-original-001");
      expect(request.headers()["content-type"]).toBe(
        "application/octet-stream",
      );
      expect(request.postDataBuffer()).toEqual(content);
      await route.fulfill({ json: metadata, headers });
      return;
    }
    await route.fulfill({
      json: { status: "ok", protocol_version: 1, setup_required: false },
      headers,
    });
  });
  await page.goto("/");
  const result = await page.evaluate(
    async ({ bytes, name }) => {
      const sessionModule = "/src/shared/session.ts";
      const apiModule = "/src/shared/api.ts";
      const { useSession } = await import(sessionModule);
      const { uploadOriginal } = await import(apiModule);
      useSession.setState({
        boot: {
          protocol_version: 1,
          api_base: "http://127.0.0.1:19098/api/v1",
          session_token: "synthetic-upload-app-session",
          data_root: "D:\\Synthetic",
        },
        token: "synthetic-upload-user-token",
        user: {
          id: "synthetic",
          username: "synthetic",
          role: "admin",
          permissions: ["*"],
        },
        connected: true,
      });
      return await uploadOriginal(
        new File([Uint8Array.from(bytes)], name),
        "workbooks",
        "upload-original-001",
      );
    },
    { bytes: [...content], name },
  );
  expect(result).toEqual(metadata);
  expect(uploads).toBe(1);
  const storage = await page.evaluate(() => ({
    local: { ...localStorage },
    session: { ...sessionStorage },
  }));
  expect(JSON.stringify(storage)).not.toContain("synthetic-upload");
});

test("oversize original fails before sending any bytes or credentials", async ({
  page,
}) => {
  let requests = 0;
  await page.route("http://127.0.0.1:19098/**", (route) => {
    requests += 1;
    return route.abort();
  });
  await page.addInitScript(() => {
    Object.assign(window, {
      __TAURI_INTERNALS__: {
        invoke: async () => ({ data_root: null, running: false }),
      },
    });
  });
  await page.goto("/");
  const failure = await page.evaluate(async () => {
    const apiModule = "/src/shared/api.ts";
    const { uploadOriginal } = await import(apiModule);
    // Model browser File metadata above the cap without allocating a 2 GiB fixture.
    const file = new File(["synthetic"], "large.xlsx");
    Object.defineProperty(file, "size", { value: 2 * 1024 ** 3 + 1 });
    try {
      await uploadOriginal(file, "workbooks", "upload-too-large");
    } catch (error) {
      return { code: (error as { code: string }).code };
    }
    return null;
  });
  expect(failure).toEqual({ code: "FILE_TOO_LARGE" });
  expect(requests).toBe(0);
});
