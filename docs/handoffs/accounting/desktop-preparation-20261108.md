# Kế toán — bàn giao chuẩn bị desktop 08/11/2026

## Nguồn và phạm vi

- Worktree: `C:\Users\NC\.codex\worktrees\cafe-fin-accounting-desktop-20261108\cafe_fin`.
- Branch: `codex/cafe-fin-accounting-desktop-20261108`.
- Baseline được giao: `eab8c96b851f039de515083189f4301cc09437c0`, trên candidate nghiệp vụ `828d575b4a3c7b18ffafd8e2665a9d79b54ea403`. Hai tag READY được giữ nguyên. Diff code giữa hai mốc bằng 0.
- Commit bàn giao được ghi trong câu trả lời cuối của chat; các lần chạy dưới đây thực hiện khi HEAD còn là baseline, harness mới được ghi hash riêng trong result. Không dùng source của worktree kế toán cũ. Interpreter ở `.venv` cũ chỉ cung cấp dependency; subprocess luôn chọn `backend` trong worktree mới.
- Chỉ thêm `tests/accounting/desktop_delivery/**`, hai file `tests/accounting/ui/desktop-mini.*` và ba handoff accounting. Không sửa product/shared/API/schema/dependency/packaging/CI; không migration. Worktree cũ giữ nguyên. Không push/merge/rebase.

## Phần đã chuẩn bị

Fixture tổng hợp mini 1.000 dòng có CSV/XLSX/XLSM thật, sheet thứ hai/header3/start4, leading-zero code, tiền exact, 17 dòng lỗi và 10 cặp trùng. Các file nguồn/repair/issue/manifest có hash, sinh ngoài Git. XLSM chứa **opaque inert vbaProject sentinel, không phải VBA hợp lệ**; việc giữ nguyên hash không chứng minh tương thích hay thực thi VBA thật. Formula ngoài/không hỗ trợ được giữ là lỗi; không chạy nội dung import.

Controller dùng private stdio bootstrap và HTTP loopback thật của sidecar; credential/token chỉ trong bộ nhớ. Có hai mode `source` và `frozen-sidecar`, không mở GUI. Frozen cần manifest ngoài repo với source SHA được điều phối chỉ định, path/bytes/SHA của executable và actual process-image check; từ chối Python fallback. Đây là ràng buộc khai báo nguồn của điều phối cộng digest, không phải compiled-source attestation độc lập. Không thử tìm binary cũ hay tự build để thay artifact05.

Controller tạo data root tổng hợp mới, không ghi đè evidence cũ, chặn output trong mọi Git worktree, dùng page/patch tối đa 200 dòng. Mini kiểm mapping/validation/decision, giữ lỗi khi import valid-only, restart sau validation, exact retry, hai lần publication, tổng tiền, original download và lineage sau shutdown sạch. CSV xuất được đọc stream để kiểm header/width/count/cells/Decimal income/raw SHA; không nạp cả dataset.

Đã chuẩn bị CSV 50k/500k/1m nhưng **chưa sinh/chạy các file tải lớn**. CLI từ chối large source, thiếu artifact identity hoặc thiếu/sai/hết hạn slot trước khi tạo output/fixture. Bộ đo có thời gian pha/status, HTTP p50/p95/max/count, PID+creation FILETIME, sampled RSS/private/OS peak, CPU seconds/delta từng process và DB/WAL/SHM/app-root/free-volume. Không cộng RSS thành RAM vật lý duy nhất. Kiến trúc từng process, OS-temp, native GUI/JS heap và mức nhiễu host chưa kiểm soát được ghi rõ. Các yêu cầu đo rộng hơn còn là kế hoạch, không suy ra từ chữ PASS.

## Kết quả đã chạy

| Gate | Kết quả và phạm vi |
| --- | --- |
| `python -m pytest tests/accounting/desktop_delivery -q` | **PASS — 41 tests, 8,66s**: parser/import thật với SQLite hiện hành, immutable source, exact money, artifact/slot/output guards, checkpoint và PID reuse. Không dùng kết quả này cho PostgreSQL cũ. |
| Ruff check + format check trên `tests/accounting/desktop_delivery` | **PASS**. |
| Strict TypeScript và source mini UI | **PASS — 1 case, 22,8s / tổng 24,6s**. App/login/AccountingPage source thật, source backend/SQLite/files/jobs thật; chỉ bootstrap native được adapter test thay thế. Sheet/header, edit, TSV copy/paste, issue coordinates, duplicate keep/skip, accepted ACK loss/cancel/replay, UI resume, repair và ledger 999/200 đã quan sát. |
| Source controller rich XLSM mini | **PASS**: 982 dòng / `103121.39` trước repair; thêm 17 đạt 999 / `104904.89`; 1 excluded. Derived export 999 dòng / 7.992 ô; 999 lineage/distinct targets, 2 PUBLISHED attempts; process đóng sạch, bản gốc nguyên hash. |
| Source CSV mini qua nhánh future-volume | **BLOCKED — CHECKPOINT_WINDOW_MISSED**; functional acceptance PASS: 999 rồi 1.000 dòng, tổng cuối `105004.99`, export 1.000 dòng / 8.000 ô, lineage/2 attempts đúng. Đã thấy 500 parsed trước exit nhưng sau restart job đã COMPLETED/1.000; không công nhận durable mid-parse resume. 3 foreground probe samples chỉ là quan sát API, không phải benchmark ổn định. |
| Frozen sidecar / packaged GUI / native clipboard / clean Windows | **NOT RUN** — chưa được cung cấp artifact05 đã duyệt. |
| 50k / 500k / 1m | **NOT RUN** — chờ candidate cuối, artifact cùng nguồn và slot tải rõ của điều phối. |
| Build frontend/installer/Cargo, toàn bộ repository suite | **NOT RUN** trong increment tests/docs này; không có product/dependency change và không chiếm slot packaging. |

Lệnh đã dùng từ worktree mới (Python 3.12/dependency pinned có sẵn):

```powershell
& 'C:\Users\NC\.codex\worktrees\cafe-fin-accounting\cafe_fin\.venv\Scripts\python.exe' -m pytest tests/accounting/desktop_delivery -q
& 'C:\Users\NC\.codex\worktrees\cafe-fin-accounting\cafe_fin\.venv\Scripts\python.exe' -m ruff check tests/accounting/desktop_delivery
& 'C:\Users\NC\.codex\worktrees\cafe-fin-accounting\cafe_fin\.venv\Scripts\python.exe' -m ruff format --check tests/accounting/desktop_delivery
& 'C:\Users\NC\.codex\worktrees\cafe-fin-accounting\cafe_fin\.venv\Scripts\python.exe' -m tests.accounting.desktop_delivery.runner --mode source --output-root C:/Users/NC/AppData/Local/Temp/cafe-fin-accounting-source-controller-eab8c96-20261108-003
& 'C:\Users\NC\.codex\worktrees\cafe-fin-accounting\cafe_fin\.venv\Scripts\python.exe' -m tests.accounting.desktop_delivery.runner --mode source --workload csv-mini-1000 --output-root C:/Users/NC/AppData/Local/Temp/cafe-fin-accounting-csv-controller-eab8c96-20261108-002
```

Hai root đã tồn tại nên lệnh tái chạy phải chọn tên mới. Giữ evidence FAIL/BLOCKED; không overwrite. Lệnh UI/TypeScript và ảnh quan sát nằm trong [desktop-mini-ui.md](desktop-mini-ui.md).

Evidence ngoài Git:

- Rich controller: `C:\Users\NC\AppData\Local\Temp\cafe-fin-accounting-source-controller-eab8c96-20261108-003\result.json`, SHA256 `3395b6446fa6bdef2d1e6a7b40999669954c8915a5f2003c679e876fd16d0a9a`.
- CSV controller: `C:\Users\NC\AppData\Local\Temp\cafe-fin-accounting-csv-controller-eab8c96-20261108-002\result.json`, SHA256 `04a8697b6c99131a0c3b4ff527d57d2cba8bd02265a4d22c33dd0b4ebfe58fc6`.
- Source UI cuối: `C:\Users\NC\AppData\Local\Temp\cafe-fin-desktop-mini-ui-repro-61f8dd0440bb4e339a97d9f4f0a80518\desktop-mini-source-deskto-9d5a4-pair-and-immutable-original\desktop-mini-evidence.json`. Screenshot đã mở kiểm; owned sidecars dừng và không còn listener1424.

## Giới hạn và bước nhận artifact

Source UI quan sát pending=0 khi cancel, không chứng minh visibility ở pending khác 0, process crash hoặc power loss. Controller rich restart sau validation đã hoàn tất, không chứng minh mid-parse. CSV checkpoint bắt buộc bị missed được giữ BLOCKED. Pending export window, hard crash, disk-full, genuine executable-VBA/no-execution OS audit chưa chạy. Browser không thấy request ngoài loopback; backend OS network không được đo toàn diện. Không biến các giới hạn này thành số 0 hay PASS native.

Khi điều phối cung cấp artifact05/source SHA cuối, chạy frozen mini với manifest đã duyệt theo [desktop-packaged-workloads.md](desktop-packaged-workloads.md), rồi nghiệm thu GUI native riêng theo checklist UI. Large chỉ chạy một workload trong slot thực, không trùng build Cargo/installer hoặc benchmark lớn khác. Nếu AppControl/Defender chặn, giữ BLOCKED; không đổi policy, exclusion, tên/path để né chặn. Không tự nhận production-ready.

Ảnh hưởng interface: **không đổi API production**. Manifest candidate/slot là contract runner-local được đề xuất cho điều phối/05; không âm thầm sửa packaging/shared handshake hay thêm endpoint lấy token. `workloads.json` là kế hoạch có hash-bound vào result, không phải engine tự thi hành mọi assertion. Chưa có artifact cuối để nghiệm thu, nên phần desktop delivery còn mở ở các gate nêu trên.
