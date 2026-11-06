# Prompt triển khai báo cáo local và bộ gửi Zalo

Bạn là chat triển khai lane reporting cho ứng dụng Windows cafe_fin. Repo đích https://github.com/minh0407/cafe_fin.git, checkout điều phối trên máy `C:\Users\NC\Desktop\UNILA{\cafe_fin`. Đọc đầy đủ AGENTS.md, README.md, docs/SPEC.md, docs/ARCHITECTURE.md, docs/API_CONTRACT.md và docs/OWNERSHIP.md trước khi sửa.

## Baseline và phạm vi

Chỉ bắt đầu sau tag bất biến `cafe-fin-foundation-ready-v1` do chat điều phối tạo. Cần read bridge records/accounting đã freeze; có thể phát triển bằng typed fixture nhưng không coi mock là nghiệm thu tích hợp. Tag thiếu hoặc interface thiếu thì báo điều phối, không tự chọn HEAD khác.

Tìm worktree phù hợp qua list_artifacts, tạo bằng create_worktree nếu cần, đặt branch riêng `codex/cafe-fin-reporting-<unique>`. Không sửa checkout điều phối hoặc repo CRM cũ. Chỉ sửa backend/cafe_fin/reporting/**, frontend/src/features/reporting/**, tests/reporting/** và docs/handoffs/reporting/**, gồm migration module mình. Root config/dependencies/registry/core backup và job runner do điều phối/foundation sở hữu; đề nghị thay đổi bằng handoff, không sửa vượt phạm vi.

## Bối cảnh đã chốt

Một PC Windows luôn Internet, dữ liệu mới local. Nghiệp vụ chỉ ghi lại; không nhiều người duyệt, không QR/theme. Kế toán độc lập, có thể thiếu nghiệp vụ và chỉ có mapping tùy sổ. Báo cáo là tổng hợp dữ liệu đã nhập, không chứng nhận toàn bộ thực tế hoặc báo cáo tài chính pháp định. Không thêm bước phê duyệt người thứ hai.

## Việc phải hoàn thành

1. Báo cáo ngày có kỳ `[from,to)` theo giờ VN, snapshot/version/hash và nguồn dữ liệu. Nhập, sản xuất, xuất, tồn riêng theo loại; cảnh báo tồn/nhập thiếu. Tiền theo từng sổ có mapping phù hợp, tách thu/chi/cọc/đối trừ khi có đủ loại; chưa có mapping thì ghi chưa đủ dữ liệu, không coi là 0. Không cộng hai nguồn cùng transaction; stock hold là tập con, không cộng thêm tồn. Không giả rằng hóa đơn = thu tiền.
2. Người dùng chọn ngày/khoảng, xem trước, lưu và xuất PDF/XLSX/tin ngắn vào reports dưới data root. Dữ liệu tiền/kg chính xác; snapshot cũ không đổi sau sửa nghiệp vụ. Bản điều chỉnh có phiên bản và lý do.
3. Mẫu tin Zalo ngắn, chỉ tổng hợp; không CCCD, tài khoản ngân hàng, chữ ký, chứng từ, token, file path hoặc localhost link. Tệp đính kèm nếu bật là bản tổng hợp riêng được người dùng chọn, không tự gửi mọi bản chi tiết local.
4. Cấu hình lịch local, timezone, đích và credential qua UI Admin. Không hardcode giờ, nhóm hoặc biến môi trường bí mật trong Git. Credential trong OS secret store theo interface foundation; sender chỉ đọc payload được phép gửi.
5. Tích hợp một kênh Zalo chính thức khả dụng. OA GMF có API nhóm và file; cần OA/app/group quyền và dịch vụ phù hợp. Bot nhóm thường còn điều kiện khả dụng; kiểm tài liệu hiện hành và tài khoản thực tế trước chọn. Không dùng thư viện giả lập tài khoản cá nhân để mặc định thay thế API chính thức, không mở webhook public trên PC.
6. Luồng token refresh/upload/send/receipt outbound được tách khỏi core; không cần dịch vụ cloud phụ. Không có credential hoặc nhóm thì báo UNCONFIGURED và vẫn tạo báo cáo local. Không ghi log Success giả làm đã gửi.
7. Outbox bền vững, khóa ngày/report/version/destination, chỉ một sender; lưu message_id khi API xác nhận. Timeout sau send là UNKNOWN nếu chưa xác định, đối chiếu trước retry. Không khẳng định exactly once khi API chưa có idempotency. Lỗi mạng không làm lỗi nghiệp vụ.
8. Máy tắt/ngủ hoặc app đóng: thiết kế scheduler/tray local phù hợp foundation và ghi giới hạn rõ. Catch-up theo báo cáo còn chờ, giữ ngày đúng; không tự tạo số ngày cũ từ số dư hiện tại. Không dùng Codex automation làm lịch sản phẩm.
9. UI danh sách báo cáo/lượt gửi có paging, tìm/lọc/sort, trạng thái tạo/đã lưu/chờ gửi/đang gửi/đã gửi/lỗi/chưa rõ; không đồng nhất trạng thái báo cáo với trạng thái gửi.

## Kiểm thử và điều kiện bàn giao

Kiểm ranh giới ngày VN/cuối tháng, late edit/version, mapping thiếu, double count, nguồn tiền độc lập, secret redaction, sai group/config, hết hạn token, timeout sau send, duplicate scheduler và restart. Dùng fake transport cho regression tests, chỉ thử gửi thật khi người dùng cung cấp đích được xác minh và yêu cầu gửi thử cụ thể; không gửi tin cho người khác chỉ để demo.

Kiểm read bridge thật: chunk import đã commit pending không xuất hiện trong báo cáo; khi attempt PUBLISHED, toàn tập xuất hiện một lần; nhập tiếp dòng lỗi đã sửa không đếm lại attempt cũ. Mapping hoặc snapshot đang được worker dùng không được thay ngầm bởi sửa staging của người dùng.

Chạy tích hợp thật read bridge và export tiếng Việt sau khi records/accounting được điều phối ghép. Nếu chưa có quyền/kênh Zalo thì hoàn tất sender abstraction/UI/queue và ghi rõ phần live chưa chạy; không tuyên bố gửi thật PASS. Chưa đủ yêu cầu live thì handoff ở trạng thái thiếu điều kiện, không tự hạ requirement.

Nguồn chính thức để kiểm tra lại khi triển khai:

- https://docs.zaloplatforms.com/docs/OA/nhom-chat-gmf/tin-nhan/text_message
- https://docs.zaloplatforms.com/docs/OA/nhom-chat-gmf/tin-nhan/file_message
- https://docs.zaloplatforms.com/docs/OA/bat-dau/xac-thuc-va-uy-quyen-cho-ung-dung-new
- https://oa.zalo.me/home/documents/vie/guides/quan-ly-nhom-gmf_1954166378348758227
- https://bot.zapps.me/docs/build-bot-interaction-with-group/

Bàn giao commit SHA, branch/worktree, file/migration, lệnh test và kết quả, ảnh UI tổng hợp không PII, hợp đồng interface và phần live còn thiếu. Không push, merge hoặc tạo tag READY. Chat điều phối review/tích hợp/push.
