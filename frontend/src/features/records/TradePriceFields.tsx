import { useLayoutEffect, useRef, useState } from "react";
import { Alert, Button, Col, Form, Input, Row, Select, Space, Typography } from "antd";
import type { FormInstance } from "antd";
import { api } from "../../shared/api";
import { isDateInputValueValid } from "../../shared/DateInput";
import { useSession } from "../../shared/session";
import { useCommerceWriteLock } from "./CommerceShared";
import { priceKindOptions, orderValue, type Direction, type PriceSnapshot, type TradeLine } from "./commerceTypes";
import { decimal, DecimalInput, displayBusinessDate, ErrorNotice } from "./helpers";

import { PriceBoardEditor } from "./PricesPage";
export function quoteMatches(line: Partial<TradeLine>, occurredOn: string): boolean {
  const s = line.price_snapshot;
  return !!s && s.price_kind === line.price_kind && s.price_date === (line.price_date || occurredOn) && s.product_id === (line.product_id || null) && s.grade === (line.grade ?? null) && s.unit_price_vnd === line.unit_price_vnd;
}
function scope(line: Partial<TradeLine>, occurredOn: string) { return JSON.stringify([line.pricing_mode, line.price_kind, line.price_date || occurredOn, line.product_id || null, line.grade ?? null]); }

/** Each Form.List key owns its request sequence; indices are never request identities. */
export function TradePriceFields({ form, index, direction }: { form: FormInstance; index: number; direction: Direction }) {
  const lines = Form.useWatch("lines", { form, preserve: true }) as TradeLine[] | undefined;
  const occurredOn = Form.useWatch("occurred_on", form) as string;
  const line = lines?.[index] ?? {} as TradeLine;
  const daily = line.pricing_mode === "daily";
  const identity = scope(line, occurredOn);
  const generation = useSession((state) => state.generation);
  const { locked, isLocked } = useCommerceWriteLock();
  const serial = useRef(0);
  const [refresh, setRefresh] = useState(0);
  const [boardEditor, setBoardEditor] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>();
  const refreshSeen = useRef(0);
  useLayoutEffect(() => {
    const request = ++serial.current;
    if (isLocked()) return;
    const current = form.getFieldValue(["lines", index]) as TradeLine;
    const force = refresh !== refreshSeen.current;
    refreshSeen.current = refresh;
    if (!current || current.pricing_mode !== "daily") { setError(undefined); setBusy(false); return; }
    if (!force && quoteMatches(current, occurredOn)) { setError(undefined); setBusy(false); return; }
    form.setFieldValue(["lines", index, "price_snapshot"], null);
    form.setFieldValue(["lines", index, "unit_price_vnd"], null);
    setError(undefined);
    const date = current.price_date || occurredOn;
    if (!date || !isDateInputValueValid(date) || !current.price_kind || (direction === "outbound" && !current.product_id)) { setBusy(false); return; }
    setBusy(true);
    const query = new URLSearchParams({ price_kind: current.price_kind, price_date: date });
    if (current.product_id) query.set("product_id", current.product_id);
    if (current.grade != null) query.set("grade", String(current.grade));
    const fresh = () => request === serial.current && !isLocked() && generation === useSession.getState().generation && identity === scope(form.getFieldValue(["lines", index]) ?? {}, form.getFieldValue("occurred_on"));
    void api<PriceSnapshot>(`/records/price-quote?${query}`).then((snapshot) => {
      if (!fresh()) return;
      const candidate = { ...form.getFieldValue(["lines", index]), price_snapshot: snapshot, unit_price_vnd: snapshot.unit_price_vnd };
      if (!quoteMatches(candidate, form.getFieldValue("occurred_on"))) throw new Error("Nguồn giá trả về không khớp tiêu chí; hãy lấy lại giá.");
      form.setFieldValue(["lines", index, "price_snapshot"], snapshot);
      form.setFieldValue(["lines", index, "unit_price_vnd"], snapshot.unit_price_vnd);
    }).catch((failure) => { if (fresh()) setError(failure); }).finally(() => { if (fresh()) setBusy(false); });
    return () => { serial.current++; };
    // Price and kg deliberately do not trigger lookup. A saved matching snapshot is frozen.
  }, [identity, index, generation, refresh, locked, occurredOn]);
  const total = orderValue([line]);
  return <><Form.Item label="Cách lấy giá" name={[index, "pricing_mode"]}><Select options={[{ value: "daily", label: "Bảng giá đúng ngày" }, { value: "manual", label: "Nhập tay / dữ liệu cũ" }]} onChange={(mode) => { if (!isLocked() && mode === "daily") form.setFieldValue(["lines", index, "price_kind"], direction === "inbound" ? "purchase_fresh" : "sale"); }} /></Form.Item>
    {daily ? <><Form.Item label="Nhóm giá" name={[index, "price_kind"]}><Select disabled={direction === "outbound" || locked} options={priceKindOptions.filter((option) => direction === "outbound" ? option.value === "sale" : option.value !== "sale")} /></Form.Item><Typography.Paragraph>Ngày giá: {displayBusinessDate(line.price_date || occurredOn)} · theo ngày nghiệp vụ (đổi ngày sẽ lấy giá mới).</Typography.Paragraph></> : <Alert type="info" title="Giá nhập tay / dữ liệu cũ: giá đã ghi được giữ nguyên khi sửa kg." />}
    <Row gutter={12}><Col span={12}><Form.Item label="Grade" name={[index, "grade"]}><Select allowClear options={[1, 2, 3, 4, 5].map((value) => ({ value, label: String(value) }))} /></Form.Item></Col><Col span={12}>{daily ? <Form.Item label="Đơn giá (VND/kg)" name={[index, "unit_price_vnd"]}><Input readOnly inputMode="decimal" /></Form.Item> : <DecimalInput label="Đơn giá (VND/kg)" name={[index, "unit_price_vnd"]} money />}</Col></Row>
    {daily && <Space orientation="vertical" className="full"><Button disabled={locked || busy} loading={busy} onClick={() => { if (!isLocked()) setRefresh((n) => n + 1); }}>Lấy lại giá mới</Button><ErrorNotice error={error} />{!quoteMatches(line, occurredOn) && <Alert type="warning" title={busy ? "Đang lấy giá đúng ngày…" : "Chưa có giá hợp lệ. Chọn đủ ngày, hàng và Grade nếu bảng tính theo Grade."} description={<Button type="link" disabled={locked} onClick={() => setBoardEditor(true)}>Thiết lập bảng giá cho dòng này</Button>} />}{line.price_snapshot && quoteMatches(line, occurredOn) && <Typography.Paragraph type="secondary">Nguồn: {priceKindOptions.find((kind) => kind.value === line.price_snapshot!.price_kind)?.label} · ngày {displayBusinessDate(line.price_snapshot.price_date)}{line.price_snapshot.grade != null ? ` · Grade ${line.price_snapshot.grade}` : ""} · bản {line.price_snapshot.price_board_version}. Giá đã xem được giữ nguyên; chỉ lấy lại khi bấm nút hoặc đổi tiêu chí.</Typography.Paragraph>}</Space>}
    {boardEditor && <PriceBoardEditor defaults={{ price_date: line.price_date || occurredOn, price_kind: line.price_kind, product_id: line.product_id || null, pricing_method: line.price_kind === "sale" ? "flat" : "grade" }} onClose={() => setBoardEditor(false)} onSaved={() => { setBoardEditor(false); if (!isLocked()) setRefresh((n) => n + 1); }} />}
    <Typography.Paragraph strong>Thành tiền dòng (VND): {total === null ? "Chưa đủ giá / kg" : decimal(total)}</Typography.Paragraph>
  </>;
}
