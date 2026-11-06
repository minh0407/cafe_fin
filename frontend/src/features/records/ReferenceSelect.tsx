import { useEffect, useRef, useState } from "react";
import { Select, Typography } from "antd";
import { api, messageOf } from "../../shared/api";
import { useSession } from "../../shared/session";
import type { Page } from "../../shared/types";
import type { Entity, Resource } from "./types";

/** A bounded server search, rather than downloading all master records. */
export function ReferenceSelect({ resource, value, onChange, disabled, label, id }: { resource: Resource; value?: string | null; onChange?: (value: string | undefined) => void; disabled?: boolean; label?: string; id?: string }) {
  const [search, setSearch] = useState("");
  const [options, setOptions] = useState<{ value: string; label: string }[]>([]);
  const [selected, setSelected] = useState<{ value: string; label: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const generation = useSession((state) => state.generation);
  const serial = useRef(0);
  useEffect(() => {
    let alive = true;
    if (!value) { setSelected(null); return; }
    void api<Entity>(`/records/${resource}/${encodeURIComponent(value)}`).then((item) => { if (alive) setSelected({ value: item.id, label: `${item.code}${item.name ? ` — ${item.name}` : ""}${item.active === false || item.deleted_at ? " (ngừng sử dụng)" : ""}` }); }).catch(() => { if (alive) setSelected({ value, label: value }); });
    return () => { alive = false; };
  }, [resource, value, generation]);
  useEffect(() => {
    const current = ++serial.current;
    const timer = setTimeout(() => {
      setBusy(true);
      setError("");
      const query = new URLSearchParams({ page: "1", page_size: "50", search, sort: "code", filters: JSON.stringify(resource === "weighings" || resource === "entries" ? {} : { active: true }) });
      void api<Page<Entity>>(`/records/${resource}?${query}`).then((page) => { if (current === serial.current) setOptions(page.items.map((item) => ({ value: item.id, label: `${item.code}${item.name ? ` — ${item.name}` : ""}` }))); }).catch((err) => { if (current === serial.current) { setOptions([]); setError(messageOf(err)); } }).finally(() => { if (current === serial.current) setBusy(false); });
    }, 180);
    return () => { clearTimeout(timer); serial.current++; };
  }, [resource, search, generation]);
  const merged = selected && !options.some((item) => item.value === selected.value) ? [selected, ...options] : options;
  return <Select id={id} aria-label={label} allowClear showSearch filterOption={false} value={value ?? undefined} disabled={disabled} onChange={onChange} onSearch={setSearch} loading={busy} options={merged} placeholder="Tìm theo mã hoặc tên" notFoundContent={error || "Không tìm thấy; thử tìm theo mã/tên khác."} popupRender={(menu) => <>{menu}<Typography.Paragraph type="secondary" style={{ padding: "4px 12px", margin: 0 }}>Tối đa 50 kết quả. Gõ để tìm trên toàn bộ danh sách.</Typography.Paragraph></>} />;
}
