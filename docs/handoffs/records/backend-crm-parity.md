# Backend records: Farm và mua/bán, 07/11/2026

Worktree: `C:\Users\NC\.codex\worktrees\cafe-fin-farm-trade-api\cafe_fin`.
Branch: `codex/cafe-fin-farm-trade-api-20261107`, từ `ac34aac` do điều phối giao.
Commit được ghi trong bàn giao của lane; không push/merge.

## Thay đổi

- Party có profile Farm/công ty, giấy phép, lô và khảo sát tổng hợp. Mã Farm nhập tay,
  chuẩn hóa `upper().strip()`, đúng bốn chữ/số, duy nhất theo mã Party và bất biến
  sau tạo; giữ nguyên fingerprint input cho retry. Mã lô tùy chọn, tối đa 60 ký tự.
  Area/ripeness là chuỗi thập phân tối đa ba số lẻ; tỷ lệ chín từ 0 đến 100.
- `/api/v1/records/trades` và `/trade-payments` có CRUD, history, restore,
  version/audit/idempotency qua writer hiện có. Chưa giao hàng vẫn ghi thu/chi được.
  Công ty cần tên, MST, người liên hệ khi ghi đơn đầu ra hiệu lực; không unique MST.
- Entry thêm `trade_id` tùy chọn. Phiếu liên kết phải đúng receipt/issue;
  outbound cùng công ty; inbound party để trống khi gộp Farm hoặc thuộc Farm của đơn.
  Kg posted cộng dồn theo sản phẩm qua mọi kho/phiếu không vượt đơn. Inbound chưa
  chọn sản phẩm vẫn lưu đơn được, nhưng cần chọn sản phẩm trước ghi sổ phiếu kho.
- Cả cap đơn và stock guard chạy cùng transaction chứa revision/ledger/audit/receipt.
  Kiểm sửa/xóa/đổi ngày/khôi phục, trạng thái hủy và hai writer SQLite vật lý.
  Đơn có phiếu draft/posted hoặc thu/chi hiệu lực không được xóa/hủy, đổi chiều,
  công ty hoặc tập Farm; sửa giá/ghi chú và số lượng còn bao phủ phiếu vẫn được.
- Filter `profile_kind`, `direction`, `trade_id` bổ sung vào list phân trang;
  `profile_kind=general` bao gồm revision cũ thiếu field mới.
- `/api/v1/records/records-dashboard` dùng một connection SQLite read-only BEGIN,
  bind InventorySummaryDTO vào chính snapshot đó. Tối đa 366 ngày gồm hai đầu.
  Farm/khảo sát/công ty đếm toàn bộ hồ sơ active chưa xóa; số đơn tính recorded
  trong khoảng ngày. Kg từ ledger receipt/issue; tồn có mọi loại movement;
  cash in/out từ thu/chi thực tế của trade; không đọc/cộng sổ Excel hay số dư thương mại.
  Giá trị đơn outbound có đủ giá là tích/sum chính xác kg × đơn giá, từ hai đến năm
  số lẻ, không làm tròn; đơn thiếu giá đếm riêng, không cộng một phần giá trị.

## Tương thích và migration

Không migration mới; **records v1 và checksum không sửa**. Dùng kind tự do và JSON
revision hiện có, không chạm core/shared read bridge v3 hoặc module khác. HTTP
response/history bổ sung default cho dữ liệu cũ. Bỏ optional default mới khỏi command
fingerprint trước gọi core để request đang chờ từ trước nâng cấp replay được;
không sửa immutable revision/receipt cũ. Tất cả fixture là dữ liệu tổng hợp mới.
Không đọc/sửa/migrate CRM cũ hoặc dữ liệu thật.

## Kiểm thử

Python dùng runtime sẵn có của điều phối:
`C:\Users\NC\.codex\worktrees\cafe-fin-foundation-recovery\cafe_fin\.venv\Scripts\python.exe`.
Chạy tại worktree của lane, pytest `pythonpath=backend` theo cấu hình repo.

- PASS: `python -m pytest tests/records/test_records_commerce.py tests/records/test_records_commerce_dashboard.py -q --tb=short` — 13 tests.
- PASS: `python -m ruff check backend/cafe_fin/records tests/records`.
- PASS: `git diff --check`.
- PASS: `python -m pytest tests/records -q --tb=short` — 168 tests trong 97,36s;
  lượt này gồm 12 tests increment, trước khi bổ sung test thứ 13 về outbound nhiều kho.
  Lượt focused 13 tests sau đó PASS trong 8,76s. Một cảnh báo Starlette/httpx có sẵn.
- NOT RUN: build frontend/browser, full backend liên module, Docker, frozen sidecar,
  Windows sạch; điều phối và lane UI kiểm sau tích hợp.

Giới hạn: chưa benchmark khối lượng lớn của trade/dashboard; không tuyên bố tốc độ
hoặc production-ready. Giữ mô hình data mới và kế toán độc lập; đây là hồ sơ người
dùng nhập, không xác nhận toàn bộ tồn/thu chi thực tế hoặc đối soát ngân hàng.
