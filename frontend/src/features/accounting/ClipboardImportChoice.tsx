import { Alert, Button, Space } from 'antd';
export function ClipboardImportChoice({ file, disabled, onAccept, onDiscard }: { file: File | null; disabled?: boolean; onAccept: () => void; onDiscard: () => void }) {
  if (!file) return null;
  return <Alert className="toolbar" type="warning" showIcon title="Clipboard lớn cần một lượt nhập mới" description={`Đã giữ ${file.size} byte trong một tệp CSV sinh từ clipboard, dấu phân cách tab, UTF-8, không có dòng header. Lượt mới cần xem mapping, validate và xác nhận. Không ghi đè job hiện tại hoặc dòng chưa tải; lưu/bỏ bản nháp hiện tại trước khi tiếp tục.`} action={<Space wrap><Button type="primary" disabled={disabled} onClick={onAccept}>Đưa clipboard lớn vào lượt nhập mới</Button><Button onClick={onDiscard}>Bỏ clipboard</Button></Space>} />;
}
