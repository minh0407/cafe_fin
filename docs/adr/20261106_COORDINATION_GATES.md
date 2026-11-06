# Mốc nền tảng phát triển và nghiệm thu phát hành

Ngày 06/11/2026. Điều phối cập nhật thứ tự nghiệm thu để giữ các module có thể phát triển độc lập mà không gọi bản chưa nghiệm thu là production.

## Bối cảnh

Core và sidecar có thể kiểm chứng bằng SQLite file thật, subprocess thật và browser gọi API thật. Tuy nhiên, Windows Application Control trên máy phát triển chặn một số DLL/build script Rust release. Build Tools và SDK đã được cài và probe C/Rust thành công. Chưa có Windows sạch sẵn dùng; Windows Sandbox đang tắt. Không thay đổi policy, bật Sandbox hoặc reboot để bỏ qua những điều kiện này.

Yêu cầu cài và dùng trên Windows sạch vẫn là yêu cầu phát hành. Đặt toàn bộ bước đó trước khi module bắt đầu viết code gây phụ thuộc không cần thiết giữa nghiệp vụ và môi trường nghiệm thu cuối.

## Quyết định

Tách hai loại mốc. Tên tag theo AGENTS vẫn giữ nguyên; chỉ điều phối công bố sau khi kiểm bằng chứng.

### Baseline phát triển foundation

Tag `cafe-fin-foundation-ready-v1` có nghĩa các interface đã được điều phối freeze để module bắt đầu, không có nghĩa bộ cài đã được nghiệm thu. Điều kiện bắt buộc:

- Core, auth local, file store, backup, jobs, import primitives và registry có code tracked đầy đủ, tests qua trên snapshot sạch.
- Các lỗi review về transaction, fencing, thu hồi quyền, bất biến snapshot, export retry/download và handshake được xử lý trước freeze.
- Typed API/DTO/migration/module/job/read-bridge contracts có ví dụ tích hợp và kiểm thử, không buộc module sửa file chung không kiểm soát.
- Frontend build và browser regression/integration với sidecar thật đạt; mock native invoke được ghi rõ.
- Có phép thử Word/PDF tiếng Việt và grid miễn phí có license, sidecar đóng gói chạy được trên máy phát triển trong điều kiện đã ghi.
- Native compile check có kết quả và các hạn chế build/install được ghi rõ. Native release build/clean-client install chưa đạt không được ghi PASS hoặc suy từ browser tests.

Nếu còn lỗi chức năng/blocker thuộc các điều kiện trên thì chưa tạo tag. Thiếu phép thử native cuối chỉ được chuyển sang release gate với trạng thái tường minh, không bị xóa khỏi checklist.

### Integration và release

Sau các module, điều phối kiểm thử liên luồng trước tag integration. Lane packaging tiếp tục phải build installer và kiểm cài/update/uninstall/backup/restore, native folder picker/lifecycle, offline runtime và Word/PDF/grid trên Windows client sạch. Benchmark 50k/500k/1m và Zalo live có bằng chứng riêng. Chưa đạt thì không phát hành hoặc tự gọi production-ready.

GitHub Actions dùng standard Windows build runner để kiểm lại source và build candidate trong môi trường được phép. Đó là kiểm chứng build khác với nghiệm thu Windows client sạch; không dùng runner đã có developer tools để giả clean-Windows acceptance. Workflow không deploy, không công bố release và không gửi báo cáo thật.

## Hệ quả

Các module vẫn phải chờ đúng tag foundation; không tự làm từ HEAD. Chỉ sau khi API baseline được kiểm mới mở các chat nghiệp vụ. Root có thể push increment được review trước tag READY và ghi rõ phần đã đạt/chưa đạt. Không thay đổi yêu cầu người dùng về local data, chặn tồn âm, không Google OAuth, Excel độc lập hoặc chất lượng bản cài cuối.
