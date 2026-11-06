# Biên bản freeze foundation phát triển v1

Điều phối chốt ngày 06/11/2026, theo [ADR phân gate](../adr/20261106_COORDINATION_GATES.md). Tag bất biến `cafe-fin-foundation-ready-v1` trỏ commit chứa biên bản này. Tag là điểm bắt đầu module, không phải bản cài hoặc chứng nhận production.

## Điều kiện phát triển đã đạt

- Code nền cuối: `7e03d2555f9551c90e5f2ba3f131a3af1b4d4980`; handoff cuối: `b1a59ff3c1cabd31f373ea464d796e4762f35e8a`.
- Điều phối kiểm 86 backend tests, lint/compile, frontend build và 10 browser tests với sidecar thật; reviewer độc lập xác nhận các lỗi đã tìm được sửa. [Increment 02](FOUNDATION_INCREMENT_02.md) ghi lệnh/kết quả. Foundation còn chạy lại toàn bộ trên archive tracked sạch, không dựa file untracked.
- Core local auth, DB/writer, audit/idempotency, jobs/fencing, storage/backup, immutable import attempt và stock guard có test hành vi.
- Module migration/router/job/startup registration, DTO/read bridges, HTTP errors/paging, original file transfer và client session đã có code/types và recipes. Lane dùng [handoff foundation](../handoffs/foundation/README.md), không đoán interface từ thiết kế cũ.
- Grid MIT và Word/PDF local đã có proof kỹ thuật; không đưa proof thành nghiệp vụ import/hợp đồng hoàn chỉnh.
- Frozen sidecar build/smoke và native cargo check đã đạt trên máy phát triển; giới hạn native release được ghi rõ.

Không có thay đổi code ứng dụng sau source cuối ở trên. Các thay đổi sau là handoff, inventory, CI và tài liệu điều phối. GitHub Windows run của increment 02 kiểm cùng source ứng dụng; kết quả đang theo dõi riêng, không suy trước thành PASS.

## Interface và thứ tự tích hợp

Records, contracts và accounting bắt đầu từ đúng tag này trên branch/worktree riêng. Reporting dùng read bridges đã freeze; concrete providers được điều phối bind sau. Packaging chưa bắt đầu code trước tag integration.

Lane chỉ sửa allowlist, export backend `module.py` và frontend `index.ts`, gửi migration/manifest/bridge cùng patch wiring cho root. Chỉ root sửa registry, shared dependencies, CI, tags và push. Sau baseline, không đổi migration checksum hoặc interface đã freeze; đề nghị additive/versioned qua handoff shared-change-request.

## Gate phát hành chưa đạt

Native NSIS build tại host bị AppControl4551 chặn; chưa có cài sạch/native GUI/offline WAN/update/uninstall end-to-end. DOCX visual/mở/in, native data-root move/relaunch và source/relink clearance cho iconv còn thiếu bằng chứng. GitHub build runner không thay máy client sạch. Các module nghiệp vụ, benchmark 50k/500k/1m, crash/recovery liên luồng và Zalo live chưa nghiệm thu.

Giữ các mục này trong release gate. Không phát hành binary hoặc gọi production-ready khi chúng chưa đạt. Dữ liệu mới/local, chặn tồn âm, kế toán độc lập, không Google OAuth và không sửa CRM cũ vẫn là yêu cầu bắt buộc.
