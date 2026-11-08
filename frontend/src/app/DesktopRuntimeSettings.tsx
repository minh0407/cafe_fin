import { useEffect, useRef, useState } from "react";
import { Alert, Button, Modal, Space, Switch, Typography } from "antd";
import {
  desktop,
  hasNativeDesktop,
  messageOf,
  type DesktopRuntimeStatus,
} from "../shared/api";
import { useSession } from "../shared/session";
import { maintenanceHeld } from "../shared/types";

export function DesktopRuntimeSettings() {
  const [open, setOpen] = useState(false);
  const [status, setStatus] = useState<DesktopRuntimeStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const generation = useSession((state) => state.generation);
  const held = useSession((state) => maintenanceHeld(state.boot));
  const native = hasNativeDesktop();
  const mounted = useRef(false);
  const sequence = useRef(0);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      sequence.current += 1;
    };
  }, []);

  async function readOrSet(enabled?: boolean) {
    const id = ++sequence.current;
    const owner = useSession.getState().generation;
    const current = () =>
      mounted.current &&
      sequence.current === id &&
      useSession.getState().generation === owner &&
      !maintenanceHeld(useSession.getState().boot);
    if (!native || held) return;
    setBusy(true);
    setError("");
    try {
      const value =
        enabled === undefined
          ? await desktop.runtimeStatus()
          : await desktop.setStartup(enabled);
      if (current()) setStatus(value);
    } catch (err) {
      if (current()) {
        setStatus(null);
        setError(messageOf(err));
      }
    } finally {
      if (current()) setBusy(false);
    }
  }
  useEffect(() => {
    sequence.current += 1;
    setStatus(null);
    setError("");
    setBusy(false);
    if (open && native && !held) void readOrSet();
    return () => {
      sequence.current += 1;
    };
  }, [open, native, generation, held]);

  return (
    <>
      <Button
        aria-label="Cài đặt chạy nền"
        onClick={() => setOpen(true)}
      >
        Chạy nền
      </Button>
      <Modal
        title="Khởi động và chạy nền"
        open={open}
        onCancel={() => {
          sequence.current += 1;
          setOpen(false);
        }}
        footer={
          <Button
            onClick={() => {
              sequence.current += 1;
              setOpen(false);
            }}
          >
            Đóng cài đặt
          </Button>
        }
      >
        <Space orientation="vertical" className="full">
          <Typography.Paragraph>
            Đóng cửa sổ bằng nút X sẽ thu ứng dụng về khay; tác vụ và lịch local
            tiếp tục khi máy đang hoạt động. Chọn Mở Cafe Fin ở khay để mở lại
            cửa sổ.
          </Typography.Paragraph>
          <Typography.Paragraph>
            Chọn Thoát ở khay sẽ dừng xử lý và lịch chạy. Ứng dụng yêu cầu xác
            nhận vì nháp chưa lưu sẽ mất. Máy ngủ hoặc tắt thì lịch không chạy.
          </Typography.Paragraph>
          <Typography.Paragraph>
            Tự mở cùng Windows mặc định tắt. Bật tùy chọn này không lưu mật khẩu
            và không tự đăng nhập.
          </Typography.Paragraph>
          {!native ? (
            <Alert
              type="info"
              showIcon
              title="Chỉ có trong ứng dụng Windows"
              description="Bản xem thử trên browser không thay đổi cấu hình khởi động hoặc chạy ở khay Windows."
            />
          ) : held ? (
            <Alert
              type="warning"
              showIcon
              title="Dữ liệu đang chờ phục hồi"
              description="Giữ trạng thái hiện tại. Kiểm tra cài đặt khởi động sau khi hoàn tất phục hồi dữ liệu."
            />
          ) : (
            <>
              <Space>
                <Switch
                  aria-label="Tự mở cùng Windows"
                  checked={status?.startup_enabled ?? false}
                  disabled={busy || !status?.startup_supported}
                  loading={busy}
                  onChange={(value) => void readOrSet(value)}
                />
                <Typography.Text>Tự mở cùng Windows</Typography.Text>
              </Space>
              {status && (
                <Typography.Text type="secondary">
                  {!status.startup_supported
                    ? "Phiên bản này chưa hỗ trợ thiết lập tự mở cùng Windows."
                    : status.startup_enabled
                      ? "Đã bật cho tài khoản Windows hiện tại."
                      : "Đang tắt cho tài khoản Windows hiện tại."}
                </Typography.Text>
              )}
              {error && <Alert type="error" showIcon title={error} />}
              <Button disabled={busy} onClick={() => void readOrSet()}>
                Kiểm tra trạng thái khởi động
              </Button>
            </>
          )}
        </Space>
      </Modal>
    </>
  );
}
