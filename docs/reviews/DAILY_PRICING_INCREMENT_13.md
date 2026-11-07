# Bảng giá mua / nhập / bán và tự điền từ cân 13

Người dùng xác nhận giá bán cài riêng; giá mua/nhập chỉ phục vụ đầu vào và tham khảo. Đọc source CRM cũ để đối chiếu bảng ngày/Grade và quy tắc 90%, không đọc/chuyển dữ liệu CRM. Increment từ `1224cce`, contract `e9cb099`; backend tích hợp `647c98a`, UI `539f54a`, điều hướng/Docker smoke `4bf5997`. Không sửa migration v1/core/shared read bridge hoặc thêm dependency.

## Hành vi đã kiểm

- Bảng giá ngày có ba nhóm: mua tươi, mua/nhập chế biến, bán riêng theo mặt hàng. Giá cố định hoặc nhập Grade5 để suy Grade4 → 1 bằng 90%, ROUND_HALF_UP đến hai số lẻ ở từng bước như CRM. Preview/save/lookup cùng một hàm integer cents; không float.
- Giá mua theo hàng ưu tiên bảng chung. Tìm đúng ngày, không lấy giá hôm trước hoặc giá 0 khi thiếu; giá bán không dùng bảng mua làm fallback. Có phân trang/bộ lọc/lịch sử, sửa giá/ngừng áp dụng/xóa mềm/khôi phục, kiểm version và chống ghi lặp; mã/tên tự sinh, khóa ngày/nhóm/hàng bất biến.
- Đơn mới mặc định tự tra bảng; chọn hàng/ngày/Grade khi cần rồi nhập kg, đơn giá readonly và thành tiền chính xác tới năm số lẻ. Có thể cài giá ngay trong modal đơn khi thiếu, giữ draft và phiên đăng nhập.
- Server kiểm snapshot nguồn/ngày/version/công thức và đơn giá. Giá vừa thay đổi trước lưu trả PRICE_CHANGED409 để lấy lại và xác nhận rõ. Sửa kg/bao/ghi chú không đổi giá đơn cũ kể cả bảng ngừng/xóa; đổi tiêu chí cần quote hiện hành. Snapshot giả/copy nguồn cũ sang dòng mới bị từ chối. Dữ liệu cũ manual và fingerprint request cũ vẫn dùng được.
- Quote chậm không ghi đè Grade/ngày/dòng khác, kể cả xóa một dòng có cùng tiêu chí với dòng còn lại đang giữ giá cũ. Unknown-save khóa mọi input/action và background quote, giữ đúng payload/key để retry. Chi tiết hiện nguồn giá với nhãn nghiệp vụ.
- Tính giá không tự tạo thu/chi hoặc ledger. Kho vẫn kiểm tồn âm và giới hạn đơn; Excel kế toán độc lập. Không cấu hình giá mẫu vào volume người dùng.

[Contract](../handoffs/records/pricing-v1.md), [backend](../handoffs/records/pricing-backend.md), [UI](../handoffs/records/pricing-frontend.md).

## Kết quả

Môi trường Windows phát triển, Python 3.12 venv/Node theo lockfile, Chromium; tất cả fixture tổng hợp, SQLite WAL thật. Docker Linux Python3.12.16/SQLite3.53.1 như preview trước.

| Gate | Kết quả |
|---|---|
| Toàn backend `python -m pytest -q` | PASS 1.493 /701,53s; một cảnh báo Starlette/httpx có sẵn |
| Records lane | PASS 192 tests, gồm 23 pricing |
| Ruff `backend tests`, compileall, diff check | PASS |
| Frontend build mặc định và Docker preview | PASS; cảnh báo bundle Vite lớn vẫn còn |
| Main browser gồm sidecar API thật | PASS 83/83 /1,5 phút, gồm 15 pricing + 8 CRM |
| Records browser API thật | Hai luồng cũ PASS21,6s/22,7s; pricing final chạy lặp 3/3 PASS56,1s và điều phối rerun1/1 PASS19,6s; không API mock |
| Accounting standalone UI | PASS 17/17 /27,8s |
| Docker HTTP + restart + production frontend | PASS toàn bộ security/auth, CRUD, import, export, bảng giá, quote, snapshot, persistence và browser |

Kiểm thử pricing thật bao gồm nhập/xem bảng Grade và giá bán riêng qua UI, chỉ nhập kg để tự tính, sửa bảng sau lưu vẫn giữ giá đơn, STOCK_NEGATIVE409 và PRICE_CHANGED409 rồi chủ động refresh/lưu giá mới. Một locator test ban đầu dùng tên nút chính xác bị icon loading AntD lưu trong CSSMotion làm sai accessible name khi nút thực đã enabled. Đã xác minh `disabled=false/loadingClass=false/loadingIcon=true`, sửa locator suffix + kiểm enabled và waiter20s (API15s), không force/sleep hoặc bỏ assertion. Ba lượt lặp đều có POST200/200/409/200 đúng kỳ vọng; backend/thuật toán không đổi để làm test pass.

Docker project tổng hợp `cafe-fin-preview-smoke-price-20261107` PASS: Grade5=100.01 → Grade4=90.01 → Grade3=81.01 → Grade2=72.91 → Grade1=65.62; giá bán riêng150.01; server tự điền từ kg, chặn quote stale, sửa kg vẫn150.01 sau bảng đổi160.01 rồi bị xóa. Sau restart snapshot version1 còn nguyên. Browser production mở trang bảng giá, mở đơn đã chốt, sửa nháp kg3.501 vẫn giữ giá150.01/tổng525.18501 và không gọi quote mới. Không lưu sửa nháp trong browser smoke này.

## Nâng cấp localhost

Đã dừng dịch vụ và sao lưu đầy đủ, nhất quán volume đang dùng trước cập nhật; xác minh hash từng file và archive. Bản local ngoài repo: `C:\Users\NC\AppData\Local\CafeFinPreviewBackups\pricing-20261107-105736`, archive SHA256 `8784cd1a78445f5e278e8d203ac934fb00607d9b7630d4c690f4f1af847574f0`. Không đọc nội dung nghiệp vụ, không commit backup/manifest/DB hoặc gửi ra mạng.

Image đã kiểm thử được promote vào project `cafe-fin-local-preview`, giữ nguyên `cafe-fin-local-preview_preview-data`. URL **http://127.0.0.1:1420**; Ctrl+F5 và đăng nhập lại. Backend image `sha256:57a5b8f9bd8a326c5055b0287586bbb074b822ab1d59bfadab6d9acf6cef972b`; gateway `sha256:4bf6067509bb8d38c87bb19266a5ee5541c1ee3b373a2e9f55b2f3a856ed4232`.

CI Windows baseline `1224cce` (run42332487848) đã SUCCESS cả source/native/frozen/NSIS. Đây là bằng chứng baseline, không thay CI increment13. NOT RUN tại máy dev: bộ cài/native GUI/Windows sạch/offline/upgrade/uninstall mới, benchmark500k/1m và gửi Telegram thật; các gate phát hành trước vẫn giữ nguyên. Không gọi production-ready. Linux preview vẫn không lưu token plaintext thay kho bí mật Windows.
