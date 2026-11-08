# Bàn giao contracts — desktop 08/11/2026

## Nhánh và phạm vi

- Worktree mới: `C:\Users\NC\.codex\worktrees\cafe-fin-contracts-desktop\cafe_fin`.
- Branch: `codex/cafe-fin-contracts-desktop-20261108`.
- Baseline điều phối chỉ định: `eab8c96b851f039de515083189f4301cc09437c0`, đã xác minh chỉ khác tài liệu so với candidate `828d575b4a3c7b18ffafd8e2665a9d79b54ea403`.
- Commit sửa product: `682861deae950de5cb4ebfb8cab7666439fd2903`. Commit bộ QA/tài liệu nằm ngay sau trên cùng nhánh; xem SHA cuối trong bàn giao chat/Git log.
- Worktree/branch contracts cũ được giữ nguyên. Không push/merge, không build sidecar/Cargo/installer, không mở root vận hành, CRM cũ hoặc volume Docker.

Chỉ thay module contracts, tests/contracts và docs/handoffs/contracts. Không migration, dependency, shared core, renderer core, desktop lifecycle, packaging hoặc API/schema mới.

## Kết quả và sửa lỗi có bằng chứng

Chuẩn bị fixture mua/bán tổng hợp giàu nội dung, expected Decimal độc lập, mã/hash cố định; harness chạy backend thật qua stdin IPC + loopback HTTP có xác thực; bộ đối chiếu nội dung application trong frozen sidecar với Git chỉ đọc; checklist 15 ca GUI/native để chạy sau khi 00/05 giao artifact cuối.

QA source tái hiện hai lỗi trình bày tại adapter `contracts/rendering.py`: in mã cách cân thay cho nhãn tiếng Việt, và in số cân nguồn dấu chấm thập phân bên cạnh số lượng hợp đồng dấu phẩy. Commit `682861d` dịch đúng các mã đã biết (`direct`, `direct_net`, `gross_minus_tare`, `gross_tare`), giữ nguyên nội dung tự do khác, dùng formatter hiện hữu cho số cân nguồn. Không thay kg/giá/thuế, dữ liệu nguồn hoặc cấu trúc snapshot; bản xuất mới có nội dung/hash mới đúng với nhãn đã sửa. Phiên bản/file đã lưu không bị dựng lại.

## Kiểm tra

Máy source QA: Windows 11 Pro x64, build `26200` (`10.0.26200`), Intel Core i5-14400F, RAM `31.79 GiB`; Python khóa `3.12.16`, SQLite `3.53.1`. Đây là máy phát triển, không phải Windows sạch. Không dùng số giây test làm benchmark sản phẩm.

| Hạng mục | Kết quả |
|---|---|
| `.venv/Scripts/python.exe -m pytest tests/contracts -q` | **PASS: 169**, 51.17 s; một warning deprecation upstream FastAPI/Starlette TestClient |
| `.venv/Scripts/python.exe -m ruff check backend/cafe_fin/contracts tests/contracts` | **PASS** |
| `git diff --check` và kiểm phạm vi staged files | **PASS** trước commit |
| Tiến trình source thật, IPC/HTTP, 3 versions/5 files, replay, sửa nguồn/draft/template, restart | **PASS**, source commit `682861d`, backend sạch, hai tiến trình exit 0/stderr rỗng |
| PDF source A4/font/byte hash và xem từng trang | **PASS: cả 8 trang**, mua 2/bán 6; nhãn và số nguồn đã sửa đúng, không cắt/đè/mất chữ; còn paragraph continuation được ghi riêng |
| DOCX byte hash/metadata/A4 OOXML | **PASS**; visual **NOT RUN**, thiếu bundled soffice |
| Browser/TypeScript/frontend build | **NOT RUN** đợt này; không thay frontend |
| Frozen/installer build | **NOT RUN**, slot build của 05; chưa được giao artifact cuối |
| Source-matched frozen, native Save/Cancel/tray/Exit, WAN ngắt thật, máy sạch/PC2 | **NOT RUN**, chờ artifact và môi trường nghiệm thu cuối |

Evidence cuối ngoài Git:

`C:\Users\NC\AppData\Local\Temp\cafe-fin-contracts-desktop-source-20261108-efa2d9ee67-output\manifest.json`

Root tổng hợp dùng cùng prefix kết thúc `-data`. Manifest ghi source commit, hash inventory backend trước/sau, executable/import origin, PID, phiên bản, snapshot, file/hash/size, public-side-effect comparisons. Backend tree SHA-256: `a9223c2f593cc6eee4d2af319efadd7aafe8301ad5c2e7cdd88c3b650efcecbc`. Secret chỉ ở memory, không lưu password/session/access token hoặc stderr thô. Các attempt trước được ghi riêng với nguyên nhân, không dùng thay evidence cuối.

Harness tắt collector bằng guard có sẵn `CAFE_FIN_MARKET_NETWORK=0` trước boot rồi public settings. Nó chứng minh nghiệp vụ local với collector tắt; không phải chứng cứ ngắt WAN vật lý. Frozen mode chuẩn bị PATH System32-only nhưng vẫn không thay thế máy Windows sạch.

## Files và interface còn chờ

- Product/tests sửa lỗi: `backend/cafe_fin/contracts/rendering.py`, `tests/contracts/test_domain.py`.
- Fixture: `tests/contracts/desktop_fixtures.py`, `tests/contracts/test_desktop_fixtures.py`.
- Real-process harness: `tests/contracts/desktop_acceptance.py`, `tests/contracts/test_desktop_acceptance.py`; hướng dẫn `desktop-harness.md`.
- Frozen identity: `tests/contracts/artifact_identity.py`, `tests/contracts/test_artifact_identity.py`; giới hạn và CLI ở `desktop-artifact-identity.md`.
- Evidence/checklist: `desktop-render-qa.md`, `desktop-native-acceptance.md`, tài liệu bàn giao này.

Không đổi interface chung. **NATIVE-CONTRACT-SAVE-01** chuyển 00/05: hiện Blob/anchor download chưa có kết quả lưu/hủy/đích file rõ ràng trong facade native; đây là phát hiện source, chưa phải lỗi WebView2 đã tái hiện. Phải quan sát trên artifact cuối và chốt trải nghiệm lưu file. Không tự mở capability filesystem/shell tùy ý. Checklist cũng ghi cách ly Windows profile/currentUser: worktree mới không tự cách ly app_config_dir/root cũ.

PDF còn paragraph continuation qua trang, đọc được nhưng chưa nhóm trọn câu số tiền/hàng hóa; interface grouping/keep-together thuộc shared renderer, chỉ đề nghị có bằng chứng, không sửa ngoài allowlist.

Đối với DOCX, Documents skill `C:/Users/NC/.codex/plugins/cache/openai-primary-runtime/documents/26.1104.22356/skills/documents/SKILL.md:474` yêu cầu: “never use the user's installed desktop LibreOffice even if the bundled version fails.” Đã thử đúng helper/bundle, thiếu `soffice.exe`, giữ NOT RUN; không dùng Office/LibreOffice cài trên máy hoặc dịch vụ online để lấp gate. Đây là giới hạn công cụ QA, không phải dependency của chức năng xuất DOCX/PDF trong app.

Chưa gọi production-ready. Tiếp theo cần artifact được giữ lại từ SHA cuối sau lifecycle 00, receipt installer/app/sidecar của 05; đối chiếu binary/application-source rồi chạy harness frozen và checklist native với root/máy QA được cách ly. Bộ helper không tự build, tải, upload hoặc chạy binary cũ.
