# Quy tắc làm việc trong cafe_fin

Đọc `README.md`, `docs/SPEC.md`, `docs/ARCHITECTURE.md`, `docs/API_CONTRACT.md`, `docs/OWNERSHIP.md` và prompt được giao trước khi sửa. Yêu cầu cafe_fin thay thế nghiệp vụ phê duyệt của CRM cũ; không áp AGENTS của repo cũ cho repo mới.

## Yêu cầu bắt buộc

- Một máy Windows, dữ liệu mới, local DB và local files. Không sửa hoặc migrate DB/source CRM cũ.
- Không QR, theme toggle, ca trưởng hoặc phê duyệt nhiều tài khoản. Ghi dữ liệu, validation, nhật ký sửa/xóa, version và chống ghi lặp vẫn có.
- Tồn âm bị chặn kể cả khi sửa, xóa, đổi ngày hoặc hoàn tác bản ghi đã ảnh hưởng kho. Không thay bằng cảnh báo đơn thuần.
- Kế toán độc lập: thiếu liên kết CRM không phải lỗi chặn import. Không tự tạo tiền hoặc thay tồn kho từ dòng Excel kế toán.
- Không chạy macro, external links hoặc nội dung thực thi từ tệp import. Không ghi đè Excel gốc; lưu bản gốc theo hash và làm việc trên projection/staging.
- Dùng thư viện production có giấy phép tương thích yêu cầu miễn phí. Không dùng key evaluation/non-commercial để lách phí thương mại.
- Không `eval`, float tính tiền/kg, nạp một triệu dòng vào UI hoặc hứa tốc độ khi chưa benchmark.

## Làm việc song song

- Foundation chỉ bắt đầu từ `cafe-fin-spec-v1`. Module chỉ bắt đầu từ `cafe-fin-foundation-ready-v1` do điều phối tạo. Tag chưa có thì không tự chọn baseline thay thế.
- Dùng branch và checkout/worktree riêng. Khi dùng Codex, tìm worktree phù hợp qua `list_artifacts`, tạo bằng `create_worktree` nếu cần. Không checkout/switch hoặc sửa trên checkout đang được chat khác sử dụng.
- Tuân thủ allowlist trong OWNERSHIP. File chung do foundation/điều phối sở hữu. Cần đổi interface thì ghi đề nghị và patch riêng, không âm thầm sửa chung.
- Không tự push, merge, rebase nhánh của người khác hoặc force-push. Người dùng giao chat điều phối quản lý push.
- Không tạo Codex chat mới hoặc gửi thông điệp tới người khác nếu chưa được yêu cầu. Có thể dùng subagent cho phần việc của lane.

## Hoàn thành và bàn giao

- Kiểm Git diff, chỉ stage file trong phạm vi. Giữ nguyên thay đổi của người khác.
- Chạy kiểm thử cần thiết cho hành vi có rủi ro, build và lint phù hợp; ghi rõ PASS/FAIL/NOT RUN với nguyên nhân. Không lấy test SQLite giả lập để chứng minh hành vi PostgreSQL cũ hoặc ngược lại.
- Với import lớn và bộ cài: bằng chứng chạy thật, cấu hình máy và thông số file quan trọng hơn một test mock hoặc thời gian ước lượng.
- Bàn giao đường dẫn worktree, branch, commit SHA, files, migration, lệnh test/kết quả, giới hạn còn lại và tác động interface. Chưa hoàn tất thì không tự gọi production-ready.
- Chỉ code/tài liệu/fixture tổng hợp được commit. DB thật, Excel thật, ảnh, chữ ký, thông tin ngân hàng, token và log nhạy cảm ở ngoài repo.
