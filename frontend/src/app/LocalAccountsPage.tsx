import { useCallback, useEffect, useRef, useState } from "react";
import { Alert, Button, Card, Form, Input, Modal, Select, Space, Switch, Table, Tag, Typography } from "antd";
import { api, ApiError, messageOf } from "../shared/api";
import { useSession } from "../shared/session";
import type { FieldError, Page, User } from "../shared/types";

interface LocalAccount {
  id: string;
  username: string;
  role: "admin" | "operator";
  version: number;
  active: boolean;
}
interface CreateValues { username: string; password: string; role: LocalAccount["role"] }
interface EditValues { role: LocalAccount["role"]; active: boolean }
interface AccountCommand {
  kind: "create" | "edit";
  path: string;
  method: "POST" | "PATCH";
  body: string;
  targetId?: string;
}
interface VisibleError { message: string; code?: string; requestId?: string; fields: FieldError[] }

const roles = [{ value: "operator", label: "Nhân viên" }, { value: "admin", label: "Admin" }];
const definitiveCodes = new Set([
  "VALIDATION_ERROR", "INVALID_USERNAME", "WEAK_PASSWORD", "INVALID_ROLE",
  "USERNAME_EXISTS", "NOT_FOUND", "VERSION_CONFLICT", "LAST_ADMIN",
  "IDEMPOTENCY_CONFLICT", "DATA_CONFLICT", "PERMISSION_DENIED", "INVALID_REQUEST_KEY",
]);
function canManage(user: User | null): boolean {
  return !!user && user.role === "admin" &&
    (user.permissions.includes("*") || user.permissions.includes("core.manage"));
}
function visibleError(error: unknown): VisibleError {
  return {
    message: messageOf(error), fields: error instanceof ApiError ? error.fields : [],
    ...(error instanceof ApiError ? { code: error.code, requestId: error.requestId } : {}),
  };
}
function ErrorNotice({ error }: { error: VisibleError | null }) {
  return error ? <Alert type="error" showIcon title={error.message} description={<>
    {error.fields.length > 0 && <ul>{error.fields.map((field, index) => <li key={index}>{field.message}</li>)}</ul>}
    {error.code === "VERSION_CONFLICT" && <div>Tải lại danh sách rồi mở lại tài khoản trước khi sửa.</div>}
    {error.requestId && <Typography.Text type="secondary">Mã yêu cầu: {error.requestId}</Typography.Text>}
  </>} /> : null;
}

/** The component itself denies operators, even when rendered outside the settings route. */
export function LocalAccountsPage() {
  const session = useSession();
  if (!session.boot || !session.token || !canManage(session.user)) {
    return <Space orientation="vertical" className="full">
      <Typography.Title level={2}>Tài khoản nội bộ</Typography.Title>
      <Alert type="warning" showIcon title="Chỉ Admin có quyền quản lý tài khoản nội bộ." />
    </Space>;
  }
  return <LocalAccountsWorkspace key={`${session.generation}/${session.user!.id}`} />;
}

function LocalAccountsWorkspace() {
  const [createForm] = Form.useForm<CreateValues>();
  const [editForm] = Form.useForm<EditValues>();
  const owner = useRef({ generation: useSession.getState().generation, id: useSession.getState().user!.id }).current;
  const alive = useRef(true);
  const current = useCallback(() => {
    const session = useSession.getState();
    return alive.current && session.generation === owner.generation &&
      session.user?.id === owner.id && canManage(session.user);
  }, [owner]);
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [role, setRole] = useState<LocalAccount["role"]>();
  const [active, setActive] = useState<"true" | "false">();
  const [reload, setReload] = useState(0);
  const [listing, setListing] = useState<Page<LocalAccount> | null>(null);
  const [reading, setReading] = useState(false);
  const [readError, setReadError] = useState<VisibleError | null>(null);
  const readSequence = useRef(0);
  const [editing, setEditing] = useState<LocalAccount | null>(null);
  const [error, setError] = useState<VisibleError | null>(null);
  const [success, setSuccess] = useState("");
  const [saving, setSaving] = useState(false);
  const [pending, setPending] = useState<AccountCommand | null>(null);
  const pendingRef = useRef<AccountCommand | null>(null);
  const inFlight = useRef(false);
  const locked = saving || pending !== null;

  useEffect(() => {
    alive.current = true;
    return () => { alive.current = false; pendingRef.current = null; };
  }, []);
  useEffect(() => {
    const sequence = ++readSequence.current;
    let disposed = false;
    setReading(true); setReadError(null); setListing(null);
    const params = new URLSearchParams({ page: String(page), page_size: "50", search });
    if (role) params.set("role", role);
    if (active) params.set("active", active);
    void api<Page<LocalAccount>>(`/users?${params}`).then((result) => {
      if (!disposed && current() && sequence === readSequence.current) setListing(result);
    }).catch((failure) => {
      if (!disposed && current() && sequence === readSequence.current) setReadError(visibleError(failure));
    }).finally(() => {
      if (!disposed && current() && sequence === readSequence.current) setReading(false);
    });
    return () => { disposed = true; };
  }, [page, search, role, active, reload, current]);

  async function execute(command: AccountCommand) {
    if (inFlight.current || !current()) return;
    inFlight.current = true;
    pendingRef.current = command;
    setPending(command); setSaving(true); setError(null); setSuccess("");
    try {
      // body is frozen once, including request_key, password and expected_version.
      const result = await api<LocalAccount>(command.path, { method: command.method, body: command.body });
      if (!current()) return;
      pendingRef.current = null; setPending(null);
      if (command.kind === "create") createForm.resetFields();
      else { setEditing(null); editForm.resetFields(); }
      // Core revokes all target sessions on every successful PATCH, even a no-op.
      if (command.targetId === owner.id) {
        useSession.getState().logout();
        return;
      }
      setSuccess(`${command.kind === "create" ? "Đã tạo" : "Đã cập nhật"} tài khoản ${result.username}.`);
      setReload((value) => value + 1);
    } catch (failure) {
      if (!current()) return;
      setError(visibleError(failure));
      if (failure instanceof ApiError && definitiveCodes.has(failure.code)) {
        pendingRef.current = null; setPending(null);
        if (command.kind === "create") createForm.setFieldValue("password", "");
        const fields = failure.fields.map((field) => ({ ...field, field: field.field.replace(/^body\./, "") }));
        if (fields.length && command.kind === "create") createForm.setFields(fields
          .filter((field) => ["username", "password", "role"].includes(field.field))
          .map((field) => ({ name: field.field as keyof CreateValues, errors: [field.message] })));
        else if (fields.length) editForm.setFields(fields
          .filter((field) => ["role", "active"].includes(field.field))
          .map((field) => ({ name: field.field as keyof EditValues, errors: [field.message] })));
        else if (command.kind === "create" && ["USERNAME_EXISTS", "INVALID_USERNAME", "WEAK_PASSWORD"].includes(failure.code)) {
          createForm.setFields([{ name: failure.code === "WEAK_PASSWORD" ? "password" : "username", errors: [failure.message] }]);
        }
      }
      // Unknown/network/body/server failures remain frozen for exact-key retry.
    } finally {
      inFlight.current = false;
      if (current()) setSaving(false);
    }
  }
  function create(values: CreateValues) {
    if (pendingRef.current || inFlight.current || !current()) return;
    void execute({ kind: "create", method: "POST", path: "/users", body: JSON.stringify({
      username: values.username, password: values.password, role: values.role, request_key: crypto.randomUUID(),
    }) });
  }
  function edit(values: EditValues) {
    if (!editing || pendingRef.current || inFlight.current || !current()) return;
    void execute({ kind: "edit", method: "PATCH", path: `/users/${encodeURIComponent(editing.id)}`, targetId: editing.id,
      body: JSON.stringify({ role: values.role, active: values.active, expected_version: editing.version, request_key: crypto.randomUUID() }) });
  }

  return <Space orientation="vertical" className="full" size="middle">
    <Typography.Title level={2}>Tài khoản nội bộ</Typography.Title>
    <Typography.Paragraph>Tạo tài khoản đăng nhập trên máy và phân công Admin hoặc Nhân viên.</Typography.Paragraph>
    <ErrorNotice error={editing ? null : error} />
    {success && <Alert type="success" showIcon title={success} />}
    {!editing && pending && !saving && <Alert type="warning" showIcon title="Chưa rõ kết quả yêu cầu"
      description="Yêu cầu được giữ nguyên. Thử lại cùng nội dung để xác nhận, tránh tạo hoặc cập nhật trùng."
      action={<Button onClick={() => void execute(pending)}>Thử lại yêu cầu</Button>} />}
    <Card title="Tạo tài khoản">
      <Form name="local-account-create" form={createForm} layout="vertical" initialValues={{ role: "operator" }} disabled={locked} onFinish={create}>
        <Form.Item name="username" label="Tên đăng nhập mới" rules={[
          { required: true, min: 3, max: 64, message: "Tên đăng nhập cần từ 3 đến 64 ký tự." },
          { validator: (_, value: string | undefined) => !value || value.trim() === value ? Promise.resolve() : Promise.reject(new Error("Tên đăng nhập không có khoảng trắng đầu hoặc cuối.")) },
        ]}><Input autoComplete="off" maxLength={64} /></Form.Item>
        <Form.Item name="password" label="Mật khẩu ban đầu" rules={[{ required: true, min: 10, max: 128, message: "Mật khẩu cần từ 10 đến 128 ký tự." }]}>
          <Input.Password autoComplete="new-password" maxLength={128} />
        </Form.Item>
        <Form.Item name="role" label="Vai trò tài khoản mới" rules={[{ required: true }]}><Select options={roles} /></Form.Item>
        <Button type="primary" htmlType="submit" aria-label="Tạo tài khoản" aria-busy={saving && pending?.kind === "create"} disabled={locked} loading={saving && pending?.kind === "create"}>Tạo tài khoản</Button>
      </Form>
    </Card>
    <Card title="Danh sách tài khoản">
      <Space wrap style={{ marginBottom: 12 }}>
        <Input.Search aria-label="Tìm tài khoản" placeholder="Tìm tên đăng nhập" maxLength={128} allowClear onSearch={(value) => { setSearch(value); setPage(1); }} />
        <Select aria-label="Lọc vai trò tài khoản" placeholder="Mọi vai trò" allowClear value={role} options={roles} style={{ width: 160 }} onChange={(value) => { setRole(value); setPage(1); }} />
        <Select aria-label="Lọc trạng thái tài khoản" placeholder="Mọi trạng thái" allowClear value={active} options={[{ value: "true", label: "Đang hoạt động" }, { value: "false", label: "Đã khóa" }]} style={{ width: 160 }} onChange={(value) => { setActive(value); setPage(1); }} />
        <Button aria-label="Tải lại danh sách" onClick={() => setReload((value) => value + 1)} loading={reading}>Tải lại danh sách</Button>
      </Space>
      <ErrorNotice error={readError} />
      <Table<LocalAccount> rowKey="id" size="small" loading={reading} dataSource={listing?.items ?? []}
        pagination={{ current: page, pageSize: 50, total: listing?.total ?? 0, showSizeChanger: false, onChange: setPage, showTotal: (total) => `${total} tài khoản` }}
        columns={[
          { title: "Tên đăng nhập", dataIndex: "username" },
          { title: "Vai trò", dataIndex: "role", render: (value: LocalAccount["role"]) => value === "admin" ? "Admin" : "Nhân viên" },
          { title: "Trạng thái", dataIndex: "active", render: (value: boolean) => <Tag color={value ? "green" : "default"}>{value ? "Đang hoạt động" : "Đã khóa"}</Tag> },
          { title: "Phiên bản", dataIndex: "version" },
          { title: "Thao tác", render: (_, row) => <Button disabled={locked} aria-label={`Sửa tài khoản ${row.username}`} onClick={() => {
            if (pendingRef.current || inFlight.current) return;
            setError(null); setSuccess(""); setEditing(row); editForm.setFieldsValue({ role: row.role, active: row.active });
          }}>Sửa</Button> },
        ]} />
    </Card>
    <Modal open={editing !== null} title={`Sửa tài khoản ${editing?.username ?? ""}`} mask={{ closable: !locked }} keyboard={!locked} closable={!locked}
      onCancel={() => { if (!locked) setEditing(null); }}
      footer={<Space><Button disabled={locked} onClick={() => setEditing(null)}>Đóng</Button><Button type="primary" aria-label="Lưu tài khoản" aria-busy={saving} disabled={locked} loading={saving} onClick={() => editForm.submit()}>Lưu tài khoản</Button></Space>}>
      {editing && <Typography.Paragraph>Phiên bản {editing.version}. Thay đổi vai trò hoặc trạng thái yêu cầu tài khoản đó đăng nhập lại.</Typography.Paragraph>}
      <ErrorNotice error={error} />
      {pending && !saving && <Alert type="warning" title="Chưa rõ kết quả yêu cầu" action={<Button onClick={() => void execute(pending)}>Thử lại yêu cầu</Button>} />}
      <Form name="local-account-edit" form={editForm} layout="vertical" disabled={locked} onFinish={edit}>
        <Form.Item name="role" label="Vai trò sửa tài khoản" rules={[{ required: true }]}><Select options={roles} /></Form.Item>
        <Form.Item name="active" label="Đang hoạt động" valuePropName="checked"><Switch aria-label="Tài khoản đang hoạt động" /></Form.Item>
      </Form>
    </Modal>
  </Space>;
}
