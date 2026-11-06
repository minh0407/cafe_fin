import { useEffect, useId, useRef, useState } from "react";
import { Alert, Button, Card, Input, Space, Table, Typography } from "antd";
import { api, ApiError, messageOf } from "../../shared/api";
import { useSession } from "../../shared/session";
import type { Page } from "../../shared/types";

interface RecordChoice {
  id: string;
  code: string;
  name?: string;
  occurred_on?: string;
  lines?: readonly unknown[];
}

/** Search one server page; list metadata is never copied into the contract. */
export function RecordSourcePicker({ kind, disabled, onSelect }: {
  kind: "parties" | "weighings";
  disabled: boolean;
  onSelect: (id: string) => void;
}) {
  const label = kind === "parties" ? "đối tác" : "phiếu cân";
  const inputId = useId();
  const owner = useRef({ generation: useSession.getState().generation, signal: useSession.getState().generationSignal }).current;
  const mounted = useRef(true);
  const sequence = useRef(0);
  const [input, setInput] = useState("");
  const [search, setSearch] = useState("");
  const [result, setResult] = useState<Page<RecordChoice> | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [searched, setSearched] = useState(false);
  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; sequence.current += 1; };
  }, []);

  async function load(query: string, page: number) {
    if (disabled || owner.signal.aborted || useSession.getState().generation !== owner.generation) return;
    const ticket = ++sequence.current;
    const current = () => mounted.current && ticket === sequence.current && !owner.signal.aborted && useSession.getState().generation === owner.generation;
    const trimmed = query.trim();
    setSearch(trimmed); setResult(null); setLoading(true); setError(""); setSearched(true);
    try {
      const params = new URLSearchParams({ page: String(page), page_size: "50", search: trimmed });
      const response = await api<Page<RecordChoice>>(`/records/${kind}?${params.toString()}`, {
        signal: AbortSignal.any([owner.signal, AbortSignal.timeout(15000)]),
      });
      if (!current()) return;
      if (!Array.isArray(response.items) || response.items.length > 50 ||
        !Number.isSafeInteger(response.page) || response.page !== page ||
        !Number.isSafeInteger(response.page_size) || response.page_size !== 50 ||
        !Number.isSafeInteger(response.total) || response.total < response.items.length)
        throw new ApiError("RECORDS_PAGE_INVALID", "Danh sách nguồn không đúng giới hạn một trang. Hãy thử tìm lại.");
      setResult(response);
    } catch (failure) {
      if (current()) setError(messageOf(failure));
    } finally {
      if (current()) setLoading(false);
    }
  }

  const recordLabel = (item: RecordChoice) => `${item.code}\u0000${kind === "parties" ? item.name : item.occurred_on}`;
  const ambiguous = (item: RecordChoice) => (result?.items.filter((other) => recordLabel(other) === recordLabel(item)).length ?? 0) > 1;

  return <section aria-label={`Tra cứu ${label}`} className="contracts-section">
    <Card size="small" title={`Tìm ${label} đã lưu`}>
      <div className="contracts-field"><label htmlFor={inputId}>{`Tìm ${label} theo tên hoặc mã`}</label>
        <Space.Compact block>
          <Input id={inputId} value={input} maxLength={200} disabled={disabled} placeholder={kind === "parties" ? "Nhập tên hoặc mã đối tác" : "Nhập mã phiếu cân"}
            onChange={(event) => setInput(event.target.value)} onPressEnter={() => void load(input, 1)} />
          <Button disabled={disabled} loading={loading} onClick={() => void load(input, 1)}>{`Tìm ${label}`}</Button>
        </Space.Compact>
      </div>
      <Typography.Paragraph type="secondary">Tìm theo thông tin bạn nhớ hoặc để trống để xem từng trang, tối đa 50 bản ghi mỗi trang. Bạn luôn có thể nhập thủ công các trường hợp đồng bên dưới.</Typography.Paragraph>
      {error && <Alert type="warning" showIcon title={`Chưa tra cứu được ${label}`} description={<>{error} Bạn vẫn có thể nhập thủ công và lưu / xuất hợp đồng.</>} />}
      {searched && !error && <Table<RecordChoice> size="small" rowKey="id" loading={loading} dataSource={result?.items ?? []} scroll={{ y: 320 }} locale={{ emptyText: loading ? "Đang tìm dữ liệu nguồn…" : "Không tìm thấy bản ghi phù hợp. Thử từ khóa khác hoặc nhập thủ công." }}
        pagination={result ? { current: result.page, total: result.total, pageSize: 50, showSizeChanger: false, size: "small", onChange: (page) => void load(search, page), showTotal: (total) => `${total} bản ghi` } : false}
        columns={[
          { title: kind === "parties" ? "Mã / tên đối tác" : "Mã / ngày cân", key: "record", render: (_, item) => <>
            <Typography.Text strong>{item.code || "Chưa có mã"}</Typography.Text>
            <div>{kind === "parties" ? item.name ?? "Chưa có tên" : item.occurred_on ?? "Chưa có ngày"}</div>
            {ambiguous(item) && <Typography.Text type="secondary" className="contracts-hint">Bản ghi …{item.id.slice(-8)}</Typography.Text>}
          </> },
          ...(kind === "weighings" ? [{ title: "Số dòng", key: "lines", render: (_: unknown, item: RecordChoice) => item.lines?.length ?? "—" }] : []),
          { title: "Chọn", key: "select", width: 160, render: (_, item) => <Button disabled={disabled || loading} onClick={() => {
            if (owner.signal.aborted || useSession.getState().generation !== owner.generation) return;
            onSelect(item.id);
          }} aria-label={`Chọn ${label} ${item.code || "chưa có mã"} ${kind === "parties" ? item.name ?? "" : item.occurred_on ?? ""}${ambiguous(item) ? ` · ${item.id.slice(-8)}` : ""}`}>{kind === "parties" ? "Xem và dùng đối tác" : "Xem dòng cân"}</Button> },
        ]} />}
    </Card>
  </section>;
}
