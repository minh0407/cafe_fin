# Bàn giao giao diện giá nhân xô tự động

Worktree: `C:\Users\NC\.codex\worktrees\cafe-fin-market-ui\cafe_fin`.
Branch: `codex/cafe-fin-market-ui-20261107`, baseline `fc7f03c`.
Commit triển khai được ghi trong bàn giao của lane; không push hoặc merge.

## Hành vi

- Thẻ “Tự động giá nhập nhân xô Robusta Gia Lai” trên Bảng giá đọc trạng thái thật từ API local. Hiện nguồn cố định, ngày bảng/ngày giá nguồn đã xác nhận, lần kiểm, thời điểm được kiểm lại, trạng thái và lý do. BLOCKED, STALE_SOURCE, MISSING_SOURCE_DATE, NETWORK_DISABLED và các trạng thái khác có nhãn tiếng Việt; thiếu dữ liệu không thay bằng 0 hoặc giá hôm qua.
- Giá quả tươi ghi rõ tiếp tục nhập tay, không quy đổi từ nhân xô; giá bán thiết lập riêng. Không có quy trình duyệt hoặc thay đổi tiền/kho.
- Khi APPLIED, hiện Grade5 từ snapshot và đủ năm Grade từ endpoint preview đã có; không tính tiền bằng float. Link nguồn chỉ dùng literal HTTPS allowlist, không render HTML hoặc URL tùy ý từ response. Decoder kiểm schema, nguồn, khoảng giá, ngày và liên kết board/version của APPLIED; phản hồi mutation không hợp lệ giữ kết quả chưa rõ.
- Toggle dùng `expected_version` và request key mới cho một thao tác mới. Check-now chỉ gửi `{request_key}`, tôn trọng enabled/network/cooldown/FETCHING/APPLIED/EXISTING_BOARD. Phiên chỉ đọc và bảo trì khóa mutation.
- Kết quả mutation chưa rõ giữ nguyên body/key/version và lựa chọn, khóa các thao tác giá tự động mới; chỉ nút kiểm tra cùng yêu cầu mới gửi lại. Tải lại GET không tự xác nhận mutation chưa rõ. Khi lỗi có kết luận như VERSION_CONFLICT, tải trạng thái mới trước thao tác tiếp.
- Status GET tối đa mỗi 30 giây khi trang giá đang hiển thị; dừng polling khi tab ẩn/rời trang. Session generation được đưa vào cache key và kiểm trước khi nhận mutation; logout/chuyển phiên bỏ phản hồi cũ. Không tự POST lại qua polling.
- Detail gọi status theo đúng ngày bảng. Chỉ APPLIED cùng board_id mới hiện lý do chỉ đọc và ẩn sửa/ngừng/xóa/khôi phục; vẫn xem lịch sử/nguồn. EXISTING_BOARD hoặc APPLIED của board khác giữ CRUD tay. Khi chưa xác minh được nguồn, tạm khóa CRUD để không mở nhầm bảng tự động. Backend vẫn là lớp kiểm tra quyền/bất biến quyết định.
- Danh sách bảng giá giữ phân trang server 25 dòng; lịch sử giữ phân trang 20 dòng. Không sửa shared App, session, API client, dependency hoặc manifest.

## Files và interface

- `frontend/src/features/records/ProcessedMarket.tsx`: DTO/decoder/status query, thẻ nguồn, provenance và mutation có phục hồi kết quả chưa rõ.
- `frontend/src/features/records/PricesPage.tsx`: gắn thẻ, xác minh quyền sửa bảng theo nguồn/ngày, giữ lịch sử.
- `frontend/tests/market.spec.ts`, `frontend/tests/market.config.ts`: fixture tổng hợp và browser contract tests.
- `frontend/tests/pricing.spec.ts`: thêm response market NETWORK_DISABLED cho fixture cũ; không bật WAN.
- `docs/handoffs/records/market-frontend.md`: bàn giao này.

API tuân thủ nguyên trạng `market-v1.md`: GET `/records/market/processed[?price_date]`, PUT `/records/market/processed/settings`, POST `/records/market/processed/check`. Năm Grade dùng POST read-only `/records/price-board-preview` đã có. Backend lane xác nhận parser_version là string, settings_version bắt đầu 1, snapshot/APPLIED coherent. Không có migration frontend hoặc yêu cầu đổi interface chung.

## Kiểm chứng

- PASS: `npm ci --ignore-scripts` (không đổi dependency/lock).
- PASS: `npm run typecheck`.
- PASS: `npx playwright test --config tests/market.config.ts`: 40 tests, gồm 17 market và 23 pricing/CRM; Chromium, Vite local port 1438, fixture tổng hợp. Kiểm APPLIED/năm Grade/nguồn/ngày, nguồn bị chặn/cũ/thiếu/network disabled, cooldown, CRUD auto/manual/different board, read-only, toggle version, bốn ca unknown mutation 200/500 và exact retry, session race, polling 30 giây và rời trang, URL nguồn không hợp lệ.
- PASS: `npm run build`. Vite giữ cảnh báo chunk lớn hơn 500 kB hiện có; không thêm dependency để xử lý ngoài phạm vi.
- PASS: `git diff --check`.
- NOT RUN: lint riêng, vì package không khai báo script lint.
- NOT RUN tại lane frontend: API/SQLite thật, collector nguồn công khai thật, Docker relay và Windows GUI. Điều phối/backend kiểm riêng sau tích hợp; fixture không chứng minh lấy được giá thị trường hiện tại. Nếu live source trả HTTP403, app phải hiện BLOCKED và không có giá tự động mới.

Không commit DB, Excel, HTML nguồn live, token hoặc ảnh chụp dữ liệu thật. Chưa gọi production-ready.
