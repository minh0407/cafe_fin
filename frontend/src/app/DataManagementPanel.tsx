import { useEffect, useRef, useState } from "react";
import { Alert, Button, Card, Space, Typography } from "antd";
import { ApiError, desktop, isMaintenanceBoot, messageOf } from "../shared/api";
import { useSession } from "../shared/session";
import { maintenanceHeld, type MaintenanceKind, type MaintenanceResult, type MaintenanceView } from "../shared/types";

const names: Record<MaintenanceKind, string> = { backup: "Sao lưu", move: "Chuyển nơi lưu", restore: "Khôi phục bản sao lưu" };
const phases: Record<MaintenanceView["phase"], string> = {
  SELECTING: "Đang chọn thư mục", INTENT: "Đã gửi yêu cầu; chưa xác nhận kết quả",
  QUIESCED: "Đã tạm dừng ghi", PREPARED: "Đã xác minh bản sao",
  OLD_CLOSED: "Đã đóng dữ liệu nguồn", CONFIG_SWITCHED: "Đã chuyển cấu hình",
  CANDIDATE_DORMANT: "Dữ liệu đích đang chờ kích hoạt",
  ACTIVATION_DISPATCHED: "Đã gửi yêu cầu kích hoạt", ACTIVE: "Đã xác nhận hoàn tất",
};
const runtimes = ["ACTIVE", "QUIESCING", "QUIESCED", "PREPARING", "PREPARED", "CLOSING", "CLOSED", "DORMANT", "ACTIVATING", "FAILED_HELD"];
function complete(operation: MaintenanceView) {
  return operation.phase === "ACTIVE" && operation.runtime_state === "ACTIVE" && !operation.recovery_required;
}

export function DataManagementPanel() {
  const session = useSession();
  const mounted = useRef(false);
  const requestSequence = useRef(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  useEffect(() => { setBusy(false); setError(""); setNotice(""); }, [session.generation]);
  const supported = session.boot?.maintenance_protocol === 1 && !!session.boot.generation;
  const allowed = (permission: string) => !!session.user && (session.user.permissions.includes("*") || session.user.permissions.includes(permission));
  const admin = session.user?.role === "admin" && allowed("core.manage");
  const held = maintenanceHeld(session.boot);
  const pending = session.boot?.pending_transition;
  const cachedOperation = session.maintenance.operation;
  const operation = cachedOperation && cachedOperation.generation === session.boot?.generation &&
    (!pending || pending.operation_id === cachedOperation.operation_id) ? cachedOperation : null;
  const operationId = operation?.operation_id ?? pending?.operation_id;
  const frozen = session.maintenance.uncertain || session.maintenance.beginUncertain || !!pending?.recovery_required || (!!operation && operation.phase !== "SELECTING");
  const canContinue = !!operation && ["INTENT", "QUIESCED", "PREPARED", "OLD_CLOSED", "CONFIG_SWITCHED"].includes(operation.phase) && operation.runtime_state !== "DORMANT";
  const canReplaceDraft = !!operation && operation.phase === "SELECTING" &&
    (!pending || pending.phase === "SELECTING") && !operation.recovery_required && !held && !frozen && !busy;

  function currentOperationId() {
    const state = useSession.getState();
    return state.boot?.pending_transition?.operation_id ?? state.maintenance.operation?.operation_id;
  }
  function owner(expectedOperationId?: string) {
    const state = useSession.getState();
    const sequence = ++requestSequence.current;
    return () => mounted.current && useSession.getState().generation === state.generation &&
      !state.generationSignal.aborted && useSession.getState().boot?.generation === state.boot?.generation &&
      useSession.getState().boot?.maintenance_protocol === 1 && requestSequence.current === sequence &&
      (expectedOperationId === undefined || currentOperationId() === expectedOperationId);
  }
  function validateView(view: MaintenanceView, generation: string | null | undefined, expectedId?: string, expectedKind?: MaintenanceKind) {
    if (!view || view.generation !== generation || typeof view.operation_id !== "string" || !view.operation_id || view.operation_id.length > 256 ||
      !Object.hasOwn(phases, view.phase) || !Object.hasOwn(names, view.kind) ||
      (expectedId !== undefined && view.operation_id !== expectedId) || (expectedKind !== undefined && view.kind !== expectedKind) ||
      (view.runtime_state !== null && !runtimes.includes(view.runtime_state)) ||
      typeof view.ready !== "boolean" || typeof view.can_activate !== "boolean" || typeof view.recovery_required !== "boolean" ||
      (view.can_activate && view.runtime_state !== "DORMANT") ||
      ![view.destination_display, view.backup_source_display].every((label) => label === null || (typeof label === "string" && label.length <= 32768)))
      throw new ApiError("NATIVE_RESULT_UNKNOWN", "Phản hồi không khớp phiên dữ liệu hiện tại. Hãy kiểm tra trạng thái.");
  }
  function acceptView(view: MaintenanceView, expectedId?: string, expectedKind?: MaintenanceKind) {
    const state = useSession.getState();
    validateView(view, state.boot?.generation, expectedId, expectedKind);
    state.maintenanceState({ operation: view, uncertain: ["INTENT", "ACTIVATION_DISPATCHED"].includes(view.phase), beginUncertain: false });
    state.bootMetadata(state.generation, view.generation, {
      runtime_state: view.runtime_state,
      pending_transition: complete(view) ? null : {
        operation_id: view.operation_id, kind: view.kind, phase: view.phase, recovery_required: view.recovery_required,
      },
    });
  }
  function acceptResult(result: MaintenanceResult, expectedId: string, expectedKind?: MaintenanceKind) {
    const boot = result?.boot_session;
    validateView(result?.operation, boot?.generation ?? useSession.getState().boot?.generation, expectedId, expectedKind);
    if (result.boot_session !== null) {
      if (!isMaintenanceBoot(boot) ||
        boot.runtime_state !== result.operation.runtime_state ||
        (!complete(result.operation) && boot.pending_transition?.operation_id !== expectedId))
        throw new ApiError("NATIVE_RESULT_UNKNOWN", "Chưa xác nhận được phiên dữ liệu đích. Hãy kiểm tra trạng thái.");
      // Always a new boundary, even when the API port is reused.
      useSession.getState().setBoot(result.boot_session);
    }
    acceptView(result.operation, expectedId, expectedKind);
  }
  async function select(purpose: "destination" | "backup_source") {
    if (!supported || !admin || busy || frozen || !operationId) return;
    const current = owner(operationId);
    setBusy(true); setError(""); setNotice("");
    useSession.getState().maintenanceState({ beginUncertain: true });
    try {
      const view = await desktop.maintenanceSelect(operationId, purpose);
      if (!current()) return;
      if (view) acceptView(view, operationId, operation?.kind ?? pending?.kind);
      else { useSession.getState().maintenanceState({ beginUncertain: false }); setNotice("Đã hủy chọn thư mục. Thao tác hiện tại được giữ nguyên."); }
    } catch (err) { if (current()) setError(messageOf(err)); }
    finally { if (current()) setBusy(false); }
  }
  async function begin(kind: MaintenanceKind) {
    if (!supported || !admin || busy || held || session.maintenance.uncertain || session.maintenance.beginUncertain ||
      (operationId ? !canReplaceDraft : (pending && pending.phase !== "ACTIVE"))) return;
    const current = owner();
    setBusy(true); setError(""); setNotice("");
    useSession.getState().maintenanceState({ beginUncertain: true });
    try {
      const view = await desktop.maintenanceBegin(kind);
      if (!current()) return;
      validateView(view, useSession.getState().boot?.generation, undefined, kind);
      if (view.phase !== "SELECTING" || view.recovery_required || (operationId && view.operation_id === operationId))
        throw new ApiError("NATIVE_RESULT_UNKNOWN", "Chưa xác nhận được bản nháp mới từ desktop. Hãy kiểm tra trạng thái.");
      acceptView(view, undefined, kind);
      useSession.getState().maintenanceState({ beginUncertain: true });
      const selected = await desktop.maintenanceSelect(view.operation_id, "destination");
      if (!current() || currentOperationId() !== view.operation_id) return;
      if (selected) acceptView(selected, view.operation_id, kind);
      else { useSession.getState().maintenanceState({ beginUncertain: false }); setNotice("Đã hủy chọn thư mục. Thao tác hiện tại được giữ nguyên."); }
    } catch (err) { if (current()) setError(messageOf(err)); }
    finally { if (current()) setBusy(false); }
  }
  async function command(kind: "run" | "status" | "activate") {
    if (!supported || !admin || busy || !operationId || !session.token) return;
    if (kind === "run" && (session.maintenance.beginUncertain || !operation ||
      (operation.phase === "SELECTING" ? !operation.ready || frozen : !canContinue))) return;
    if (kind === "activate" && (!operation?.can_activate || operation.runtime_state !== "DORMANT" || session.maintenance.uncertain)) return;
    const current = owner(operationId);
    const token = useSession.getState().token!;
    setBusy(true); setError(""); setNotice("");
    if (kind !== "status") {
      useSession.getState().maintenanceState({ uncertain: true });
      if (operation) {
        const phase = kind === "activate" ? "ACTIVATION_DISPATCHED" : operation.phase === "SELECTING" ? "INTENT" : operation.phase;
        const intent = { ...operation, phase, can_activate: false } as MaintenanceView;
        useSession.getState().maintenanceState({ operation: intent });
        const state = useSession.getState();
        state.bootMetadata(state.generation, operation.generation, { pending_transition: {
          operation_id: operation.operation_id, kind: operation.kind, phase, recovery_required: operation.recovery_required,
        } });
      }
    }
    try {
      const result = await (kind === "run" ? desktop.maintenanceRun(operationId, token) :
        kind === "activate" ? desktop.maintenanceActivate(operationId, token) : desktop.maintenanceStatus(operationId, token));
      if (!current()) return;
      acceptResult(result, operationId, operation?.kind ?? pending?.kind);
      // A non-null boot unmounts this actor's UI. Its target must log in afresh.
      if (current() && complete(result.operation)) setNotice("Desktop đã xác nhận thao tác hoàn tất.");
    } catch (err) { if (current()) setError(messageOf(err)); }
    finally { if (current()) setBusy(false); }
  }
  async function desktopStatus() {
    if (!supported || busy) return;
    const current = owner();
    setBusy(true); setError("");
    try {
      const status = await desktop.status();
      if (!current()) return;
      if (status.maintenance_protocol !== 1 || !status.generation)
        throw new ApiError("GENERATION_MISMATCH", "Desktop chưa xác nhận phiên dữ liệu. Trạng thái hiện tại vẫn được giữ.");
      if (status.generation !== session.boot?.generation) {
        setNotice("Desktop đang giữ phiên dữ liệu khác. Kết nối phiên desktop hiện tại để đăng nhập lại; thao tác cũ vẫn được giữ.");
        return;
      }
      if (status.pending_transition && operationId && status.pending_transition.operation_id !== operationId && !session.maintenance.beginUncertain)
        throw new ApiError("NATIVE_RESULT_UNKNOWN", "Trạng thái desktop không khớp thao tác hiện tại.");
      const state = useSession.getState();
      // Absence/process death is not proof of completion or a safe abandonment.
      if (status.pending_transition) {
        state.bootMetadata(state.generation, status.generation!, { pending_transition: status.pending_transition, runtime_state: status.runtime_state });
      }
      setNotice("Đã đọc trạng thái desktop. Đăng nhập Admin để kiểm tra chi tiết thao tác đang giữ.");
    } catch { if (current()) setError("Chưa xác nhận được trạng thái desktop. Giữ nguyên thao tác hiện tại."); }
    finally { if (current()) setBusy(false); }
  }
  async function attach() {
    if (!supported || busy) return;
    const current = owner();
    setBusy(true); setError("");
    try {
      const status = await desktop.status();
      if (!current()) return;
      if (!status.running || status.maintenance_protocol !== 1 || !status.generation)
        throw new ApiError("MAINTENANCE_RECOVERY_HELD", "Chưa xác minh được phiên desktop đang chạy. Dữ liệu vẫn được giữ; không khởi động lại để hủy.");
      const boot = await desktop.attach();
      if (!current()) return;
      if (!isMaintenanceBoot(boot)) throw new ApiError("MAINTENANCE_RECOVERY_HELD", "Chưa xác minh được phiên dữ liệu desktop. Trạng thái hiện tại vẫn được giữ.");
      // Native verifies the actual current child under its lifecycle lock. The
      // earlier status is not permission to return a cached or replacement root.
      useSession.getState().setBoot(boot);
    } catch (err) { if (current()) setError(messageOf(err)); }
    finally { if (current()) setBusy(false); }
  }
  async function openReports() {
    if (!supported || !allowed("reporting.read") || busy || held || !session.token) return;
    const current = owner();
    setBusy(true); setError("");
    try { await desktop.openReports(useSession.getState().token!); if (current()) setNotice("Đã yêu cầu desktop mở thư mục báo cáo."); }
    catch (err) { if (current()) setError(messageOf(err)); }
    finally { if (current()) setBusy(false); }
  }

  return <Card title="Quản lý dữ liệu trên máy" className="toolbar">
    {!supported ? <Alert type="info" title="Phiên desktop này chưa hỗ trợ quản lý dữ liệu. Các thao tác hiện không khả dụng." /> : <Space orientation="vertical" className="full">
      {held && <Alert type="warning" showIcon title="Dữ liệu đang chờ phục hồi hoặc kích hoạt" description="Nghiệp vụ được tạm giữ. Không khởi động lại để hủy và không tự chuyển về dữ liệu cũ." />}
      {!held && allowed("reporting.read") && <Button disabled={busy} onClick={() => void openReports()}>Mở thư mục báo cáo</Button>}
      {!admin ? held && <Alert type="info" title="Cần đăng nhập Admin của dữ liệu hiện tại để kiểm tra và kích hoạt." /> : <>
        {!held && !operationId && !session.maintenance.beginUncertain && <Space wrap>
          {(["backup", "move", "restore"] as const).map((kind) => <Button key={kind} disabled={busy} onClick={() => void begin(kind)}>{names[kind]}</Button>)}
        </Space>}
        {operation && <>
          <Typography.Text strong>{names[operation.kind]} — {phases[operation.phase]}</Typography.Text>
          <Typography.Paragraph>Đích đã chọn: <span>{operation.destination_display ?? "Chưa chọn"}</span></Typography.Paragraph>
          {operation.kind === "restore" && <Typography.Paragraph>Bản sao nguồn: <span>{operation.backup_source_display ?? "Chưa chọn"}</span></Typography.Paragraph>}
          {operation.phase === "SELECTING" && !frozen && <Space wrap>
            <Button disabled={busy} onClick={() => void select("destination")}>Chọn nơi lưu</Button>
            {operation.kind === "restore" && <Button disabled={busy} onClick={() => void select("backup_source")}>Chọn bản sao lưu</Button>}
            <Button type="primary" disabled={busy || !operation.ready} onClick={() => void command("run")}>Thực hiện</Button>
          </Space>}
          {canReplaceDraft && <>
            <Typography.Text strong>Chọn thao tác khác</Typography.Text>
            <Space wrap>
              {(["backup", "move", "restore"] as const).filter((kind) => kind !== operation.kind).map((kind) =>
                <Button key={kind} onClick={() => void begin(kind)}>Đổi sang: {names[kind]}</Button>)}
            </Space>
          </>}
          {operation.runtime_state === "DORMANT" && <Button type="primary" disabled={busy || !operation.can_activate || session.maintenance.uncertain} onClick={() => void command("activate")}>Kích hoạt dữ liệu hiện tại</Button>}
          {complete(operation) && !held && <Button disabled={busy} onClick={() => useSession.getState().maintenanceState({ operation: null, uncertain: false })}>Thao tác dữ liệu tiếp theo</Button>}
        </>}
        {session.maintenance.uncertain && <Alert type="warning" title="Chưa rõ kết quả thao tác" description="Giữ nguyên thao tác và thư mục. Kiểm tra trạng thái hoặc thử lại đúng thao tác đã gửi; không tạo thao tác mới." />}
        {operationId && <Space wrap>
          <Button disabled={busy} onClick={() => void command("status")}>Kiểm tra trạng thái thao tác</Button>
          {canContinue && <Button disabled={busy || session.maintenance.beginUncertain} onClick={() => void command("run")}>{session.maintenance.uncertain ? "Thử lại cùng thao tác" : "Tiếp tục cùng thao tác"}</Button>}
        </Space>}
        {session.maintenance.beginUncertain && <Alert type="warning" title="Chưa xác nhận lựa chọn hoặc thao tác desktop. Không tạo yêu cầu mới; kiểm tra trạng thái desktop hoặc thao tác." />}
      </>}
      <Button disabled={busy} onClick={() => void desktopStatus()}>Kiểm tra trạng thái desktop</Button>
      {(held || session.maintenance.uncertain || session.maintenance.beginUncertain) && <Button disabled={busy} onClick={() => void attach()}>Kết nối phiên desktop hiện tại</Button>}
    </Space>}
    {error && <Alert className="toolbar" type="error" title={error} showIcon />}
    {notice && <Alert className="toolbar" type="info" title={notice} showIcon />}
  </Card>;
}
