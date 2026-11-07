import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Alert, Button, Card, Descriptions, Space, Switch, Table, Typography } from "antd";
import { api, ApiError } from "../../shared/api";
import { useSession } from "../../shared/session";
import { isDateInputValueValid } from "../../shared/DateInput";
import { invalidateRecords, useRecordsWrite } from "./CommerceShared";
import { decimal, displayBusinessDate, ErrorNotice } from "./helpers";

export const MARKET_SOURCE = "https://banggianongsan.com/bang-gia-ca-phe/";
const statusLabels = {
  DISABLED: "Đã tắt tự động", NETWORK_DISABLED: "Mạng lấy giá đang bị tắt trên máy này",
  WAITING_SOURCE: "Đang chờ kiểm tra nguồn", FETCHING: "Đang kiểm tra nguồn",
  APPLIED: "Đã áp dụng giá đúng ngày", EXISTING_BOARD: "Đã có bảng giá nhập tay, giữ nguyên bảng giá",
  NO_HISTORY: "Chưa có lịch sử giá tự động", BLOCKED: "Nguồn đang chặn truy cập",
  RATE_LIMITED: "Nguồn giới hạn lượt truy cập", NETWORK_ERROR: "Không kết nối được nguồn",
  HTTP_ERROR: "Nguồn trả lỗi", REDIRECT_BLOCKED: "Nguồn chuyển hướng ngoài phạm vi cho phép",
  UNSAFE_ADDRESS: "Địa chỉ nguồn không an toàn", SOURCE_CHANGED: "Không xác minh được cấu trúc nguồn",
  CONFLICTING_SOURCE: "Các giá trên nguồn không khớp", MISSING_SOURCE_DATE: "Nguồn thiếu ngày công bố",
  STALE_SOURCE: "Giá nguồn đã cũ, chưa áp dụng", FUTURE_SOURCE: "Ngày giá nguồn ở tương lai, chưa áp dụng",
  INVALID_PRICE: "Giá nguồn không hợp lệ", WRONG_UNIT: "Đơn vị giá nguồn không phù hợp",
  DAY_CHANGED: "Đã đổi ngày Việt Nam, chờ lượt kiểm tra mới",
} as const;
export interface MarketSnapshot {
  source_url: string; source_date: string; price_vnd_per_kg: string; fetched_at: string;
  region: "Gia Lai"; product: "ROBUSTA_GREEN_BEAN"; unit: "VND/kg";
  parser_version: string; html_sha256: string; board_id: string; board_version: number;
}
export interface MarketStatus {
  price_date: string; today: string; enabled: boolean; settings_version: number; network_available: boolean;
  status: keyof typeof statusLabels; source_url: string; board_id: string | null; board_version: number | null;
  attempts: number; last_checked_at: string | null; next_attempt_at: string | null;
  detail: string | null; snapshot: MarketSnapshot | null;
}
const isDate = (value: unknown): value is string => typeof value === "string" && !!value && isDateInputValueValid(value);
const isTime = (value: unknown) => typeof value === "string" && Number.isFinite(Date.parse(value));
const positiveInteger = (value: unknown) => Number.isSafeInteger(value) && Number(value) > 0;
const sourcePrice = (value: unknown) => {
  if (typeof value !== "string" || !/^\d+(?:\.\d{1,2})?$/.test(value)) return false;
  const [whole, fraction = ""] = value.split(".");
  const minor = BigInt(whole) * 100n + BigInt(fraction.padEnd(2, "0"));
  return minor >= 1000000n && minor <= 50000000n;
};
// A malformed successful mutation is uncertain, never evidence that a setting was saved.
export function marketStatus(value: unknown): MarketStatus {
  const v = value as MarketStatus | null;
  const s = v?.snapshot;
  const validSnapshot = s === null || (s && s.source_url === MARKET_SOURCE &&
    isDate(s.source_date) && sourcePrice(s.price_vnd_per_kg) && isTime(s.fetched_at) &&
    s.region === "Gia Lai" && s.product === "ROBUSTA_GREEN_BEAN" && s.unit === "VND/kg" &&
    typeof s.parser_version === "string" && typeof s.html_sha256 === "string" &&
    typeof s.board_id === "string" && positiveInteger(s.board_version));
  if (!v || !isDate(v.price_date) || !isDate(v.today) || typeof v.enabled !== "boolean" ||
    !positiveInteger(v.settings_version) || typeof v.network_available !== "boolean" ||
    !Object.hasOwn(statusLabels, v.status) || v.source_url !== MARKET_SOURCE ||
    !(v.board_id === null || typeof v.board_id === "string") ||
    !(v.board_version === null || positiveInteger(v.board_version)) ||
    !Number.isSafeInteger(v.attempts) || v.attempts < 0 ||
    !(v.last_checked_at === null || isTime(v.last_checked_at)) ||
    !(v.next_attempt_at === null || isTime(v.next_attempt_at)) ||
    !(v.detail === null || typeof v.detail === "string") || !validSnapshot ||
    (v.status === "APPLIED" && (!s || s.board_id !== v.board_id || s.board_version !== v.board_version || s.source_date !== v.price_date))) {
    throw new ApiError("INVALID_API_RESPONSE", "Chưa xác minh được phản hồi giá tự động. Hãy tải lại trạng thái; chưa có giá mới được xác nhận.");
  }
  return v;
}

function usePricesTabOpen() {
  const active = () => document.visibilityState === "visible" && location.hash.split("?")[0] === "#/records/prices";
  const [open, setOpen] = useState(active);
  useEffect(() => { const update = () => setOpen(active()); document.addEventListener("visibilitychange", update); window.addEventListener("hashchange", update); return () => { document.removeEventListener("visibilitychange", update); window.removeEventListener("hashchange", update); }; }, []);
  return open;
}
export function useProcessedMarket(priceDate?: string, enabled = true) {
  const generation = useSession((state) => state.generation);
  const user = useSession((state) => state.user);
  const open = usePricesTabOpen();
  return useQuery({ queryKey: ["records", generation, "processed-market", priceDate ?? "today"], queryFn: async ({ signal }) => marketStatus(await api(`/records/market/processed${priceDate ? `?price_date=${priceDate}` : ""}`, { signal: AbortSignal.any([signal, AbortSignal.timeout(15000)]) })), enabled: enabled && !!user && open, retry: false, gcTime: 0, refetchInterval: open ? 30000 : false, refetchIntervalInBackground: false });
}
const timeText = (value: string | null) => value ? new Date(value).toLocaleString("vi-VN", { timeZone: "Asia/Ho_Chi_Minh" }) : "Chưa có";
export function MarketProvenance({ value }: { value: MarketStatus }) {
  return <Descriptions bordered size="small" column={1} items={[
    { key: "source", label: "Nguồn công khai", children: <a href={MARKET_SOURCE} target="_blank" rel="noreferrer noopener">Bảng Giá Nông Sản · Robusta nhân xô Gia Lai</a> },
    { key: "day", label: "Ngày bảng giá", children: displayBusinessDate(value.price_date) },
    { key: "source-day", label: "Ngày giá nguồn đã xác nhận", children: value.snapshot ? displayBusinessDate(value.snapshot.source_date) : "Chưa xác nhận" },
    { key: "checked", label: "Lần kiểm tra gần nhất (giờ Việt Nam)", children: timeText(value.last_checked_at) },
    { key: "next", label: "Được kiểm tra lại từ (giờ Việt Nam)", children: timeText(value.next_attempt_at) },
  ]} />;
}
export function ProcessedMarketCard({ onOpenBoard }: { onOpenBoard: (id: string) => void }) {
  const query = useProcessedMarket();
  const generation = useSession((state) => state.generation);
  const canWrite = useRecordsWrite();
  const maintenance = useSession((state) => state.maintenance);
  const cache = useQueryClient();
  const [pending, setPending] = useState<{ kind: "settings" | "check"; body: Record<string, unknown> }>();
  const [busy, setBusy] = useState(false);
  const [uncertain, setUncertain] = useState(false);
  const [error, setError] = useState<unknown>();
  const lock = useRef(false);
  const mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  const current = () => mounted.current && generation === useSession.getState().generation;
  const blocked = !!maintenance.operation || maintenance.uncertain || maintenance.beginUncertain;
  const value = query.data;
  // Time only controls the button; the server remains authoritative about cooldown.
  const [now, setNow] = useState(Date.now);
  useEffect(() => { const timer = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(timer); }, []);
  const cooling = !!value?.next_attempt_at && Date.parse(value.next_attempt_at) > now;
  const frozen = busy || uncertain || blocked || !canWrite || !value || !!query.error;
  async function send(attempt: NonNullable<typeof pending>) {
    if (lock.current || !canWrite || blocked || !current()) return;
    lock.current = true; setPending(attempt); setBusy(true); setError(undefined);
    try {
      const result = marketStatus(await api(`/records/market/processed/${attempt.kind === "settings" ? "settings" : "check"}`, { method: attempt.kind === "settings" ? "PUT" : "POST", body: JSON.stringify(attempt.body) }));
      if (!current()) return;
      setUncertain(false); setPending(undefined);
      cache.setQueryData(["records", generation, "processed-market", "today"], result);
      await invalidateRecords(cache);
    } catch (failure) {
      if (!current()) return;
      setError(failure);
      const knownRejection = failure instanceof ApiError && ["VERSION_CONFLICT", "IDEMPOTENCY_CONFLICT", "VALIDATION_ERROR", "INVALID_REQUEST", "PERMISSION_DENIED", "FORBIDDEN", "MAINTENANCE_BUSY", "MAINTENANCE_REQUIRED", "MARKET_DISABLED", "MARKET_COOLDOWN"].includes(failure.code);
      const unknown = !knownRejection;
      setUncertain(unknown);
      if (!unknown) { setPending(undefined); void query.refetch(); }
    } finally { lock.current = false; if (current()) setBusy(false); }
  }
  const snapshot = value?.status === "APPLIED" ? value.snapshot : null;
  const preview = useQuery({ queryKey: ["records", generation, "market-grades", snapshot?.board_id, snapshot?.board_version, snapshot?.price_vnd_per_kg], enabled: !!snapshot, retry: false, gcTime: 0, queryFn: async () => {
    const result = await api<{ grade_prices: { grade: number; unit_price_vnd: string }[] }>("/records/price-board-preview", { method: "POST", body: JSON.stringify({ pricing_method: "grade", flat_price_vnd: null, grade5_price_vnd: snapshot!.price_vnd_per_kg }) });
    if (!Array.isArray(result.grade_prices) || result.grade_prices.length !== 5 || ![1, 2, 3, 4, 5].every((grade) => result.grade_prices.some((row) => row.grade === grade && /^\d+(?:\.\d{1,2})?$/.test(row.unit_price_vnd)))) throw new ApiError("INVALID_API_RESPONSE", "Chưa đọc được đủ năm Grade từ bảng giá.");
    return result;
  } });
  return <Card title="Tự động giá nhập nhân xô Robusta Gia Lai" style={{ marginBottom: 20 }}>
    <Space orientation="vertical" className="full">
      <Typography.Paragraph>Giá nhân xô chỉ áp dụng đúng ngày Việt Nam, lấy làm Grade5 của giá nhập chế biến chung. Giá quả tươi tiếp tục nhập tay, không quy đổi từ nhân xô. Giá bán thiết lập riêng. Ứng dụng chỉ kiểm tra khi đang chạy.</Typography.Paragraph>
      <ErrorNotice error={query.error} />
      {query.error && value && <Alert type="warning" title="Chưa tải được trạng thái mới; bên dưới là lần đọc gần nhất." />}
      {value ? <><Alert showIcon type={value.status === "APPLIED" ? "success" : ["DISABLED", "WAITING_SOURCE", "FETCHING", "EXISTING_BOARD", "NO_HISTORY"].includes(value.status) ? "info" : "warning"} title={statusLabels[value.status]} description={value.detail || undefined} /><MarketProvenance value={value} />
        {snapshot && <><Typography.Text strong>Grade5 đã áp dụng: {decimal(snapshot.price_vnd_per_kg)} VND/kg</Typography.Text><ErrorNotice error={preview.error} /><Table aria-label="Năm Grade giá nhân xô tự động" rowKey="grade" size="small" pagination={false} loading={preview.isPending} dataSource={preview.data?.grade_prices ?? []} columns={[{ title: "Grade", dataIndex: "grade" }, { title: "VND/kg", dataIndex: "unit_price_vnd", render: decimal }]} /></>}
        {value.board_id && <Button onClick={() => onOpenBoard(value.board_id!)}>Xem bảng giá {value.status === "APPLIED" ? "tự động" : "đã có"}</Button>}
        <Space wrap><label><Switch aria-label="Tự động lấy giá nhân xô" checked={uncertain && pending?.kind === "settings" ? pending.body.enabled === true : value.enabled} disabled={frozen} onChange={(enabled) => void send({ kind: "settings", body: { request_key: crypto.randomUUID(), expected_version: value.settings_version, enabled } })} /> Tự động lấy giá nhân xô</label><Button aria-label="Kiểm tra nguồn ngay" loading={busy && pending?.kind === "check"} disabled={frozen || !value.enabled || !value.network_available || cooling || ["FETCHING", "APPLIED", "EXISTING_BOARD"].includes(value.status)} onClick={() => void send({ kind: "check", body: { request_key: crypto.randomUUID() } })}>Kiểm tra nguồn ngay</Button>{cooling && <Typography.Text>Đang chờ đến lượt kiểm tra tiếp theo.</Typography.Text>}</Space>
      </> : !query.error && <Typography.Text>Đang đọc trạng thái giá tự động…</Typography.Text>}
      <ErrorNotice error={error} />
      {uncertain && <Alert type="warning" title="Chưa xác nhận kết quả thao tác giá tự động" description="Giữ nguyên lựa chọn và yêu cầu đang gửi. Không tự gửi lại; dùng nút kiểm tra cùng yêu cầu để tránh ghi lặp." />}
      {uncertain && pending && <Button aria-label="Kiểm tra lại cùng yêu cầu giá tự động" loading={busy} disabled={busy || !canWrite || blocked} onClick={() => void send(pending)}>Kiểm tra lại cùng yêu cầu giá tự động</Button>}
      <Button disabled={busy} onClick={() => void query.refetch()}>Tải lại trạng thái giá tự động</Button>
    </Space>
  </Card>;
}
