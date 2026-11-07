# cafe_fin

Ứng dụng Windows ghi nhận hoạt động kinh doanh cà phê, lập hợp đồng và làm việc với sổ kế toán dạng bảng. Một máy tính lưu DB, Excel gốc, chứng từ và báo cáo; không cần người dùng vận hành Docker hoặc terminal.

## Trạng thái

Repo đã ghép core/API local, ghi nhận với ledger chặn tồn âm, hợp đồng mua/bán tự điền và Word/PDF, kế toán độc lập dạng bảng/import có phục hồi, cùng báo cáo snapshot PDF/XLSX/TXT lưu trên máy. App có quản lý tài khoản local và chọn sổ theo tên; không có Google OAuth hoặc chuỗi phê duyệt. [Core 01](docs/reviews/CORE_INCREMENT_01.md), [API/UI 02](docs/reviews/FOUNDATION_INCREMENT_02.md), [ghi nhận 03](docs/reviews/RECORDS_INCREMENT_03.md), [hợp đồng và app 04](docs/reviews/CONTRACTS_INCREMENT_04.md), [kế toán và báo cáo 05](docs/reviews/ACCOUNTING_REPORTING_INCREMENT_05.md).

[Increment 12](docs/reviews/FARM_CUSTOMER_FLOWS_12.md) bổ sung hồ sơ Farm/mã vùng/lô/khảo sát, công ty khách hàng, luồng đầu vào/đầu ra và dashboard; đã qua 1.470 backend tests, browser với API thật và Docker production smoke. Bản localhost giữ volume/tài khoản đang có và đã được sao lưu trước nâng cấp.

[Bảng giá 13](docs/reviews/DAILY_PRICING_INCREMENT_13.md) thêm giá mua tươi/nhập chế biến và giá bán riêng, tự điền theo cân, giữ giá đơn đã chốt và kiểm thay đổi giá trước lưu. Bảng đúng ngày, giá cố định hoặc theo Grade; không dùng giá mua thay giá bán.

[Giá thị trường 14](docs/reviews/AUTOMATIC_MARKET_INCREMENT_14.md) nối nguồn Robusta nhân xô Gia Lai của CRM vào bảng giá nhập đúng ngày, có lịch kiểm tra và bằng chứng nguồn. Quả tươi nhập tay, giá bán cài riêng. Nguồn thật hiện trả trang xác minh truy cập; app báo bị chặn và không tạo giá thay thế.

Baseline phát triển `cafe-fin-foundation-ready-v1` và [baseline tích hợp](docs/reviews/INTEGRATION_BASELINE_V1.md) `cafe-fin-integration-ready-v1` đã được điều phối chốt. Bản tích hợp qua CI Windows với 1.029 backend tests, các bộ browser, frozen sidecar và build NSIS. Lane đóng gói tiếp tục hoàn thiện và nghiệm thu desktop; chưa gọi production-ready. Windows sạch, native GUI/offline và các bước phát hành vẫn phải qua [gate phát hành](docs/adr/20261106_COORDINATION_GATES.md).

[Tích hợp quản lý dữ liệu 06](docs/reviews/DESKTOP_MAINTENANCE_INCREMENT_06.md) bổ sung core/protocol sao lưu, chuyển/khôi phục và giao diện đối soát; [native controller 07](docs/reviews/NATIVE_CONTROLLER_INCREMENT_07.md) đã nối các lệnh desktop. Lượt CI backend đạt 1.119 tests; các kiểm thử adapter native thật được chạy riêng trước nghiệm thu. Khôi phục giữ các lượt gửi chưa rõ, tạm dừng lịch đến khi Admin kiểm tra và tạo lại tệp báo cáo trong thư mục mới từ bản gốc đã xác minh.

[Windows candidate 09](docs/reviews/WINDOWS_DESKTOP_CANDIDATE_09.md) đã qua CI tại source `baa8e86`: 1.153 backend tests, 57 main browser tests, các bộ feature, 47 native tests, Rust/Python interoperability, hai ca production controller với frozen sidecar thật và build NSIS đều PASS. Chưa phát hành file cài hoặc nghiệm thu GUI/offline trên Windows sạch; các giới hạn phục hồi và giấy phép phân phối vẫn ghi trong biên bản.

[Telegram 10](docs/reviews/TELEGRAM_DELIVERY_INCREMENT_10.md) thay bộ gửi và cấu hình Zalo bằng Telegram Bot API, giữ tạo báo cáo local và lịch sử kênh cũ. Token nằm trong kho bí mật Windows; chưa cấu hình bot/nhóm thật hoặc gửi thật. Biên bản ghi riêng kết quả source, browser và bản đóng gói của thay đổi này.

- [Yêu cầu sản phẩm](docs/SPEC.md)
- [Hướng dẫn, ma trận quyền và mẫu báo cáo](docs/USER_GUIDE.md)
- [Kiến trúc và quyết định kỹ thuật](docs/ARCHITECTURE.md)
- [Hợp đồng tích hợp giữa các module](docs/API_CONTRACT.md)
- [Quyền sở hữu file và cách tích hợp](docs/OWNERSHIP.md)
- [Cách sử dụng các prompt](docs/prompts/README.md)

## Các quyết định chính

- [Farm, công ty khách hàng, Đầu vào/Đầu ra và dashboard](docs/handoffs/records/crm-parity-v1.md): giữ chức năng CRM hữu ích với dữ liệu mới, bỏ ảnh farm và chuỗi duyệt; đơn/thu chi liên kết nhưng kho vẫn qua ledger có kiểm tra.

- Ghi lại nghiệp vụ, bỏ phê duyệt nhiều người, QR và chuyển theme. Vẫn kiểm dữ liệu, giữ lịch sử và chặn tồn âm.
- Hợp đồng mua/bán tự điền theo thông tin người nhập, cho sửa điều khoản và phương thức thanh toán; xuất Word/PDF.
- Kế toán là khu vực riêng, không ép phải ghi đủ hoặc khớp mọi nghiệp vụ CRM.
- Upload Excel → xem/sửa/copy/paste trong modal → báo mới/trùng/lỗi → xác nhận → import dòng hợp lệ, giữ dòng lỗi để sửa tiếp.
- Giữ nguyên byte của file Excel gốc có macro. Không chạy VBA, không cam kết tái tạo mọi tính năng Excel trong grid.
- Thư viện miễn phí phù hợp production; không dùng license evaluation cho sản phẩm thật.
- Bắt đầu dữ liệu mới. CRM cũ và dữ liệu cũ giữ nguyên để tra cứu; không chuyển trong bản đầu.
- Lưu báo cáo local và gửi tổng hợp cuối ngày qua Telegram Bot; Admin cấu hình bot, nhóm và lịch trên máy. Không tích hợp Zalo. Xem [quyết định Telegram](docs/adr/20261107_TELEGRAM_REPORT_DELIVERY.md).

## Quy trình triển khai

`cafe-fin-spec-v1` là mốc bộ yêu cầu. Chat nền tảng chạy trước; sau khi điều phối kiểm tra, tag `cafe-fin-foundation-ready-v1` mới cho phép các lane module bắt đầu. Các chat không tự push hoặc merge. Chat điều phối tích hợp và push repo đích.

Không có DB, chứng từ, Excel thật, credential hoặc lịch sử Git của CRM cũ trong repo này.

## Bản thử trên localhost bằng Docker

Theo yêu cầu kiểm thử bổ sung, repo có bản preview dùng cùng API và nghiệp vụ thật.
Mở Docker Desktop ở Linux engine, chạy tại thư mục repo:

```powershell
docker compose -f compose.preview.yaml up --build -d
```

Mở **http://127.0.0.1:1420** và tự tạo Admin local ở lần đầu. Dữ liệu nằm trong
volume riêng `cafe-fin-local-preview_preview-data`, giữ qua các lần khởi động lại.
Dùng dữ liệu tổng hợp để thử; CRM cũ không được gắn vào container. Dừng bằng
`docker compose -f compose.preview.yaml stop`.

Preview dành cho thao tác web: đối tác/kho, hợp đồng, sổ/import và tải báo cáo.
Chọn ổ Windows, mở Explorer và quản lý dữ liệu qua native controller cần app
Windows. Kho bí mật Windows không có trong Linux container, nên Telegram giữ
**Chưa cấu hình**; không có lưu token dạng plaintext thay thế. Xem
[hướng dẫn Docker](docs/handoffs/packaging/docker-preview.md).
