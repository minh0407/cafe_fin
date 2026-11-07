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
| Điều phối xem ảnh browser tổng hợp | PASS; form Telegram, token trống sau lưu, không có OA/GMF input |
| Kết nối TLS trực tiếp từ máy dev tới api.telegram.org:443 | PASS / TLSv1.3; không gọi bot hoặc gửi dữ liệu |
| Full Windows backend | 1.439 PASS / 922.30 s; no skips |
| Main browser với real API | 57 PASS / 54.0 s |
| Feature browser | accounting 17 + 1 + 11; contracts 3; records 1; reporting wrapper 1 PASS |
| Native library + Rust/Python interoperability | 47 PASS + explicit 1 PASS / 7.08 s |
| Frozen sidecar không có developer PATH | 1 PASS / 14.42 s |
| Production native controller với frozen sidecar thật | 2 PASS / 22.17 s; zero ignored |
| Tauri release compile + NSIS | PASS; release compile 3m01s |

Source của ba dòng PASS đầu là application checkpoint `f98f44f`, cùng shared
consumer test trong `b354fa6`. Tests dùng dữ liệu và secret tổng hợp; không token,
credential, DB, workbook hoặc nhóm thật được đưa vào Git.

Lượt reporting đầy đủ đầu chạy 403 ca trong 190.29 s: 402 PASS, gồm timer 60 giây;
một fixture API còn dùng body credential cũ. Sau khi đổi fixture sang bot_token và
kiểm không lộ token, test đó PASS riêng; lượt cuối 402 ca không gồm timer đã PASS.
Không sửa runtime để bỏ qua fixture lỗi. Chi tiết ở
[handoff Telegram](../handoffs/reporting/telegram-handoff.md).

## Windows build receipt

Run [42323839819](https://github.com/minh0407/cafe_fin/actions/runs/42323839819),
source `f4a6167846625989bd24dbc4b3bad6036f6311a8`: **SUCCESS**. Điều phối đã đọc
trạng thái hai job và logs hoàn tất. Jobs `128254396374` (native-library) và
`128254396760` (Windows). Runner `windows-2025-vs2026`, Python 3.12.16,
SQLite 3.53.1, Node 24, Rust 1.99.1, dependencies khóa.

Frozen sidecar SHA256:
`49596FEA48372332E8E23DAB753768EC1B6F72210914D3239C08996CE46B0122`.

Installer `Cafe Fin_0.1.0_x64-setup.exe`: **253.049.170 bytes**.
SHA256 `13F890BA4CB7372CC82ABDDEDE0ADBDFECF6E914B29FF2F52F627AD0FD447E93`.

Không upload hoặc giữ artifact trên runner, không cài/gửi installer hoặc tạo
release. Receipt này không phải đường tải. Native headless tests và browser
không thay bằng chứng GUI/cài sạch. Commit tài liệu sau đó không đổi source đã
build/test. Bản Docker localhost theo yêu cầu tiếp theo là preview riêng, không
thay app Windows hoặc chứng minh Windows secret/native APIs hoạt động trong Linux.

## Giới hạn nghiệm thu

Chưa cấu hình bot/nhóm thật và chưa gửi thật. Người dùng nhập token riêng trong
app, không gửi token vào chat. Native GUI/cài Windows sạch/offline/upgrade,
packaged large imports và source/relink distribution evidence vẫn theo gate đã
ghi ở [candidate 09](WINDOWS_DESKTOP_CANDIDATE_09.md); không gọi toàn app
production-ready chỉ từ increment này. Không xuất bản installer hoặc release.

Không sửa hoặc migrate source/DB CRM cũ; nghiệp vụ và file vẫn lưu trên máy.
