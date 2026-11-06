# Kiểm tra foundation increment 02

Ngày 06/11/2026. Source được tích hợp tới `7e03d2555f9551c90e5f2ba3f131a3af1b4d4980`; root merge tương ứng `e6c41ec2c56566b80b2e18227bdd5d1280fb1856`. Đây là increment source đã kiểm, chưa phải bản phát hành hoặc nghiệm thu bộ cài.

## Phạm vi đã kiểm

- API loopback có app-session, local auth, CORS/origin và error envelope; không Google OAuth.
- Module migration/router/job/startup registration có test, không mở generic endpoint để vượt validator/confirmation của module.
- Upload streaming tệp nguyên bản theo file ID/hash, giới hạn kích thước, idempotency, quyền và containment; không parse hoặc chạy nội dung tệp trong API này.
- Download xác minh tệp trước HTTP 200; export Word/PDF phục hồi từ đầu ra đã lưu khi bị ngắt, không đổi ngầm bản trước.
- CLI chỉ phát handshake ready sau startup thật; lỗi startup không bị báo thành công.
- React shell, grid MIT phân trang/virtualization và bản thử chứng từ. Phiên đăng nhập có generation fence, hủy request cũ và xóa cache/draft khi đổi actor.

## Lỗi đã được sửa trước tích hợp

Review độc lập tìm lỗi export retry sau khi đã ghi đầu ra từng định dạng, download tệp hỏng chỉ phát hiện sau HTTP 200, startup phát ready trước lifespan và phản hồi phiên cũ tác động phiên mới. Các bản sửa có tracked regression tests; reviewer chạy lại probe cũ trên commit đã sửa. Không còn P1/P2 đã biết trong phạm vi delta này.

## Kiểm chứng của điều phối

Máy Windows 11 Pro x64 10.0.26200, RAM khoảng 32 GiB, Python 3.12.16 / SQLite 3.53.1, Node 24.21.0 / npm 11.19.0. Môi trường từ lockfile. Dữ liệu kiểm thử là dữ liệu tổng hợp ngoài Git.

| Lệnh | Kết quả |
|---|---|
| `.venv\Scripts\python.exe -m pytest tests/core -q` | PASS 86 tests, 37,28 giây |
| `.venv\Scripts\python.exe -m ruff check backend/cafe_fin tests/core scripts` | PASS |
| `.venv\Scripts\python.exe -m compileall -q backend/cafe_fin scripts` | PASS |
| `npm run build` trong frontend | PASS; TypeScript và Vite, JS 932,79 KB / gzip 305,06 KB |
| `CAFE_FIN_REAL_API=1 npm test` trong frontend | PASS 10 tests, 9,9 giây |
| `git diff --check` | PASS |
| Workflow YAML và full-SHA action references | PASS kiểm cú pháp/cấu hình; chưa có kết quả CI tại thời điểm viết |

Bộ frontend test có một ca gọi sidecar Python thật: tạo tài khoản local, upload hơn 2 MiB, replay/conflict, hash bản gốc, Word/PDF và grid server page 500. Chỉ native invoke được stub; đây không phải nghiệm thu Tauri GUI. Các ca còn lại kiểm client/grid với mocks có ghi rõ. Các nhóm review độc lập có giao nhau với bộ test chính, không cộng số lượng thành tổng khác.

Một cảnh báo deprecation Starlette/httpx và một cảnh báo Vite chunk trên 500 KB còn tồn tại; không có lỗi build/test. Chưa tối ưu thời gian khởi động từ bộ cài thật.

## Giới hạn còn giữ

- Bốn module records/contracts/accounting/reporting chưa có nghiệp vụ hoàn chỉnh. Grid và renderer là proof nền tảng; chưa có import 500k/1m hoặc bộ công thức kế toán.
- Frozen sidecar đã build và smoke trên máy dev theo handoff foundation; native cargo check đạt. Rust release/NSIS trên máy này bị Windows Application Control chặn (4551), có CodeIntegrity logs. Không đổi policy hoặc đường dẫn để né chặn.
- Workflow Windows standard runner sẽ kiểm lại source và build candidate; không deploy, không phát hành, không upload artifact và không thay cho clean-Windows client acceptance.
- Chưa kiểm cài/update/uninstall, native picker/lifecycle hoặc offline WAN trên Windows client sạch. Không công bố production-ready.
- Distribution clearance còn mở cho native iconv trong lxml wheel: cần khép provenance và vật liệu source/relink phù hợp trước khi phân phối binary. Không coi thêm notice đơn thuần là hoàn tất.
- Chưa cấu hình hoặc gửi Zalo thật. Báo cáo sẽ chỉ phản ánh phần người dùng đã nhập.

Các điều kiện phát hành được giữ tại [ADR gate](../adr/20261106_COORDINATION_GATES.md). Thư mục tích hợp của người dùng: `C:\Users\NC\Desktop\UNILA{\cafe_fin`; CRM cũ giữ nguyên.
