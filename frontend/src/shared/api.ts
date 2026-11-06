import { invoke } from "@tauri-apps/api/core";
import { useSession } from "./session";
import type { BootSession, DesktopStatus, ErrorEnvelope } from "./types";

export class ApiError extends Error {
  constructor(
    public code: string,
    message: string,
    public requestId?: string,
    public fields: ErrorEnvelope["error"]["field_errors"] = [],
  ) {
    super(message);
  }
}
export const desktop = {
  status: () => invoke<DesktopStatus>("desktop_status"),
  chooseDataRoot: () => invoke<string | null>("choose_data_root"),
  start: (initialize: boolean) =>
    invoke<BootSession>("start_backend", { initialize }),
  restart: () => invoke<BootSession>("restart_backend"),
};

export async function api<T>(
  path: string,
  init: RequestInit = {},
  auth = true,
  responseType: "json" | "blob" = "json",
): Promise<T> {
  const session = useSession.getState();
  if (!session.boot)
    throw new ApiError("BACKEND_UNAVAILABLE", "Chưa kết nối dữ liệu local.");
  if (!/^\/[a-z0-9/_?=&%.,:+-]*$/i.test(path) || path.includes(".."))
    throw new ApiError("INVALID_API_PATH", "Đường dẫn API không hợp lệ.");
  const headers = new Headers(init.headers);
  headers.set("X-App-Session", session.boot.session_token);
  if (auth && session.token)
    headers.set("Authorization", `Bearer ${session.token}`);
  if (init.body && !(init.body instanceof FormData))
    headers.set("Content-Type", "application/json");
  let response: Response;
  try {
    response = await fetch(`${session.boot.api_base}${path}`, {
      ...init,
      headers,
      credentials: "omit",
      redirect: "error",
      signal: init.signal ?? AbortSignal.timeout(15000),
    });
  } catch {
    useSession.getState().connection(false);
    throw new ApiError(
      "BACKEND_UNAVAILABLE",
      "Mất kết nối dữ liệu local. Chưa xác nhận thao tác đã được lưu; kiểm tra lại trước khi gửi lại.",
    );
  }
  useSession.getState().connection(true);
  if (!response.ok) {
    let envelope: ErrorEnvelope | undefined;
    try {
      envelope = (await response.json()) as ErrorEnvelope;
    } catch {
      /* never expose a raw server response */
    }
    if (response.status === 401 && auth) useSession.getState().logout();
    throw new ApiError(
      envelope?.error?.code ?? "API_ERROR",
      envelope?.error?.message ?? "Không thể hoàn thành thao tác.",
      envelope?.request_id,
      envelope?.error?.field_errors,
    );
  }
  if (response.status === 204) return undefined as T;
  if (responseType === "blob") return (await response.blob()) as T;
  return (await response.json()) as T;
}
export function messageOf(error: unknown): string {
  return error instanceof Error
    ? error.message
    : "Không thể hoàn thành thao tác.";
}
