import { useCallback, useEffect, useRef, useState } from "react";
import { Alert, Button, Card, Checkbox, Col, Descriptions, Empty, Input, Modal, Row, Select, Space, Spin, Table, Tabs, Tag, Typography } from "antd";
import { api, ApiError, messageOf, uploadOriginal } from "../../shared/api";
import { useSession } from "../../shared/session";
import type { Page } from "../../shared/types";
import { ContractEditor, Field } from "./ContractEditor";
import { DocumentView } from "./DocumentView";
import type { Attachment, ContractData, ContractDTO, ContractListItem, ContractTemplate, ExportFormat, ExportVersion, Party, Preview, Weighing } from "./types";
import { emptyLine, newContract } from "./types";
import { contractDateIssues } from "./dateValidation";
import "./contracts.css";

type PendingCommand = { label: string; execute: () => Promise<unknown>; complete: (value: unknown) => void | Promise<void> };
const encoded = encodeURIComponent;
const isUncertain = (error: unknown) => error instanceof ApiError && ["BACKEND_UNAVAILABLE", "INVALID_API_RESPONSE", "UPLOAD_TIMEOUT"].includes(error.code);
const formatDate = (date?: string) => date ? new Date(date).toLocaleString("vi-VN") : "—";

/** A generation key resets drafts even when this feature is mounted outside App. */
export function ContractsPage() {
  const generation = useSession((state) => state.generation);
  const user = useSession((state) => state.user);
  if (!user) return <Empty description="Đăng nhập để mở hợp đồng." />;
  return <ContractsWorkspace key={generation} />;
}

function ContractsWorkspace() {
  const [modal, modalContext] = Modal.useModal();
  const owner = useRef(useSession.getState().generation).current;
  const alive = useRef(true);
  const current = useCallback(() => alive.current && useSession.getState().generation === owner, [owner]);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  const user = useSession((state) => state.user);
  const can = (permission: string) => !!user && (user.role === "admin" || user.permissions.includes("*") || user.permissions.includes(permission));
  const canWrite = can("contracts.write");
  const params = new URLSearchParams(location.hash.split("?")[1] ?? "");
  const [search, setSearch] = useState(params.get("search") ?? "");
  const [query, setQuery] = useState(params.get("search") ?? "");
  const [includeDeleted, setIncludeDeleted] = useState(params.get("include_deleted") === "true");
  const initialPage = Number(params.get("page") ?? 1);
  const [page, setPage] = useState(Number.isSafeInteger(initialPage) && initialPage > 0 ? initialPage : 1);
  const [listing, setListing] = useState<Page<ContractListItem>>({ items: [], total: 0, page: 1, page_size: 20 });
  const [listBusy, setListBusy] = useState(false);
  const [listError, setListError] = useState("");
  const [reload, setReload] = useState(0);
  const listSequence = useRef(0);
  const [templates, setTemplates] = useState<ContractTemplate[]>([]);
  const [selected, setSelected] = useState<ContractDTO | null>(null);
  const [draft, setDraft] = useState<ContractData>(newContract);
  const [pristine, setPristine] = useState(() => JSON.stringify(draft));
  const dirty = JSON.stringify(draft) !== pristine;
  const [preview, setPreview] = useState<Preview | null>(null);
  const [previewPayload, setPreviewPayload] = useState("");
  const [weighing, setWeighing] = useState<Weighing | null>(null);
  const [versions, setVersions] = useState<ExportVersion[]>([]);
  const [versionTotal, setVersionTotal] = useState(0);
  const [versionPage, setVersionPage] = useState(1);
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const [attachmentTotal, setAttachmentTotal] = useState(0);
  const [attachmentPage, setAttachmentPage] = useState(1);
  const [history, setHistory] = useState<ExportVersion | null>(null);
  const [activeTab, setActiveTab] = useState("edit");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [fieldErrors, setFieldErrors] = useState<{ field: string; message: string }[]>([]);
  const [success, setSuccess] = useState("");
  const [pending, setPending] = useState<PendingCommand | null>(null);
  const operation = useRef(false);
  const [attachmentFile, setAttachmentFile] = useState<File | null>(null);
  const [attachmentNote, setAttachmentNote] = useState("");
  const [attachmentStatus, setAttachmentStatus] = useState<Attachment["status"]>("uploaded");
  const [attachmentVersion, setAttachmentVersion] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const [templateEdit, setTemplateEdit] = useState<ContractTemplate | null>(null);
  const [templateTitle, setTemplateTitle] = useState("");
  const [templateBody, setTemplateBody] = useState("");
  const locked = !!busy || !!pending;

  const showError = (err: unknown) => {
    if (!current()) return;
    setError(messageOf(err));
    setFieldErrors(err instanceof ApiError ? err.fields : []);
  };
  useEffect(() => {
    const sequence = ++listSequence.current;
    setListBusy(true);
    setListError("");
    const values = new URLSearchParams({ page: String(page), page_size: "20", search: query, include_deleted: String(includeDeleted) });
    const hash = `/contracts?${values.toString()}`;
    if (location.hash.slice(1) !== hash) historyReplace(hash);
    void api<Page<ContractListItem>>(`/contracts?${values.toString()}`).then((result) => {
      if (current() && sequence === listSequence.current) setListing(result);
    }).catch((err) => {
      if (current() && sequence === listSequence.current) setListError(messageOf(err));
    }).finally(() => { if (current() && sequence === listSequence.current) setListBusy(false); });
  }, [page, query, includeDeleted, reload, current]);
  useEffect(() => {
    void api<{ items: ContractTemplate[] }>("/contracts/templates").then((result) => { if (current()) setTemplates(result.items); }).catch(showError);
    // This effect belongs to a single actor generation.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [current]);

  function adopt(contract: ContractDTO) {
    setSelected(contract); setDraft(contract.data); setPristine(JSON.stringify(contract.data));
    setPreview(null); setPreviewPayload(""); setWeighing(null); setFieldErrors([]);
  }
  async function loadExtras(id: string) {
    const results = await Promise.allSettled([
      api<Page<ExportVersion>>(`/contracts/${encoded(id)}/versions?page=1&page_size=20`),
      api<Page<Attachment>>(`/contracts/${encoded(id)}/attachments?page=1&page_size=20`),
    ]);
    if (!current()) return;
    if (results[0].status === "fulfilled") { setVersions(results[0].value.items); setVersionTotal(results[0].value.total); setVersionPage(1); }
    if (results[1].status === "fulfilled") { setAttachments(results[1].value.items); setAttachmentTotal(results[1].value.total); setAttachmentPage(1); }
    const failure = results.find((result) => result.status === "rejected");
    if (failure?.status === "rejected") showError(failure.reason);
  }
  async function read(label: string, work: () => Promise<void>) {
    if (operation.current || pending || !current()) return;
    operation.current = true; setBusy(label); setError(""); setFieldErrors([]); setSuccess("");
    try { await work(); } catch (err) { showError(err); }
    finally { if (current()) { operation.current = false; setBusy(""); } }
  }
  async function executeCommand(command: PendingCommand) {
    if (operation.current || !current()) return;
    operation.current = true; setBusy(command.label); setError(""); setFieldErrors([]); setSuccess("");
    try {
      const value = await command.execute();
      if (!current()) return;
      setPending(null);
      await command.complete(value);
    } catch (err) {
      if (!current()) return;
      if (isUncertain(err)) setPending(command);
      else setPending(null);
      showError(err);
    } finally { if (current()) { operation.current = false; setBusy(""); } }
  }
  function mutate<T>(label: string, path: string, payload: Record<string, unknown>, complete: (value: T) => void | Promise<void>, method = "POST") {
    if (locked || operation.current) return;
    const body = JSON.stringify({ request_key: crypto.randomUUID(), ...payload });
    const command: PendingCommand = { label, execute: () => api<T>(path, { method, body }), complete: (value) => complete(value as T) };
    void executeCommand(command);
  }
  async function discardGuard(action: () => void | Promise<void>) {
    if (locked) return;
    if (!dirty) { void action(); return; }
    modal.confirm({ title: "Bỏ thay đổi chưa lưu?", content: "Các trường đang sửa sẽ được thay bằng hợp đồng bạn chọn.", okText: "Bỏ thay đổi", cancelText: "Tiếp tục sửa", onOk: () => { if (current()) return action(); } });
  }
  function openContract(id: string) {
    void discardGuard(() => read("Đang mở hợp đồng", async () => {
      const result = await api<ContractDTO>(`/contracts/${encoded(id)}`);
      if (!current()) return;
      adopt(result); setVersions([]); setAttachments([]); setActiveTab("edit"); setHistory(null);
      setAttachmentFile(null); setAttachmentNote(""); setAttachmentVersion(null); if (fileInput.current) fileInput.current.value = "";
      await loadExtras(id);
    }));
  }
  function createNew() {
    void discardGuard(() => {
      const blank = newContract(); setSelected(null); setDraft(blank); setPristine(JSON.stringify(blank)); setPreview(null); setVersions([]); setVersionTotal(0); setAttachments([]); setAttachmentTotal(0); setHistory(null); setWeighing(null); setActiveTab("edit"); setError(""); setSuccess(""); setFieldErrors([]);
      setAttachmentFile(null); setAttachmentNote(""); setAttachmentVersion(null); setAttachmentStatus("uploaded"); if (fileInput.current) fileInput.current.value = "";
    });
  }
  function save() {
    if (!validateDraftDates()) return;
    mutate<ContractDTO>("Đang lưu hợp đồng", selected ? `/contracts/${encoded(selected.id)}` : "/contracts", { ...(selected ? { expected_version: selected.version } : {}), data: draft }, async (result) => {
      adopt(result); setSuccess(`Đã lưu hợp đồng ${result.data.number || "chưa có số"} · phiên bản ${result.version}.`); setReload((value) => value + 1); await loadExtras(result.id);
    }, selected ? "PATCH" : "POST");
  }
  function buildPreview() {
    if (!validateDraftDates()) return;
    const payload = JSON.stringify(draft);
    void read("Đang tính và dựng bản xem trước", async () => {
      const result = await api<Preview>("/contracts/preview", { method: "POST", body: JSON.stringify({ data: draft }) });
      if (current()) { setPreview(result); setPreviewPayload(payload); setActiveTab("preview"); }
    });
  }
  function exportCurrent() {
    if (!validateDraftDates()) return;
    if (!selected || dirty) return;
    mutate<ExportVersion>("Đang xuất Word và PDF", `/contracts/${encoded(selected.id)}/exports`, { expected_version: selected.version, formats: ["docx", "pdf"] }, async (result) => {
      setHistory(result); setActiveTab("history"); setSuccess("Đã lưu snapshot xuất. Xem trạng thái từng định dạng bên dưới."); await loadExtras(selected.id);
    });
  }
  function validateDraftDates() {
    const issues = contractDateIssues(draft);
    if (!issues.length) return true;
    setError("Kiểm tra ngày trong hợp đồng trước khi lưu, xem trước hoặc xuất.");
    setFieldErrors(issues);
    setSuccess("");
    setActiveTab("edit");
    return false;
  }
  function retryFormat(version: ExportVersion, format: ExportFormat) {
    mutate<ExportVersion>(`Đang tạo lại ${format.toUpperCase()} từ snapshot`, `/contracts/${encoded(version.contract_id)}/versions/${encoded(version.id)}/files`, { formats: [format] }, async (result) => {
      setHistory(result); await loadExtras(version.contract_id);
    });
  }
  function openVersion(version: ExportVersion) {
    void read("Đang đọc snapshot đã xuất", async () => {
      const result = await api<ExportVersion>(`/contracts/${encoded(version.contract_id)}/versions/${encoded(version.id)}`);
      if (current()) setHistory(result);
    });
  }
  async function download(path: string, filename: string) {
    void read("Đang tải tệp", async () => {
      const blob = await api<Blob>(path, {}, true, "blob");
      if (!current()) return;
      const url = URL.createObjectURL(blob);
      try {
        if (!current()) return;
        const link = document.createElement("a"); link.href = url; link.download = filename.replace(/[\\/:*?"<>|\u0000-\u001f]/g, "_"); link.click();
      } finally { setTimeout(() => URL.revokeObjectURL(url), 60000); }
    });
  }
  function attach() {
    if (!selected || !attachmentFile || locked) return;
    if (attachmentFile.size > 20 * 1024 ** 2 || !/\.(pdf|docx|png|jpe?g|tiff?)$/i.test(attachmentFile.name)) {
      setError("Chọn tệp PDF, DOCX, PNG, JPEG hoặc TIFF, tối đa 20 MiB."); return;
    }
    const id = selected.id, file = attachmentFile;
    const uploadKey = crypto.randomUUID(), attachmentKey = crypto.randomUUID();
    const details = { version_id: attachmentVersion, note: attachmentNote, status: attachmentStatus };
    const command: PendingCommand = {
      label: "Đang lưu tệp đính kèm",
      execute: async () => {
        const original = await uploadOriginal(file, "documents", uploadKey);
        if (!current()) throw new ApiError("STALE_SESSION", "Phiên đã thay đổi.");
        return api<Attachment>(`/contracts/${encoded(id)}/attachments`, { method: "POST", body: JSON.stringify({ request_key: attachmentKey, file_id: original.id, ...details }) });
      },
      complete: async () => {
        setAttachmentFile(null); setAttachmentNote(""); if (fileInput.current) fileInput.current.value = "";
        setSuccess("Đã lưu tệp đính kèm và tình trạng do bạn ghi."); await loadExtras(id);
      },
    };
    void executeCommand(command);
  }
  function loadParty(id: string, target: "company" | "counterparty") {
    void read("Đang lấy thông tin đối tác", async () => {
      const { id: sourceId, version, ...party } = await api<Party & { id: string; version: number }>(`/contracts/sources/parties/${encoded(id)}`);
      if (!current()) return;
      modal.confirm({ title: "Xem và áp dụng thông tin đối tác", width: 780, okText: "Dùng thông tin nguồn", cancelText: "Giữ thông tin đang nhập", content: <>
        <Typography.Paragraph>Thông tin của {target === "company" ? "công ty" : "đối tác"} sẽ được thay bằng bản sao nguồn v{version}. Bạn có thể sửa tiếp trước khi lưu.</Typography.Paragraph>
        <Row gutter={16}><Col span={12}><PartySummary title="Đang nhập" party={draft[target]} /></Col><Col span={12}><PartySummary title="Từ nguồn" party={party} /></Col></Row>
      </>, onOk: () => {
        if (!current() || operation.current) return;
        setDraft((value) => ({ ...value, [target]: party, source_refs: [...value.source_refs.filter((ref) => !(ref.type === "party" && ref.id === sourceId)), { type: "party", id: sourceId, version }] }));
      } });
    });
  }
  function loadWeighing(id: string) {
    setWeighing(null);
    void read("Đang lấy phiếu cân", async () => {
      const result = await api<Weighing>(`/contracts/sources/weighings/${encoded(id)}`);
      if (current()) setWeighing(result);
    });
  }
  function useWeighing(indices: number[]) {
    if (!weighing || locked) return;
    if (indices.some((index) => draft.lines.some((line) => line.source?.id === weighing.id && line.source.line_index === index))) {
      setError("Một dòng phiếu cân đã có trong hợp đồng. Bỏ dòng hoặc liên kết cũ trước khi chọn lại để tránh cộng hai lần."); return;
    }
    const selectedLines = indices.map((index) => {
      const line = weighing.lines[index];
      return { ...emptyLine(), ...line, description: line.description ?? "", quantity_kg: line.net_kg ?? "", unit_price: "", source: { type: "weighing" as const, id: weighing.id, version: weighing.version, line_index: index, code: weighing.code, occurred_on: weighing.occurred_on }, source_snapshot: { ...line } };
    });
    setDraft((value) => ({ ...value, lines: value.lines.length === 1 && !value.lines[0].description && !value.lines[0].quantity_kg && !value.lines[0].unit_price && !value.lines[0].source ? selectedLines : [...value.lines, ...selectedLines], source_refs: [...value.source_refs.filter((ref) => !(ref.type === "weighing" && ref.id === weighing.id)), { type: "weighing", id: weighing.id, version: weighing.version }] }));
    setSuccess("Đã sao chép các dòng cân đã chọn. Kiểm tra kg hợp đồng và nhập đơn giá trước khi lưu.");
  }

  const versionPanel = (version: ExportVersion) => <Card size="small" className="contracts-section" title={`Snapshot · hợp đồng v${version.contract_version}`}>
    <Typography.Paragraph type="secondary">{formatDate(version.created_at)} · {version.id}</Typography.Paragraph>
    <Typography.Paragraph className="contracts-hash">SHA-256 snapshot: {version.snapshot_sha256}</Typography.Paragraph>
    {version.template_version && <Typography.Paragraph type="secondary">Mẫu phiên bản {version.template_version}{version.sequence ? ` · lần xuất ${version.sequence}` : ""}</Typography.Paragraph>}
    <Row gutter={12}>{(["docx", "pdf"] as const).map((format) => {
      const file = version.files?.[format];
      const ready = file?.status === "succeeded" && !!file.file_id && !file.error_code;
      return <Col span={12} key={format}><Card size="small" title={format === "docx" ? "Word (.docx)" : "PDF"}>
        <Tag color={ready ? "green" : "orange"}>{ready ? "Đã tạo" : file?.error_code ? "Tạo tệp gặp lỗi" : "Chưa có tệp"}</Tag>
        {file?.error_code && <Typography.Paragraph type="danger">{file.error_code}{file.error_message ? `: ${file.error_message}` : ""}</Typography.Paragraph>}
        {file?.sha256 && <Typography.Paragraph className="contracts-hash">SHA-256: {file.sha256}</Typography.Paragraph>}
        {ready ? <Button disabled={locked} onClick={() => void download(`/contracts/${encoded(version.contract_id)}/versions/${encoded(version.id)}/files/${format}`, `${selected?.data.number ?? "hop-dong"}-v${version.contract_version}-${version.id.slice(0, 8)}.${format}`)}>Tải {format.toUpperCase()}</Button> : <Button disabled={locked || !canWrite} onClick={() => retryFormat(version, format)}>Thử tạo {format.toUpperCase()} từ bản này</Button>}
      </Card></Col>;
    })}</Row>
  </Card>;

  return <div className="contracts-workspace">
    {modalContext}
    <div className="contracts-heading"><div><Typography.Title level={2}>Hợp đồng mua và bán</Typography.Title><Typography.Paragraph type="secondary">Nhập thông tin, kiểm tra nội dung và lưu từng bản Word / PDF.</Typography.Paragraph></div><Space wrap>
      {can("contracts.templates") && <Button disabled={locked || !templates.length} onClick={() => { const template = templates.find((item) => item.id === draft.template_id); if (template) { setTemplateEdit(template); setTemplateTitle(template.title ?? ""); setTemplateBody(template.body ?? ""); } }}>Sửa mẫu đang chọn</Button>}
      <Button type="primary" disabled={locked || !canWrite} onClick={createNew}>Lập hợp đồng mới</Button></Space></div>
    <Row gutter={20}>
      <Col flex="330px"><Card size="small" title="Danh sách hợp đồng">
        <Input.Search aria-label="Tìm hợp đồng" placeholder="Tìm số hoặc tên đối tác" value={search} onChange={(e) => setSearch(e.target.value)} onSearch={() => { setPage(1); setQuery(search.trim()); }} allowClear enterButton />
        <Checkbox className="contracts-section" checked={includeDeleted} onChange={(event) => { setIncludeDeleted(event.target.checked); setPage(1); }}>Hiện cả hợp đồng đã xóa</Checkbox>
        {listError && <Alert className="contracts-section" type="error" title={listError} action={<Button size="small" onClick={() => setReload((value) => value + 1)}>Tải lại</Button>} />}
        <Table<ContractListItem> className="contracts-section" size="small" rowKey="id" loading={listBusy} dataSource={listing.items} showHeader={false} locale={{ emptyText: "Chưa có hợp đồng phù hợp" }} pagination={{ current: page, pageSize: 20, total: listing.total, size: "small", showSizeChanger: false, onChange: setPage, showTotal: (total) => `${total} hợp đồng` }} columns={[{ key: "contract", render: (_, item) => <button disabled={locked} className={`contracts-list-item ${selected?.id === item.id ? "selected" : ""}`} onClick={() => openContract(item.id)}>
          <strong>{item.number ?? item.data?.number ?? "Chưa có số"}</strong><Tag color={(item.kind ?? item.data?.kind) === "sale" ? "cyan" : "blue"}>{(item.kind ?? item.data?.kind) === "sale" ? "Bán" : "Mua"}</Tag>
          <span>{item.party_name ?? item.counterparty_name ?? item.data?.counterparty.name ?? "Đối tác"}</span><small>{item.occurred_on ?? item.data?.occurred_on ?? ""} · v{item.version}{item.deleted_at ? " · đã xóa" : ""}</small>
        </button> }]} />
      </Card></Col>
      <Col flex="1" style={{ minWidth: 650 }}>
        <div className="contracts-actionbar"><Space wrap><Typography.Text strong>{selected ? `${selected.data.number || "Hợp đồng"} · v${selected.version}` : "Hợp đồng mới"}</Typography.Text><Tag color={dirty || !selected ? "orange" : "green"}>{dirty || !selected ? "Chưa lưu" : "Đã lưu"}</Tag></Space><Space wrap>
          <Button disabled={locked || !canWrite} onClick={buildPreview}>Xem trước</Button>
          <Button type="primary" disabled={locked || !canWrite || !!selected?.deleted_at || (!!selected && !dirty)} onClick={save}>Lưu hợp đồng</Button>
          <Button disabled={locked || !selected || dirty || !!selected.deleted_at || !canWrite} onClick={exportCurrent}>Xuất Word + PDF</Button>
          {selected && <Button danger={!selected.deleted_at} disabled={locked || !canWrite || dirty} onClick={() => {
            const restoring = !!selected.deleted_at;
            modal.confirm({ title: restoring ? "Khôi phục hợp đồng?" : "Xóa hợp đồng khỏi danh sách đang dùng?", content: "Các snapshot và tệp đã xuất vẫn được giữ để tra cứu.", okText: restoring ? "Khôi phục" : "Xóa hợp đồng", cancelText: "Hủy", onOk: () => {
              if (!current()) return;
              mutate<ContractDTO>(restoring ? "Đang khôi phục hợp đồng" : "Đang xóa hợp đồng", `/contracts/${encoded(selected.id)}${restoring ? "/restore" : ""}`, { expected_version: selected.version }, (result) => { adopt(result); setReload((value) => value + 1); setSuccess(restoring ? "Đã khôi phục hợp đồng." : "Đã xóa hợp đồng; bản đã xuất vẫn được giữ."); }, restoring ? "POST" : "DELETE");
            } });
          }}>{selected.deleted_at ? "Khôi phục" : "Xóa"}</Button>}
        </Space></div>
        {dirty && selected && <Alert className="contracts-section" type="info" title="Có thay đổi chưa lưu. Lưu hợp đồng trước khi xuất phiên bản mới." />}
        {selected?.deleted_at && <Alert className="contracts-section" type="warning" title="Hợp đồng đã xóa. Bạn vẫn có thể đọc và tải các bản đã xuất; khôi phục để sửa tiếp." />}
        {busy && <div className="contracts-section"><Spin size="small" /> <span role="status">{busy}…</span></div>}
        {error && <Alert className="contracts-section" showIcon type="error" title={error} description={fieldErrors.length ? <ul>{fieldErrors.map((field, index) => <li key={index}><code>{field.field}</code>: {field.message}</li>)}</ul> : undefined} />}
        {pending && <Alert className="contracts-section" type="warning" showIcon title="Chưa xác nhận thao tác đã hoàn tất" description="Nội dung gửi đang được giữ nguyên. Kết nối lại rồi thử lại cùng yêu cầu để tránh ghi lặp." action={<Button loading={!!busy} onClick={() => void executeCommand(pending)}>Thử lại yêu cầu đã gửi</Button>} />}
        {success && <Alert className="contracts-section" type="success" showIcon title={success} closable onClose={() => setSuccess("")} />}
        <Tabs activeKey={activeTab} onChange={setActiveTab} className="contracts-section" items={[
          { key: "edit", label: "Nội dung hợp đồng", children: <ContractEditor data={draft} onChange={setDraft} templates={templates} disabled={locked || !canWrite || !!selected?.deleted_at} onLoadParty={loadParty} onLoadWeighing={loadWeighing} weighing={weighing} onUseWeighing={useWeighing} /> },
          { key: "preview", label: "Xem trước", children: preview ? <>
            {previewPayload !== JSON.stringify(draft) && <Alert className="contracts-section" type="warning" title="Dữ liệu đã thay đổi sau lần xem trước. Bấm Xem trước để cập nhật nội dung và số liệu." />}
            <DocumentView preview={preview} />
          </> : <Empty description="Bấm Xem trước để tính số liệu và xem nội dung sẽ đưa vào hợp đồng." /> },
          { key: "history", label: `Bản đã xuất (${versionTotal})`, children: !selected ? <Empty description="Lưu hợp đồng để xuất và giữ lịch sử." /> : <>
            <Typography.Paragraph type="secondary">Mỗi bản xuất giữ dữ liệu, mẫu và tệp riêng. Tạo lại định dạng còn thiếu sử dụng đúng snapshot của bản đó.</Typography.Paragraph>
            <Table<ExportVersion> size="small" rowKey="id" dataSource={versions} pagination={{ pageSize: 20, total: versionTotal, current: versionPage, showSizeChanger: false, onChange: (nextPage) => void read("Đang tải lịch sử xuất", async () => { const result = await api<Page<ExportVersion>>(`/contracts/${encoded(selected.id)}/versions?page=${nextPage}&page_size=20`); if (current()) { setVersions(result.items); setVersionTotal(result.total); setVersionPage(nextPage); } }) }} columns={[
              { title: "Phiên bản hợp đồng", dataIndex: "contract_version", render: (value: number) => `v${value}` },
              { title: "Lần xuất", dataIndex: "created_at", render: formatDate },
              { title: "Định dạng", render: (_, version) => <Space>{(["docx", "pdf"] as const).map((format) => <Tag key={format} color={version.files?.[format]?.status === "succeeded" ? "green" : "orange"}>{format.toUpperCase()}{version.files?.[format]?.error_code ? " · lỗi" : ""}</Tag>)}</Space> },
              { title: "Nội dung", render: (_, version) => <Button size="small" disabled={locked} onClick={() => openVersion(version)}>Xem bản này</Button> },
            ]} />
            {history && <>{versionPanel(history)}{(history.document ?? history.snapshot?.document) ? <DocumentView historical preview={{ document: (history.document ?? history.snapshot?.document)!, totals: history.totals ?? history.snapshot?.totals ?? {} }} /> : <Alert className="contracts-section" type="info" title="Chọn Xem bản này để đọc snapshot đầy đủ." />}</>}
          </> },
          { key: "attachments", label: `Tệp đính kèm (${attachmentTotal})`, children: !selected ? <Empty description="Lưu hợp đồng trước khi đính kèm tệp." /> : <>
            <Card size="small" title="Đính kèm bản ký / scan hoặc chứng từ">
              <fieldset disabled={locked || !canWrite} className="contracts-fieldset">
                <div className="contracts-field"><label htmlFor="contracts-attachment">Chọn tệp</label><input id="contracts-attachment" ref={fileInput} type="file" accept=".pdf,.docx,.png,.jpg,.jpeg,.tif,.tiff" onChange={(e) => setAttachmentFile(e.target.files?.[0] ?? null)} /><Typography.Text type="secondary">PDF, DOCX, PNG, JPEG hoặc TIFF · tối đa 20 MiB.</Typography.Text></div>
                <div className="contracts-field"><label>Gắn với bản xuất</label><Select aria-label="Gắn với bản xuất" disabled={locked || !canWrite} value={attachmentVersion ?? ""} onChange={(value) => setAttachmentVersion(value || null)} options={[{ value: "", label: "Hợp đồng (không chọn bản xuất)" }, ...versions.map((version) => ({ value: version.id, label: `Hợp đồng v${version.contract_version} · ${formatDate(version.created_at)} · ${version.id.slice(0, 8)}` }))]} /></div>
                <div className="contracts-field"><label>Tình trạng do bạn ghi</label><Select aria-label="Tình trạng do bạn ghi" disabled={locked || !canWrite} value={attachmentStatus} onChange={setAttachmentStatus} options={[{ value: "uploaded", label: "Đã đính kèm" }, { value: "user_recorded_signed", label: "Người nhập ghi là đã ký" }]} /></div>
                <Field label="Ghi chú tệp" area value={attachmentNote} onChange={setAttachmentNote} />
                <Button disabled={locked || !canWrite || !attachmentFile} onClick={attach}>Lưu tệp đính kèm</Button>
              </fieldset>
              <Typography.Paragraph type="secondary" className="contracts-section">Tình trạng đã ký là thông tin do người nhập ghi, không xác minh chữ ký điện tử.</Typography.Paragraph>
            </Card>
            <Table<Attachment> className="contracts-section" size="small" rowKey="id" dataSource={attachments} pagination={{ pageSize: 20, total: attachmentTotal, current: attachmentPage, showSizeChanger: false, onChange: (nextPage) => void read("Đang tải tệp đính kèm", async () => { const result = await api<Page<Attachment>>(`/contracts/${encoded(selected.id)}/attachments?page=${nextPage}&page_size=20`); if (current()) { setAttachments(result.items); setAttachmentTotal(result.total); setAttachmentPage(nextPage); } }) }} columns={[
              { title: "Ngày lưu", dataIndex: "created_at", render: formatDate },
              { title: "Tình trạng", dataIndex: "status", render: (value: string) => value === "user_recorded_signed" ? "Người nhập ghi đã ký" : "Đã đính kèm" },
              { title: "Ghi chú", dataIndex: "note" },
              { title: "Bản xuất", dataIndex: "version_id", render: (id: string | null) => id ? id.slice(0, 8) : "Hợp đồng" },
              { title: "Tệp", render: (_, attachment) => <Space orientation="vertical"><Typography.Text>{attachment.original_name ?? "Tệp đính kèm"}</Typography.Text><Button size="small" disabled={locked} onClick={() => void download(`/contracts/${encoded(selected.id)}/attachments/${encoded(attachment.id)}/content`, attachment.original_name ?? `dinh-kem-${attachment.id}`)}>Tải tệp gốc</Button></Space> },
            ]} />
          </> },
        ]} />
      </Col>
    </Row>
    <Modal title={`Sửa mẫu ${templateEdit?.id ?? ""} · v${templateEdit?.version ?? ""}`} open={!!templateEdit} width={900} closable={!locked} maskClosable={!locked} onCancel={() => { if (!locked) setTemplateEdit(null); }} cancelButtonProps={{ disabled: locked }} okButtonProps={{ disabled: locked || !templateTitle.trim() || !templateBody.trim() }} okText="Lưu phiên bản mẫu" cancelText="Hủy" onOk={() => {
      if (!templateEdit) return;
      mutate<ContractTemplate>("Đang lưu mẫu hợp đồng", `/contracts/templates/${encoded(templateEdit.id)}`, { expected_version: templateEdit.version, title: templateTitle, body: templateBody }, (result) => { setTemplates((values) => values.map((item) => item.id === result.id ? result : item)); setTemplateEdit(null); setPreview(null); setPreviewPayload(""); setSuccess("Đã lưu phiên bản mẫu. Các bản đã xuất giữ nguyên nội dung."); }, "PATCH");
    }}>
      <Alert type="info" title="Giữ nguyên các token của mẫu cần điền. Bản xem trước và lần xuất tiếp theo dùng phiên bản mẫu mới; các snapshot cũ không thay đổi." />
      <fieldset disabled={locked} className="contracts-fieldset contracts-section"><Field label="Tiêu đề mẫu" value={templateTitle} onChange={setTemplateTitle} /><Field label="Nội dung mẫu" area value={templateBody} onChange={setTemplateBody} /></fieldset>
    </Modal>
  </div>;
}

function historyReplace(hash: string) {
  window.history.replaceState(null, "", `${location.pathname}${location.search}#${hash}`);
}
function PartySummary({ title, party }: { title: string; party: Party }) {
  return <Card size="small" title={title}><Descriptions column={1} size="small" items={[
    { key: "name", label: "Tên", children: party.name || "—" },
    { key: "type", label: "Loại", children: party.type },
    { key: "address", label: "Địa chỉ", children: party.address || "—" },
    { key: "tax", label: "Mã số thuế", children: party.tax_code || "—" },
    { key: "representative", label: "Đại diện", children: party.representative ? `${party.representative.name} · ${party.representative.title ?? ""}` : "—" },
    { key: "contacts", label: "Liên hệ", children: party.contacts.map((contact) => `${contact.kind}: ${contact.value}`).join("; ") || "—" },
    { key: "banks", label: "Tài khoản", children: party.bank_details.map((bank) => `${bank.bank_name} · ${bank.account_number} · ${bank.account_holder ?? ""} · ${bank.branch ?? ""}`).join("; ") || "—" },
  ]} /></Card>;
}
