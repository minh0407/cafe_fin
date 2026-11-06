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

## Theo dõi CI và sửa test quan sát cạnh tranh

Run [42255278298](https://github.com/minh0407/cafe_fin/actions/runs/42255278298) trên source `26a1f93` có 278 PASS và một assertion thất bại: bộ quan sát engine-wide đếm thêm connection của JobRunner poll (3 thay vì 2). Hai lệnh nghiệp vụ vẫn có một thành công và một `STOCK_NEGATIVE`; chưa coi run này là PASS.

Commit module `163ef00` chỉ sửa instrumentation/tests và tài liệu, không đổi implementation kho. Phép đo nay bám đúng actor/action/request_key, giữ hai physical connection còn sống, chứng minh writer thứ hai thực sự đợi SQLite lock, rồi kiểm ledger/audit/receipt và rollback. Các BEGIN không thuộc lệnh mục tiêu được chủ động tạo và chứng minh không tính vào số đo. Điều phối chạy lại focused test sáu lần sau sửa, đều PASS; Ruff/diff PASS. CI mới phải kết thúc trước khi báo Windows run đạt, không rerun source cũ để che flake.

Run [42260894313](https://github.com/minh0407/cafe_fin/actions/runs/42260894313) sau sửa có toàn bộ 279 backend tests, lint/build và 11 UI tests PASS. Bước browser lane chưa khởi động vì port 80 của standard runner đã có dịch vụ. Commit module `1b18f3a` đổi riêng harness sang loopback 1421 có strict port, thống nhất origin/browser/backend và URL readiness cụ thể. Không reuse hoặc dừng dịch vụ khác, không đổi origin/CSP sản phẩm. Điều phối chạy lại luồng records thật: PASS 1 / 20,2 giây; CI mới tiếp tục kiểm toàn bộ tới native build.
