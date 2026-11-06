# Frontend và desktop foundation candidate

## Phạm vi và interfaces

Frontend dùng React 19.3.1, TypeScript 5.9.3, Ant Design 6.7.0, TanStack React Query 5.106.1, Zustand 5.0.16. Dependency trực tiếp khóa đúng phiên bản trong `frontend/package.json`; toàn cây khóa bằng `frontend/package-lock.json`. Tauri 2.12.5/build 2.7.4/dialog 2.8.4/single-instance 2.5.5 khóa trong Cargo.toml/Cargo.lock. Không dùng Tauri 3 alpha.

`frontend/src/app/registry.tsx` export `FeatureModule`, `FeatureRoute`, `defineModules`. Module lane export manifest từ feature-owned index.ts; điều phối thêm import vào registry. Manifest có id/title/permission/routes. Registry chặn id/path trùng và route ngoài namespace. Stub bốn module chỉ hiển thị chưa triển khai, không được coi là nghiệm thu nghiệp vụ. Permission UI chỉ hỗ trợ hiển thị; backend vẫn kiểm quyền.

`frontend/src/shared/types.ts` định nghĩa error, page, user, health, boot, DecimalString, source issue, import counts và job states. Tiền/mã ở grid giữ string; không chuyển sang Number. `api.ts` gắn app session header và user Bearer token, timeout 15s, không retry mutation, không trả response/exception thô. Credentials chỉ ở Zustand memory, không localStorage/sessionStorage. Health poll kết nối local 5s, không dùng navigator.onLine. Lỗi mạng không báo lưu thành công; retry nghiệp vụ cần giữ request_key phía consumer.

## IPC v1

- Command renderer được cấp riêng cho main window: desktop_status, choose_data_root, start_backend(initialize), restart_backend. Không có command nhận arbitrary path từ renderer; choose_data_root mở folder dialog native. Không expose shell/fs/dialog plugin APIs cho JavaScript.
- Rust chọn executable cố định `cafe-fin-sidecar.exe` cạnh app. Debug có fallback binary `desktop/binaries/cafe-fin-sidecar-x86_64-pc-windows-msvc.exe`, sau đó `.venv/Scripts/python.exe -m cafe_fin` trong backend. Không có command tùy ý chạy chương trình khác.
- Rust tạo token random 32 byte, truyền JSON một dòng qua stdin: `{protocol_version:1,session_token,data_root,initialize,allowed_origin}`. Token không trong args/env/log/URL. Child Windows có CREATE_NO_WINDOW.
- Backend stdout trả `{protocol_version:1,status:'ready',api_base:'http://127.0.0.1:<port>/api/v1'}`. Rust kiểm scheme/host/port/path, protocol và health thật có X-App-Session trước khi trả BootSession cho renderer. Tổng deadline startup 20s.
- Lỗi startup backend dùng `{protocol_version:1,status:'error',api_base:'',code,message}` với code/message đã được backend che nội dung nhạy cảm; desktop đưa thông báo này lên wizard.
- Đóng app gửi stdin `{command:'shutdown'}`, chờ tối đa 8s rồi kill. Parent crash đóng stdin; backend chịu trách nhiệm xử lý EOF. Single-instance desktop kết hợp data-root lock backend. Restart bỏ user token và dùng initialize=false.
- Machine config chỉ chứa version1/data_root tại app_config_dir, ghi temp+sync+rename sau health thành công. Khi root cũ mất, không tự tạo root/DB rỗng. Wizard mặc định không initialize; người dùng cần chọn rõ checkbox khởi tạo mới.
- CSP giới hạn tài nguyên self và connect loopback 127.0.0.1:* để dùng port động. Không remote frames/object/form. Navigation plugin chỉ cho origin app hoặc dev127.0.0.1:1420. Capabilities không có remote origin. Không nới sang LAN/HTTPS bất kỳ.

## Grid spike và giấy phép

Chọn **react-data-grid 7.0.0-beta.64**, MIT, peers React ^19.2. Đây là phiên bản beta được pin và phải review trước nâng cấp. Glide npm stable6.0.3 có peer React16–18 nên không dùng ép peer install. Source/version: https://github.com/Comcast/react-data-grid ; tarball https://registry.npmjs.org/react-data-grid/-/react-data-grid-7.0.0-beta.64.tgz . LICENSE thực trong tarball đã đọc, gồm bản quyền Prometheus Research/Comcast và MIT grant. Không có enterprise key/trial/import-export thương mại.

Feature spike dùng: virtualized rows/columns, edit bằng keyboard/double click, frozen source column, resize, source error cell tooltip, copy vùng Shift+click, paste TSV giới hạn500 ô/100.000 ký tự. Dữ liệu tải server page500, frontend chỉ giữ trang hiện tại; query `gcTime:0` loại trang nguồn cũ khi không active, không tích lũy page history. Pager bị khóa khi có draft chưa bỏ. Backend sample có Unicode/ngày/mã đầu0/số lớn/formula text. Grid không parse workbook, không VBA/external links, không tính formula, không dùng kết quả cache để giả đã tính. Lane accounting phải triển khai validate/formulas/import thật qua interfaces đã freeze.

UI gọi GET /api/v1/spikes/grid?page=&page_size=500. Page total1m trong test chỉ kiểm paging/virtualization; không phải benchmark file1m hoặc full import. Draft chưa có persistence; nhãn UI nói rõ. Lỗi nguồn không tự biến mất sau edit; backend cần validate lại. Undo/redo, kéo điền, full workbook fidelity và engine công thức thuộc lane kế toán, chưa nghiệm thu ở spike này.

Notices: chạy `npm run notices` trong frontend tạo `desktop/notices/frontend.txt` từ license files/metadata của 146 package đã khóa, kể cả dev tools để bảo thủ. Tauri bundle resources chứa notices/*. Phần giấy phép Python/native/fonts được báo trong handoff renderer của foundation.

## Word/PDF UI spike

Nút tại trang Nền tảng gọi POST /api/v1/spikes/documents `{request_key}`; hiển thị hash snapshot, từng DOCX/PDF độc lập, lỗi từng định dạng. Download GET /api/v1/files/{file_id}/content dùng authenticated fetch Blob; không token trong link. Đây là mẫu kỹ thuật tổng hợp, không tạo domain hợp đồng. Việc mở/in tệp thực tế và kiểm rendering/Office-free theo báo cáo renderer/native chung.

## Lệnh dev/build Windows

1. Python backend venv/sidecar theo handoff core, cài Node dev và Rust stable MSVC với Windows SDK cho máy build.
2. `cd frontend; npm ci; npm run typecheck; npm run build; npm run notices`.
3. `npm test` chạy Chromium headless. Lần đầu `npx playwright install chromium`.
4. `cargo fmt -- --check` trong desktop; `cargo check --locked` sau khi đủ SDK và binary externalBin.
5. Từ desktop chạy `../frontend/node_modules/.bin/tauri.cmd dev` hoặc `build`; binary đóng gói phải nằm tại desktop/binaries/cafe-fin-sidecar-x86_64-pc-windows-msvc.exe. Installer NSIS currentUser, WebView2 offlineInstaller. Hook npm chạy từ app root nên prefix là `frontend`. Native release build đang bị host Application Control chặn, chưa có installer để chứng minh phân phối offline.

## Bằng chứng hiện tại

Máy Windows11Pro10.0.26200, RAM34.138.931.200 byte, Node24.21.0/npm11.19.0, Rust1.99.1. Không phải Windows sạch.

- PASS `npm run typecheck`.
- PASS `npm run build` (Vite7.3.7), chạy lại sau DocumentSpike/actual source-column mapping: bundle930.91KB/gzip304.61KB; cảnh báo chunk>500KB là hạn chế tối ưu khởi động, không bỏ qua lỗi compile.
- PASS `npm audit` sau nâng Vite7.3.7: zero vulnerabilities tại thời điểm chạy; `npm audit --omit=dev` zero.
- PASS `cargo fmt` (rustfmt đã tải qua rustup).
- PASS `npm test` lần đầu 3tests/23.3s trên Chromium158.0.8127.18: grid React19 edit/code/amount string, DOM<40rows với page500, error Tổng hợp!D2, server page2, token không persist; wizard explicit initialize; backend loss hiển thị sau health fail.
- PASS `npm test` sau bổ sung clipboard và page-cache bound: 4tests/8.2s; paste4cells giữ mã đầu0/Unicode, từ chối501ô, frontend vẫn chỉ giữ500rows. Native bridge và API trong browser test là mock có ghi rõ trong test; kiểm hành vi React/grid/client, không chứng minh native.
- PASS native `cargo check --locked` với BuildTools18/SDK10.0.26100.0. FAIL/BLOCKED release NSIS build bởi Windows Application Control4551, có CodeIntegrity3033/3077 xác nhận. Không bypass hoặc lặp lại release build khi policy chưa thay đổi. Xem [native-build-evidence.md](native-build-evidence.md) để có lệnh/path/log receipt chính xác.
- PASS real sidecar API browser integration1test/5.1s: CORS/auth thật, tạo/download Word/PDF thật, hash khớp metadata, grid500page/error coordinate và logout thật. Chỉ native invoke bridge stub. Chạy opt-in `CAFE_FIN_REAL_API=1 npx playwright test tests/real-api.spec.ts` sau sync Python venv.
- PASS final `CAFE_FIN_REAL_API=1 npm test`: 5tests/8.9s (4frontend behavior +1real-sidecar integration). `npm run build` và `cargo fmt -- --check` final PASS cùng lượt. Source frontend/desktop được giữ ổn định sau lượt này để root commit.
- PASS kiểm lại backend freeze `976475c1df7b78eb7e7e9a32105e9f1d79945994`: `CAFE_FIN_REAL_API=1 npm test`, 5tests/8.6s. Actual workbook source_file_id/source_sha256/projection_note được kiểm, tooltip D2 dùng issue EXACT_TEXT_AMOUNT từ response thật; không còn phụ thuộc câu thông báo mẫu cũ. User DTO bổ sung version không phá frontend. Build vẫn930.91KB/gzip304.61KB. UI/Rust không thay ngoài cập nhật test integration cho workbook thật.
- FAIL/BLOCKED xác nhận final packaging input đúng1lần theo chỉ thị điều phối lúc20:00ICT: sidecar SHA256 `EF636343329730D3B0CC6A73F9F6C72C55D0121FB149A75B0EC1BAAC324F357E`, standard NSIS command exit1 cùng AppControl4551 trên release serde_derive DLL. New CodeIntegrity3033/3077 xác nhận20:00:13ICT. Hash input không đổi trước/sau; không có installer, không install/launch, không retry thêm. Receipt đầy đủ trong native-build-evidence.md.
- NOT RUN clean-Windows install, offline WAN/native download, DOCX/PDF open/print từ UI. Cần test trên môi trường đích và ghi kết quả thật trước foundation READY.

Không push, merge hoặc tag READY. Root tổng hợp commit và cập nhật gate từ các bằng chứng native còn lại.
