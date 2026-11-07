import type { BootSession, DesktopStatus } from "./types";

// Set only by the separate Docker preview build. Desktop releases keep native IPC.
declare const __CAFE_FIN_BROWSER_PREVIEW__: boolean;
export const isBrowserPreview = typeof __CAFE_FIN_BROWSER_PREVIEW__ !== "undefined" && __CAFE_FIN_BROWSER_PREVIEW__ === true;
export const previewNativeLimitation =
  "Bản xem thử Docker không hỗ trợ thao tác Windows này. Hãy dùng ứng dụng Windows để chọn thư mục, khởi động lại, mở báo cáo hoặc sao lưu/chuyển/khôi phục dữ liệu.";

const previewOrigin = "http://127.0.0.1:1420";
const bootstrapFailure = "Chưa kết nối được bản xem thử Docker. Mở http://127.0.0.1:1420 và tải lại trang để thử kết nối.";

export async function browserPreviewStart(): Promise<BootSession> {
  if (!isBrowserPreview || window.location.origin !== previewOrigin)
    throw new Error(bootstrapFailure);
  try {
    const response = await fetch(`${previewOrigin}/preview/bootstrap`, {
      method: "POST",
      headers: { "X-Preview-Bootstrap": "1" },
      credentials: "omit",
      redirect: "error",
      cache: "no-store",
      signal: AbortSignal.timeout(15000),
    });
    if (!response.ok) throw new Error(bootstrapFailure);
    const boot: unknown = await response.json();
    if (!boot || typeof boot !== "object") throw new Error(bootstrapFailure);
    const value = boot as Record<string, unknown>;
    if (value.protocol_version !== 1 || value.api_base !== `${previewOrigin}/api/v1` ||
      value.data_root !== "/data" || typeof value.session_token !== "string" ||
      !/^[A-Za-z0-9_-]{32,128}$/.test(value.session_token) ||
      value.maintenance_protocol != null || value.generation != null ||
      (value.runtime_state != null && value.runtime_state !== "ACTIVE") ||
      value.pending_transition != null)
      throw new Error(bootstrapFailure);
    // Return only the preview contract. Tokens remain in the existing memory-only
    // session store; never browser storage, a URL, logging, or a native shim.
    return {
      protocol_version: 1,
      api_base: `${previewOrigin}/api/v1`,
      session_token: value.session_token,
      data_root: "/data",
      runtime_state: "ACTIVE",
    };
  } catch {
    throw new Error(bootstrapFailure);
  }
}

export async function browserPreviewStatus(): Promise<DesktopStatus> {
  const boot = await browserPreviewStart();
  return { data_root: boot.data_root, running: true, runtime_state: "ACTIVE" };
}
