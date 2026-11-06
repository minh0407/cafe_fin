import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Alert, Tabs, Typography } from "antd";
import { useSession } from "../../shared/session";
import { Coverage } from "./helpers";
import { RecordDetail } from "./RecordDetail";
import { RecordEditor } from "./RecordEditor";
import { RecordList } from "./RecordList";
import { InventoryView, MovementView, ReceivableView } from "./StockViews";
import type { Entry, RecordEntity, Resource, Weighing } from "./types";

const masters: { key: Resource; label: string }[] = [
  { key: "parties", label: "Đối tác" },
  { key: "products", label: "Hàng hóa" },
  { key: "products/warehouses", label: "Vị trí / kho" },
  { key: "products/units", label: "Đơn vị" },
  { key: "weighings", label: "Phiếu cân tay" },
  { key: "entries", label: "Phiếu hàng" },
];
const validTabs = [...masters.map((item) => item.key), "inventory", "movements", "receivables"];
function tabFromHash(): string {
  const key = new URLSearchParams(location.hash.split("?")[1] || "").get("tab") || "parties";
  return validTabs.includes(key) ? key : "parties";
}

export function RecordsPage() {
  const [tab, setTab] = useState(tabFromHash);
  const [editor, setEditor] = useState<{ resource: Resource; value?: Partial<RecordEntity>; key: string } | null>(null);
  const [detail, setDetail] = useState<{ resource: Resource; value: RecordEntity; saved: boolean } | null>(null);
  const cache = useQueryClient();
  const generation = useSession((state) => state.generation);
  const user = useSession((state) => state.user);
  const canWrite = !!user && (user.role === "admin" || user.permissions.includes("*") || user.permissions.includes("records.write"));
  useEffect(() => {
    const change = () => { setTab(tabFromHash()); setEditor(null); setDetail(null); };
    window.addEventListener("hashchange", change);
    return () => window.removeEventListener("hashchange", change);
  }, []);
  useEffect(() => { setEditor(null); setDetail(null); }, [generation]);
  function switchTab(key: string) {
    setTab(key); setEditor(null); setDetail(null);
    const params = new URLSearchParams({ tab: key });
    history.replaceState(null, "", `${location.pathname}${location.search}#/records?${params}`);
  }
  function edit(resource: Resource, value?: Partial<RecordEntity>) {
    setDetail(null);
    setEditor({ resource, value, key: crypto.randomUUID() });
  }
  async function saved(value: RecordEntity) {
    const resource = editor!.resource;
    setEditor(null);
    setDetail({ resource, value, saved: true });
    await cache.invalidateQueries({ queryKey: ["records"] });
    await cache.invalidateQueries({ queryKey: ["records-reference"] });
  }
  function fromWeighing(value: Weighing) {
    switchTab("entries");
    edit("entries", { occurred_on: value.occurred_on, party_id: value.party_id, weighing_id: value.id, entry_type: "receipt", status: "draft", note: `Lập từ phiếu cân ${value.code}`, lines: value.lines.map((line) => ({ product_id: line.product_id || "", warehouse_id: "", quantity_kg: line.net_kg || "", direction: "in" as const, note: line.description || line.note || null })) } as Partial<Entry>);
  }
  return <>
    <Typography.Title level={2}>Ghi nhận cà phê</Typography.Title>
    <Coverage />
    {!canWrite && <Alert type="info" title="Tài khoản hiện tại chỉ xem dữ liệu ghi nhận." showIcon />}
    <Tabs activeKey={tab} onChange={switchTab} destroyOnHidden items={[
      ...masters.map(({ key, label }) => ({ key, label, children: <RecordList key={`${key}/${generation}`} resource={key} canWrite={canWrite} onCreate={() => edit(key)} onEdit={(value) => edit(key, value)} onView={(value) => setDetail({ resource: key, value, saved: false })} /> })),
      { key: "inventory", label: "Tổng hợp tồn", children: <InventoryView /> },
      { key: "movements", label: "Lịch sử kho", children: <MovementView onView={(value) => setDetail({ resource: "entries", value, saved: false })} /> },
      { key: "receivables", label: "Số dư thương mại", children: <ReceivableView /> },
    ]} />
    {editor && <RecordEditor key={editor.key} resource={editor.resource} initial={editor.value} title={`${editor.value?.id ? "Sửa" : "Thêm"} ${masters.find((item) => item.key === editor.resource)?.label.toLocaleLowerCase()}`} onClose={() => setEditor(null)} onSaved={(value) => void saved(value)} />}
    {detail && <RecordDetail key={`${detail.resource}/${detail.value.id}/${detail.value.version}`} resource={detail.resource} value={detail.value} saved={detail.saved} onClose={() => setDetail(null)} onEdit={canWrite && !(detail.resource === "entries" && (detail.value as Entry).status === "cancelled") ? () => edit(detail.resource, detail.value) : undefined} onUseWeighing={canWrite && detail.resource === "weighings" ? fromWeighing : undefined} />}
  </>;
}
