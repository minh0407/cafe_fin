# Farm, khách hàng, luồng đầu vào/đầu ra và dashboard 12

Người dùng xác nhận giữ chức năng/mã Farm, bắt đầu dữ liệu mới; không chuyển danh sách hoặc DB CRM cũ. Source CRM chỉ được đọc để đối chiếu trường và luồng. Increment triển khai từ `449093b`, contract điều phối `ac34aac`, source tích hợp `3c2c3bd`. Các lane dùng branch/worktree riêng, bàn giao commit; chỉ điều phối ghép và push.

## Hành vi

- Hồ sơ Farm có mã bốn chữ/số (giữ số 0 đầu, chuẩn hóa chữ hoa, bất biến), chủ Farm/giấy tờ, liên hệ/ngân hàng, mã vùng, lô trồng và khảo sát mùa vụ. Không ảnh, sơ đồ, GPS, phân công nhân viên hoặc chuỗi duyệt.
- Công ty khách hàng có tên công ty riêng với người liên hệ/đại diện, MST, giấy phép, liên hệ. Đầu ra yêu cầu chọn công ty đủ thông tin trước nhập đơn/thu tiền.
- Trang Đầu vào và Đầu ra tách danh sách/chi tiết. Dòng đầu vào chọn Farm; đầu ra chọn công ty và sản phẩm. Lưu hồ sơ mua/bán chưa thay kho. Chi tiết có các lần nhập/xuất và thu/chi liên kết, lịch sử và sửa/xóa/khôi phục có version.
- Phiếu kho liên kết đúng chiều, đúng công ty/Farm; lượng posted cộng dồn theo sản phẩm qua mọi lần giao/kho không vượt đơn. Đổi số lượng, xóa/hủy/khôi phục vẫn kiểm cùng transaction với ledger chống tồn âm. Hồ sơ độc lập trước increment tiếp tục dùng được.
- Thu/chi ghi số tiền/ngày/phương thức/tham chiếu thực tế, có thể ghi trước giao hàng. Không chuyển tiền, bắt chứng từ ngân hàng hoặc tạo tiền/kho từ Excel. Mất phản hồi lưu giữ đúng payload/request key để kiểm tra lại, khóa sửa nháp cho đến khi xác nhận kết quả.
- Dashboard mặc định có kỳ tuần/tháng/ngày, hồ sơ Farm/khảo sát/công ty, đơn theo chiều, kg nhập/xuất, tồn, thu/chi và xu hướng/bảng ngày. Một snapshot đọc, giờ Việt Nam, số Decimal string. Giá trị đơn bán giữ tích chính xác tối đa năm số lẻ, tách đơn thiếu giá; không gọi là doanh thu và không cộng chồng với sổ Excel.

Không đổi migration records v1/checksum hoặc shared read bridge v3. Dữ liệu cũ có default tương thích; command fingerprint cũ vẫn replay được. [Contract increment](../handoffs/records/crm-parity-v1.md), [backend](../handoffs/records/backend-crm-parity.md), [frontend](../handoffs/records/frontend-crm-parity.md).

## Kiểm thử trên Windows phát triển

Python 3.12 từ venv khóa của worktree điều phối, frontend theo lockfile; PowerShell, Chromium Playwright. Tất cả dữ liệu kiểm thử tổng hợp trong thư mục tạm, không dùng DB/Excel CRM hoặc dữ liệu người dùng.

| Kiểm tra | Kết quả |
|---|---|
| `python -m pytest -q` toàn backend | PASS 1.470 tests / 722,49s; một cảnh báo Starlette/httpx có sẵn |
| Records focused + ledger/history/bridge | PASS trong full suite; 13 ca mới gồm hai writer vật lý, snapshot WAL, capping theo sản phẩm, sửa/xóa/restore và retry sau nâng cấp |
| Ruff `backend tests`, compileall, diff check | PASS |
| Frontend build mặc định và Docker preview | PASS; còn cảnh báo bundle Vite lớn, không thêm dependency |
| Main browser + API sidecar thật | PASS 68 ca qua lượt 67 và lượt sửa/rerun 1 ca: selector menu cũ đổi sang “Phiếu cân và kho”; 1 ca API thật rerun /18,5s |
| Records browser thật | PASS 2/2 /46,9s trên source tích hợp: CRUD qua React/HTTP/SQLite, công ty chưa đủ thông tin, phiếu nháp, ghi sổ, lỗi vượt đơn, thu tiền và dashboard |
| Accounting standalone UI | PASS 17/17 /28,5s; khắc phục lỗi import.meta trong loader CJS bằng compile constant mặc định false |
| Accounting real import/CRUD + schema | PASS 1/1 /25,5s và 11/11 /24,0s |
| Contracts browser thật, nguồn và snapshot xuất | PASS 3/3 /33,1s |
| Reporting wrapper và hai assertion harness | PASS 1/1 /18,4s |

Lỗi CI Windows của source `449093b` đã được phân loại: backend 1.457 và main browser 57 PASS, feature loader dừng vì `import.meta`. Increment sửa flag ở Vite/shared bridge; không sửa auth/native hoặc giả Tauri. Windows installer candidate của increment này vẫn cần CI riêng; không lấy kiểm thử web làm bằng chứng cài Windows sạch.

## Docker thật và nâng cấp dữ liệu đang dùng

Project tổng hợp `cafe-fin-preview-smoke-crm-c-20261107` PASS toàn bộ HTTP/security/auth, farm/công ty/đơn/thu chi/dashboard, import một phần, original hash, báo cáo/chứng từ Word/PDF, restart/capability mới và persistence. Chromium mở đúng frontend production, đăng nhập local, đọc dashboard, đi bốn trang và chi tiết kho liên kết; không shim/mock API. Hai lượt trước dừng tại selector kiểm thử tên công ty (UI hiển thị cả mã và tên); sửa selector, chạy lại toàn bộ trên volume tổng hợp mới. Giữ các volume thử đã dừng, không xóa dữ liệu để làm test pass.

Đã dừng dịch vụ preview người dùng và sao lưu nhất quán toàn bộ volume trước nâng cấp. Archive được xác minh hash từng tệp và toàn archive; bản sao ở thư mục local ngoài repo `C:\Users\NC\AppData\Local\CafeFinPreviewBackups\crm-parity-20261107-100229`. Không đọc nội dung nghiệp vụ, xuất dữ liệu hoặc commit archive/manifest. SHA256 archive: `95e8a7f9c83e8e8b266ff0abb1fd1bc0c5a45f9dca280f64195741515ccdf12e`.

Promote chính image đã PASS sang project `cafe-fin-local-preview`, chạy từ `C:\Users\NC\Desktop\UNILA{\cafe_fin`. Giữ nguyên volume `cafe-fin-local-preview_preview-data`; sau nâng cấp backend healthy, gateway chỉ bind `127.0.0.1:1420`, health xác nhận tài khoản local đã có vẫn tồn tại (`setup_required=false`). Không đăng nhập/xem dữ liệu người dùng để nghiệm thu.

- Backend image: `sha256:fd4ac75958ab2ff24a8468ca4a529beef29dec908f2d3cc582708535fa7bb4a6`.
- Gateway image: `sha256:b80b34374135112a6b9a4b62da88dd80db0c417d55000d1c096218d5ed8f01c9`.
- URL: **http://127.0.0.1:1420**; Ctrl+F5 và đăng nhập lại sau đổi capability.
- Docker context loại riêng frontend test/results/config, ngoài các quy tắc loại DB/Excel/token/runtime hiện có. Không upload image hoặc dữ liệu lên GitHub.

NOT RUN cho increment: Windows sạch/native GUI/offline/upgrade/uninstall, frozen release mới, benchmark 500k/1m và gửi Telegram thật. Linux preview tiếp tục không có kho bí mật Windows, không có plaintext fallback; Telegram chưa cấu hình. Chưa gọi production-ready. Gate phát hành trong biên bản trước vẫn giữ nguyên.
