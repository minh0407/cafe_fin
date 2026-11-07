# Prompt triển khai báo cáo local và bộ gửi Telegram

Bạn là chat triển khai lane reporting cho ứng dụng Windows cafe_fin. Repo đích https://github.com/minh0407/cafe_fin.git, checkout điều phối trên máy `C:\Users\NC\Desktop\UNILA{\cafe_fin`. Đọc đầy đủ AGENTS.md, README.md, docs/SPEC.md, docs/ARCHITECTURE.md, docs/API_CONTRACT.md và docs/OWNERSHIP.md trước khi sửa.

## Baseline và phạm vi

Chỉ bắt đầu sau tag bất biến `cafe-fin-foundation-ready-v1` do chat điều phối tạo. Cần read bridge records/accounting đã freeze; có thể phát triển bằng typed fixture nhưng không coi mock là nghiệm thu tích hợp. Tag thiếu hoặc interface thiếu thì báo điều phối, không tự chọn HEAD khác.

Tìm worktree phù hợp qua list_artifacts, tạo bằng create_worktree nếu cần, đặt branch riêng `codex/cafe-fin-reporting-<unique>`. Không sửa checkout điều phối hoặc repo CRM cũ. Chỉ sửa backend/cafe_fin/reporting/**, frontend/src/features/reporting/**, tests/reporting/** và docs/handoffs/reporting/**, gồm migration module mình. Root config/dependencies/registry/core backup và job runner do điều phối/foundation sở hữu; đề nghị thay đổi bằng handoff, không sửa vượt phạm vi.

## Bối cảnh đã chốt

Một PC Windows luôn Internet, dữ liệu mới local. Nghiệp vụ chỉ ghi lại; không nhiều người duyệt, không QR/theme. Kế toán độc lập, có thể thiếu nghiệp vụ và chỉ có mapping tùy sổ. Báo cáo là tổng hợp dữ liệu đã nhập, không chứng nhận toàn bộ thực tế hoặc báo cáo tài chính pháp định. Không thêm bước phê duyệt người thứ hai.

## Việc phải hoàn thành

1. Báo cáo ngày có kỳ `[from,to)` theo giờ VN, snapshot/version/hash và nguồn dữ liệu. Nhập, sản xuất, xuất, tồn riêng theo loại; cảnh báo tồn/nhập thiếu. Tiền theo từng sổ có mapping phù hợp, tách thu/chi/cọc/đối trừ khi có đủ loại; chưa có mapping thì ghi chưa đủ dữ liệu, không coi là 0. Không cộng hai nguồn cùng transaction; stock hold là tập con, không cộng thêm tồn. Không giả rằng hóa đơn = thu tiền.
2. Người dùng chọn ngày/khoảng, xem trước, lưu và xuất PDF/XLSX/tin ngắn vào reports dưới data root. Dữ liệu tiền/kg chính xác; snapshot cũ không đổi sau sửa nghiệp vụ. Bản điều chỉnh có phiên bản và lý do.
3. Mẫu tin Telegram ngắn, thuần văn bản, chỉ tổng hợp; không CCCD, tài khoản ngân hàng, chữ ký, chứng từ, token, file path hoặc localhost link. Tệp đính kèm nếu bật là bản tổng hợp PDF/XLSX riêng được người dùng chọn, không tự gửi mọi bản chi tiết local. Kiểm giới hạn độ dài và dung lượng trước gửi; không nạp toàn bộ workbook lớn vào bộ nhớ.
4. Cấu hình lịch local, timezone, đích và credential qua UI Admin. Không hardcode giờ, nhóm hoặc biến môi trường bí mật trong Git. Credential trong OS secret store theo interface foundation; sender chỉ đọc payload được phép gửi.
5. Chỉ Telegram Bot API chính thức; bỏ runtime/config/UI Zalo. Xác minh getMe/getChat/getChatMember, numeric chat_id âm của group/supergroup và quyền gửi tối thiểu. Connection-check không gửi tin. Chỉ gọi HTTPS api.telegram.org, không theo redirect hoặc cho endpoint tùy ý; không mở webhook public. Token nằm trong path API nhưng URL/exception không được lộ token ra UI, log hoặc error. Không giả lập tài khoản cá nhân.
6. Bot token không có OAuth refresh. Dùng namespace OS secret riêng cafe_fin/reporting/<root_uuid>/telegram/<bot_id>; không reuse credential cũ. sendMessage gửi plain text, sendDocument upload multipart tệp tổng hợp được chọn. Không có token hoặc nhóm thì UNCONFIGURED, không request mạng/attempt và vẫn tạo báo cáo local. Không ghi log Success giả làm đã gửi.
7. Outbox bền vững, khóa ngày/report/version/provider/bot/destination, chỉ một sender; receipt phải đúng chat_id và message_id hợp lệ. Timeout/response không kết luận được sau POST là UNKNOWN, không tự retry. Telegram không có API đọc lịch sử tin đã gửi để bịa kết quả đối chiếu. Không khẳng định exactly once. Migration giữ nguyên lịch sử/payload/receipt cũ, tắt lịch cũ và giữ các lượt Zalo không replay sang Telegram khi upgrade/restore/catch-up/retry. Lỗi mạng không làm lỗi nghiệp vụ.
8. Máy tắt/ngủ hoặc app đóng: thiết kế scheduler/tray local phù hợp foundation và ghi giới hạn rõ. Catch-up theo báo cáo còn chờ, giữ ngày đúng; không tự tạo số ngày cũ từ số dư hiện tại. Không dùng Codex automation làm lịch sản phẩm.
9. UI danh sách báo cáo/lượt gửi có paging, tìm/lọc/sort, trạng thái tạo/đã lưu/chờ gửi/đang gửi/đã gửi/lỗi/chưa rõ; không đồng nhất trạng thái báo cáo với trạng thái gửi.

## Kiểm thử và điều kiện bàn giao

Kiểm ranh giới ngày VN/cuối tháng, late edit/version, mapping thiếu, double count, nguồn tiền độc lập, secret redaction cả URL/token/error.description, sai chat/config/receipt, token bị thu hồi, HTTP 429/401/403, redirect, response quá lớn/malformed, timeout sau send, duplicate scheduler, restart và legacy upgrade/restore không replay. Dùng fake transport cho regression tests, chỉ thử gửi thật khi người dùng cung cấp đích được xác minh và yêu cầu gửi thử cụ thể; không gửi tin cho người khác chỉ để demo.

Kiểm read bridge thật: chunk import đã commit pending không xuất hiện trong báo cáo; khi attempt PUBLISHED, toàn tập xuất hiện một lần; nhập tiếp dòng lỗi đã sửa không đếm lại attempt cũ. Mapping hoặc snapshot đang được worker dùng không được thay ngầm bởi sửa staging của người dùng.

Chạy tích hợp thật read bridge và export tiếng Việt sau khi records/accounting được điều phối ghép. Nếu chưa có bot/nhóm Telegram thật thì hoàn tất sender/UI/queue và ghi rõ phần live chưa chạy; không tuyên bố gửi thật PASS. Chưa đủ yêu cầu live thì handoff ở trạng thái thiếu điều kiện, không tự hạ requirement.

Nguồn chính thức để kiểm tra lại khi triển khai:

- https://core.telegram.org/bots/features#botfather
- https://core.telegram.org/bots/api#making-requests
- https://core.telegram.org/bots/api#getme
- https://core.telegram.org/bots/api#getchat
- https://core.telegram.org/bots/api#getchatmember
- https://core.telegram.org/bots/api#sendmessage
- https://core.telegram.org/bots/api#senddocument
- docs/adr/20261107_TELEGRAM_REPORT_DELIVERY.md

Bàn giao commit SHA, branch/worktree, file/migration, lệnh test và kết quả, ảnh UI tổng hợp không PII, hợp đồng interface và phần live còn thiếu. Không push, merge hoặc tạo tag READY. Chat điều phối review/tích hợp/push.
