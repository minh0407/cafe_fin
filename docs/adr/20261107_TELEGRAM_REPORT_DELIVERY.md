# Gửi báo cáo cuối ngày qua Telegram

Ngày: 07/11/2026. Người dùng đã yêu cầu chuyển sang Telegram và bỏ Zalo.
Quyết định này thay phần kênh gửi trong ADR
[nhóm Zalo và máy kiểm thử](20261107_PERSONAL_ZALO_GROUP_AND_CLIENT_TEST.md).
Các biên bản cũ giữ nguyên để truy được bằng chứng của những candidate trước.

## Quyết định

- Chỉ tích hợp Telegram Bot API chính thức cho báo cáo nhóm. Bỏ adapter, endpoint
  runtime, cấu hình OAuth/OA/GMF và hướng dẫn vận hành Zalo hiện hành.
- Một máy Windows giữ DB và file local. Scheduler local tạo snapshot và tệp báo
  cáo trước khi gửi; không phụ thuộc Telegram để nhập, xem hoặc xuất dữ liệu.
- Bot tạo bằng BotFather, được thêm vào nhóm người dùng chọn. Admin nhập token
  riêng trong app, không gửi token vào chat hoặc đưa token vào browser URL.
- Nhóm đích là group/supergroup có numeric chat_id; xác minh bot, loại nhóm và
  quyền trước gửi. Kiểm kết nối không tạo tin nhắn. Không tự dò hoặc gửi tới
  người nhận chưa chọn; không cần cấp quyền quản trị nhóm vượt nhu cầu gửi.
- Sender chỉ gọi HTTPS `api.telegram.org`, không theo redirect hoặc cho chọn URL
  tùy ý. Không mở webhook, tunnel hoặc cổng từ Internet vào máy người dùng.
- Gửi tin thuần văn bản và tùy chọn tệp tổng hợp PDF/XLSX được chọn. Không gửi
  Excel gốc, hợp đồng, chữ ký, thông tin ngân hàng hoặc toàn bộ DB.
- Namespace credential riêng `cafe_fin/reporting/<root_uuid>/telegram/<bot_id>`;
  target Windows Credential Manager khác namespace cũ. Token không được lưu
  trong DB, request receipt, audit, backup hoặc error details. Bot token không
  có luồng OAuth refresh. Đổi máy/Windows user cần cấu hình lại bí mật.

## Outbox và nâng cấp

Mỗi yêu cầu gắn snapshot/version/hash, provider, bot identity và nhóm đích. Chỉ
đánh dấu SENT sau receipt có đúng chat_id và message_id hợp lệ. Dữ liệu được
pin trước gửi; đổi cấu hình không thay đích/payload của bản cũ.

Telegram không cam kết idempotency cho sendMessage/sendDocument và không có API
lấy toàn bộ lịch sử tin đã gửi. Timeout hoặc response không đủ chứng minh sau
POST phải giữ UNKNOWN; không tự retry hoặc dựng message_id từ text/thời gian.
Người dùng kiểm tra nhóm; nếu cần gửi lại, tạo lựa chọn/bản gửi mới rõ ràng theo
khả năng của UI. Một lượt gửi đã rõ bị từ chối khác với một lượt chưa rõ kết quả.

Migration module giữ lịch sử/payload/receipt cũ. Cấu hình và lượt gửi Zalo cũ không
được diễn giải thành Telegram, không tự gửi lại khi nâng cấp, restore, catch-up
hoặc sửa cấu hình. Lịch gửi cũ bị tắt để Admin cấu hình Telegram; các file báo cáo
vẫn nằm trên máy. Restore guard hiện có vẫn chặn scheduler/sender trước khi Admin
kiểm tra và mở lại. Không mang theo token trong backup.

## Kiểm chứng và giới hạn

Phải kiểm transport có HTTP giả lập, receipt, quyền, secret redaction, missing
config không gọi mạng, legacy upgrade/restore không replay, daily generation và
UI; chạy regression cùng consumer dùng chung trước push. Mock không chứng minh
đã gửi vào nhóm thật. Chưa có bot token/nhóm test được nhập hoặc lần gửi thật
được thực hiện khi viết quyết định này.

Máy phải bật, backend đang chạy và có Internet khi gửi. Máy ngủ/tắt không bảo đảm
đúng giờ. Catch-up giữ đúng snapshot/ngày còn chờ, không dựng lại ngày cũ từ số dư
hiện tại. Máy nghiệm thu thứ hai được xác nhận Windows 11 x64; kiểm bộ cài/native
trên máy đó vẫn là gate riêng, không thay bằng unit/browser tests.

Tài liệu chính thức đối chiếu ngày 07/11/2026:

- [BotFather và quản lý bot](https://core.telegram.org/bots/features#botfather)
- [Bot API, HTTPS và methods](https://core.telegram.org/bots/api#making-requests)
- [getMe](https://core.telegram.org/bots/api#getme),
  [getChat](https://core.telegram.org/bots/api#getchat),
  [getChatMember](https://core.telegram.org/bots/api#getchatmember)
- [sendMessage](https://core.telegram.org/bots/api#sendmessage),
  [sendDocument](https://core.telegram.org/bots/api#senddocument)
- [Giới hạn gửi miễn phí](https://core.telegram.org/bots/faq#my-bot-is-hitting-limits-how-do-i-avoid-this)
