import { useEffect, useRef, useState } from "react";
import { Alert, Button, Card, Table, Tag } from "antd";
import { api, messageOf } from "../../shared/api";
import type { Page } from "../../shared/types";
import type { DailyRun } from "./types";

const states: Record<string, string> = {
  PENDING: "Chờ tạo",
  RUNNING: "Đang tạo",
  COMPLETED: "Đã tạo / xếp gửi",
  FAILED: "Lỗi; giữ dữ liệu đã có",
  MISSED: "Bỏ lỡ; cần tạo thủ công",
  NEEDS_MANUAL: "Cần xử lý thủ công",
  BLOCKED: "Bị chặn quyền",
};
const policies: Record<string, string> = {
  GENERATED_CURRENT_DAY: "Tạo ngày hiện tại",
  REUSED_SAVED_MANUAL: "Dùng bản thủ công đã lưu",
  REUSED_ALREADY_QUEUED_MANUAL: "Giữ bản thủ công đã xếp gửi",
  MISSED_NO_SNAPSHOT: "Không có snapshot kỳ đã xác định",
};

export function DailyScheduleHistory({
  onOpenReport,
}: {
  onOpenReport: (id: string) => void;
}) {
  const [page, setPage] = useState(1);
  const [revision, setRevision] = useState(0);
  const [result, setResult] = useState<Page<DailyRun>>({
    items: [],
    total: 0,
    page: 1,
    page_size: 25,
  });
  const [error, setError] = useState("");
  const sequence = useRef(0);
  useEffect(() => {
    let mounted = true;
    async function load() {
      const request = ++sequence.current;
      try {
        const response = await api<Page<DailyRun>>(
          `/reporting/scheduler/daily-runs?page=${page}&page_size=25`,
        );
        if (mounted && sequence.current === request) {
          setResult(response);
          setError("");
        }
      } catch (cause) {
        if (mounted && sequence.current === request) setError(messageOf(cause));
      }
    }
    void load();
    const timer = setInterval(() => void load(), 30000);
    return () => {
      mounted = false;
      clearInterval(timer);
    };
  }, [page, revision]);
  return (
    <Card
      title="Lượt tạo báo cáo cuối ngày"
      style={{ marginTop: 16 }}
      extra={
        <Button onClick={() => setRevision((x) => x + 1)}>
          Cập nhật trạng thái
        </Button>
      }
    >
      {error && <Alert type="error" title={error} />}
      <Table
        rowKey="id"
        size="small"
        dataSource={result.items}
        scroll={{ x: 950 }}
        columns={[
          { title: "Ngày VN", dataIndex: "business_on" },
          {
            title: "Tạo / lưu",
            dataIndex: "state",
            render: (value: string) => <Tag>{states[value] ?? value}</Tag>,
          },
          { title: "Bước", dataIndex: "phase" },
          {
            title: "Cách chọn bản",
            dataIndex: "policy",
            render: (value: string) => policies[value] ?? value,
          },
          { title: "Lượt thử", dataIndex: "attempts" },
          { title: "Mã lỗi", dataIndex: "error_code" },
          {
            title: "",
            key: "report",
            render: (_: unknown, row: DailyRun) =>
              row.report_id ? (
                <Button onClick={() => onOpenReport(row.report_id!)}>
                  Xem snapshot
                </Button>
              ) : (
                "Chưa có snapshot"
              ),
          },
        ]}
        pagination={{
          current: page,
          pageSize: 25,
          total: result.total,
          showSizeChanger: false,
          onChange: setPage,
        }}
      />
    </Card>
  );
}
