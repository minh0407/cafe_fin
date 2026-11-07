# Nhóm Zalo cá nhân và máy kiểm thử Windows

Ngày xác nhận: 07/11/2026, giờ Việt Nam.

**Đã được thay thế về kênh gửi:** người dùng sau đó chọn Telegram và bỏ Zalo.
Xem [quyết định Telegram](20261107_TELEGRAM_REPORT_DELIVERY.md). Nội dung dưới đây
là lịch sử xác minh, không phải hướng dẫn cấu hình cho phiên bản hiện hành.
Máy Windows thứ hai sau đó đã được xác nhận là Windows 11 x64.

Người dùng xác nhận đích nhận báo cáo là **nhóm Zalo cá nhân thông thường**,
không phải nhóm OA/GMF, và có một máy Windows khác để thử bộ cài.

## Khả năng gửi báo cáo

Adapter đang có trong Cafe Fin là OA/GMF. Không nhập ID nhóm cá nhân vào cấu hình
GMF rồi coi đó là tích hợp được hỗ trợ. Việc tạo snapshot và các tệp báo cáo local
vẫn hoạt động độc lập khi chưa có kênh gửi phù hợp.

Đã đọc tài liệu chính thức ngày 07/11/2026:

- [Zalo Bot trong nhóm](https://bot.zapps.me/docs/build-bot-interaction-with-group/)
  mô tả mời Bot vào nhóm, trưởng nhóm xác nhận và lấy chat.id từ sự kiện. Trang
  vẫn ghi tính năng đang thử nghiệm nội bộ; không suy ra mọi tài khoản đã được bật.
- [Zalo Bot Platform](https://bot.zapps.me/) liệt kê khả năng nhóm ở trạng thái
  Beta. Vì thế cần kiểm tra mục **Mời Bot vào nhóm** trên tài khoản thực tế.
- [sendMessage](https://bot.zapps.me/docs/apis/sendMessage/) hỗ trợ text tới chat_id
  với giới hạn 2.000 ký tự. Đây chưa phải bằng chứng tài khoản/nhóm cụ thể được phép
  gửi chủ động hằng ngày hoặc gửi PDF/XLSX.

Hướng tiếp theo là adapter **Zalo Bot chính thức**, có kiểm chứng bot đã được mời
vào đúng nhóm và quyền gửi của tài khoản. Trước khi bật lịch cần thử bằng dữ liệu
tổng hợp ở đích do người dùng chọn rõ. Chưa có token, chat_id hoặc lần gửi thật nào
được cung cấp/thực hiện trong lượt xác nhận này.

Không thay bằng API tài khoản cá nhân không chính thức, cookie đăng nhập hoặc
script giả thao tác gửi Zalo. Không dùng OA credential cho Bot. Mọi token chỉ nhập
ở chỗ cấu hình bí mật local phù hợp; không gửi token vào chat, Git, log hoặc báo cáo.
Không tự mở webhook public/tunnel hoặc chuyển dữ liệu nghiệp vụ lên máy chủ ngoài.

Nếu triển khai Bot, phải giữ nguyên lịch sử/payload/đích OA đã pin; provider mới
cần interface và migration bổ sung được review. Timeout không rõ vẫn phải là
UNKNOWN, không tự thử gửi lại và không dựng receipt. Tập tin PDF/XLSX/TXT tiếp tục
ở reports; chưa hứa tự đính kèm qua Bot khi chưa xác minh API tương ứng.

Đây là quyết định phạm vi và bước xác minh tiếp theo, **không phải tuyên bố đã có
adapter Bot hoặc đã hoàn tất gửi tự động vào nhóm cá nhân**. Câu hỏi đang chờ người
dùng là tài khoản có mục mời Bot vào nhóm hay chưa.

## Máy Windows thứ hai

Máy khác giúp thực hiện nghiệm thu cài đặt/giao diện/offline, nhưng cần xác minh
Windows version/build, x64 và phần mềm sẵn có trước khi gọi đó là máy sạch.
Mục tiêu hiện tại của sản phẩm là Windows 11 x64.

[Bộ hướng dẫn kiểm thử](../release/CLEAN_WINDOWS_TEST_KIT.md) ghi ca thử, fixture
tổng hợp, kết quả mong đợi và mẫu evidence. Không sửa CRM cũ hoặc dùng dữ liệu thật
để thử cài đặt, chuyển/khôi phục hay gỡ ứng dụng.

Run 42314420634 đã build NSIS thành công nhưng không giữ/upload installer. Receipt
candidate09 không phải file để chép sang máy kia. Phải tạo và giữ một candidate
xác định source/runtime/notices/checksum, đối chiếu các gate phân phối đang mở rồi
mới bàn giao kit. Build mới phải có hash mới; không mượn hash của run trước.
Không đổi policy bảo vệ máy hoặc tự gọi lần cài đó PASS trước khi quan sát kết quả.
