# Ghi nhận increment 03

Source module được kiểm tới `6abf833` trên baseline `e668355`. Điều phối tích hợp riêng module records cùng các shared fixes đã review vào checkout `C:\Users\NC\Desktop\UNILA{\cafe_fin`, không đưa module còn đang sửa vào increment này.

## Hành vi và kiểm chứng

Đối tác, sản phẩm, đơn vị/kho, cân tay và phiếu hàng có CRUD/version/audit/idempotency. Cân không tự thay tồn. Ledger nhập/xuất/sản xuất/chuyển/điều chỉnh kiểm mọi prefix theo ngày và thứ tự ổn định; sửa/xóa/hủy/restore/backdate không được làm âm lịch sử. Tổng thương mại có dấu do người nhập ghi, không tự sinh thu/chi kế toán.

Reviewer độc lập chạy 79 tests trước sửa cuối, sau đó 63 ca snapshot (các bộ có giao nhau) và probes nhiều sản phẩm/kho: tăng tiêu thụ sản xuất, hủy chuyển đã tiêu thụ, xóa sản xuất đã dùng và chuyển lùi ngày đều chặn `STOCK_NEGATIVE`, rollback cả domain/ledger/audit/receipts. Lỗi raw SQL đổi transaction nhưng giữ wrapper SQLAlchemy đã được sửa: reader cũ từ chối, reader mới đọc đúng snapshot mới.

Kiểm lại của điều phối tại checkout tích hợp, Windows 11 x64, Python 3.12.16/SQLite 3.53.1, Node 24.21.0:

| Kiểm tra | Kết quả |
|---|---|
| `python -m pytest tests -q` | PASS 279 tests / 127,95 giây (148 core + 131 records) |
| Ruff toàn backend/tests/scripts và compileall | PASS |
| Frontend TypeScript/Vite build | PASS; JS 1.207,22 KB / gzip 389,31 KB |
| `CAFE_FIN_REAL_API=1 npm test` | PASS 11 tests / 10,6 giây |
| Browser nghiệp vụ records với HTTP/SQLite thật | PASS 1 flow / 21,4 giây |
| Bổ sung ca app-shell gọi default registry records | PASS 1 focused integration / 7,1 giây |
| Git whitespace và workflow/config kiểm cú pháp | PASS |

Browser nghiệp vụ ghi nhập 100,125 kg → xuất 10,001 → tồn 90,124; xuất quá tồn bị từ chối, lịch sử cân không đổi kho. Ảnh tổng hợp đã xem trực quan, giữ ngoài Git. Test shell cuối mở menu records thật, nhận HTTP 200 từ registry mặc định và thấy các tab ghi nhận; không chỉ chạy feature harness. Các ca focused có giao nhau với bộ chính, không cộng thành một tổng khác.

Shared fixes gồm typed read bridge v2, generic file/job read ownership, API error.details, Windows Credential Manager và trusted background actor resolver. Tất cả vẫn không có Google OAuth. Không động source/DB CRM cũ hoặc nhập dữ liệu thật. CI đã mở rộng từ core sang toàn tests và tìm mọi cấu hình browser lane.

## Giới hạn

Đây là source phát triển đã kiểm, không phải release client. Native date input còn phụ thuộc định dạng hiển thị của hệ điều hành; cần chuẩn hóa hiển thị ngày Việt Nam khi hoàn thiện UI. Cảnh báo bundle lớn và Starlette/httpx còn ghi rõ. Hợp đồng/kế toán/reporting chưa được đưa vào increment này, chưa có import 500k/1m hoặc Zalo live acceptance.

Windows CI foundation trước đó có hai lần build NSIS thành công; lần [42237481263](https://github.com/minh0407/cafe_fin/actions/runs/42237481263) còn smoke frozen executable PASS, native installer 252.385.014 bytes SHA256 `B835FB225ED67C24A537E604B333AC8FE435875108675A53F79A3429B3C5A531`. Đây là source foundation `8755345`, không được dùng làm chứng minh native records. Binary chỉ tồn tại trong runner tạm, không upload/phát hành/cài thử. CI mới của increment này sẽ được theo dõi riêng.

Clean-Windows install/native GUI/offline/update/uninstall, DOCX visual/in và nghĩa vụ native iconv source/relink còn là gate phát hành. Không thay Windows AppControl policy để build tại host.
