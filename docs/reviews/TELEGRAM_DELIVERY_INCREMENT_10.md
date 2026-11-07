# Telegram delivery increment 10

Theo yêu cầu mới ngày 07/11/2026, Cafe Fin chuyển kênh báo cáo sang Telegram và
bỏ runtime/config/UI Zalo. Quyết định: [ADR Telegram](../adr/20261107_TELEGRAM_REPORT_DELIVERY.md).

## Thay đổi đã ghép

Source checkpoint lane `5ef2f734d5a4985c6cb933d69fe5ad0052b7c55c` được điều phối
cherry-pick thành `f98f44f`; namespace OS store ở `516b536`, contract/prompts ở
`7db219d`, shared restore consumer và hướng dẫn giới hạn tệp ở `b354fa6`.
Kết quả regression của lane được ghi riêng bên dưới và trong handoff Telegram.

- Telegram Bot API qua HTTPS outbound, không webhook public hoặc server thuê.
  Cấu hình dùng chat_id và bot_token; bỏ OA/app_secret/refresh_token. Token chỉ ở
  Windows Credential Manager theo root UUID/bot ID, namespace tách biệt kênh cũ.
- Lưu token không gọi WAN. Xóa proof xác minh bền vững trước thay secret; lỗi hoặc
  crash không giữ nhầm proof cũ. Connection-check chỉ đọc getMe/getChat/getChatMember,
  xác minh bot/nhóm/quyền, không gửi tin. Đổi nhóm/token phải kiểm lại.
- Tin thuần văn bản tối đa 4096 UTF-16 units; đính kèm chỉ PDF/XLSX tổng hợp của
  báo cáo được chọn, tối đa 5 MiB trong app. Lịch tự động không tự chọn tệp chi tiết.
- Receipt phải có đúng chat_id, bot và message_id nguyên dương. Text/document có
  receipt riêng. POST chưa rõ giữ UNKNOWN, không tự retry; Telegram không có API
  lịch sử tin đã gửi để app tự bịa kết quả đối chiếu.
- Thiếu cấu hình vẫn tạo và xuất local, không WAN/attempt. Placeholder chưa có
  identity không chiếm route thật; sau cấu hình, báo cáo cũ có thể queue bình thường.
  Đổi từ bot đã pin sang bot khác cần bản gửi/bản điều chỉnh rõ ràng; lịch sử xung
  đột không chặn những report khác hợp lệ.
- Retry-after 1..3600 giây được giữ đúng và chặn toàn bot đến deadline bền vững.
  Giá trị không hỗ trợ đặt hold toàn bot; không rút ngắn hoặc lách bằng report khác.
  Chưa có cơ chế tự giải quyết exceptional hold này trong UI hiện tại.
- Migration reporting v4 chỉ thêm provenance/receipt/backoff và giữ lịch sử kênh
  cũ. Lượt cũ chưa chắc kết quả bị giữ UNKNOWN, lịch cũ tắt; không replay sang
  Telegram. Report snapshot, exported files và payload cũ giữ nguyên. Restore
  guard và tạm dừng lịch trước Admin review vẫn áp dụng.

## Kiểm chứng

Điều phối chạy trên Windows 11 x64, Python 3.12.16, locked dependencies.

| Kiểm tra | Kết quả đã quan sát |
| --- | --- |
| Core secret + actual wire restore/default registry + real business workflow | 30 PASS / 16.35 s |
| Frontend production build | PASS; Vite bundle size warning hiện có |
| Backend lint + compile | PASS |
| Reporting regression cuối | 402 PASS, không chạy lại timer đã PASS với cùng runtime source; tổng 403 ca được kiểm |
| Reporting browser | PASS: hai assertion harnesses trong một Playwright wrapper / 16.1 s |
| Full Windows CI/frozen/native/NSIS cho source mới | Chưa chạy; chờ push source đã kiểm |

Source của ba dòng PASS đầu là application checkpoint `f98f44f`, cùng shared
consumer test trong `b354fa6`. Tests dùng dữ liệu và secret tổng hợp; không token,
credential, DB, workbook hoặc nhóm thật được đưa vào Git.

Lượt reporting đầy đủ đầu chạy 403 ca trong 190.29 s: 402 PASS, gồm timer 60 giây;
một fixture API còn dùng body credential cũ. Sau khi đổi fixture sang bot_token và
kiểm không lộ token, test đó PASS riêng; lượt cuối 402 ca không gồm timer đã PASS.
Không sửa runtime để bỏ qua fixture lỗi. Chi tiết ở
[handoff Telegram](../handoffs/reporting/telegram-handoff.md).

## Giới hạn nghiệm thu

Chưa cấu hình bot/nhóm thật và chưa gửi thật. Người dùng nhập token riêng trong
app, không gửi token vào chat. Native GUI/cài Windows sạch/offline/upgrade,
packaged large imports và source/relink distribution evidence vẫn theo gate đã
ghi ở [candidate 09](WINDOWS_DESKTOP_CANDIDATE_09.md); không gọi toàn app
production-ready chỉ từ increment này. Không xuất bản installer hoặc release.

Không sửa hoặc migrate source/DB CRM cũ; nghiệp vụ và file vẫn lưu trên máy.
