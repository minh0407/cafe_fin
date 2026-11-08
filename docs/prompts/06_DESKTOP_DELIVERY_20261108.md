# Bàn giao Cafe Fin thành app Windows — 08/11/2026

Người dùng yêu cầu giải thích trạng thái desktop và phân việc cho sáu chat Cafe Fin hiện có để hoàn thiện app cài trực tiếp, tự chạy phần xử lý local, không cần mở browser/Docker/terminal. Điều phối được giao quản lý luồng code, kiểm tra và push; các lane không push/merge/rebase nhánh khác hoặc tạo release.

## Candidate và cách nhận việc

Candidate nghiệp vụ được điều phối chỉ định: `828d575b4a3c7b18ffafd8e2665a9d79b54ea403` (sau market increment14). Đã xác minh là hậu duệ của `cafe-fin-foundation-ready-v1` và `cafe-fin-integration-ready-v1`; không di chuyển hai tag. CI Windows run42344896417 SUCCESS. Đây là điểm bắt đầu đợt nâng cấp sau tích hợp được điều phối cho phép, thay SHA cũ trong prompt lane, không phải tag release mới.

Lệnh giao việc cung cấp SHA coordination mới chỉ thêm tài liệu phân công/OWNERSHIP trên candidate nghiệp vụ này; dùng SHA coordination đó để worktree có cùng phân quyền. Điều phối sẽ kiểm diff code giữa hai mốc bằng 0 trước khi gửi.

Mỗi chat đọc README, AGENTS hiện hành, SPEC, ARCHITECTURE, API_CONTRACT, OWNERSHIP, prompt gốc của lane và tài liệu này. Dùng `list_artifacts`, tái dùng worktree sạch phù hợp hoặc `create_worktree` từ đúng candidate; branch riêng. Không tự kéo candidate mới hoặc reset checkout cũ. Worktree cũ có commits riêng thì giữ nguyên và tạo worktree mới; không cần hỏi lại chỉ vì tên branch không trùng. Mọi phần việc code bắt đầu từ candidate được chỉ định, không từ source lane cũ. High cho các chat triển khai và subagent; điều phối giữ thiết lập riêng.

## Hành vi desktop cần hoàn thiện

- Cài bằng bộ `.exe`, mở từ shortcut, frontend đóng gói trong cửa sổ app và tự khởi động frozen sidecar. Không mở trang web, dev server, Docker, terminal hoặc yêu cầu Python/Node/Office cài riêng. Backend vẫn có API loopback nội bộ có xác thực; điều này không làm sản phẩm trở thành website mà người dùng phải tự chạy.
- Chọn ổ/thư mục dữ liệu bằng GUI; giữ DB/tệp/báo cáo ở nơi đã chọn, tách thư mục cài. Không reset dữ liệu khi root không mở được; giữ bảo vệ backup/move/restore và journal hiện có.
- Bổ sung khay hệ thống với Mở Cafe Fin/Thoát. Đóng cửa sổ thu về khay và có thông báo rõ lần đầu; Thoát là đóng thật, dừng sidecar sạch. Không mất nháp âm thầm; không để nhiều instance hoặc sidecar mồ côi. Tạo app ẩn từ startup không được bỏ qua bootstrap/data-root guard hoặc lưu thông tin đăng nhập.
- Có tùy chọn tự mở cùng Windows, mặc định tắt, chỉ thay cấu hình startup của chính app cho currentUser khi người dùng bật trong app. Có thể tắt lại. Không tự cài Windows service, task quản trị, đổi policy hệ thống hoặc bật startup trên máy phát triển khi test. Không auto-login/lưu mật khẩu local.
- Scheduler báo cáo và giá chạy theo backend khi cửa sổ đã thu về khay; không phụ thuộc mở trang Báo cáo/Bảng giá. Máy tắt/ngủ hoặc người dùng Thoát thì không chạy; mở lại dùng catch-up/cooldown đã chốt. Mất Internet không chặn nhập/xem/xuất local. Chỉ Internet cho Telegram và nguồn giá cố định, không Google OAuth/cloud DB.
- Giá nhân xô tự lấy theo contract thị trường; quả tươi nhập tay và giá bán riêng. Nguồn trả challenge phải giữ BLOCKED; bộ cài không được biến fixture thành giá thật. Telegram giữ UNCONFIGURED khi thiếu cấu hình, không gọi gửi thật để làm test đẹp.

## Quyền sửa và sản phẩm của từng chat

| Chat | Quyền ghi riêng trong đợt này | Sản phẩm và kiểm tra |
|---|---|---|
| Cafe Fin 00 — Nền tảng desktop | `desktop/src/**`, `desktop/Cargo.toml`, `desktop/Cargo.lock`, `desktop/capabilities/**`, `frontend/src/app/**`, `frontend/src/shared/**`, core runtime nếu cần; tests core/shared/native runtime và handoff foundation. Không sửa bundle config/scripts/notices của05. | Hoàn thiện tray, close/exit, tùy chọn startup, single-instance, backend auto-start/close/crash recovery và GUI trạng thái. Giữ maintenance fencing/session/lock. Test meaningful, Rust fmt/check/test và frontend build. Đề xuất interface mới trước khi lane04 cần dùng; không thiết kế scheduler thứ hai. |
| Cafe Fin 01 — Ghi nhận nghiệp vụ | `backend/cafe_fin/records/**`, `frontend/src/features/records/**`, `tests/records/**`, handoff records. | Chuẩn bị và kiểm fixture farm/company, đầu vào/đầu ra, dashboard, giá mua/bán và nguồn giá trên app/native sidecar đúng source. Kiểm tồn âm, edit/delete/backdate/restore, giá đơn bất biến. Chỉ sửa lỗi có repro trong module, không đổi quy tắc giá để giả nguồn hoạt động. |
| Cafe Fin 02 — Hợp đồng và chứng từ | contracts module/UI/tests/handoff; không sửa shared renderer hoặc dependency chung. | Hợp đồng mua/bán, cân, điều khoản/phương thức/lịch thanh toán, DOCX/PDF offline với native sidecar và GUI khi có artifact. Tạo fixture tổng hợp và expected snapshot/hash; kiểm tiếng Việt/layout theo skill phù hợp, không lấy structural check làm visual PASS. Lỗi renderer chung gửi patch cho điều phối. |
| Cafe Fin 03 — Kế toán Excel và import | accounting module/UI/tests/handoff. | Kiểm preview/edit/copy/paste/import một phần/resume, macro gốc nguyên hash, không external execution. Chuẩn bị harness packaged benchmark và ca mini trước. Chỉ chạy50k/500k/1m sau candidate cuối và điều phối cấp slot tải riêng; ghi riêng source/native/clean-client evidence, không mượn kết quả source cũ cho app mới. |
| Cafe Fin 04 — Báo cáo và Telegram | reporting module/UI/tests/handoff. | Lịch chạy nền/khay, xuất local, catch-up sau mở lại, secret Windows Credential Manager, mất mạng/thiếu token/UNKNOWN không gửi lặp. Kiểm với transport tổng hợp trước; không cấu hình hoặc gửi nhóm thật khi chưa có đích test được giao. Không sửa lifecycle Tauri của00 hoặc lưu token plaintext. |
| Cafe Fin 05 — Bộ cài và nghiệm thu | `desktop/tauri.conf.json`, `desktop/build.rs`, `desktop/scripts/**`, `desktop/notices/**`, `desktop/icons/**`, `scripts/packaging/**`, tests packaging mới tách riêng, handoff packaging và `docs/release/**`. Không sửa source runtime/Cargo/capability của00; không sửa CI trực tiếp. | Build source-matched frozen sidecar/NSIS, WebView2 offline, dependency/notices/source/relink evidence, manifest/checksums; tìm và sửa lỗi packaging trong phạm vi. Chuẩn bị kit Windows11x64, hướng dẫn cài/chọn ổ/backup/update/uninstall và fixture nhỏ. Kiểm local có thể làm; Windows sạch/PC2 chưa truy cập được phải NOT RUN. Đề xuất patch CI giữ artifact nếu local build vẫn bị policy chặn; không né policy, không public release/upload tự ý. |

File test runtime `tests/desktop/{Cargo.toml,Cargo.lock,*.rs}` do00 giữ. 05 thêm acceptance dưới thư mục con riêng hoặc dùng script packaging, không cùng sửa harness native chung. Root manifests ngoài desktop/Cargo*, `.github/**`, SPEC/API_CONTRACT/OWNERSHIP/ADR và USER_GUIDE thuộc điều phối. Mỗi lane có thể ghi đề nghị patch riêng cho file ngoài allowlist, không phải dừng phần việc độc lập để chờ.

## Thứ tự chạy và freeze artifact

1. 00 và05 bắt đầu ngay: 00 runtime; 05 kiểm build/notices/kit trên candidate gốc. 01–04 cập nhật fixtures/harness và kiểm module/native sidecar từ cùng candidate. Không gọi bản05 dựng trước runtime mới là bản cuối.
2. Các lane bàn giao commit nhỏ đã test, đề nghị interface và lỗi có repro trong chính chat/handoff. Không nhắn chéo các chat; điều phối đọc và chuyển patch. Ghi PASS/FAIL/NOT RUN cùng nguyên nhân, đường dẫn/branch/SHA và lệnh test.
3. Điều phối tích hợp, review lifecycle và module, chạy gate liên quan rồi chỉ định SHA candidate cuối. 05 build lại đúng SHA đó; không cherry-pick các bản lane tùy ý để tự hợp nhất.
4. 01–04 nghiệm thu trên artifact cuối bằng dữ liệu tổng hợp; 03 giữ slot benchmark riêng để không cạnh tranh RAM/CPU. 05 tập hợp kết quả cài/offline/root/backup/upgrade/uninstall, xuất kit ngoài Git có checksum/source/version khớp.
5. Điều phối kiểm code/diff/tests, quản lý push và bàn giao installer cùng trạng thái nghiệm thu thật. Không lấy NSIS build SUCCESS làm clean-Windows PASS; không tự gọi production-ready khi còn gate. Kiểm máy Windows thứ hai cần người dùng thao tác hoặc kênh truy cập thực, không suy diễn từ việc người dùng nói có máy.

Không chạy đồng thời nhiều cargo build hoặc benchmark lớn trên máy này. 05 giữ slot build installer; 00 dùng kiểm runtime nhỏ trước, phối hợp lịch qua điều phối khi cần build nặng. Không tắt Defender/AppControl, thêm exclusion hoặc đổi tên/path để vượt chặn thực thi. Chỉ DB/fixture tổng hợp ngoài repo; không đụng volume Docker người dùng, DB/Excel/token thật hoặc CRM cũ. Artifact nhị phân/raw benchmark ngoài Git, chỉ commit code/docs/fixture tổng hợp nhỏ.
