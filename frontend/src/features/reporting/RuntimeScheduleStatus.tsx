import { useEffect, useRef, useState } from "react";
import { Alert, Button, Space, Typography } from "antd";
import { api, messageOf } from "../../shared/api";
import type { Settings } from "./types";

const labels: Record<string, string> = {
  UNBOUND: "Chưa đăng ký",
  NEW: "Chưa khởi động",
  RUNNING: "Đang chạy",
  IDLE: "Không có tác vụ",
  STOPPING: "Đang dừng",
  STOPPED: "Đã dừng",
  FAILED: "Lỗi",
};

export function RuntimeScheduleStatus({
  settings,
}: {
  settings: Settings | null;
}) {
  const [current, setCurrent] = useState(settings);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [revision, setRevision] = useState(0);
  const sequence = useRef(0);
  const manualKey = useRef<string | null>(null);
  useEffect(() => {
    ++sequence.current;
    setCurrent(settings);
  }, [settings]);
  useEffect(() => {
    let mounted = true;
    async function load() {
      const request = ++sequence.current;
      try {
        const value = await api<Settings>("/reporting/settings");
        if (mounted && request === sequence.current) {
          setCurrent(value);
          setError("");
        }
      } catch (cause) {
        if (mounted && request === sequence.current) setError(messageOf(cause));
      }
    }
    void load();
    const timer = setInterval(() => void load(), 30000);
    return () => {
      mounted = false;
      clearInterval(timer);
    };
  }, [revision]);
  const status = current?.scheduler_status;
  const title = !status
    ? "Đang đọc trạng thái lịch nền"
    : `Lịch nền: ${status.state === "RUNNING" && !status.running ? "Không hoạt động" : (labels[status.state] ?? status.state)}`;
  return (
    <Space orientation="vertical" style={{ display: "flex", marginBlock: 12 }}>
      <Alert
        type={
          status?.error_code || status?.task_error_code
            ? "error"
            : status && (!status.registered || !status.running)
              ? "warning"
              : "info"
        }
        title={title}
        description={
          <Space orientation="vertical">
            <Typography.Text>
              {current?.scheduler_limit ?? "Chưa có trạng thái từ backend."}
            </Typography.Text>
            {status && (
              <Typography.Text>
                Lượt kiểm tra nền: {status.runs}; lượt lỗi: {status.failures}.
                {status.active ? " Đang kiểm tra lịch." : ""}
                {status.error_code
                  ? ` Lỗi hiện tại: ${status.error_code}.`
                  : ""}
                {status.task_error_code
                  ? ` Lỗi tác vụ: ${status.task_error_code}.`
                  : ""}
                {status.last_error_code
                  ? ` Mã lỗi gần nhất: ${status.last_error_code}.`
                  : ""}
              </Typography.Text>
            )}
          </Space>
        }
      />
      {error && <Alert type="error" title={error} />}
      {notice && <Alert type="info" title={notice} />}
      <Button
        aria-label="Yêu cầu kiểm tra lịch ngay"
        loading={busy}
        onClick={() => {
          setBusy(true);
          setNotice("");
          manualKey.current ??= crypto.randomUUID();
          void api("/reporting/scheduler/tick", {
            method: "POST",
            body: JSON.stringify({ request_key: manualKey.current }),
          })
            .then(() => {
              manualKey.current = null;
              setNotice(
                "Đã xếp yêu cầu kiểm tra; xem kết quả ở lịch sử tạo và lượt gửi.",
              );
              setRevision((value) => value + 1);
            })
            .catch((cause) => setError(messageOf(cause)))
            .finally(() => setBusy(false));
        }}
      >
        Yêu cầu kiểm tra lịch ngay
      </Button>
    </Space>
  );
}
