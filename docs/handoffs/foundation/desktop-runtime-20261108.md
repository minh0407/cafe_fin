# Runtime desktop — 08/11/2026

Lane00, baseline coordination `eab8c96b851f039de515083189f4301cc09437c0` (code bằng business candidate `828d575b4a3c7b18ffafd8e2665a9d79b54ea403`).

- Worktree: `C:\Users\NC\.codex\worktrees\cafe-fin-runtime-20261108\cafe_fin`.
- Branch: `codex/cafe-fin-runtime-20261108`.
- Commit code: `c7a7a44b6edd9b5ebda4861fb08f4de5a145eb42`; commit handoff kế tiếp chỉ thêm tài liệu này. Không push, merge, tag hoặc tạo installer.
- Không sửa nguồn/config/DB CRM cũ, DB/Excel/token thật, bundle config, build.rs, CI hoặc notices. Không thay scheduler/backend nghiệp vụ.

## Hành vi và interface

Tray native có **Mở Cafe Fin** và **Thoát**. Mở/nhấn trái biểu tượng/shortcut thủ công sẽ show, unminimize và focus cửa sổ hiện có; không khởi động sidecar thứ hai. Duplicate `--startup-v1` không kéo phiên đang chạy ra trước.

Nút X giữ cửa sổ/WebView, nháp và phiên trong bộ nhớ; lần đầu giải thích bằng native dialog, sau đó thu về khay. Marker UX `app_config_dir/tray-notice-v1` chứa `1\n`; lỗi/phiên bản lạ chỉ khiến lặp lại giải thích, không ghi đè machine.json/journal. Nếu tạo tray lỗi, cửa sổ vẫn hiện và nút X chuyển sang xác nhận Thoát. Không thu một app không có tray.

Thoát luôn hỏi rõ nháp chưa lưu sẽ mất và lịch nền sẽ dừng. Native fence chặn command mới xếp hàng sau khi xác nhận; controller mutex chờ thao tác đã chạy xong. Picker maintenance đang mở chặn thoát, nhưng callback đúng ticket vẫn được settlement sau fence; lỗi store/child/handles cũng trả latch đúng ticket, không hủy selection mới. Explicit Exit gửi lệnh dừng có sẵn rồi chờ exit0 và reader kết thúc; lỗi pipe/timeout/nonzero được báo, không kill tiến trình còn sống hoặc vứt handle của nó. Journal/config vẫn nguyên. Core hiện có chỉ return0 sau drain/đóng periodic, jobs, writer, DB/root; không thêm shutdown/scheduler thứ hai. Fallback shutdown cuối tiến trình có sẵn được giữ.

Frontend giữ nguyên auto-start trong App. Sau health đầu tiên của **existing-root auto-start**, chỉ khi setup đã hoàn tất, đúng generation, kết nối tốt và không held/error mới gọi ready. Native chỉ thu startup một lần khi root còn tồn tại, child đang chạy đúng generation/protocol, ACTIVE, không pending maintenance và tray sẵn sàng. Quyết định/apply visibility dùng cùng main-thread queue; ready đọc lại native status tại lúc apply, controller bận thì giữ cửa sổ hiện. Setup mới, root lỗi/mất, journal held và lỗi health vẫn hiện; thao tác Mở thủ công thắng phản hồi ready đến muộn. Dialog thông báo trả false/lỗi thì không ghi marker hoặc thu cửa sổ. Không lưu mật khẩu, không auto-login.

Ba command mới, chỉ main capability local:

| Command | Input | Output |
|---|---|---|
| `desktop_runtime_status` | không | `{startup_enabled: boolean, startup_supported: boolean}` |
| `set_desktop_startup` | `{enabled: boolean}` | cùng DTO trên, chỉ sau explicit UI toggle |
| `desktop_background_ready` | không | void; không spawn/restart, chỉ cân nhắc visibility |

Startup mặc định OFF khi không có value. Windows adapter chỉ đọc/ghi **HKCU\Software\Microsoft\Windows\CurrentVersion\Run / CafeFin**, command cố định `"<current_exe>" --startup-v1`. Không nhận path/args từ renderer; kiểm executable local, tồn tại, không reparse, command tối đa260 UTF16 theo [Microsoft Run key contract](https://learn.microsoft.com/en-us/windows/win32/setupapi/run-and-runonce-registry-keys). So sánh raw REG_SZ chính xác và transaction compare/set/delete để không đè/xóa value bị thay đổi đồng thời; đọc lại trước khi báo thành công. Không tự repair khi app mở hoặc khi đọc status, không service/task/policy. Production chỉ trả `STARTUP_CONFLICT`, `STARTUP_COMMAND_INVALID`, `STARTUP_UNAVAILABLE`; không trả path/exception.

`startup_enabled` phản ánh registration của app, không ghi/chỉnh override StartupApproved hoặc policy Windows. Nếu cài/move sang executable path khác hoặc flag/version khác, value cũ được giữ và báo conflict; installer upgrade nên giữ install path. Disable chỉ xóa exact owned value, không xóa Run key hoặc entry khác.

**Interface cho04:** không có event/scheduler mới cần subscribe. Sidecar hiện có tiếp tục sống khi X/hide; periodic backend chạy độc lập trang Báo cáo/Bảng giá. Thoát thật, máy ngủ/tắt không chạy; catch-up/cooldown thuộc scheduler backend của04. Code này không cấu hình Telegram và không thực hiện send/fetch để nghiệm thu giả.

## Patch chung bắt buộc trước tích hợp/build

`desktop/build.rs` và `desktop/permissions/**` ngoài allowlist00. Đã chuẩn bị [runtime-acl-20261108.patch](runtime-acl-20261108.patch), không áp vào worktree lane. Điều phối/05 cần đăng ký ba command trong AppManifest và giữ các permission TOML được generator tạo. Capability trong commit này đã tham chiếu chúng; **source riêng chưa áp patch này chưa phải candidate có thể đóng gói**. `git apply --check docs/handoffs/foundation/runtime-acl-20261108.patch` PASS trên baseline này.

05 cần kiểm notices/lock sau khi enable Tauri `tray-icon` và thêm direct dependency winreg0.56.0 (`transactions`); winreg đã tồn tại trong product lock trước đây. Uninstaller cần chỉ cleanup own startup value nếu exact owned executable command còn khớp; không xóa toàn bộ Run key/value lạ. Đây là đề nghị cho packaging, không có thay đổi NSIS/config trong lane00.

## Kiểm chứng

Máy thực: Windows11 Pro10.0.26200 x64; Intel i5-14400F10 cores/16 logical, RAM31.8GiB; rustc1.99.1, Node24.21.0, npm11.19.0. Rust commands chạy trong MSVC x64 environment đã có, không thay policy hoặc exclusion. Đây không phải chứng minh MSRV1.90 hay Windows sạch.

- PASS: `cargo fmt --manifest-path desktop/Cargo.toml -- --check` và harness tương tự.
- PASS: `cargo check --manifest-path tests/desktop/Cargo.toml --locked --offline --all-targets -j 1` (shared library/harness, không phải Tauri binary).
- PASS: `cargo test --manifest-path tests/desktop/Cargo.toml --locked --offline -j 1 -- --skip reports_reparse_substitution_after_selection_is_refused`: **72 PASS**, 1 privileged test filtered, 2 ignored entries (synthetic subprocess entrypoint và Python wire interop opt-in). Có26 test mới:8 clean-exit (2 tiến trình tổng hợp thật),6 lifecycle,8 startup mock,1 normalize lỗi,3 correlated picker cancellation.
- FAIL môi trường ở lần full không skip: test cũ `reports_reparse_substitution_after_selection_is_refused` không tạo được symlink, Windows error1314 (thiếu privilege). Không đổi policy để vượt lỗi; ca này cần môi trường nghiệm thu có quyền thích hợp.
- PASS: `npm --prefix frontend run build` (TypeScript + Vite). Bundle chính1598.77KB/gzip507.13KB; có cảnh báo chunk lớn, không phải benchmark tốc độ.
- PASS (cwd `frontend`): `npx playwright test tests/desktop-runtime.spec.ts tests/maintenance-ui.spec.ts tests/foundation.spec.ts tests/session-race.spec.ts --workers=2`:40 cases,28.3s (9 runtime mới); native IPC bị mock, không nhận là GUI/registry nghiệm thu.
- BLOCKED/FAIL native `cargo check --manifest-path desktop/Cargo.toml --offline -j 1`: trên bản sao ngoài Git có ACL proposal áp thành công, `TAURI_CONFIG={"bundle":{"externalBin":[],"resources":[]}}` chỉ để kiểm source không mượn sidecar. Rust dừng E0463 tại cssparser_macros **trước khi typecheck Tauri binary**; CodeIntegrity events3077/3033 ngày08/11/2026 lúc11:05 xác nhận DLL không đạt enterprise signing policy. Không retry bằng đổi path, thay policy hoặc exclusion; không có native binary check PASS cho revision này. Build.rs/capability/schema mới cũng còn cần gate trên runner được phép.
- NOT RUN: hai frozen production-controller probes mới (clean Exit/picker/relaunch/fresh-login và callback sau child crash), native GUI/tray/frozen sidecar/NSIS, startup registry enable/disable thực, đăng nhập Windows lại/clean Windows/PC2. Không bật startup trên máy phát triển. Python wire interop opt-in chưa chạy trong đợt này. Không benchmark import lớn hoặc gửi Telegram thật.

Native check có patch ACL chỉ là kiểm nguồn; nếu dùng override loại externalBin/resources để không mượn artifact sidecar chưa cùng source thì phải ghi rõ. Không coi source check, browser mock hoặc build thành công là nghiệm thu bộ cài.

## Phạm vi file và migration

- `desktop/src/main.rs`, `native_shell.rs`, `native_lifecycle.rs`: tray, visibility, startup-ready, native exit fence.
- `desktop/src/native_controller.rs`, `native_exit.rs`, `native_draft.rs`: graceful explicit Exit, process/transport seam dùng chung và correlated picker settlement.
- `desktop/src/native_startup.rs`: currentUser opt-in adapter.
- `desktop/src/lib.rs`, desktop Cargo/lock/capability; native harness Cargo/lock, ba file test mới, picker cases trong maintenance và hai production-controller opt-in probes.
- `frontend/src/app/App.tsx`, `DesktopRuntimeSettings.tsx`, `frontend/src/shared/api.ts`; runtime browser tests/harness tổng hợp nhỏ.
- Handoff này và patch ACL riêng.

Không migration DB/API HTTP/BootSession/DesktopStatus DTO. Registry value opt-in và marker UX là cấu hình desktop riêng; không lưu user credentials.

Trước artifact cuối: điều phối tích hợp ACL patch, review code rồi chỉ định SHA;05 dựng lại source-matched. Nghiệm thu thực cần X/hide giữ nháp/scheduler, Open restore focus, duplicate shortcut/startup không duplicate sidecar, Exit cancel/clean/timeout, root mất/new setup/held hiển thị và enable/disable startup trên máy test phù hợp. Chưa gọi production-ready.
