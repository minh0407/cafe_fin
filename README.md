# cafe_fin

Ứng dụng Windows ghi nhận hoạt động kinh doanh cà phê, lập hợp đồng và làm việc với sổ kế toán dạng bảng. Một máy tính lưu DB, Excel gốc, chứng từ và báo cáo; không cần người dùng vận hành Docker hoặc terminal.

## Trạng thái

Repo đã có phần core được điều phối review và kiểm thử: số liệu chính xác, migration, serialized writer, tài khoản local, job phục hồi, snapshot import, lưu tệp, sao lưu và bộ render chứng từ local. [Kết quả kiểm tra increment 01](docs/reviews/CORE_INCREMENT_01.md).

Đây là phần nền tảng đang phát triển. Chưa có ứng dụng nghiệp vụ hoặc bộ cài hoàn chỉnh; chưa công bố tag foundation READY và chưa nghiệm thu production. Các module nghiệp vụ vẫn chờ baseline được điều phối xác nhận.

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
