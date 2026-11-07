# Backend giá nhân xô tự động — increment 14

Worktree: `C:\Users\NC\.codex\worktrees\cafe-fin-market-api\cafe_fin`.
Branch: `codex/cafe-fin-market-api-20261107`; baseline điều phối `fc7f03c`.

## Phạm vi và interface

Chỉ tạo bảng chung `purchase_processed`, Grade5 Robusta nhân xô Gia Lai đúng ngày Việt Nam. Quả tươi tiếp tục nhập tay; giá bán tách riêng. Dùng lại validator PriceBoard, normalizer và công thức Grade hiện có. Không thay snapshot đơn đã lưu, không tạo tiền/kho, không đọc DB/env hoặc sửa CRM cũ.

API giữ nguyên contract [market-v1](market-v1.md): GET status thuần đọc; PUT settings optimistic version/idempotency; POST check chống lặp và không vượt disabled/cooldown. Public API kiểm records.read/write trong transaction; finalize kiểm lại quyền. Service UUID `00000000-0000-4000-8000-000000000014` chỉ ghi collector/audit, không tạo tài khoản đăng nhập.

`market_http.py` export `MarketError(code, detail, retry_at=None)`, `download_direct() -> str`, `download_html() -> str`, `SOURCE_URL`, `MAX_HTML_BYTES`. Direct chỉ nguồn HTTPS đã chốt; relay chỉ nhận env chính xác `CAFE_FIN_MARKET_RELAY_URL=http://market-source:8080/source`, GET `/source` với `X-Cafe-Fin-Market-Relay: 1`; mã lỗi relay qua `X-Cafe-Fin-Market-Error`. Không nhận URL từ API.

## Migration và giao dịch

Migration records v2 mới nằm riêng `migrations/market_v2.py`, khai báo trong manifest; không đổi nội dung/schema/checksum v1. Ba bảng mới `records_market_settings` (enabled=true, version=1), `records_market_days` (claim/cooldown/lease), `records_market_evidence` (bất biến bằng trigger UPDATE/DELETE).

Claim và finalize là hai transaction writer ngắn. Fetch/parse ở giữa, ngoài writer. Lease 30 giây; tối thiểu 5 phút giữa lần tải, BLOCKED chờ 1 giờ, 429 tôn trọng Retry-After. Replay check giữ invocation ownership nên không tải lại cùng receipt, kể cả concurrent retry. Recheck lease/ngày/cấu hình/quyền/bảng hiện có trước ghi; key của bảng thủ công đã xóa vẫn ngăn tạo lại. Board + revision + evidence + audit + APPLIED cùng transaction; lỗi làm rollback toàn bộ phần áp.

Bảng đã áp bị chặn update/delete/restore bằng `MARKET_BOARD_MANAGED`409; vẫn xem lịch sử/quote bình thường. Snapshot nguồn chứa ngày đã xác minh, giá Decimal string, thời điểm tải UTC, tên vùng/hàng/đơn vị, parser version, hash HTML và board/version.

## Lifecycle và transport

Module PeriodicTask 10 giây dùng runner core; cooldown lưu DB kiểm soát tần suất thực. Callback giữ maintenance admission qua claim/fetch/finalize. `CAFE_FIN_MARKET_NETWORK=0` chặn collector trước mọi tải, mặc định production1. Không chạy khi app/máy tắt.

Deadline tổng8 giây bắt đầu trước DNS, OS DNS chỉ chờ tối đa2 giây. Theo quyết định điều phối, duy nhất một daemon transport helper phân giải DNS được giới hạn bằng semaphore; nếu OS DNS treo thì giữ slot và các lần sau trả NETWORK_ERROR, không tích lũy thread. Helper không giữ runtime/DB/callback và không là scheduler mới. Tất cả IP direct phải public; socket pin IP; TLS xác minh hostname nguồn. DeadlineRaw kiểm deadline trước từng recv, kể cả status/header slow-drip. Không redirect, nén, JS/VBA, proxy tùy ý; tối đa2MiB UTF8. User-Agent riêng CafeFin, không giả trình duyệt.

Parser port từ adapter nguồn đã được người dùng chỉ định, loại bỏ ORM/task/DB cũ. Chấp nhận Dataset đúng identity/nhãn/đơn vị hoặc bảng cùng metadata công bố có timezone; ngày máy chỉ là ngày yêu cầu, không là fallback. JSON decimals parse trực tiếp Decimal, precision tối đa2, giá10.000–500.000. Challenge, nguồn cũ/tương lai/mâu thuẫn/mất ngày trả lỗi có kiểu, không lưu quote giả.

## Kiểm chứng và giới hạn

- PASS: focused parser/transport/service tests42 ca, gồm transaction rollback, revoke-during-fetch và timer thật/close.
- PASS: lint `python -m ruff check backend/cafe_fin/records tests/records/test_market.py tests/records/test_market_transport.py`; format các file mới/module.
- PASS: `CAFE_FIN_MARKET_NETWORK=0 python -m pytest tests/records -q`:231 passed/132,39s ở lượt trước3 ca bổ sung;3 ca bổ sung đã PASS trong focused42 ca/19,65s.
- Synthetic tests không gọi WAN. Dùng file-backed SQLite thật của Cafe Fin, không dùng PostgreSQL hoặc chứng minh hành vi CRM cũ.
- LiveGET adapter mới từ host07/11/2026: HTTP200,11953 bytes/0,531s; parser nhận challenge và trả `BLOCKED`, không tạo giá. Lệnh in thông báo tiếng Việt ở console cp1252 gặp UnicodeEncodeError sau khi đã nhận mã BLOCKED; không phải lỗi parser/transport. Lần GET adapter cũ do điều phối chạy trước đó trả HTTP403/BLOCKED. Không có bằng chứng nguồn trả báo giá hiện tại; không gọi production-ready. Relay Docker/Compose, full-backend/CI/browser và gate đóng gói thuộc điều phối.

Không đổi shared/core/dependency/bridge API. Không push/merge. Chỉ code, fixture tổng hợp và handoff được commit; không HTML live/DB/log nhạy cảm trong repo.
