import { invoke } from "@tauri-apps/api/core";
import { useSession } from "./session";
import { browserPreviewStart, browserPreviewStatus, isBrowserPreview, previewNativeLimitation } from "./browserPreview";
import type {
  BootSession,
  DesktopStatus,
  ErrorEnvelope,
  FileCategory,
  FileDTO,
  MaintenanceKind,
  MaintenanceResult,
  MaintenanceView,
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
export interface DesktopRuntimeStatus {
  startup_enabled: boolean;
  startup_supported: boolean;
}
export function hasNativeDesktop(): boolean {
  if (isBrowserPreview || typeof window === "undefined") return false;
  const bridge = (window as unknown as { __TAURI_INTERNALS__?: { invoke?: unknown } }).__TAURI_INTERNALS__;
  return typeof bridge?.invoke === "function";
}
export const desktop = {
  status: () => isBrowserPreview ? browserPreviewStatus() : invoke<DesktopStatus>("desktop_status"),
  chooseDataRoot: () => isBrowserPreview ? previewUnsupported<string | null>() : invoke<string | null>("choose_data_root"),
  start: (initialize: boolean) =>
    isBrowserPreview ? browserPreviewStart() : invoke<BootSession>("start_backend", { initialize }),
  restart: () => isBrowserPreview ? previewUnsupported<BootSession>() : invoke<BootSession>("restart_backend"),
  // Contract v1: while a transition is pending native may ONLY attach to an
  // existing verified child here; no spawn/restart/config fallback is allowed.
  attach: () => nativeMaintenance<BootSession>("start_backend", { initialize: false }),
  maintenanceBegin: (kind: MaintenanceKind) => nativeMaintenance<MaintenanceView>("maintenance_begin", { kind }),
  maintenanceSelect: (operationId: string, purpose: "destination" | "backup_source") =>
    nativeMaintenance<MaintenanceView | null>("maintenance_select", { operationId, purpose }),
  maintenanceRun: (operationId: string, userToken: string) =>
    nativeMaintenance<MaintenanceResult>("maintenance_run", { operationId, userToken }),
  maintenanceStatus: (operationId: string, userToken: string) =>
    nativeMaintenance<MaintenanceResult>("maintenance_status", { operationId, userToken }),
  maintenanceActivate: (operationId: string, userToken: string) =>
    nativeMaintenance<MaintenanceResult>("maintenance_activate", { operationId, userToken }),
  openReports: (userToken: string) => nativeMaintenance<null>("open_reports", { userToken }),
  runtimeStatus: () => nativeRuntimeStatus("desktop_runtime_status"),
  setStartup: (enabled: boolean) => nativeRuntimeStatus("set_desktop_startup", { enabled }),
  backgroundReady: () => nativeMaintenance<void>("desktop_background_ready", {}),
};

async function nativeRuntimeStatus(command: string, args: Record<string, unknown> = {}): Promise<DesktopRuntimeStatus> {
  const value = await nativeMaintenance<unknown>(command, args);
  if (!value || typeof value !== "object" ||
    typeof (value as DesktopRuntimeStatus).startup_enabled !== "boolean" ||
    typeof (value as DesktopRuntimeStatus).startup_supported !== "boolean")
    throw new ApiError("STARTUP_UNAVAILABLE", nativeMessages.STARTUP_UNAVAILABLE);
  const status = value as DesktopRuntimeStatus;
  return { startup_enabled: status.startup_enabled, startup_supported: status.startup_supported };
}

async function previewUnsupported<T>(): Promise<T> {
  throw new ApiError("PREVIEW_NATIVE_UNAVAILABLE", previewNativeLimitation);
}

const nativeMessages: Record<string, string> = {
  PERMISSION_DENIED: "Tài khoản hiện tại không có quyền thực hiện thao tác này.",
  LOGIN_REQUIRED: "Vui lòng đăng nhập lại.",
  SESSION_EXPIRED: "Phiên đăng nhập đã hết hạn. Vui lòng đăng nhập lại.",
  MAINTENANCE_BUSY: "Một thao tác dữ liệu đang diễn ra. Hãy kiểm tra trạng thái hiện tại.",
  MAINTENANCE_UNSUPPORTED: "Phiên desktop hiện tại chưa hỗ trợ quản lý dữ liệu.",
  MAINTENANCE_HELD: "Chuyển dữ liệu đang được giữ để phục hồi an toàn. Hãy kiểm tra trạng thái.",
  MAINTENANCE_RECOVERY_HELD: "Chưa xác minh được phiên dữ liệu đang giữ. Không khởi động lại hoặc chuyển về dữ liệu cũ.",
  GENERATION_MISMATCH: "Phiên dữ liệu đã thay đổi. Hãy kiểm tra trạng thái hiện tại.",
  BACKUP_EXISTS: "Thư mục sao lưu đã tồn tại; ứng dụng không ghi đè.",
  MOVE_DESTINATION_EXISTS: "Thư mục đích đã tồn tại; ứng dụng không ghi đè.",
  RESTORE_DESTINATION_EXISTS: "Thư mục đích đã tồn tại; ứng dụng không ghi đè.",
  SHUTDOWN_FAILED: "Dịch vụ chưa xác nhận dừng an toàn. Chưa thể hoàn tất chuyển dữ liệu.",
  STARTUP_CONFLICT: "Cấu hình khởi động hiện tại không khớp Cafe Fin. Ứng dụng giữ nguyên cấu hình đó.",
  STARTUP_UNAVAILABLE: "Chưa xác nhận được tùy chọn khởi động Windows. Hãy kiểm tra trạng thái trước khi thử lại.",
  STARTUP_COMMAND_INVALID: "Lệnh khởi động Cafe Fin không hợp lệ. Chưa thay đổi thiết lập Windows.",
};
export function isMaintenanceBoot(boot: BootSession | null | undefined): boot is BootSession & { generation: string } {
  return !!boot && boot.protocol_version === 1 && boot.maintenance_protocol === 1 &&
    typeof boot.generation === "string" && !!boot.generation && boot.generation.length <= 256 &&
    typeof boot.session_token === "string" && !!boot.session_token && boot.session_token.length <= 128 &&
    typeof boot.data_root === "string" && !!boot.data_root && boot.data_root.length <= 32768 &&
    typeof boot.api_base === "string" && /^http:\/\/127\.0\.0\.1:\d{1,5}\/api\/v1$/.test(boot.api_base) &&
    typeof boot.runtime_state === "string" && ["ACTIVE", "QUIESCING", "QUIESCED", "PREPARING", "PREPARED", "CLOSING", "CLOSED", "DORMANT", "ACTIVATING", "FAILED_HELD"].includes(boot.runtime_state);
}
async function nativeMaintenance<T>(command: string, args: Record<string, unknown>): Promise<T> {
  if (isBrowserPreview) return previewUnsupported<T>();
  try { return await invoke<T>(command, args); }
  catch (error) {
    // Native may reject with CODE: message. Never echo the remaining text: it
    // can include paths, tokens or arbitrary exception data.
    const code = typeof error === "string" ? /^([A-Z][A-Z0-9_]*)(?::|$)/.exec(error)?.[1] : undefined;
    throw new ApiError(code && nativeMessages[code] ? code : "NATIVE_RESULT_UNKNOWN",
      code && nativeMessages[code] ? nativeMessages[code] :
        "Chưa xác nhận được kết quả desktop. Kiểm tra trạng thái trước khi thử lại cùng thao tác.");
  }
}

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
