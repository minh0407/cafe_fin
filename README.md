# cafe_fin

Ứng dụng Windows ghi nhận hoạt động kinh doanh cà phê, lập hợp đồng và làm việc với sổ kế toán dạng bảng. Một máy tính lưu DB, Excel gốc, chứng từ và báo cáo; không cần người dùng vận hành Docker hoặc terminal.

## Trạng thái

Repo đã có core, API local, ghi nhận và hợp đồng được điều phối review: đối tác/hàng/cân tay, phiếu nhập/xuất/sản xuất/chuyển kho, ledger chặn tồn âm; hợp đồng mua/bán tự điền, điều khoản/thanh toán, snapshot Word/PDF và chứng từ đính kèm. App mở phần nghiệp vụ và có quản lý tài khoản local trong cài đặt. [Core 01](docs/reviews/CORE_INCREMENT_01.md), [API/UI 02](docs/reviews/FOUNDATION_INCREMENT_02.md), [ghi nhận 03](docs/reviews/RECORDS_INCREMENT_03.md), [hợp đồng và app 04](docs/reviews/CONTRACTS_INCREMENT_04.md).

Baseline phát triển được điều phối chốt tại tag `cafe-fin-foundation-ready-v1` để các module bắt đầu. [Biên bản freeze](docs/reviews/FOUNDATION_BASELINE_V1.md) ghi bằng chứng và phần còn thiếu. Kế toán và báo cáo đang được kiểm tích hợp riêng; chưa có bộ cài hoàn chỉnh hoặc nghiệm thu production. Native/Windows sạch vẫn phải qua [gate phát hành](docs/adr/20261106_COORDINATION_GATES.md).

- [Yêu cầu sản phẩm](docs/SPEC.md)
- [Kiến trúc và quyết định kỹ thuật](docs/ARCHITECTURE.md)
- [Hợp đồng tích hợp giữa các module](docs/API_CONTRACT.md)
- [Quyền sở hữu file và cách tích hợp](docs/OWNERSHIP.md)
- [Cách sử dụng các prompt](docs/prompts/README.md)

## Các quyết định chính

- Ghi lại nghiệp vụ, bỏ phê duyệt nhiều người, QR và chuyển theme. Vẫn kiểm dữ liệu, giữ lịch sử và chặn tồn âm.
- Hợp đồng mua/bán tự điền theo thông tin người nhập, cho sửa điều khoản và phương thức thanh toán; xuất Word/PDF.
- Kế toán là khu vực riêng, không ép phải ghi đủ hoặc khớp mọi nghiệp vụ CRM.
- Upload Excel → xem/sửa/copy/paste trong modal → báo mới/trùng/lỗi → xác nhận → import dòng hợp lệ, giữ dòng lỗi để sửa tiếp.
- Giữ nguyên byte của file Excel gốc có macro. Không chạy VBA, không cam kết tái tạo mọi tính năng Excel trong grid.
- Thư viện miễn phí phù hợp production; không dùng license evaluation cho sản phẩm thật.
- Bắt đầu dữ liệu mới. CRM cũ và dữ liệu cũ giữ nguyên để tra cứu; không chuyển trong bản đầu.
- Lưu báo cáo local và chuẩn bị khả năng tự gửi tổng hợp Zalo cuối ngày; đích và lịch do người dùng cấu hình khi tích hợp khả dụng.

## Quy trình triển khai

`cafe-fin-spec-v1` là mốc bộ yêu cầu. Chat nền tảng chạy trước; sau khi điều phối kiểm tra, tag `cafe-fin-foundation-ready-v1` mới cho phép các lane module bắt đầu. Các chat không tự push hoặc merge. Chat điều phối tích hợp và push repo đích.

Không có DB, chứng từ, Excel thật, credential hoặc lịch sử Git của CRM cũ trong repo này.
