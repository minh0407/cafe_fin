# Backend bảng giá — increment 13

Worktree: `C:\Users\NC\.codex\worktrees\cafe-fin-pricing-api\cafe_fin`.
Branch: `codex/cafe-fin-pricing-api-20261107`; baseline giao bởi điều phối `e9cb099`.
Không push hoặc merge lane khác.

## Thay đổi

- Resource `price-boards` dùng các bảng version/audit/idempotency records hiện có,
  CRUD, lịch sử, xóa mềm/khôi phục và khóa duy nhất cả sau xóa. Code/name server
  sinh; ngày/nhóm/hàng bất biến. Không migration hoặc sửa core/read bridge.
- `POST /api/v1/records/price-board-preview` và
  `GET /api/v1/records/price-quote` theo contract `pricing-v1.md`.
  Giá theo đúng ngày, hàng riêng ưu tiên chung; giá bán chọn hàng và độc lập
  hoàn toàn với mua tươi/mua chế biến. Flat không cần Grade.
- Tính Grade5 xuống Grade1 bằng integer cents: `(previous * 90 + 50) // 100`
  từng bước, tương đương ROUND_HALF_UP 2 số lẻ cho giá không âm. Chỉ đọc
  `backend/app/services/grade_prices.py` của CRM cũ để đối chiếu quy tắc;
  không truy cập hoặc thay đổi DB cũ.
- Daily TradeLine được server quyết định đơn giá, lưu đủ nguồn/version/công thức.
  Quote giả bị 422; quote hợp lệ nhưng không còn hiện hành khi tạo/đổi tiêu chí
  bị `PRICE_CHANGED`409, kể cả bảng đã ngừng/xóa. Thiếu bảng không có fallback
  giá hôm trước hoặc giá 0. Đơn không tự tạo tiền hay ledger.
- Khi chỉ sửa kg/bao/ghi chú, xác thực snapshot theo revision bảng bất biến rồi
  đối chiếu một dòng cũ cùng chiều/ngày nghiệp vụ/Farm/ngày giá/nhóm/hàng/Grade.
  Mỗi dòng cũ được tiêu thụ tối đa một lần; đổi thứ tự/xóa dòng không đổi nguồn,
  sao chép không cấp thêm quyền dùng giá cũ. Thay đơn giá bị chặn. Bảng thay
  đổi/ngừng/xóa không làm hỏng sửa, xóa hoặc khôi phục đơn đã lưu.
- Đổi `occurred_on` luôn kiểm quote hiện hành kể cả `price_date` tường minh
  vẫn giữ nguyên. Ngày giá tường minh là ngày lookup. Update daily với
  snapshot null bị `PRICE_SNAPSHOT_REQUIRED`422; phải giữ snapshot hoặc gửi
  quote mới. Create daily với snapshot null được tra hiện hành tại server.
- Trade cũ mặc định manual; các field mặc định mới được bỏ khỏi fingerprint
  đệ quy theo từng line, giữ replay receipt trước nâng cấp và nguyên JSON
  revision cũ. HTTP đọc áp default qua DTO, không viết lại revision.

## Kiểm chứng

Python dùng interpreter của worktree điều phối, `pytest` lấy backend của
worktree này qua cấu hình `pythonpath=backend`. Fixture là SQLite WAL file thật
và HTTP xác thực thật, dữ liệu tổng hợp; không dùng SQLite để chứng minh CRM
PostgreSQL cũ.

- PASS: `python -m pytest tests/records -q --tb=short`: **192 passed**,
  115,76 giây; gồm **23** pricing tests và hồi quy toàn bộ records. Chỉ có
  cảnh báo deprecation Starlette/httpx hiện có.
- PASS: `python -m compileall -q backend/cafe_fin/records`.
- PASS: `python -m ruff check backend/cafe_fin/records tests/records/test_records_pricing.py`.
- PASS: `git diff --check`.
- NOT RUN tại commit backend đầu: toàn bộ backend, browser thật, Docker và
  native Windows. Điều phối thực hiện kiểm liên module/Docker sau tích hợp;
  browser pricing có thể bàn giao commit kiểm thử tiếp theo.

Không thêm dependency, file DB, Excel, token hoặc log nhạy cảm. Không tuyên bố
production-ready hoặc benchmark triệu bảng giá. Bộ cài Windows không nằm trong
phạm vi increment backend này.

## Kiểm thử browser bổ sung

Commit kiểm thử tiếp theo chỉ thay `tests/records/browser/**` và handoff này.
Nguồn UI lane pricing được chép tạm vào worktree để chạy, không đưa vào commit
backend/test; khi tích hợp cần lấy commit UI của lane riêng.

- PASS: `node frontend/node_modules/@playwright/test/cli.js test --config
  tests/records/browser/playwright.config.mts pricing.spec.mts`: **1 passed**,
  test 18,6 giây, toàn lệnh 21,0 giây. Env
  `CAFE_FIN_RECORDS_TEST_PORT=1423`, `CAFE_FIN_RECORDS_TEST_PYTHON` trỏ interpreter
  worktree `cafe-fin-foundation-recovery/cafe_fin/.venv/Scripts/python.exe`.
- PASS: cùng lệnh với `commerce.spec.mts records.spec.mts`, port1424:
  **2 passed**, 44,7 giây. Luồng nhập tay cũ chọn rõ mode manual và giữ nguyên
  toàn bộ assertion nghiệp vụ/stock/payment/retry trước đây.
- Pricing browser chạy Chromium thật, React thật, authenticated HTTP và SQLite
  WAL mới. Không mock API. Chỉ catalog được seed qua API; bảng mua/bán, preview,
  tạo/sửa đơn, cập nhật bảng và tạo/post phiếu kho qua UI. Một writer HTTP thật
  sửa bảng sau lúc xem quote để mô phỏng cạnh tranh, kiểm stale409 và lấy lại.
- Kiểm Grade3 từ Grade5=100.05 cho81.05; SALE riêng200.01, nhập kg3.001 cho
  600.23001. Sửa bảng bán300.00 rồi sửa kg đơn thành4.001 vẫn giữ nguồnv1/
  200.01 và cho800.24001, không request quote lại. Đơn/giá không tự tạo tồn;
  post phiếu xuất bị `STOCK_NEGATIVE`409. Quotev2 bị đổi thànhv3 trong lúc xem
  trả `PRICE_CHANGED`409, không tạo đơn; bấm “Lấy lại giá mới” rồi lưu400.00.
- Đã phát hiện lỗi PricesPage tự ghi lại hash trang cũ khi rời trang; lane UI
  sửa guard listener/URL effect, sau đó browser pricing PASS cả điều hướng thật.
- Đã xem screenshot kết quả trong `frontend/test-results/records/`; dữ liệu
  tổng hợp, không commit ảnh hoặc DB. Detail hiển thị nguồn/ngày/version giá.

Toàn bộ backend liên module, Docker và native Windows vẫn do điều phối xác nhận.

Lượt tích hợp UI cuối: khi điều phối chạy đồng thời browser chính83 tests và
toàn bộ backend, browser pricing hết hạn waiter10 giây ở lần lưu sau stale409/
refresh; UI vẫn hiện nguồnv3/400.00 và nút loading. Chạy riêng đúng UI cuối,
test/backend chưa sửa: PASS17,7 giây (toàn lệnh19,8 giây), không tái hiện lỗi
nghiệp vụ. Waiter riêng của pricing được chỉnh20 giây vì nó khởi đầu trước khi
click/form submit và API sản phẩm cho15 giây mỗi request. Giữ nguyên predicate
endpoint/method/status và mọi assertion; không tăng timeout API sản phẩm hoặc
đổi nghiệp vụ.
