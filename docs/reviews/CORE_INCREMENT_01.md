# Kiểm tra core increment 01

Ngày 06/11/2026. Mã nguồn ứng dụng được review tới commit `5b3fb4c29131f7b72727d876dc053c894abe7454`, trên baseline đặc tả `cafe-fin-spec-v1`. Đây là phần được phép tích hợp và push sau kiểm thử, chưa phải nền tảng READY hoặc bản phát hành.

## Phạm vi mã đã kiểm

- Decimal strings, tiền scale 2 và kg scale 3, kiểm miền số và tổng chính xác.
- Migration theo namespace/thứ tự, checksum nội dung schema đã cố định; chặn schema mới hơn hoặc migration thay đổi.
- SQLite WAL, writer tuần tự, transaction bao gồm dữ liệu/audit/idempotency.
- Tài khoản local, quyền Admin/Operator và kiểm lại quyền tại transaction. Không Google OAuth.
- Job có checkpoint, phục hồi, backpressure và generation fencing để context cũ không ghi kết quả sau resume.
- Snapshot/manifest import bất biến, claim/receipt, pending visibility và atomic publication; chưa có nghiệp vụ import Excel triệu dòng hoàn chỉnh.
- Kho tệp local bảo toàn nguyên byte, khóa data root, kiểm containment/hash, sao lưu WAL và restore/move có xác minh.
- Renderer DOCX/PDF local và font có giấy phép; đây là phép thử kỹ thuật, chưa phải module hợp đồng mua/bán hoàn chỉnh.

## Lỗi đã tìm và sửa trước tích hợp

1. Migration có thể chạy version 2 trước version 1 dù bước kiểm tra tính liên tục đã pass.
2. Worker có thể chết khi hàng đợi writer đầy.
3. Context job cũ có thể finalize sau khi job đã phục hồi/resume sang generation mới.
4. Mutation dùng Principal cũ có thể tiếp tục sau khi quyền admin bị thu hồi.
5. SQLite INSERT OR REPLACE có thể vượt các trigger bất biến khi recursive triggers chưa bật.
6. Một kiểm thử trong increment trước phụ thuộc file chưa commit; snapshot dùng để review lần này đã chứa đủ dependency.

Các ca lỗi có regression tests và kiểm lại trên Git snapshot, không chỉ working tree đang có file chưa tracked.

## Kiểm chứng thực tế

Điều phối fast-forward worktree riêng tới đúng commit trên, tạo môi trường từ lockfile bằng Python 3.12.16 / SQLite 3.53.1 và chạy:

```text
uv sync --frozen --python <Python 3.12.16 đã xác minh>
.venv\Scripts\python.exe -m pytest tests/core -q
.venv\Scripts\python.exe -m ruff check backend/cafe_fin tests/core
.venv\Scripts\python.exe -m compileall -q backend/cafe_fin
git diff --check
```

Kết quả: **57 tests PASS trong 9,74 giây**, lint PASS, compile PASS, diff check PASS. Danh sách file tracked không chứa DB vận hành, Excel thật, credential, log hoặc executable build.

Review độc lập trên snapshot còn kiểm lại nhóm auth/jobs với 13 ca và nhóm import/storage/migration với 33 ca; không thấy lỗi nghiêm trọng còn mở trong phạm vi increment này. Các nhóm này có giao nhau với bộ test chính, không cộng thành tổng số test khác.

## Phần chưa đưa vào increment này

API/IPC và workbook spike ở commit sau vẫn đang được review, có lỗi download/export retry cần sửa; không gộp chúng vào kết luận PASS này. GUI Tauri và bộ cài Windows chưa được nghiệm thu. Không có kết quả import 500k/1m hoặc gửi Zalo thật.

Build Tools và Windows SDK đã cài thành công, nhưng release build native gặp Windows Application Control policy chặn một số DLL/build script sinh ra. Không thay đổi policy hoặc chọn đường dẫn khác để né chặn. Cần môi trường build được cho phép và kiểm thử Windows sạch trước khi kết luận phần native đạt.

Thư mục tích hợp chính là `C:\Users\NC\Desktop\UNILA{\cafe_fin`. CRM cũ và dữ liệu cũ giữ nguyên. Chỉ đưa source, lockfile, test tổng hợp và tài liệu thuộc increment này lên GitHub.
