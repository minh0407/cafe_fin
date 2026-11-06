import { test, expect } from "@playwright/test";

test("late responses and body completions cannot cross actor or boot generations", async ({
  page,
}) => {
  await page.route("**/session-race-test", (route) =>
    route.fulfill({
      contentType: "text/html",
      body: "<!doctype html><html><body></body></html>",
    }),
  );
  await page.goto("/session-race-test");
  const evidence = await page.evaluate(async () => {
    const apiModule = "/src/shared/api.ts";
    const sessionModule = "/src/shared/session.ts";
    const { api, ApiError, uploadOriginal } = await import(apiModule);
    const { useSession } = await import(sessionModule);
    const boot = {
      protocol_version: 1,
      api_base: "http://127.0.0.1:19096/api/v1",
      session_token: "synthetic-boot-A",
      data_root: "D:\\Synthetic-A",
    };
    const userA = {
      id: "A",
      username: "old-admin",
      role: "admin",
      version: 1,
      permissions: ["*"],
    };
    const userB = {
      id: "B",
      username: "new-operator",
      role: "operator",
      version: 1,
      permissions: ["core.read"],
    };
    const resetA = () => {
      useSession.getState().setBoot(boot);
      useSession.getState().login("token-A", userA);
      useSession.getState().connection(true);
    };
    const switchB = (connected = false) => {
      useSession.getState().logout();
      useSession.getState().login("token-B", userB);
      useSession.getState().connection(connected);
    };
    const outcome = (pending: Promise<unknown>) =>
      pending.then(
        (value) => ({ resolved: true, value }),
        (error) => ({
          resolved: false,
          code: error.code,
          isApiError: error instanceof ApiError,
        }),
      );
    const current = () => ({
      id: useSession.getState().user?.id ?? null,
      token: useSession.getState().token,
      connected: useSession.getState().connected,
    });
    const originalFetch = window.fetch;
    const results = [];
    let calls = 0;
    try {
      for (const kind of [
        "401",
        "200",
        "204",
        "network-error",
        "boot",
        "reset",
        "direct-login",
        "auth-response",
        "upload",
      ]) {
        resetA();
        let deliver!: (response: Response) => void;
        let reject!: (reason: Error) => void;
        let signal!: AbortSignal;
        window.fetch = async (_input, init) => {
          calls += 1;
          signal = init!.signal as AbortSignal;
          return await new Promise<Response>((resolve, failed) => {
            deliver = resolve;
            reject = failed;
          });
        };
        const pending = outcome(
          kind === "upload"
            ? uploadOriginal(
                new File(["synthetic original"], "Nguồn.xlsm"),
                "workbooks",
                "actor-A-upload",
              )
            : api(
                kind === "auth-response" ? "/auth/login" : "/old-request",
                {},
                kind !== "auth-response",
              ),
        );
        if (kind === "boot") {
          useSession
            .getState()
            .setBoot({
              ...boot,
              session_token: "synthetic-boot-B",
              data_root: "D:\\Synthetic-B",
            });
          useSession.getState().login("token-B", userB);
          useSession.getState().connection(false);
        } else if (kind === "reset") useSession.getState().reset();
        else if (kind === "direct-login") {
          useSession.getState().login("token-B", userB);
          useSession.getState().connection(false);
        } else switchB(kind === "network-error");
        const aborted = signal.aborted;
        if (kind === "network-error")
          reject(new TypeError("private A network error"));
        else
          deliver(
            kind === "204"
              ? new Response(null, { status: 204 })
              : new Response(
                  JSON.stringify(
                    kind === "401"
                      ? {
                          error: {
                            code: "SESSION_EXPIRED",
                            message: "private A expired",
                            field_errors: [],
                          },
                        }
                      : { owner: "A", private_A: "must never cross session" },
                  ),
                  { status: kind === "401" ? 401 : 200 },
                ),
          );
        results.push({
          kind,
          aborted,
          outcome: await pending,
          current: current(),
          boot: useSession.getState().boot?.session_token ?? null,
        });
      }
      for (const kind of ["json-body", "blob-body", "401-body"]) {
        resetA();
        let started!: () => void;
        let controller!: ReadableStreamDefaultController<Uint8Array>;
        let signal!: AbortSignal;
        const reading = new Promise<void>((resolve) => {
          started = resolve;
        });
        const body = new ReadableStream<Uint8Array>(
          {
            start(value) {
              controller = value;
            },
            pull() {
              started();
            },
          },
          { highWaterMark: 0 },
        );
        window.fetch = async (_input, init) => {
          calls += 1;
          signal = init!.signal as AbortSignal;
          return new Response(body, {
            status: kind === "401-body" ? 401 : 200,
          });
        };
        const pending = outcome(
          api("/body-gate", {}, true, kind === "blob-body" ? "blob" : "json"),
        );
        await reading; // The response headers are already handled; body consumption is pending.
        switchB();
        controller.enqueue(
          new TextEncoder().encode(
            kind === "401-body"
              ? '{"error":{"code":"SESSION_EXPIRED","message":"private A","field_errors":[]}}'
              : '{"owner":"A","private_A":true}',
          ),
        );
        controller.close();
        results.push({
          kind,
          aborted: signal.aborted,
          outcome: await pending,
          current: current(),
          boot: useSession.getState().boot.session_token,
        });
      }
      return { results, calls };
    } finally {
      window.fetch = originalFetch;
      useSession.getState().reset();
    }
  });
  expect(evidence.results).toHaveLength(12);
  for (const entry of evidence.results) {
    expect(entry.aborted, entry.kind).toBe(true);
    expect(entry.outcome, entry.kind).toEqual({
      resolved: false,
      code: "STALE_SESSION",
      isApiError: true,
    });
    expect(JSON.stringify(entry.outcome)).not.toContain("private_A");
    if (entry.kind === "reset")
      expect(entry.current).toEqual({
        id: null,
        token: null,
        connected: false,
      });
    else
      expect(entry.current).toEqual({
        id: "B",
        token: "token-B",
        connected: entry.kind === "network-error",
      });
    if (entry.kind === "boot") expect(entry.boot).toBe("synthetic-boot-B");
  }
  expect(evidence.calls).toBe(12);
});

test("actor change clears cached pages and private drafts before the new page arrives", async ({
  page,
}) => {
  let releaseB!: () => void;
  let requestedB!: () => void;
  const gateB = new Promise<void>((resolve) => {
    releaseB = resolve;
  });
  const newPageRequested = new Promise<void>((resolve) => {
    requestedB = resolve;
  });
  await page.addInitScript(() => {
    Object.assign(window, {
      __TAURI_INTERNALS__: {
        invoke: async (command: string) =>
          command === "desktop_status"
            ? { data_root: "D:\\Synthetic", running: false }
            : {
                protocol_version: 1,
                api_base: "http://127.0.0.1:19095/api/v1",
                session_token: "synthetic-app",
                data_root: "D:\\Synthetic",
              },
      },
    });
  });
  await page.route("http://127.0.0.1:19095/api/v1/**", async (route) => {
    const request = route.request();
    const headers = {
      "Access-Control-Allow-Origin": "http://127.0.0.1:1420",
      "Access-Control-Allow-Headers":
        "Content-Type,Authorization,X-App-Session",
      "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
    };
    if (request.method() === "OPTIONS") {
      await route.fulfill({ status: 204, headers });
      return;
    }
    if (request.url().endsWith("/health")) {
      await route.fulfill({
        json: { status: "ok", protocol_version: 1, setup_required: false },
        headers,
      });
      return;
    }
    if (request.url().endsWith("/auth/login")) {
      const actor = request.postDataJSON().username as string;
      await route.fulfill({
        json: {
          access_token: `token-${actor}`,
          user: {
            id: actor,
            username: actor,
            role: "admin",
            version: 1,
            permissions: ["*"],
          },
        },
        headers,
      });
      return;
    }
    const actor =
      request.headers().authorization === "Bearer token-B" ? "B" : "A";
    if (actor === "B") {
      requestedB();
      await gateB;
    }
    await route.fulfill({
      json: {
        items: [
          {
            id: "row-1",
            source_sheet: "Synthetic",
            source_row: 2,
            code: `${actor}-source`,
            description: `${actor}-private-description`,
            occurred_on: "2026-11-06",
            amount: "1.00",
            formula: "",
            issues: [],
          },
        ],
        total: 1,
        page: 1,
        page_size: 500,
      },
      headers,
    });
  });
  try {
    await page.goto("/");
    await page.getByLabel("Tên đăng nhập").fill("A");
    await page
      .getByLabel("Mật khẩu", { exact: true })
      .fill("synthetic-password");
    await page.getByRole("button", { name: "Đăng nhập", exact: true }).click();
    await page.getByRole("menuitem", { name: "Bản thử bảng tính" }).click();
    const grid = page.getByRole("grid", { name: "Grid projection" });
    await grid.getByText("A-source", { exact: true }).dblclick();
    await grid.getByRole("textbox").fill("A-private-draft");
    await grid.getByRole("textbox").press("Enter");
    await expect(
      grid.getByText("A-private-draft", { exact: true }),
    ).toBeVisible();
    await page.evaluate(async () => {
      const module = "/src/shared/session.ts";
      const { useSession } = await import(module);
      useSession.getState().logout();
    });
    await page.getByLabel("Tên đăng nhập").fill("B");
    await page
      .getByLabel("Mật khẩu", { exact: true })
      .fill("synthetic-password");
    await page.getByRole("button", { name: "Đăng nhập", exact: true }).click();
    await newPageRequested;
    await expect(
      grid.getByText("A-private-draft", { exact: true }),
    ).toHaveCount(0);
    await expect(
      grid.getByText("A-private-description", { exact: true }),
    ).toHaveCount(0);
    await expect(
      page.getByText("Bản nháp chưa lưu", { exact: true }),
    ).toHaveCount(0);
    releaseB();
    await expect(grid.getByText("B-source", { exact: true })).toBeVisible();
    await expect(grid.getByText("A-source", { exact: true })).toHaveCount(0);
  } finally {
    releaseB();
  }
});
