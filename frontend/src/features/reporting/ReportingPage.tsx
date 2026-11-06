import { useCallback, useEffect, useRef, useState } from "react";
import {
  Alert,
  Button,
  Card,
  Form,
  Input,
  Modal,
  Select,
  Space,
  Switch,
  Table,
  Tabs,
  Tag,
  Typography,
} from "antd";
import { api, messageOf } from "../../shared/api";
import { useSession } from "../../shared/session";
import type { Page } from "../../shared/types";
import type {
  Attempt,
  Delivery,
  DeliveryPage,
  ExportFile,
  Report,
  ReportDetail,
  ReportPage,
  Settings,
} from "./types";

const labels: Record<string, string> = {
  PREVIEW: "Đang xem trước",
  SAVED: "Đã lưu",
  WAITING: "Chờ gửi",
  SENDING: "Đang gửi",
  SENT: "Đã gửi",
  FAILED: "Lỗi",
  UNKNOWN: "Chưa rõ",
  UNCONFIGURED: "Chưa cấu hình",
};
const warningLabels: Record<string, string> = {
  PRODUCTION_BREAKDOWN_UNAVAILABLE:
    "Chưa đủ dữ liệu tách sản xuất khỏi nhập/xuất tổng.",
  HOLD_BREAKDOWN_UNAVAILABLE:
    "Không có dữ liệu giữ hàng riêng; không cộng thêm vào tồn.",
  CROSS_SOURCE_SNAPSHOT_NOT_ATTESTED:
    "Nguồn chưa xác nhận đọc đồng thời trong một snapshot.",
  NO_ENTERED_INVENTORY: "Chưa có dữ liệu tồn kho đã nhập.",
  NO_BOOKS_SELECTED: "Chưa chọn sổ kế toán.",
  MONEY_DATA_INCOMPLETE: "Một số sổ chưa có đủ mapping tiền.",
  UNINTERPRETED_MONEY_METRICS:
    "Một số chỉ tiêu tiền chưa có ngữ nghĩa xác nhận; chỉ hiển thị local.",
  MONEY_TOTALS_PARTIAL:
    "Sổ chưa có đủ cả tổng thu và chi; chỉ tiêu chưa có không được coi là 0.",
};
const moneyLabels: Record<string, string> = {
  cash_receipts: "Tổng thu tiền",
  cash_payments: "Tổng chi tiền",
  noncash_offsets: "Đối trừ không tiền",
  cash_receipt_deposits: "Cọc thu (trong tổng thu)",
  cash_payment_deposits: "Cọc chi (trong tổng chi)",
};
const status = (state: string) => (
  <Tag
    color={
      state === "SENT" ? "green" : state === "UNKNOWN" ? "orange" : undefined
    }
  >
    {labels[state] ?? state}
  </Tag>
);
const exact = (value: string) => {
  const [whole, fraction] = value.split(".");
  return (
    whole.replace(/\B(?=(\d{3})+(?!\d))/g, ".") +
    (fraction ? `,${fraction}` : "")
  );
};
function todayVN() {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Ho_Chi_Minh",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(new Date());
  const get = (key: string) => parts.find((x) => x.type === key)?.value;
  return `${get("year")}-${get("month")}-${get("day")}`;
}
const emptyReports: ReportPage = {
  items: [],
  total: 0,
  page: 1,
  page_size: 25,
};
const emptyDeliveries: DeliveryPage = {
  items: [],
  total: 0,
  page: 1,
  page_size: 25,
};

export function ReportingPage() {
  const generation = useSession((state) => state.generation);
  return <ReportingView key={generation} />;
}

function ReportingView() {
  const user = useSession((state) => state.user);
  const generation = useRef(useSession.getState().generation).current;
  const live = useCallback(
    () => useSession.getState().generation === generation,
    [generation],
  );
  const isAdmin = user?.role === "admin";
  const query = new URLSearchParams(location.search);
  const [tab, setTab] = useState(query.get("reporting_tab") ?? "reports");
  const [page, setPage] = useState(
    Math.max(1, Number(query.get("reporting_page")) || 1),
  );
  const [search, setSearch] = useState(query.get("reporting_search") ?? "");
  const [filter, setFilter] = useState<string | undefined>(
    query.get("reporting_state") || undefined,
  );
  const [sort, setSort] = useState(
    query.get("reporting_sort") ?? "created_at:desc",
  );
  const [reports, setReports] = useState<ReportPage>(emptyReports);
  const [deliveries, setDeliveries] = useState<DeliveryPage>(emptyDeliveries);
  const [detail, setDetail] = useState<ReportDetail | null>(null);
  const [attempts, setAttempts] = useState<Page<Attempt> | null>(null);
  const [attemptOwner, setAttemptOwner] = useState("");
  const [attachment, setAttachment] = useState<string | undefined>();
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [settings, setSettings] = useState<Settings | null>(null);
  const [periodForm] = Form.useForm();
  const [settingsForm] = Form.useForm();
  const [secretForm] = Form.useForm();
  // Preserve each mutation's request key on ambiguous connection failure. Keys
  // and drafts are only in this actor-generation component, never persisted.
  const keys = useRef(new Map<string, string>());
  const listSequence = useRef(0);
  async function mutate<T>(
    path: string,
    payload: object,
    method = "POST",
  ): Promise<T> {
    const signature = `${path}:${JSON.stringify(payload)}`;
    const requestKey = keys.current.get(signature) ?? crypto.randomUUID();
    keys.current.set(signature, requestKey);
    const result = await api<T>(path, {
      method,
      body: JSON.stringify({ ...payload, request_key: requestKey }),
    });
    keys.current.delete(signature);
    return result;
  }
  async function action(operation: () => Promise<void>) {
    if (!live()) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await operation();
    } catch (cause) {
      if (live()) setError(messageOf(cause));
    } finally {
      if (live()) setBusy(false);
    }
  }
  const reload = useCallback(async () => {
    const sequence = ++listSequence.current;
    if (tab === "settings") return;
    const params = new URLSearchParams({
      page: String(page),
      page_size: "25",
      search,
      sort,
    });
    if (filter) params.set("state", filter);
    try {
      if (tab === "reports") {
        const result = await api<ReportPage>(`/reporting/reports?${params}`);
        if (live() && sequence === listSequence.current) setReports(result);
      } else {
        const result = await api<DeliveryPage>(
          `/reporting/deliveries?${params}`,
        );
        if (live() && sequence === listSequence.current) setDeliveries(result);
      }
    } catch (cause) {
      if (live() && sequence === listSequence.current)
        setError(messageOf(cause));
    }
  }, [tab, page, search, sort, filter, live]);
  useEffect(() => {
    const url = new URL(location.href);
    for (const [key, value] of Object.entries({
      reporting_tab: tab,
      reporting_page: String(page),
      reporting_search: search,
      reporting_sort: sort,
      reporting_state: filter ?? "",
    })) {
      if (value) url.searchParams.set(key, value);
      else url.searchParams.delete(key);
    }
    history.replaceState(null, "", url);
    void reload();
  }, [tab, page, search, sort, filter, reload]);
  useEffect(() => {
    // Core job runner owns execution. This heartbeat runs only while app UI is
    // mounted; native lifecycle timer/tray binding is a separate integration gate.
    const timer = setInterval(() => {
      if (!live()) return;
      void api("/reporting/scheduler/tick", {
        method: "POST",
        body: JSON.stringify({
          request_key: `ui-minute-${Math.floor(Date.now() / 60000)}`,
        }),
      })
        .then(() => reload())
        .catch((cause) => {
          if (live()) setError(messageOf(cause));
        });
    }, 60000);
    return () => clearInterval(timer);
  }, [reload, live]);
  useEffect(() => {
    if (!isAdmin) return;
    void api<Settings>("/reporting/settings")
      .then((result) => {
        if (live()) {
          setSettings(result);
          settingsForm.setFieldsValue(result);
        }
      })
      .catch((cause) => {
        if (live()) setError(messageOf(cause));
      });
  }, [isAdmin, settingsForm, live]);
  async function openReport(id: string) {
    const result = await api<ReportDetail>(
      `/reporting/reports/${encodeURIComponent(id)}`,
    );
    if (live()) {
      setDetail(result);
      setAttachment(undefined);
    }
  }
  async function download(file: ExportFile) {
    const blob = await api<Blob>(
      `/files/${encodeURIComponent(file.file_id)}/content`,
      {},
      true,
      "blob",
    );
    if (!live()) return;
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `CafeFin-tong-hop.${file.format}`;
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 60000);
  }
  async function loadAttempts(id: string, nextPage = 1) {
    const result = await api<Page<Attempt>>(
      `/reporting/deliveries/${encodeURIComponent(id)}/attempts?page=${nextPage}&page_size=25`,
    );
    if (live()) {
      setAttemptOwner(id);
      setAttempts(result);
    }
  }
  const reportColumns = [
    {
      title: "Mốc ngày đã lưu (VN)",
      key: "period",
      render: (_: unknown, row: Report) => `${row.from_on} → ${row.through_on}`,
    },
    { title: "Phiên bản", dataIndex: "version", key: "version" },
    { title: "Báo cáo", dataIndex: "state", key: "state", render: status },
    { title: "Tạo lúc", dataIndex: "created_at", key: "created_at" },
    {
      title: "",
      key: "open",
      render: (_: unknown, row: Report) => (
        <Button
          disabled={busy}
          onClick={() => void action(() => openReport(row.id))}
        >
          Xem bản {row.version}
        </Button>
      ),
    },
  ];
  const deliveryColumns = [
    {
      title: "Báo cáo",
      dataIndex: "report_id",
      key: "report",
      render: (id: string) => (
        <Button type="link" onClick={() => void action(() => openReport(id))}>
          {id.slice(0, 8)}
        </Button>
      ),
    },
    { title: "Nhóm đích", dataIndex: "destination", key: "destination" },
    { title: "Gửi", dataIndex: "state", key: "state", render: status },
    { title: "Lượt thử", dataIndex: "attempts", key: "attempts" },
    {
      title: "Kết quả",
      key: "result",
      render: (_: unknown, row: Delivery) =>
        row.error_code ?? row.message_id ?? "Chưa có xác nhận",
    },
    {
      title: "",
      key: "actions",
      render: (_: unknown, row: Delivery) => (
        <Space wrap>
          <Button
            disabled={busy}
            onClick={() => void action(() => loadAttempts(row.id))}
          >
            Nhật ký
          </Button>
          {["FAILED", "UNCONFIGURED"].includes(row.state) && (
            <Button
              disabled={busy}
              onClick={() =>
                void action(async () => {
                  await mutate(`/reporting/deliveries/${row.id}/retry`, {
                    expected_version: row.version,
                  });
                  await reload();
                })
              }
            >
              Thử lại
            </Button>
          )}
          {isAdmin && row.state === "UNKNOWN" && (
            <Button
              disabled={busy}
              onClick={() =>
                void action(async () => {
                  await mutate(`/reporting/deliveries/${row.id}/reconcile`, {
                    expected_version: row.version,
                  });
                  if (live())
                    setNotice(
                      "Đã yêu cầu đối chiếu. Nếu chưa có bằng chứng, trạng thái vẫn Chưa rõ và không tự gửi lại.",
                    );
                  await reload();
                })
              }
            >
              Đối chiếu
            </Button>
          )}
        </Space>
      ),
    },
  ];
  const inventoryColumns = [
    {
      title: "Kho / loại",
      key: "scope",
      render: (_: unknown, row: { warehouse_id: string; product_id: string }) =>
        `${row.warehouse_id} / ${row.product_id}`,
    },
    ...(
      [
        ["opening_kg", "Đầu kỳ"],
        ["received_kg", "Nhập tổng"],
        ["issued_kg", "Xuất tổng"],
        ["closing_kg", "Cuối kỳ"],
      ] as const
    ).map(([key, title]) => ({
      title: `${title} kg`,
      dataIndex: key,
      key,
      render: exact,
    })),
  ];
  const movementColumns = [
    {
      title: "Kho / loại",
      key: "scope",
      render: (_: unknown, row: { warehouse_id: string; product_id: string }) =>
        `${row.warehouse_id} / ${row.product_id}`,
    },
    ...(
      [
        ["purchased_kg", "Mua"],
        ["sold_kg", "Bán"],
        ["production_input_kg", "Vào sản xuất"],
        ["production_output_kg", "Sản xuất ra"],
        ["transfer_in_kg", "Chuyển vào"],
        ["transfer_out_kg", "Chuyển ra"],
        ["adjustment_in_kg", "Điều chỉnh tăng"],
        ["adjustment_out_kg", "Điều chỉnh giảm"],
      ] as const
    ).map(([key, title]) => ({
      title: `${title} kg`,
      dataIndex: key,
      key,
      render: exact,
    })),
  ];
  const toolbar = (
    <Space wrap style={{ marginBottom: 16 }}>
      <Input.Search
        aria-label="Tìm báo cáo hoặc nhóm"
        placeholder={
          tab === "reports"
            ? "Tìm ngày hoặc mã báo cáo"
            : "Tìm nhóm hoặc mã lượt gửi"
        }
        value={search}
        onChange={(e) => {
          setSearch(e.target.value);
          setPage(1);
        }}
        allowClear
      />
      <Select
        aria-label="Lọc trạng thái"
        allowClear
        placeholder="Tất cả trạng thái"
        value={filter}
        style={{ width: 180 }}
        onChange={(value) => {
          setFilter(value);
          setPage(1);
        }}
        options={(tab === "reports"
          ? ["PREVIEW", "SAVED"]
          : ["WAITING", "SENDING", "SENT", "FAILED", "UNKNOWN", "UNCONFIGURED"]
        ).map((value) => ({ value, label: labels[value] }))}
      />
      <Select
        aria-label="Sắp xếp"
        value={sort}
        style={{ width: 180 }}
        onChange={(value) => {
          setSort(value);
          setPage(1);
        }}
        options={[
          { value: "created_at:desc", label: "Mới trước" },
          { value: "created_at:asc", label: "Cũ trước" },
          { value: "state:asc", label: "Theo trạng thái" },
          tab === "reports"
            ? { value: "version:desc", label: "Phiên bản báo cáo" }
            : { value: "attempts:desc", label: "Lượt thử nhiều trước" },
        ]}
      />
      <Button onClick={() => void reload()}>Làm mới</Button>
    </Space>
  );
  return (
    <Space orientation="vertical" size="large" style={{ display: "flex" }}>
      <Typography.Title level={2}>
        Báo cáo local &amp; gửi tổng hợp
      </Typography.Title>
      <Alert
        type="info"
        showIcon
        title="Chỉ tổng hợp dữ liệu đã nhập; không phải báo cáo tài chính pháp định."
        description="Báo cáo đã lưu giữ nguyên snapshot. Trạng thái lưu và trạng thái gửi được theo dõi riêng."
      />
      {error && (
        <Alert
          role="alert"
          type="error"
          showIcon
          title={error}
          closable
          onClose={() => setError("")}
        />
      )}
      {notice && <Alert type="info" showIcon title={notice} />}
      <Card title="Chọn kỳ và xem trước">
        <Typography.Paragraph>
          Kỳ gồm cả ngày đầu và ngày cuối theo giờ Việt Nam. Báo cáo một ngày:
          chọn hai ô cùng ngày.
        </Typography.Paragraph>
        <Form
          form={periodForm}
          layout="vertical"
          initialValues={{
            from_on: todayVN(),
            through_on: todayVN(),
            books: "",
            reason: "",
          }}
          onFinish={(values) =>
            void action(async () => {
              const result = await mutate<Report>(
                "/reporting/reports/preview",
                {
                  from_on: values.from_on,
                  through_on: values.through_on,
                  book_ids: String(values.books ?? "")
                    .split(",")
                    .map((x) => x.trim())
                    .filter(Boolean),
                  reason: values.reason ?? "",
                },
              );
              await openReport(result.id);
              await reload();
            })
          }
        >
          <Space wrap align="start">
            <Form.Item
              name="from_on"
              label="Từ ngày (VN)"
              rules={[{ required: true }]}
            >
              <Input type="date" />
            </Form.Item>
            <Form.Item
              name="through_on"
              label="Đến hết ngày (VN)"
              rules={[{ required: true }]}
            >
              <Input type="date" />
            </Form.Item>
            <Form.Item name="books" label="Mã sổ (cách bằng dấu phẩy)">
              <Input
                placeholder="Để trống nếu chưa chọn sổ"
                style={{ width: 320 }}
              />
            </Form.Item>
          </Space>
          <Form.Item
            name="reason"
            label="Lý do điều chỉnh (bắt buộc khi tạo lại cùng kỳ/sổ)"
          >
            <Input.TextArea maxLength={1000} rows={2} />
          </Form.Item>
          <Button htmlType="submit" type="primary" loading={busy}>
            Xem trước báo cáo
          </Button>
        </Form>
      </Card>
      <Tabs
        activeKey={tab}
        onChange={(value) => {
          setTab(value);
          setPage(1);
          setFilter(undefined);
          setSearch("");
          setSort("created_at:desc");
        }}
        items={[
          {
            key: "reports",
            label: "Báo cáo",
            children: (
              <>
                {toolbar}
                <Table
                  rowKey="id"
                  columns={reportColumns}
                  dataSource={reports.items}
                  pagination={{
                    current: page,
                    pageSize: 25,
                    total: reports.total,
                    showSizeChanger: false,
                    onChange: setPage,
                  }}
                />
              </>
            ),
          },
          {
            key: "deliveries",
            label: "Lượt gửi",
            children: (
              <>
                {toolbar}
                <Alert
                  type="warning"
                  style={{ marginBottom: 16 }}
                  title="Chưa rõ không được tự thử lại; cần đối chiếu xác nhận API."
                />
                <Table
                  rowKey="id"
                  columns={deliveryColumns}
                  dataSource={deliveries.items}
                  pagination={{
                    current: page,
                    pageSize: 25,
                    total: deliveries.total,
                    showSizeChanger: false,
                    onChange: setPage,
                  }}
                />
              </>
            ),
          },
          ...(isAdmin
            ? [
                {
                  key: "settings",
                  label: "Cấu hình Admin",
                  children: (
                    <Card title="Lịch local và Zalo OA GMF">
                      <Alert
                        type="info"
                        title={settings?.sender_status ?? "UNCONFIGURED"}
                        description={
                          settings?.scheduler_limit ??
                          "Hiện lịch cập nhật khi màn hình Báo cáo đang mở. Máy ngủ/tắt hoặc app đóng không gửi; mở lại xử lý các bản đã lưu còn chờ."
                        }
                      />
                      <Form
                        form={settingsForm}
                        layout="vertical"
                        onFinish={(values) =>
                          void action(async () => {
                            await mutate(
                              "/reporting/settings",
                              {
                                ...values,
                                send_at: values.send_at || null,
                                expected_version: settings?.version ?? 0,
                              },
                              "PUT",
                            );
                            const result = await api<Settings>(
                              "/reporting/settings",
                            );
                            if (live()) {
                              setSettings(result);
                              settingsForm.setFieldsValue(result);
                              setNotice("Đã lưu cấu hình.");
                            }
                          })
                        }
                      >
                        <Form.Item name="oa_id" label="OA ID">
                          <Input maxLength={128} />
                        </Form.Item>
                        <Form.Item name="group_id" label="Nhóm GMF đích">
                          <Input maxLength={128} />
                        </Form.Item>
                        <Form.Item
                          name="timezone"
                          label="Múi giờ lịch"
                          rules={[{ required: true }]}
                        >
                          <Input placeholder="Asia/Ho_Chi_Minh" />
                        </Form.Item>
                        <Form.Item name="send_at" label="Giờ gửi">
                          <Input type="time" />
                        </Form.Item>
                        <Form.Item
                          name="attachments_enabled"
                          label="Cho phép người dùng chọn tệp tổng hợp đính kèm"
                          valuePropName="checked"
                        >
                          <Switch />
                        </Form.Item>
                        <Form.Item
                          name="enabled"
                          label="Bật gửi theo lịch đối với báo cáo đã lưu"
                          valuePropName="checked"
                        >
                          <Switch />
                        </Form.Item>
                        <Button htmlType="submit" type="primary" loading={busy}>
                          Lưu cấu hình
                        </Button>
                      </Form>
                      {!settings?.credential_store_available && (
                        <Alert
                          type="warning"
                          title="Kho bí mật Windows chưa được kết nối; credential chưa thể lưu. Báo cáo local vẫn dùng được."
                        />
                      )}
                      <Form
                        form={secretForm}
                        layout="vertical"
                        preserve={false}
                        onFinish={(values) =>
                          void action(async () => {
                            try {
                              await api("/reporting/credentials", {
                                method: "PUT",
                                body: JSON.stringify({
                                  ...values,
                                  access_token: "",
                                }),
                              });
                              if (live())
                                setNotice(
                                  "Đã lưu credential trong kho bí mật.",
                                );
                            } finally {
                              secretForm.resetFields();
                            }
                          })
                        }
                      >
                        <Form.Item
                          name="app_id"
                          label="App ID"
                          rules={[{ required: true }]}
                        >
                          <Input autoComplete="off" />
                        </Form.Item>
                        <Form.Item
                          name="app_secret"
                          label="App secret"
                          rules={[{ required: true }]}
                        >
                          <Input.Password autoComplete="new-password" />
                        </Form.Item>
                        <Form.Item
                          name="refresh_token"
                          label="Refresh token"
                          rules={[{ required: true }]}
                        >
                          <Input.Password autoComplete="new-password" />
                        </Form.Item>
                        <Space wrap>
                          <Button
                            htmlType="submit"
                            loading={busy}
                            disabled={!settings?.credential_store_available}
                          >
                            Lưu credential
                          </Button>
                          <Button
                            disabled={busy}
                            onClick={() =>
                              void action(async () => {
                                const result = await mutate<{
                                  state: string;
                                  code: string | null;
                                }>("/reporting/connection-check", {});
                                if (live())
                                  setNotice(
                                    `Kiểm tra kết nối: ${result.state}${result.code ? ` (${result.code})` : ""}. Chưa gửi tin.`,
                                  );
                              })
                            }
                          >
                            Kiểm tra kết nối
                          </Button>
                        </Space>
                      </Form>
                    </Card>
                  ),
                },
              ]
            : []),
        ]}
      />
      <Modal
        open={!!detail}
        title="Snapshot báo cáo"
        width={1100}
        onCancel={() => {
          setDetail(null);
          setAttachment(undefined);
        }}
        footer={null}
        destroyOnHidden
      >
        {detail && (
          <Space
            orientation="vertical"
            size="middle"
            style={{ display: "flex" }}
          >
            <Space>
              {status(detail.state)}
              <Typography.Text>
                Phiên bản {detail.version} • {detail.from_on}{" "}
                {detail.snapshot.period.date_range_contract ===
                "inclusive_business_dates_v1"
                  ? "đến hết"
                  : "/"}{" "}
                {detail.through_on}
              </Typography.Text>
            </Space>
            <Typography.Text copyable>SHA-256: {detail.sha256}</Typography.Text>
            <Typography.Text>Cutoff: {detail.snapshot.cutoff}</Typography.Text>
            {detail.snapshot.period.date_range_contract !==
              "inclusive_business_dates_v1" && (
              <Alert
                type="warning"
                title="Kỳ cũ chưa định danh cách chọn ngày. Bản cũ giữ nguyên; tạo bản điều chỉnh để dùng ngày cuối được bao gồm."
              />
            )}
            {detail.reason && (
              <Typography.Paragraph>
                Lý do: {detail.reason}
              </Typography.Paragraph>
            )}
            {detail.snapshot.warnings.map((code) => (
              <Alert
                key={code}
                type="warning"
                title={warningLabels[code] ?? code}
              />
            ))}
            <Table
              size="small"
              rowKey={(row) => `${row.warehouse_id}:${row.product_id}`}
              dataSource={detail.snapshot.sources.inventory.items}
              columns={inventoryColumns}
              pagination={{ pageSize: 10 }}
              scroll={{ x: 850 }}
            />
            {detail.snapshot.sources.inventory.movement_breakdown && (
              <>
                <Alert
                  type="info"
                  title="Các thành phần nằm trong nhập/xuất tổng; không cộng thêm vào tồn."
                />
                <Table
                  size="small"
                  rowKey={(row) => `${row.warehouse_id}:${row.product_id}`}
                  dataSource={
                    detail.snapshot.sources.inventory.movement_breakdown
                  }
                  columns={movementColumns}
                  pagination={{ pageSize: 10 }}
                  scroll={{ x: 1500 }}
                />
              </>
            )}
            {detail.snapshot.sources.books.map((book) => (
              <Card
                key={book.book_id}
                size="small"
                title={`Sổ ${book.book_id}`}
              >
                {!book.has_valid_money_mapping || !book.metrics.length ? (
                  <Typography.Text>Chưa đủ dữ liệu tiền</Typography.Text>
                ) : (
                  book.metrics.map((metric) => (
                    <Typography.Paragraph key={metric.key}>
                      {moneyLabels[metric.meaning ?? ""] ??
                        `Chỉ tiêu chưa diễn giải: ${metric.key}`}
                      : {exact(metric.amount_vnd)} VND (mapping v
                      {metric.mapping_revision})
                    </Typography.Paragraph>
                  ))
                )}
              </Card>
            ))}
            <Typography.Paragraph style={{ whiteSpace: "pre-wrap" }}>
              {detail.short_message}
            </Typography.Paragraph>
            <Space wrap>
              {detail.state === "PREVIEW" && (
                <Button
                  type="primary"
                  loading={busy}
                  onClick={() =>
                    void action(async () => {
                      await mutate(`/reporting/reports/${detail.id}/save`, {
                        expected_version: detail.version,
                      });
                      await openReport(detail.id);
                      await reload();
                    })
                  }
                >
                  Lưu snapshot
                </Button>
              )}
              {detail.state === "SAVED" &&
                (["pdf", "xlsx", "txt"] as const).map((format) => (
                  <Button
                    key={format}
                    disabled={busy}
                    onClick={() =>
                      void action(async () => {
                        const file = await mutate<ExportFile>(
                          `/reporting/reports/${detail.id}/exports`,
                          { format },
                        );
                        await openReport(detail.id);
                        await download(file);
                      })
                    }
                  >
                    Xuất {format.toUpperCase()}
                  </Button>
                ))}
            </Space>
            {detail.state === "SAVED" && (
              <Space wrap>
                <Select
                  aria-label="Tệp tổng hợp đính kèm"
                  style={{ width: 290 }}
                  allowClear
                  value={attachment}
                  placeholder="Không đính kèm tệp"
                  onChange={setAttachment}
                  options={detail.exports.map((file) => ({
                    value: file.id,
                    label: `Tổng hợp ${file.format.toUpperCase()} - ${file.sha256.slice(0, 8)}`,
                  }))}
                />
                <Button
                  disabled={
                    busy ||
                    detail.snapshot.period.date_range_contract !==
                      "inclusive_business_dates_v1"
                  }
                  onClick={() =>
                    void action(async () => {
                      const result = await mutate<Delivery>(
                        `/reporting/reports/${detail.id}/deliveries`,
                        { attachment_export_id: attachment ?? null },
                      );
                      if (live())
                        setNotice(
                          `Lượt gửi: ${labels[result.state]}. Báo cáo đã lưu vẫn giữ nguyên.`,
                        );
                    })
                  }
                >
                  Xếp gửi bản tổng hợp này
                </Button>
              </Space>
            )}
          </Space>
        )}
      </Modal>
      <Modal
        open={!!attempts}
        title="Nhật ký lượt gửi"
        width={900}
        footer={null}
        onCancel={() => setAttempts(null)}
      >
        <Table
          rowKey="id"
          dataSource={attempts?.items}
          columns={[
            { title: "Thời điểm", dataIndex: "created_at" },
            { title: "Bước", dataIndex: "phase" },
            { title: "Kết quả", dataIndex: "outcome", render: status },
            { title: "Mã lỗi", dataIndex: "code" },
            { title: "Message ID", dataIndex: "message_id" },
          ]}
          pagination={{
            current: attempts?.page ?? 1,
            pageSize: 25,
            total: attempts?.total ?? 0,
            showSizeChanger: false,
            onChange: (value) =>
              void action(() => loadAttempts(attemptOwner, value)),
          }}
        />
      </Modal>
    </Space>
  );
}
