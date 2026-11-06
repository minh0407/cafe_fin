import { test, expect } from "@playwright/test";

test("response bodies complete before connected status, and body failures stay sanitized", async ({
  page,
}) => {
  // Same-origin browser harness without the app's health polling, so it cannot
  // hide a client connection-state regression by changing the store concurrently.
  await page.route("**/body-phase-test", (route) =>
    route.fulfill({
      contentType: "text/html",
      body: "<!doctype html><html><body></body></html>",
    }),
  );
  await page.goto("/body-phase-test");
  const result = await page.evaluate(async () => {
    const apiModule = "/src/shared/api.ts";
    const sessionModule = "/src/shared/session.ts";
    const { api, ApiError } = await import(apiModule);
    const { useSession } = await import(sessionModule);
    const originalFetch = window.fetch;
    const reset = (connected = true) =>
      useSession.setState({
        boot: {
          protocol_version: 1,
          api_base: "http://127.0.0.1:19097/api/v1",
          session_token: "synthetic-body-app-session",
          data_root: "D:\\Synthetic",
        },
        token: "synthetic-body-user-session",
        user: {
          id: "synthetic",
          username: "synthetic",
          role: "admin",
          permissions: ["*"],
        },
        connected,
      });
    const failures = [];
    let calls = 0;
    try {
      for (const kind of ["json", "blob"] as const) {
        reset();
        window.fetch = async () => {
          calls += 1;
          if (kind === "json")
            return new Response(
              '{"saved":true,"sensitive":"synthetic workbook payload"',
              { status: 200, headers: { "Content-Type": "application/json" } },
            );
          const stream = new ReadableStream<Uint8Array>({
            start(controller) {
              controller.enqueue(new Uint8Array([80, 75, 3, 4]));
              controller.error(
                new DOMException(
                  "synthetic private document body failure",
                  "AbortError",
                ),
              );
            },
          });
          return new Response(stream, { status: 200 });
        };
        try {
          await api("/body-phase-probe", {}, true, kind);
        } catch (error) {
          failures.push({
            kind,
            isApiError: error instanceof ApiError,
            code: (error as { code: string }).code,
            message: (error as Error).message,
            connected: useSession.getState().connected,
          });
        }
      }
      reset(false);
      let started!: () => void;
      const bodyStarted = new Promise<void>((resolve) => {
        started = resolve;
      });
      let body!: ReadableStreamDefaultController<Uint8Array>;
      const delayed = new ReadableStream<Uint8Array>(
        {
          start(controller) {
            body = controller;
          },
          pull() {
            started();
          },
        },
        { highWaterMark: 0 },
      );
      window.fetch = async () => {
        calls += 1;
        return new Response(delayed, { status: 200 });
      };
      const pending = api("/body-phase-probe");
      await bodyStarted;
      const connectedBeforeBodyCompletes = useSession.getState().connected;
      body.enqueue(new TextEncoder().encode('{"complete":true}'));
      body.close();
      const valid = await pending;
      const connectedAfterBodyCompletes = useSession.getState().connected;

      reset(false);
      window.fetch = async () => {
        calls += 1;
        return new Response(null, { status: 204 });
      };
      await api("/body-phase-probe");
      const connectedAfter204 = useSession.getState().connected;

      reset();
      window.fetch = async () => {
        calls += 1;
        return new Response(
          JSON.stringify({
            error: {
              code: "SESSION_EXPIRED",
              message: "Phiên đăng nhập đã hết hạn.",
              field_errors: [],
            },
            request_id: "synthetic-body-request",
          }),
          { status: 401 },
        );
      };
      let unauthorized;
      try {
        await api("/body-phase-probe");
      } catch (error) {
        unauthorized = {
          code: (error as { code: string }).code,
          requestId: (error as { requestId: string }).requestId,
          token: useSession.getState().token,
          user: useSession.getState().user,
          connected: useSession.getState().connected,
        };
      }

      reset();
      window.fetch = async () => {
        calls += 1;
        return new Response("synthetic invalid error body", { status: 401 });
      };
      let invalidUnauthorized;
      try {
        await api("/body-phase-probe");
      } catch (error) {
        invalidUnauthorized = {
          isApiError: error instanceof ApiError,
          code: (error as { code: string }).code,
          token: useSession.getState().token,
          connected: useSession.getState().connected,
        };
      }
      return {
        failures,
        valid,
        connectedBeforeBodyCompletes,
        connectedAfterBodyCompletes,
        connectedAfter204,
        unauthorized,
        invalidUnauthorized,
        calls,
      };
    } finally {
      window.fetch = originalFetch;
    }
  });
  expect(result.failures).toHaveLength(2);
  for (const failure of result.failures) {
    expect(failure.isApiError).toBe(true);
    expect(failure.code).toBe("INVALID_API_RESPONSE");
    expect(failure.connected).toBe(false);
    expect(failure.message).toContain("Chưa xác nhận");
    expect(failure.message).not.toMatch(
      /synthetic|DOMException|SyntaxError|AbortError/,
    );
  }
  expect(result.connectedBeforeBodyCompletes).toBe(false);
  expect(result.valid).toEqual({ complete: true });
  expect(result.connectedAfterBodyCompletes).toBe(true);
  expect(result.connectedAfter204).toBe(true);
  expect(result.unauthorized).toEqual({
    code: "SESSION_EXPIRED",
    requestId: "synthetic-body-request",
    token: null,
    user: null,
    connected: true,
  });
  expect(result.invalidUnauthorized).toEqual({
    isApiError: true,
    code: "API_ERROR",
    token: null,
    connected: false,
  });
  expect(result.calls).toBe(6); // One explicit call per scenario, no automatic replay.
});
