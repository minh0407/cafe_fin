# Tự lấy giá thị trường nhân xô — increment 14

Điều phối giao từ `be1b696`. Người dùng yêu cầu lấy cơ chế tự động trong CRM cũ và xác nhận: **nhân xô tự động, quả tươi tiếp tục nhập tay**. Giá bán vẫn cài riêng. Đây là ngoại lệ Internet mới do người dùng yêu cầu, ngoài Telegram; toàn bộ DB/tệp/nghiệp vụ vẫn local. Không đọc/chuyển DB CRM cũ.

## Provider và quy tắc

- Chỉ GET cố định `https://banggianongsan.com/bang-gia-ca-phe/`, Robusta nhân xô Gia Lai, VND/kg. Port bộ đọc `market_banggianongsan.py`/HTTP đã kiểm trong CRM, không port Celery/PostgreSQL/ảnh/duyệt nguồn. Không cấu hình URL tùy ý, không sử dụng fixture fresh như nguồn thật.
- Giá nhân xô là Grade5 của bảng chung `price_kind=purchase_processed`, product_id=null, method=grade. Grade4→1 dùng hàm hiện có (90% từng bước HALF_UP2). Chỉ áp đúng ngày Việt Nam; không lấy hôm qua hoặc đổi ngày nguồn thành ngày máy. Không tạo giá tươi/giá bán/payment/stock.
- Parser xác minh nhãn hàng/vùng/đơn vị, ngày công bố có timezone từ Dataset/dateModified hoặc metadata như CRM; kiểm xung đột structured/table. Giá10.000–500.000 VND/kg, precision2. Không chạy JS hoặc lấy chart/futures/USD làm giá nhập. Thiếu/sai/ngày cũ/tương lai/challenge => trạng thái lỗi rõ, không tạo bảng.
- HTTPS443, TLS hostname verification, pin public DNS IP, cấm private/loopback/link-local/metadata/redirect, max2MiB UTF8 HTML, no compression, timeout tổng có giới hạn phù hợp shutdown (mục tiêu8s kể cả DNS). User-Agent nhận diện CafeFin, không giả browser để vượt chặn. 403/challenge giữ BLOCKED, backoff1h; 429 tôn trọng Retry-After; lỗi khác tối thiểu5phút. Không log raw HTML/body/credential. Lưu hash/provenance, không commit HTML live.
- Mỗi ngày tối đa một lần áp. Bảng chung đã có (kể cả ngừng/xóa mềm) hoặc lịch sử đã áp => giữ nguyên, không overwrite/refetch sau thành công. Bảng tự động đã áp không được PUT/delete/restore qua CRUD tay, trả MARKET_BOARD_MANAGED409; có thể thêm giá riêng theo hàng nếu cần. Giá của đơn đã chốt vẫn frozen như increment13.

## Backend và lifecycle

- Records sở hữu migration **v2 mới**, prefix records_, không sửa v1/checksum. Settingssingleton enabled=true mặc định (yêu cầu tự động), version; trạng thái theo ngày có attempts/last_checked/next_attempt/lease token+expiry; evidence bất biến theo ngày chứa URL/source_date/price/fetched_at/region/product/unit/parser_version/html_sha256/board_id+version. Giá/board/evidence/APPLIED/audit cùng transaction ngắn. Fetch ở ngoài writer, claim+finalize có lease, recheck ngày/config/board. Hai request/timer/restart không tải hoặc áp lặp.
- Service identity UUID cố định `00000000-0000-4000-8000-000000000014`, chỉ dùng nội bộ collector/audit; không tạo tài khoản đăng nhập/giả người dùng hoặc cho client chọn actor. Public API vẫn auth records.read/write, revalidate quyền khi mutation. Có thể helper tạo board nội bộ trong transaction, dùng PriceBoard validator/normalizer hiện có; không gọi writer lồng nhau hoặc bỏ validation cho public CRUD.
- Dùng ModuleManifest PeriodicTask khoảng10s, persistedcooldown5m thực tế giữa lần tải; không giữ writer khi HTTP, tuân thủ admission/maintenance/shutdown. Runtime mở sẽ kiểm sau khi sẵn sàng; không hứa chạy khi máy/app tắt. GET status không ghi DB. Tắt enabled dừng lần tải mới; checkNow vẫn tôn trọng cooldown và không bypass tắt.
- Gate môi trường `CAFE_FIN_MARKET_NETWORK=0` chặn mạng collector kể cả settings enabled; mặc định production1. Root đặt0 cho unit/browser CI (test cụ thể bật1 và fake adapter), Docker thật bật1. Status nêu network_available thật. Tránh unit fixtures tự gọi WAN.
- API tương đối `/api/v1/records`:
  - `GET /market/processed?price_date=YYYY-MM-DD` (mặc định hôm nay).
  - `PUT /market/processed/settings` body `{request_key,expected_version,enabled}`.
  - `POST /market/processed/check` body `{request_key}`; check hôm nay, không URL/date tùy ý, bounded HTTP hoặc enqueue hữu hạn; trả Status giống GET để UI poll.
- Status thống nhất: `price_date,today,enabled,settings_version,network_available,status,source_url,board_id,board_version,attempts,last_checked_at,next_attempt_at,detail,snapshot`.
- Status enum `DISABLED,NETWORK_DISABLED,WAITING_SOURCE,FETCHING,APPLIED,EXISTING_BOARD,NO_HISTORY,BLOCKED,RATE_LIMITED,NETWORK_ERROR,HTTP_ERROR,REDIRECT_BLOCKED,UNSAFE_ADDRESS,SOURCE_CHANGED,CONFLICTING_SOURCE,MISSING_SOURCE_DATE,STALE_SOURCE,FUTURE_SOURCE,INVALID_PRICE,WRONG_UNIT,DAY_CHANGED` (parser lỗi khác ánh xạ an toàn sang SOURCE_CHANGED). Snapshot nullable gồm `source_url,source_date,price_vnd_per_kg,fetched_at,region='Gia Lai',product='ROBUSTA_GREEN_BEAN',unit='VND/kg',parser_version,html_sha256,board_id,board_version`.

## UI

Card trên Bảng giá: “Tự động giá nhập nhân xô Robusta Gia Lai”, nguồn/link/ngày giá/tình trạng/lần kiểm/kiểm lại/toggleenabled, Grade5 và năm Grade nếu đã áp. Giá quả tươi nhập tay ghi rõ, giá bán riêng. Dữ liệu không lấy được phải báo nguồn bị chặn/cũ/thiếu, không hiện đã cập nhật. Status refetch hữu hạn khi tab mở; requestkey/version/unknown-save giữ ổn định, session reset và nút theo quyền. Auto board detail giữ readonly với lý do; lịch sử/nguồn vẫn xem được.

## Docker và phân công

Backend giữ internalnetwork. Root thêm service relay `market-source` không mount data/secret, không publishhostport, chỉ endpoint cố định `/source`, có egress riêng, TLS directfetch cùng adapter đã kiểm. Backend chỉ dùng relay khi `CAFE_FIN_MARKET_RELAY_URL=http://market-source:8080/source` cấu hình Compose; không nhận URL từ người dùng. Relay timeout/bodysize/header/error phải bounded; không là openproxy và không lấy mạng khi healthcheck. Backend vẫn parse/validate trước ghi. Windows dùng direct HTTPS.

Backend lane: backend/cafe_fin/records/** tests/records/** docs/handoffs/records/market-backend.md; thêm migrationv2/collector/parser/http/guard/module. Root sở hữu relay script/Docker/Compose/test env/CI/commondocs. Frontend lane: frontend/src/features/records/** frontend/tests/market* docs/handoffs/records/market-frontend.md; không sửa App/shared. Báo interface cần đổi sớm. Không push/merge lane khác.

Kiểm: parser synthetic + transportpublicDNS/TLS/redirect/time/2MiB; exactday/currentdate metadata; writer-free fetch, two claims, midnight/configflip/lease expiry, atomic apply/audit/evidence, alreadyboard/deleted/manualrace, immutableauto board và snapshot cũ, timer real/cancel/maintenance, auth/version/idempotency; browser thật; Docker relay khôngpublic/no data; liveGET riêng và báo chính xác ACCEPTED/BLOCKED/STALE, không dùng fake chứng minh nguồn thật.
