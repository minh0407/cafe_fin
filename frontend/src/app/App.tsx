import { useEffect, useRef, useState } from "react";
import {
  Alert,
  Button,
  Card,
  Checkbox,
  Empty,
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
import { api, ApiError, desktop, isMaintenanceBoot, messageOf } from "../shared/api";
import { useSession } from "../shared/session";
import { isBrowserPreview } from "../shared/browserPreview";
import { maintenanceHeld, type AuthResponse, type DesktopStatus, type Health } from "../shared/types";
import { GridSpike } from "../shared/GridSpike";
import { DocumentSpike } from "../shared/DocumentSpike";
import { modules } from "./registry";
import { LocalAccountsPage } from "./LocalAccountsPage";
import { DataManagementPanel } from "./DataManagementPanel";

// Technical proofs are opt-in development fixtures, never product navigation.
const showProofs = import.meta.env.DEV && import.meta.env.VITE_CAFE_FIN_PROOFS === "1";
const initialRoute = showProofs ? "/foundation" : "/records";

export function App() {
  const session = useSession();
  const cache = useQueryClient();
  const [authForm] = Form.useForm();
  const [path, setPath] = useState<string | null>(null);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState("");
  const [initialize, setInitialize] = useState(false);
  const [route, setRoute] = useState(location.hash.slice(1) || initialRoute);
  const initialized = useRef(false);
  const mounted = useRef(false);
  const [desktopState, setDesktopState] = useState<DesktopStatus | null>(null);
  const held = maintenanceHeld(session.boot);
  const setupHeld = !desktopState || desktopState.running || !!desktopState.pending_transition || (!!desktopState.runtime_state && desktopState.runtime_state !== "ACTIVE");
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  useEffect(() => {
    if (!held) return;
    void cache.cancelQueries({ predicate: (query) => query.queryKey[0] !== "health" });
    cache.removeQueries({ predicate: (query) => query.queryKey[0] !== "health" });
  }, [held, cache]);
  useEffect(
    () =>
      useSession.subscribe((current, previous) => {
        if (current.generation === previous.generation) return;
        void cache.cancelQueries();
        cache.clear();
        setError("");
        setBusy(false);
        authForm.resetFields();
      }),
    [cache, authForm],
  );
  useEffect(() => {
    const changed = () => setRoute(location.hash.slice(1) || initialRoute);
    addEventListener("hashchange", changed);
    return () => removeEventListener("hashchange", changed);
  }, []);
  useEffect(() => {
    if (initialized.current) return;
    initialized.current = true;
    let generation = useSession.getState().generation;
    void desktop
      .status()
      .then(async (status) => {
        if (!mounted.current || useSession.getState().generation !== generation) return;
        setDesktopState(status);
        setPath(status.data_root);
        if (status.data_root) {
          setBusy(true);
          try {
            const boot = await desktop.start(false);
            if (!mounted.current || useSession.getState().generation !== generation) return;
            useSession.getState().setBoot(boot);
            generation += 1;
          } finally {
            if (mounted.current && useSession.getState().generation === generation) setBusy(false);
          }
        } else setBusy(false);
      })
      .catch((err) => {
        if (mounted.current && useSession.getState().generation === generation) {
          setError(messageOf(err));
          setBusy(false);
        }
      });
  }, []);
  const health = useQuery({
    queryKey: ["health", session.generation, session.boot?.api_base],
    queryFn: () => api<Health>("/health", {}, false),
    // Core's maintenance admission allowlist keeps health/login/logout safe in
    // every held state, so an expired actor can authenticate for status again.
    enabled: !!session.boot,
    refetchInterval: held ? false : 5000,
    retry: false,
  });
  async function start(restart = false) {
    if (held || (!session.boot && setupHeld)) return;
    let generation = useSession.getState().generation + 1;
    useSession.getState().logout();
    if (useSession.getState().generation !== generation) return;
    setBusy(true);
    setError("");
    cache.clear();
    try {
      const boot = restart
        ? await desktop.restart()
        : await desktop.start(initialize);
      if (!mounted.current || useSession.getState().generation !== generation) return;
      useSession.getState().setBoot(boot);
      generation += 1;
    } catch (err) {
      if (mounted.current && useSession.getState().generation === generation)
        setError(messageOf(err));
    } finally {
      if (mounted.current && useSession.getState().generation === generation) setBusy(false);
    }
  }
  async function authenticate(values: { username: string; password: string }) {
    if (held && health.data?.setup_required) return;
    let generation = useSession.getState().generation;
    setBusy(true);
    setError("");
    try {
      const auth = await api<AuthResponse>(
        health.data?.setup_required ? "/auth/setup" : "/auth/login",
        { method: "POST", body: JSON.stringify(values) },
        false,
      );
      if (useSession.getState().generation !== generation) return;
      useSession.getState().login(auth.access_token, auth.user);
      generation += 1;
    } catch (err) {
      if (useSession.getState().generation !== generation) return;
      if (err instanceof ApiError)
        authForm.setFields(
          err.fields.map((field) => ({
            name: field.field,
            errors: [field.message],
          })),
        );
      setError(messageOf(err));
    } finally {
      if (useSession.getState().generation === generation) setBusy(false);
    }
  }
  async function logout() {
    const generation = useSession.getState().generation;
    let failure = "";
    setBusy(true);
    try {
      await api("/auth/logout", { method: "POST" });
    } catch (err) {
      if (useSession.getState().generation === generation)
        failure = messageOf(err);
    } finally {
      if (useSession.getState().generation === generation) {
        useSession.getState().logout();
        setBusy(false);
        if (failure) setError(failure);
      }
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
  async function chooseRoot() {
    if (busy || held || setupHeld) return;
    const generation = useSession.getState().generation;
    setBusy(true);
    try {
      const value = await desktop.chooseDataRoot();
      if (!mounted.current || useSession.getState().generation !== generation) return;
      if (value) { setPath(value); setInitialize(false); setError(""); }
    } catch (err) {
      if (mounted.current && useSession.getState().generation === generation) setError(messageOf(err));
    } finally { if (mounted.current && useSession.getState().generation === generation) setBusy(false); }
  }
  async function refreshDesktop() {
    const generation = useSession.getState().generation;
    setBusy(true);
    try {
      const status = await desktop.status();
      if (!mounted.current || useSession.getState().generation !== generation) return;
      // A missing summary is not an authorization to abandon a held recovery.
      if (status.pending_transition || status.running || desktopState === null) setDesktopState(status);
    } catch { if (mounted.current && useSession.getState().generation === generation) setError("Chưa đọc được trạng thái desktop. Dữ liệu vẫn được giữ an toàn."); }
    finally { if (mounted.current && useSession.getState().generation === generation) setBusy(false); }
  }
  async function attachDesktop() {
    const generation = useSession.getState().generation;
    const current = () => mounted.current && useSession.getState().generation === generation;
    setBusy(true); setError("");
    try {
      const status = await desktop.status();
      if (!current()) return;
      if (!status.running || (status.pending_transition && status.maintenance_protocol !== 1))
        throw new ApiError("MAINTENANCE_RECOVERY_HELD", "Chưa xác minh được phiên desktop đang chạy. Dữ liệu vẫn được giữ.");
      const boot = await desktop.attach();
      if (!current()) return;
      if (status.maintenance_protocol === 1 ? !isMaintenanceBoot(boot) : boot.protocol_version !== 1 || boot.maintenance_protocol != null)
        throw new ApiError("MAINTENANCE_RECOVERY_HELD", "Chưa xác minh được phiên dữ liệu desktop. Trạng thái hiện tại vẫn được giữ.");
      useSession.getState().setBoot(boot);
    } catch (err) { if (current()) setError(messageOf(err)); }
    finally { if (current()) setBusy(false); }
  }
  return (
    <Layout className="shell">
      <Layout.Header className="header">
        <div>
          <strong>Cafe Fin</strong>
          <span>Dữ liệu trên máy của bạn</span>
        </div>
        <Space>
          <Tag color={!held && session.connected && !health.error ? "green" : "orange"}>
            {held ? "Dữ liệu đang tạm giữ" : session.connected && !health.error
              ? "Local đã kết nối"
              : "Chưa kết nối local"}
          </Tag>
          {session.user && (
            <>
              <span>{session.user.username}</span>
              <Button loading={busy} onClick={() => void logout()}>
                Đăng xuất
              </Button>
            </>
          )}
        </Space>
      </Layout.Header>
      {isBrowserPreview && <Alert
        banner
        type="warning"
        title="Bản xem thử Docker trên máy này"
        description="Dữ liệu được lưu trong volume Docker. Bản xem thử Linux không có chọn thư mục Windows, sao lưu/chuyển/khôi phục hoặc mở thư mục báo cáo. Telegram chưa cấu hình vì không có kho bí mật Windows; vẫn có thể tạo và tải tệp báo cáo local."
      />}
      {!session.boot ? (
        <Layout.Content className="setup">
          <Card title="Chọn nơi lưu dữ liệu" className="setup-card">
            <Typography.Paragraph>
              Chọn thư mục trên ổ local, ngoài OneDrive, Dropbox và các thư mục
              đồng bộ cloud. Chương trình và dữ liệu được lưu riêng. Thư mục đã
              cấu hình bị mất sẽ không tự tạo dữ liệu rỗng.
            </Typography.Paragraph>
            {path && <Typography.Paragraph code>{path}</Typography.Paragraph>}
            {setupHeld ? <Space orientation="vertical">
              <Alert type="warning" title={!desktopState ? "Chưa xác nhận được trạng thái desktop" : desktopState.pending_transition ? "Chuyển dữ liệu đang chờ phục hồi" : "Phiên dữ liệu desktop đang chờ kết nối"} description="Giữ nguyên dữ liệu và cấu hình hiện tại. Không chọn lại, khởi tạo hoặc khởi động lại để hủy thao tác." />
              <Button loading={busy} onClick={() => void refreshDesktop()}>Kiểm tra trạng thái desktop</Button>
              {desktopState?.running && <Button disabled={busy} onClick={() => void attachDesktop()}>Kết nối phiên desktop hiện tại</Button>}
            </Space> : <Space orientation="vertical" className="full">
              <Button
                disabled={busy}
                onClick={() => void chooseRoot()}
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
            </Space>}
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
              health.data?.setup_required && !held
                ? "Tạo tài khoản quản trị đầu tiên"
                : "Đăng nhập local"
            }
          >
            {(health.isPending || busy) && <Spin />}
            {held && <Alert type="warning" title="Đăng nhập vào dữ liệu hiện tại để kiểm tra phục hồi" description="Cần tài khoản Admin của dữ liệu đích để kích hoạt. Đăng nhập chưa tự chạy nghiệp vụ." />}
            {error && <Alert type="error" title={error} showIcon />}
            {health.error && !held && (
              <Alert
                type="error"
                title={messageOf(health.error)}
                action={
                  <Button onClick={() => void start(true)}>Kết nối lại</Button>
                }
                showIcon
              />
            )}
            {held && health.data?.setup_required ? <Alert type="warning" title="Không khởi tạo tài khoản trong khi dữ liệu đang chờ phục hồi." /> : <Form
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
            </Form>}
            {held && <DataManagementPanel />}
          </Card>
        </Layout.Content>
      ) : (
        <Layout key={session.generation}>
          {!held && <Layout.Sider theme="light" width={220}>
            <Menu
              selectedKeys={[selected?.path ?? routePath]}
              items={[
                ...(showProofs ? [
                  { key: "/foundation", label: "Nền tảng" },
                  { key: "/grid-spike", label: "Bản thử bảng tính" },
                ] : []),
                ...available.map((module) => ({
                  key: module.routes[0].path,
                  label: module.title,
                })),
                { key: "/settings", label: "Cài đặt trên máy" },
              ]}
              onClick={({ key }) => {
                location.hash = key;
              }}
            />
          </Layout.Sider>}
          <Layout.Content className="content">
            {held && <Typography.Title level={2}>Phục hồi dữ liệu trên máy</Typography.Title>}
            {(held || routePath === "/settings") && <DataManagementPanel />}
            {!held && (error || health.error || !session.connected) && (
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
            {held ? null : showProofs && routePath === "/grid-spike" ? (
              <GridSpike />
            ) : selected ? (
              <selected.component />
            ) : routePath === "/settings" ? (
              <>
                <Typography.Title level={2}>Cài đặt trên máy</Typography.Title>
                <Card title="Thư mục dữ liệu">
                  <Typography.Paragraph code>{session.boot.data_root}</Typography.Paragraph>
                  <Typography.Paragraph>
                    Dữ liệu, chứng từ và báo cáo được lưu tại thư mục này trên máy.
                  </Typography.Paragraph>
                </Card>
                {session.user.role === "admin" && <LocalAccountsPage />}
              </>
            ) : showProofs && routePath === "/foundation" ? (
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
            ) : (
              <Empty description="Không tìm thấy trang hoặc tài khoản chưa có quyền xem.">
                <Button onClick={() => { location.hash = available[0]?.routes[0].path ?? "/settings"; }}>
                  Về trang chính
                </Button>
              </Empty>
            )}
          </Layout.Content>
        </Layout>
      )}
    </Layout>
  );
}
