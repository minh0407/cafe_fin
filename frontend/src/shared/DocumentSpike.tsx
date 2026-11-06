import { useState } from "react";
import { Alert, Button, Card, List, Space, Typography } from "antd";
import { api, messageOf } from "./api";
interface SpikeDocument {
  format: string;
  file_id: string;
  sha256: string;
  size: number;
}
interface DocumentResult {
  snapshot_sha256: string;
  documents: SpikeDocument[];
  errors: { format: string; code: string; message: string }[];
}
export function DocumentSpike() {
  const [result, setResult] = useState<DocumentResult | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function generate() {
    setBusy(true);
    setError("");
    try {
      setResult(
        await api<DocumentResult>("/spikes/documents", {
          method: "POST",
          body: JSON.stringify({ request_key: crypto.randomUUID() }),
        }),
      );
    } catch (err) {
      setError(messageOf(err));
    } finally {
      setBusy(false);
    }
  }
  async function download(document: SpikeDocument) {
    setError("");
    try {
      const blob = await api<Blob>(
        `/files/${encodeURIComponent(document.file_id)}/content`,
        {},
        true,
        "blob",
      );
      const url = URL.createObjectURL(blob);
      const link = window.document.createElement("a");
      link.href = url;
      link.download = `Cafe-Fin-mau-tong-hop.${document.format.toLowerCase()}`;
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 60000);
    } catch (err) {
      setError(messageOf(err));
    }
  }
  return (
    <Card title="Bản thử Word / PDF tiếng Việt" className="toolbar">
      <Typography.Paragraph>
        Cùng một snapshot tổng hợp được xuất local thành hai tệp độc lập. Đây là
        chứng từ mẫu kỹ thuật, chưa phải hợp đồng nghiệp vụ.
      </Typography.Paragraph>
      <Button type="primary" loading={busy} onClick={() => void generate()}>
        Tạo mẫu Word / PDF
      </Button>
      {error && (
        <Alert className="toolbar" type="error" title={error} showIcon />
      )}
      {result && (
        <>
          <Typography.Paragraph className="toolbar">
            Snapshot SHA-256:{" "}
            <Typography.Text code>{result.snapshot_sha256}</Typography.Text>
          </Typography.Paragraph>
          <List
            dataSource={result.documents}
            renderItem={(document) => (
              <List.Item>
                <Space wrap>
                  <Button onClick={() => void download(document)}>
                    Tải {document.format}
                  </Button>
                  <Typography.Text>
                    {document.size.toLocaleString("vi-VN")} byte
                  </Typography.Text>
                  <Typography.Text code>{document.sha256}</Typography.Text>
                </Space>
              </List.Item>
            )}
          />
          {result.errors.map((item) => (
            <Alert
              key={item.format}
              type="error"
              title={`${item.format}: ${item.message}`}
              showIcon
            />
          ))}
        </>
      )}
    </Card>
  );
}
