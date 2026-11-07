# Docker localhost preview 11

Trạng thái tiếp nối: [increment Farm/khách hàng và luồng 12](FARM_CUSTOMER_FLOWS_12.md) đã cập nhật preview, giữ tài khoản/volume sau bản sao lưu nhất quán. Bằng chứng lần tạo Admin đầu tiên bên dưới là lịch sử nghiệm thu ban đầu.

Người dùng yêu cầu dựng bản localhost trên Docker sau khi kiểm thử Telegram.
Source Telegram đã qua [Windows CI increment 10](TELEGRAM_DELIVERY_INCREMENT_10.md).
Preview dùng nghiệp vụ/API thật, dữ liệu mới trong volume riêng, không mount CRM cũ.

## Bản đang chạy

- URL: **http://127.0.0.1:1420**. Dùng đúng địa chỉ; guard không nhận hostname khác.
- Project: `cafe-fin-local-preview`; backend `cafe-fin` healthy, gateway đang chạy.
- Chỉ gateway xuất bản `127.0.0.1:1420`. Backend không có host port và chỉ ở mạng
  internal `preview-local`. Gateway chỉ proxy tới backend cố định; không giữ DB.
- Data volume `cafe-fin-local-preview_preview-data`, không gắn thư mục dữ liệu thật.
  Trang thật đã được kiểm tra ở trạng thái **Tạo tài khoản quản trị đầu tiên**;
  không tạo sẵn tài khoản hoặc password cho người dùng.
- Python 3.12.16, SQLite 3.53.1, Docker Engine 29.9.1 linux/amd64 trên Docker Desktop.
  Image chỉ build/lưu trên máy, không upload image hoặc phát hành installer.

Từ repo `C:\Users\NC\Desktop\UNILA{\cafe_fin`:

```powershell
docker compose -f compose.preview.yaml up --build -d
docker compose -f compose.preview.yaml ps
docker compose -f compose.preview.yaml stop
```

## Bằng chứng thực tế

| Kiểm tra | Kết quả |
| --- | --- |
| Preview ASGI/guard/storage/version tests, sau tích hợp | 18 PASS / 6.16 s |
| Regression API/sidecar/recovery/secret của lane | 43 PASS trước bổ sung SQLite/gateway |
| Giao diện desktop mặc định, có real API | 57 PASS / 37.0 s |
| Build frontend thường + preview, browser adapter probe | PASS |
| Hai target Docker, pinned source/images, nonroot nginx syntax | PASS |
| Python liên kết SQLite thực trong image | 3.53.1, official source ID và integrity PASS |
| HTTP container: Host/Origin/session/Bearer và Linux secret unavailable | PASS |
| HTTP container: kho, chặn tồn âm/xóa sai tồn, idempotency | PASS |
| HTTP container: import CSV hợp lệ một phần, sửa/nhập tiếp, giữ byte gốc | PASS |
| HTTP container: snapshot báo cáo, TXT/PDF, hợp đồng DOCX/PDF và hashes | PASS |
| Restart backend, capability mới, login/dữ liệu/tệp giữ nguyên | PASS |
| Browser thật tới bản Docker cuối: bootstrap/API, banner, trang tạo Admin | PASS; không native shim hoặc capability trong browser storage |
| Ruff toàn repo và Git whitespace | PASS |

Actual HTTP smoke chạy bằng `tests/preview/docker_smoke.py` trên project tách riêng
`cafe-fin-preview-smoke-20261107-3`; password và tokens chỉ trong bộ nhớ tiến trình.
Script kiểm đúng labels, service, image config, volume, loopback và network trước
khi restart. Kết quả: `SECURITY_AUTH_LINUX`, `RECORDS_IMPORT_REPORT_CONTRACT`,
`RESTART_PERSISTENCE_NEW_CAPABILITY`, `DOCKER_HTTP_SMOKE` đều PASS. Smoke project
được dừng sau thử, volumes giữ lại. Bản cho người dùng dùng project/volume khác.

Image IDs được Docker báo cho bản đang chạy từ checkout chính:

- Backend: `sha256:4606836e45afac1c8a4b8ec9dbc8cc002e04851dbc6e6857c43c3c3cda26c371`.
- Gateway: `sha256:947dd10b6bab916992f9ab010ae9dbd0a947b60a25f8607b72cd59cd7423385e`.

Những ID này là receipt của lượt build, không cam kết reproducible build.

## Quyết định từ chạy thật

Python image Bookworm mang SQLite 3.40.1, bị core từ chối đúng chính sách WAL.
Docker builder biên dịch SQLite 3.53.1 từ archive chính thức có SHA256 pin, kiểm
SHA3 của `sqlite3.c` theo release, rồi kiểm source ID/integrity qua Python. Runtime
chỉ liên kết private library; không hạ guard hoặc đổi dependency/migration core.
Preflight chạy trước khi tạo marker nên phiên bản không hỗ trợ không để lại data
root mới dở dang. Volume synthetic của lượt đầu được giữ, không sửa hoặc tái dùng.

Docker Engine này không xuất bản cổng của service ở network internal. Gateway
riêng giải quyết truy cập loopback và vẫn giữ backend không có WAN. Không mở
backend/public port hoặc thay guard Host/Origin của app để lách vấn đề mạng.

## Giới hạn

Docker preview kiểm thử web và nghiệp vụ local, không thay nghiệm thu app Windows.
Native picker/Explorer/maintenance không được giả thành công. Windows Credential
Manager không có trên Linux: Telegram giữ UNCONFIGURED, không fallback plaintext,
không gửi thật. Tệp báo cáo vẫn tạo và tải qua web. Không dùng Docker preview để
kết luận native installer, clean Windows, packaged million-row benchmark hoặc
source/relink distribution đã hoàn tất. Xem [handoff](../handoffs/packaging/docker-preview.md).
