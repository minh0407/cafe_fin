import { invoke } from "@tauri-apps/api/core";
import { useSession } from "./session";
import type {
  BootSession,
  DesktopStatus,
  ErrorEnvelope,
  FileCategory,
  FileDTO,
} from "./types";

export class ApiError extends Error {
  constructor(
    public code: string,
    message: string,
    public requestId?: string,
    public fields: ErrorEnvelope["error"]["field_errors"] = [],
    public details: Record<string, unknown> = {},
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
  const assertCurrent = () => {
    if (
      session.generation !== useSession.getState().generation ||
      session.generationSignal.aborted
    )
      throw new ApiError(
        "STALE_SESSION",
        "Phiên dữ liệu đã thay đổi; phản hồi cũ đã bị bỏ qua.",
      );
  };
  const signal = AbortSignal.any([
    session.generationSignal,
    init.signal ?? AbortSignal.timeout(15000),
  ]);
  const headers = new Headers(init.headers);
  headers.set("X-App-Session", session.boot.session_token);
  if (auth && session.token)
    headers.set("Authorization", `Bearer ${session.token}`);
  if (typeof init.body === "string" && !headers.has("Content-Type"))
    headers.set("Content-Type", "application/json");
  let response: Response;
  try {
    response = await fetch(`${session.boot.api_base}${path}`, {
      ...init,
      headers,
      credentials: "omit",
      redirect: "error",
      signal,
    });
  } catch {
    assertCurrent();
    useSession.getState().connection(false);
    throw new ApiError(
      "BACKEND_UNAVAILABLE",
      "Mất kết nối dữ liệu local. Chưa xác nhận thao tác đã được lưu; kiểm tra lại trước khi gửi lại.",
    );
  }
  assertCurrent();
  if (!response.ok) {
    let envelope: ErrorEnvelope | undefined;
    let bodyComplete = false;
    try {
      envelope = (await response.json()) as ErrorEnvelope;
      bodyComplete = true;
    } catch {
      /* never expose a raw server response */
    }
    assertCurrent();
    useSession.getState().connection(bodyComplete);
    assertCurrent();
    if (response.status === 401 && auth) useSession.getState().logout();
    throw new ApiError(
      envelope?.error?.code ?? "API_ERROR",
      envelope?.error?.message ?? "Không thể hoàn thành thao tác.",
      envelope?.request_id,
      envelope?.error?.field_errors,
      envelope?.error?.details ?? {},
    );
  }
  if (response.status === 204) {
    assertCurrent();
    useSession.getState().connection(true);
    assertCurrent();
    return undefined as T;
  }
  try {
    const result =
      responseType === "blob" ? await response.blob() : await response.json();
    assertCurrent();
    useSession.getState().connection(true);
    assertCurrent();
    return result as T;
  } catch {
    assertCurrent();
    useSession.getState().connection(false);
    throw new ApiError(
      "INVALID_API_RESPONSE",
      "Không đọc được phản hồi từ dữ liệu local. Chưa xác nhận thao tác đã hoàn tất; kiểm tra lại trước khi gửi lại.",
    );
  }
}

export async function uploadOriginal(
  file: File,
  category: FileCategory,
  requestKey: string,
): Promise<FileDTO> {
  if (
    !Number.isSafeInteger(file.size) ||
    file.size < 0 ||
    file.size > 2 * 1024 ** 3
  )
    throw new ApiError("FILE_TOO_LARGE", "Tệp gốc vượt giới hạn 2 GiB.");
  if (!["workbooks", "documents", "imports", "reports"].includes(category))
    throw new ApiError("FILE_CATEGORY_INVALID", "Loại tệp không hợp lệ.");
  if (
    !file.name ||
    file.name.length > 255 ||
    /[\\/\u0000-\u001f\u007f]/.test(file.name)
  )
    throw new ApiError("FILE_NAME_INVALID", "Tên tệp gốc không hợp lệ.");
  if (!/^[\u0021-\u007e]{1,128}$/.test(requestKey))
    throw new ApiError(
      "INVALID_REQUEST_KEY",
      "Khóa chống ghi lặp không hợp lệ.",
    );
  const signal = AbortSignal.timeout(300000);
  try {
    // Pass the native File body directly; do not JSON/base64 encode or read the
    // entire workbook into application memory. A retry must reuse requestKey.
    return await api<FileDTO>(`/files?category=${category}`, {
      method: "POST",
      headers: {
        "Content-Type": file.type || "application/octet-stream",
        "X-File-Name": encodeURIComponent(file.name),
        "X-Request-Key": requestKey,
      },
      body: file,
      signal,
    });
  } catch (error) {
    if (error instanceof ApiError && error.code === "STALE_SESSION")
      throw error;
    if (signal.aborted)
      throw new ApiError(
        "UPLOAD_TIMEOUT",
        "Tải tệp quá thời hạn. Chưa xác nhận đã lưu; kiểm tra lại bằng cùng khóa yêu cầu.",
      );
    throw error;
  }
}

export function messageOf(error: unknown): string {
  return error instanceof Error
    ? error.message
    : "Không thể hoàn thành thao tác.";
}
