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
- NOT RUN tại lane frontend: collector nguồn công khai thật, Docker relay và Windows GUI. Fixture không chứng minh lấy được giá thị trường hiện tại. Nếu live source trả HTTP403 hoặc trang challenge, app phải hiện BLOCKED và không có giá tự động mới.

Không commit DB, Excel, HTML nguồn live, token hoặc ảnh chụp dữ liệu thật. Chưa gọi production-ready.

## Bổ sung kiểm thử API thật

Theo allowlist mở rộng của điều phối, chỉ thêm `tests/records/browser/market.spec.mts`, sửa test host `tests/records/browser/server.py` và cập nhật bàn giao này. Backend `8c85f7e` được cherry-pick cục bộ để chạy; commit bổ sung chỉ chứa tests/bàn giao, không đưa lại backend khi tích hợp.

Test host luôn đặt `CAFE_FIN_MARKET_NETWORK=0` cho các suite thông thường. Chỉ child process có `CAFE_FIN_RECORDS_TEST_MARKET=1` mới đặt network gate 1 và thay đúng transport `market_http.download_html` bằng HTML tổng hợp đúng ngày, challenge hoặc ngày hôm qua. Parser, API auth, runtime, timer chu kỳ 10 giây, service, writer, migration, evidence/audit và SQLite WAL đều chạy thật. Không mock HTTP route hoặc sửa product API. Các control test-only cần app session, local user có quyền ghi và khóa ngẫu nhiên riêng; không đăng ký khi marker môi trường vắng. Control chỉ đổi nguồn fixture, xem số lần fetch/timer và kết thúc cooldown fixture để không đợi một giờ.

Hai ca browser thật chứng minh:

1. Timer tự tạo APPLIED đúng ngày từ HTML tổng hợp, provenance và năm Grade hiện qua UI, hai lượt timer vẫn chỉ một lần fetch. Toggle tắt/bật qua UI tăng settings_version; bảng tự động ẩn sửa/xóa. Bảng theo hàng và đơn đã lưu trước lượt tự lấy giữ nguyên snapshot/giá; không có chuyển động kho.
2. Timer đọc challenge thành BLOCKED, nút kiểm bị khóa trong cooldown; khi cooldown fixture hết, check-now đọc HTML ngày hôm qua thành STALE_SOURCE. Cả hai không có snapshot/board và UI không hiện giá đã áp dụng. Bảng chung nhập tay của ngày trước trả EXISTING_BOARD, sửa giá qua UI thành version 2.

Lệnh trên Windows PowerShell (port riêng, không đụng phiên 1421 của điều phối):

```powershell
$env:CAFE_FIN_RECORDS_TEST_PORT='1423'
$env:CAFE_FIN_RECORDS_TEST_PYTHON='C:\Users\NC\.codex\worktrees\cafe-fin-foundation-recovery\cafe_fin\.venv\Scripts\python.exe'
node frontend/node_modules/@playwright/test/cli.js test --config tests/records/browser/playwright.config.mts market.spec.mts
```

PASS: 2 tests / 39,3 giây (ca APPLIED 22,9 giây, ca BLOCKED/STALE 14,2 giây); không có browser page error. PASS: `git diff --check`. Không sửa mã sản phẩm trong lượt bổ sung nên giữ kết quả typecheck/build đã ghi ở trên.

Nguồn trong hai ca này là tổng hợp, không gọi WAN và không được dùng làm bằng chứng nguồn công khai đang có giá. DB mới nằm trong thư mục tạm, được xóa khi test kết thúc; chỉ mã/fixture generator được commit. Proof JSON đính kèm kết quả Playwright ghi mode actual API/SQLite, source_date động, số fetch/timer và trạng thái từ API thật.
