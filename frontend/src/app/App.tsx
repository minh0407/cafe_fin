import { useEffect, useRef, useState } from "react";
import {
  Alert,
  Button,
  Card,
  Checkbox,
  Form,
  Input,
  Layout,
  Menu,
  Space,
  Spin,
  Tag,
  Typography,
} from "antd";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError, desktop, messageOf } from "../shared/api";
import { useSession } from "../shared/session";
import type { AuthResponse, Health } from "../shared/types";
import { GridSpike } from "../shared/GridSpike";
import { DocumentSpike } from "../shared/DocumentSpike";
import { modules } from "./registry";

export function App() {
  const session = useSession();
  const cache = useQueryClient();
  const [authForm] = Form.useForm();
  const [path, setPath] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [initialize, setInitialize] = useState(false);
  const [route, setRoute] = useState(location.hash.slice(1) || "/foundation");
  const initialized = useRef(false);
  useEffect(() => {
    const changed = () => setRoute(location.hash.slice(1) || "/foundation");
    addEventListener("hashchange", changed);
    return () => removeEventListener("hashchange", changed);
  }, []);
  useEffect(() => {
    if (initialized.current) return;
    initialized.current = true;
    void desktop
      .status()
      .then(async (status) => {
        setPath(status.data_root);
        if (status.data_root) {
          setBusy(true);
          try {
            useSession.getState().setBoot(await desktop.start(false));
          } finally {
            setBusy(false);
          }
        }
      })
      .catch((err) => setError(messageOf(err)));
  }, []);
  const health = useQuery({
    queryKey: ["health", session.boot?.api_base],
    queryFn: () => api<Health>("/health", {}, false),
    enabled: !!session.boot,
    refetchInterval: 5000,
    retry: false,
  });
  async function start(restart = false) {
    setBusy(true);
    setError("");
    cache.clear();
    useSession.getState().logout();
    try {
      useSession
        .getState()
        .setBoot(
          restart ? await desktop.restart() : await desktop.start(initialize),
        );
    } catch (err) {
      setError(messageOf(err));
    } finally {
      setBusy(false);
    }
  }
  async function authenticate(values: { username: string; password: string }) {
    setBusy(true);
    setError("");
    try {
      const auth = await api<AuthResponse>(
        health.data?.setup_required ? "/auth/setup" : "/auth/login",
        { method: "POST", body: JSON.stringify(values) },
        false,
      );
      useSession.getState().login(auth.access_token, auth.user);
      await health.refetch();
    } catch (err) {
      if (err instanceof ApiError)
        authForm.setFields(
          err.fields.map((field) => ({
            name: field.field,
            errors: [field.message],
          })),
        );
      setError(messageOf(err));
    } finally {
      setBusy(false);
    }
  }
  async function logout() {
    try {
      await api("/auth/logout", { method: "POST" });
    } catch (err) {
      setError(messageOf(err));
    } finally {
      useSession.getState().logout();
      cache.removeQueries({
        predicate: (query) => query.queryKey[0] !== "health",
      });
    }
  }
  const available = modules.filter(
    (module) =>
      session.user?.role === "admin" ||
      session.user?.permissions.includes("*") ||
      session.user?.permissions.includes(module.permission),
  );
  const routePath = route.split("?")[0];
  const selected = available
    .flatMap((module) => module.routes)
    .sort((a, b) => b.path.length - a.path.length)
    .find(
      (item) =>
        item.path === routePath || routePath.startsWith(`${item.path}/`),
    );
  return (
    <Layout className="shell">
      <Layout.Header className="header">
        <div>
          <strong>Cafe Fin</strong>
          <span>Dữ liệu trên máy của bạn</span>
        </div>
        <Space>
          <Tag color={session.connected && !health.error ? "green" : "orange"}>
            {session.connected && !health.error
              ? "Local đã kết nối"
              : "Chưa kết nối local"}
          </Tag>
          {session.user && (
            <>
              <span>{session.user.username}</span>
              <Button onClick={() => void logout()}>Đăng xuất</Button>
            </>
          )}
        </Space>
      </Layout.Header>
      {!session.boot ? (
        <Layout.Content className="setup">
          <Card title="Chọn nơi lưu dữ liệu" className="setup-card">
            <Typography.Paragraph>
              Chọn thư mục trên ổ local, ngoài OneDrive, Dropbox và các thư mục
              đồng bộ cloud. Chương trình và dữ liệu được lưu riêng. Thư mục đã
              cấu hình bị mất sẽ không tự tạo dữ liệu rỗng.
            </Typography.Paragraph>
            {path && <Typography.Paragraph code>{path}</Typography.Paragraph>}
            <Space orientation="vertical" className="full">
              <Button
                disabled={busy}
                onClick={() =>
                  void desktop
                    .chooseDataRoot()
                    .then((value) => {
                      if (value) {
                        setPath(value);
                        setInitialize(false);
                        setError("");
                      }
                    })
                    .catch((err) => setError(messageOf(err)))
                }
              >
                Chọn thư mục dữ liệu
              </Button>
              <Checkbox
                checked={initialize}
                disabled={busy || !path}
                onChange={(event) => setInitialize(event.target.checked)}
              >
                Khởi tạo dữ liệu mới tại thư mục đã chọn
              </Checkbox>
              <Button
                type="primary"
                loading={busy}
                disabled={!path}
                onClick={() => void start()}
              >
                Mở dữ liệu local
              </Button>
            </Space>
            {error && (
              <Alert className="toolbar" type="error" title={error} showIcon />
            )}
          </Card>
        </Layout.Content>
      ) : !session.user ? (
        <Layout.Content className="setup">
          <Card
            className="setup-card"
            title={
              health.data?.setup_required
                ? "Tạo tài khoản quản trị đầu tiên"
                : "Đăng nhập local"
            }
          >
            {(health.isPending || busy) && <Spin />}
            {error && <Alert type="error" title={error} showIcon />}
            {health.error && (
              <Alert
                type="error"
                title={messageOf(health.error)}
                action={
                  <Button onClick={() => void start(true)}>Kết nối lại</Button>
                }
                showIcon
              />
            )}
            <Form
              form={authForm}
              layout="vertical"
              onFinish={(values) => void authenticate(values)}
            >
              <Form.Item
                label="Tên đăng nhập"
                name="username"
                rules={[{ required: true, message: "Nhập tên đăng nhập." }]}
              >
                <Input autoComplete="username" />
              </Form.Item>
              <Form.Item
                label="Mật khẩu"
                name="password"
                rules={[{ required: true, message: "Nhập mật khẩu." }]}
              >
                <Input.Password
                  autoComplete={
                    health.data?.setup_required
                      ? "new-password"
                      : "current-password"
                  }
                />
              </Form.Item>
              <Button
                htmlType="submit"
                type="primary"
                disabled={!health.data || !!health.error}
                loading={busy}
              >
                {health.data?.setup_required
                  ? "Tạo quản trị và đăng nhập"
                  : "Đăng nhập"}
              </Button>
            </Form>
          </Card>
        </Layout.Content>
      ) : (
        <Layout>
          <Layout.Sider theme="light" width={220}>
            <Menu
              selectedKeys={[route]}
              items={[
                { key: "/foundation", label: "Nền tảng" },
                { key: "/grid-spike", label: "Bản thử bảng tính" },
                ...available.map((module) => ({
                  key: module.routes[0].path,
                  label: module.title,
                })),
              ]}
              onClick={({ key }) => {
                location.hash = key;
              }}
            />
          </Layout.Sider>
          <Layout.Content className="content">
            {(error || health.error || !session.connected) && (
              <Alert
                className="toolbar"
                type="error"
                title={
                  error ||
                  (health.error
                    ? messageOf(health.error)
                    : "Mất kết nối backend local.")
                }
                action={
                  <Button onClick={() => void start(true)}>
                    Khởi động lại kết nối
                  </Button>
                }
                showIcon
              />
            )}
            {route === "/grid-spike" ? (
              <GridSpike />
            ) : selected ? (
              <selected.component />
            ) : (
              <>
                <Typography.Title level={2}>Nền tảng Cafe Fin</Typography.Title>
                <Typography.Paragraph>
                  Foundation candidate cung cấp đăng nhập local, kết nối desktop
                  và bản thử kỹ thuật. Các module nghiệp vụ sẽ được tích hợp sau
                  khi điều phối duyệt baseline.
                </Typography.Paragraph>
                <Card title="Lưu trữ local">
                  <Typography.Paragraph code>
                    {session.boot.data_root}
                  </Typography.Paragraph>
                  <Typography.Text>
                    Thao tác local dùng kết nối thực tới backend; tình trạng
                    Internet không quyết định trạng thái lưu.
                  </Typography.Text>
                </Card>
                <DocumentSpike />
              </>
            )}
          </Layout.Content>
        </Layout>
      )}
    </Layout>
  );
}
