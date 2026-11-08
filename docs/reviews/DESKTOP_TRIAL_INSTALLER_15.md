# Bộ cài Cafe Fin dùng thử — 08/11/2026

Đã tích hợp sáu lane desktop trên baseline `eab8c96`, review runtime/đóng gói và giữ bộ cài **0.1.0, Windows 11 x64**. Đây là bản để chủ máy cài thử, chưa nghiệm thu phát hành. Không thay source hoặc dữ liệu CRM cũ, không chuyển dữ liệu thật và không migration DB trong đợt này.

## Hành vi đã tích hợp

App chứa frontend và tự mở frozen sidecar qua IPC, dùng DB/tệp local; không yêu cầu người dùng chạy Docker, browser hoặc terminal. Có khay **Mở Cafe Fin / Thoát**. Nút X giữ cửa sổ/WebView và nháp trong bộ nhớ rồi thu về khay, giải thích ở lần đầu. Thoát có xác nhận, fence command và chờ sidecar dừng sạch; không thêm scheduler thứ hai.

Tùy chọn mở cùng Windows mặc định tắt, chỉ đăng ký cho currentUser sau thao tác của người dùng. Native kiểm đúng executable/command của app, không ghi đè hoặc xóa startup value lạ. Startup không auto-login. Khi root lỗi, setup chưa xong hoặc maintenance đang giữ, cửa sổ vẫn hiện. ACL cho ba command mới đã tích hợp; contract ở [API_CONTRACT](../API_CONTRACT.md).

Hợp đồng sửa nhãn nguồn kg và định dạng Decimal tiếng Việt trong DOCX/PDF. Các lane còn lại bổ sung fixture/harness nghiệm thu nguồn và frozen sidecar: farm/công ty/đầu vào/đầu ra/kho/giá, hợp đồng mua/bán, Excel độc lập, lịch báo cáo và Windows Credential Manager. Không thay quy tắc chặn tồn âm, tạo giao dịch từ sổ kế toán hoặc tự gửi Telegram thật.

## Bộ cài và nguồn chính xác

Nguồn build: `34593701477204cde2f5dc76181cb22a62e6eea2`. Tooling/doc nghiệm thu có thể được commit sau mốc này; không đưa thay đổi app mới vào bộ cài bằng cách đổi nhãn source.

| Tệp | Byte | SHA-256 |
|---|---:|---|
| `Cafe Fin_0.1.0_x64-setup.exe` | 253177367 | `0a992ffca654528616dbb61628c09cdb7cf99bc6fe0149838eb9cf039f973123` |
| `cafe-fin-sidecar-x86_64-pc-windows-msvc.exe` | 33475885 | `337a2e9ba21c7ad4c47bdcdebec5deb7c43aa26b54b2e0454869a442cd241f77` |

[CI build cuối](https://github.com/minh0407/cafe_fin/actions/runs/42457677174) **SUCCESS**, artifact `13608093184`. ZIP tải về đúng 292798135 byte, SHA-256 `4400108add099696392e7ef17d42a5b997e0457a1304c5e3bc42f6cebacfc16e`; CRC và toàn bộ receipt/checksum khớp. Proof NSIS xác nhận sidecar đóng trong installer đúng byte với sidecar và inventory đã giao; đây là `PAYLOAD_MATCH_ONLY`, không phải chạy installer.

File thử được chép và kiểm hash tại `C:\Users\NC\Downloads\CafeFin-0.1.0-3459370`, kèm hướng dẫn và proof. Kit đầy đủ ngoài Git tại `C:\Users\NC\.codex\artifacts\cafe-fin\20261108\trial-3459370.zip`, gồm nguồn, notices, source/relink materials, fixture tổng hợp và checklist PC2. Kit có 8641 tệp, ZIP 556495410 byte, SHA-256 `9f36272b9c1325d5a3266a540c8845f803ac92561626c7713e5bad71b8184483`; chỉ xác nhận tính toàn vẹn tệp, không phải clearance phát hành. Artifact GitHub lưu bảy ngày; bản local không phụ thuộc thời hạn đó.

## Bằng chứng kiểm tra

| Phạm vi | Kết quả |
|---|---|
| Backend tích hợp ban đầu, local | PASS 1667 tests; năm cảnh báo đã ghi trong log |
| Main browser, có API thật | PASS 109 cases; build frontend PASS, còn cảnh báo chunk lớn |
| [Source gates tại `0f72018`](https://github.com/minh0407/cafe_fin/actions/runs/42454419287) | Backend 1752 PASS / 1 skip; browser/features, frozen smoke, bốn production native controller và NSIS build PASS |
| Fixture uninstall trong lượt source trên | FAIL ở fixture thiếu NUL bị Windows chuẩn hóa; không giữ artifact của lượt này |
| Build lại `3459370` | PASS frozen smoke, bốn production controller, native harness, NSIS và bốn native cleanup tests; fixture dùng NtSetValueKey và assert raw readback trước kiểm macro |
| Gắn source vào sidecar | 79 module Python và entrypoint khớp; hai font khớp byte; chín tệp text đúng phép LF→CRLF, không đổi nội dung |
| Verifier EOL | PASS 30 tests; strict raw-byte FAIL được giữ, policy opt-in chỉ cho chín path text đã nêu, giữ raw digests/diffs và strict_status |
| Module frozen trên runner được phép | [SUCCESS](https://github.com/minh0407/cafe_fin/actions/runs/42459588030): records 22 checks + restart/shutdown; contracts mua/bán DOCX/PDF + snapshot/hash/restart; mini XLSM 1000 dòng, sửa lỗi rồi công bố 999/loại 1; checkpoint 5000; reporting 4 PASS / 107.93s |

Lượt build cuối chỉ kế thừa source gates sau khi kiểm API CI trước, đúng ancestor và diff allowlist: app, dependencies, recipe không đổi từ `0f72018`. Nó build lại, chạy lại frozen/controller/native/NSIS/cleanup/payload trước khi giữ artifact. Không che lượt CI thất bại trước đó.

Lượt module frozen dùng chính artifact `13608093184` đã kiểm digest, không build sidecar khác. Checkout chạy harness đúng source `3459370`, verifier opt-in dùng từ tooling `71c84db`. Checkpoint đã dừng hợp tác qua API tại 1000 dòng, mở tiến trình mới thấy đúng checkpoint và tiếp tục cùng batch đến 5000 dòng/5000 target riêng biệt; không phải bằng chứng crash hoặc mất điện. Reporting chạy timer thật 60 giây, catch-up không bịa snapshot và Credential Manager với khóa/token tổng hợp, không gửi Telegram. GUI và ngắt WAN thực vẫn NOT RUN.

Evidence artifact `13609222628`: sáu báo cáo JSON/JUnit, ZIP 43755 byte, SHA-256 `308c099abad3bc248af0ff4535f6e2f6029cfee7dec2d9d7665f787d10cbf77a`. Đã tải và kiểm digest/CRC; không đưa DB, workbook hoặc credential vào Git. Evidence được giao kèm riêng sau kit, không sửa checksum hoặc giả nhận kit cũ đã chứa kết quả mới.

Máy local: Windows 11 build 26200 x64, i5-14400F, 16 logical CPUs, RAM khoảng 32 GiB; Python 3.12.16 / SQLite 3.53.1. Phép thử records trên frozen sidecar tải về bị **BLOCKED trước bootstrap**: harness báo OSError, CodeIntegrity có events 3033/3077 cho đúng binary lúc 14:34:04. Chưa assertion nghiệp vụ nào chạy. Không retry bằng đổi tên/path, tắt bảo vệ hoặc thêm exclusion. Các probe frozen local còn lại NOT RUN; kiểm bổ sung chuyển sang Windows Actions với chính artifact và source checkout `3459370`.

## Giới hạn còn mở

- Authenticode trên installer: **NotSigned**. Chưa chạy installer/GUI hoặc cài WebView2 trên máy sạch.
- Windows sạch/PC2, chọn ổ thực, tray/focus/draft, startup đăng nhập lại, Save/Cancel và đích file tải thực, offline bằng ngắt mạng, upgrade/uninstall thực: **NOT RUN**.
- Native source/relink materials đã có; bằng chứng provenance lịch sử của wheel và recipient relink thực vẫn còn mở. Không coi manifest/source archive là hoàn tất gate giấy phép phân phối.
- Benchmark packaged 50k/500k/1m: **NOT RUN**; không hứa tốc độ. Kết quả source cũ không thay bằng chứng bản đóng gói.
- Telegram thật chưa cấu hình/gửi; giá nhân xô từ nguồn thật có thể BLOCKED. Không tạo giá thay thế, không dùng kết quả mock làm giá thị trường thật.

Bản Docker demo tại `http://127.0.0.1:1420` đã được mở lại bằng các image/container hiện có theo yêu cầu, giữ volume/tài khoản. Không reset hoặc đọc dữ liệu nghiệp vụ thật; không dừng/rebuild phiên demo để thử bộ cài.
