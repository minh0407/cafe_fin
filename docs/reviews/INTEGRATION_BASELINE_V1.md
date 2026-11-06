# Baseline tích hợp v1 cho đóng gói

Điều phối chốt tag bất biến `cafe-fin-integration-ready-v1` từ source nghiệp vụ `548029875f702161b83b5e6137fd98da244062fb`, sau các kiểm tra ở [increment 05](ACCOUNTING_REPORTING_INCREMENT_05.md). Commit tạo biên bản/tag chỉ bổ sung tài liệu; code/config/tests khớp source CI đã kiểm. Tag này cho phép lane packaging bắt đầu, không phải release hoặc production acceptance.

## Bằng chứng Windows

Run [42286460765](https://github.com/minh0407/cafe_fin/actions/runs/42286460765), job `128128442154`, **SUCCESS**:

| Phần | Kết quả |
|---|---|
| Backend tất cả module | 1.029 PASS / 772,64 giây |
| Frontend chính và real app shell | 32 PASS / 48,7 giây |
| Accounting mock/helper | 17 PASS / 32,9 giây |
| Accounting real API/import/repair/export | 1 flow PASS / 31,3 giây |
| SchemaEditor mất ACK | 11 PASS / 29,1 giây |
| Contracts real API | 3 PASS / 41,0 giây |
| Records real API | 1 PASS / 22,5 giây |
| Reporting wrapper | 1 PASS / 17,7 giây, 31 nhóm assertion nội bộ |
| Frozen sidecar với PATH không chứa dev tools | PASS / 17,46 giây |
| Lint, build frontend, Rust format, NSIS | PASS |

Installer tạm: `Cafe Fin_0.1.0_x64-setup.exe`, **252.887.920 bytes**, SHA256 `20EA58B8CAF1FA913FDC4E3795EE0DB6F5E62754ECBDF39E06B2801DFF0F6A93`. Binary chỉ có trong runner tạm, không upload/phát hành/cài thử. Runner có developer tools, không phải Windows client sạch.

## Những gì đã freeze

Registry thật có records, contracts, accounting, reporting. Read bridge v3, money/kg chính xác, auth local/Admin–Operator, file/job scopes, inclusive business dates, import immutable attempt/pending/publication và report snapshot đã kiểm liên luồng. Migration namespace: core/foundation theo baseline, records v1, contracts v1–2, accounting v1–2, reporting v1–3. Không sửa checksum cũ, tag foundation hoặc nguồn/DB CRM cũ.

Các lỗi review đã đóng gồm tồn âm khi sửa/xóa/backdate, borrowed snapshot fencing, nguồn file khác actor, formula cache cũ, duplicate identity sau thêm cột nullable, filter ô trống, schema command mất ACK, export/job response khác snapshot, contract/report export phục hồi khác actor, download/revocation, delivery terminal receipt và thiếu nhóm nhận. Handoff giữ riêng lịch sử FAIL và bản sửa, không dùng rerun để xóa bằng chứng.

## Việc packaging tiếp tục

Đọc prompt 05 và allowlist. Hoàn thiện native controls/Settings cho mở reports, backup/restore/move bằng picker, quiesce và clean-stop trước chuyển root, native config/transition recovery. Không coi primitives backup hoặc nút restart hiện tại là luồng chuyển dữ liệu đã dùng được. Candidate restore phải được kiểm trước khi khởi động jobs/sender; backup cũ không được tự gửi lại báo cáo bằng credential Windows hiện có.

Code mới trong core/app/shared cần patch điều phối; desktop/scripts/tests/docs packaging thuộc lane. Không mở thêm nghiệp vụ, sửa private ORM module hoặc nới security để qua test. Host AppControl giữ nguyên; native maintenance protocol và restore activation hook sẽ được phối hợp, không đoán interface từ proposal chưa triển khai.

Các gate còn mở: Windows sạch, native folder picker/lifecycle/offline, update/uninstall, DB+tệp+job backup/restore/move, DOCX mở/in, benchmark trên app đã cài và giấy phép/native source/relink. Benchmark CSV 50k/500k/1m, parser XLSX gần giới hạn và Chromium UI clone 1m đã có bằng chứng riêng, không thay thế native acceptance. Loại nhóm/quyền API/credential Zalo thật còn cần người dùng; chưa gửi thật. Không gọi source này production-ready.
