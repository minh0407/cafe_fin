# Accounting harness delta sau f1bfc4f

Worktree: `C:\Users\NC\.codex\worktrees\cafe-fin-accounting-desktop-20261108\cafe_fin`; branch `codex/cafe-fin-accounting-desktop-20261108`. Parent commit: `f1bfc4f0fd12e8bd586e5ebdded6cf9e176b9913`. Commit delta được báo riêng trong câu trả lời cuối. Không merge/push/rebase hoặc sửa checkout điều phối. Product/runtime/dependency paths không đổi; không migration, endpoint hay interface production mới.

## Hai thay đổi

**Approved source:** UI nhận `CAFE_FIN_MINI_APPROVED_SOURCE_SHA` full40hex từ điều phối/caller. Chỉ khi biến vắng mặt mới dùng eab legacy; không lấy HEAD để tự hợp thức hóa approval. Commit phải tồn tại, là tổ tiên của harness HEAD và toàn bộ source/runtime paths phải sạch, bằng đúng tree của commit được chỉ định. Evidence tách approved SHA với harness HEAD. Bộ test dùng Git repo tổng hợp tạm kiểm cả candidate có product khác eab, source sai/thiếu/malformed/noncommit/nonancestor và staged/untracked changes. Xem [source-identity delta](desktop-mini-source-identity-delta.md) để có danh sách paths và lệnh UI/TypeScript. Đây là chế độ chọn nguồn cho source UI; không chứng minh binary/native cùng nguồn.

**Durable CSV checkpoint:** harness quan sát ngay sau tạo batch, trước mọi foreground probe. Khi public job counts và checkpoint cùng đạt ít nhất 500 nhưng chưa đủ source rows, gửi Cancel qua API hiện có; chờ worker thật chuyển `CANCELLED`. Chỉ sau đó mới shutdown và xác minh exit sạch. DB tổng hợp đã đóng được mở read-only/immutable để đối soát job checkpoint, staged/distinct source IDs, receipt `parse:N` và hash ordered source prefix. Restart phải giữ nguyên job/batch/book/file/hash, trạng thái `CANCELLED` và checkpoint dở; API Resume chạy lại cùng job, generation tăng đúng một, parse đủ tập. Cuối lượt kiểm receipt/prefix còn nguyên, không lặp source/target/lineage.

Không thêm barrier/monkeypatch vào parser, không inject frozen code hoặc sửa product. Đây là **cooperative cancel/restart/resume**, không phải hard crash, power loss hay `RECOVERABLE` recovery. Cancel có thể đi qua thêm chunk trước khi dừng; actual stopped checkpoint phải được đo, không mặc định 500. Nếu đã parse đủ tập thì giữ `WINDOW_MISSED`/BLOCKED, kể cả job có tên CANCELLED.

## Kết quả

| Gate | Kết quả |
| --- | --- |
| `python -m pytest tests/accounting/desktop_delivery -q` | **PASS — 63 tests, 8,51s**. Có 22 guard tests mới cho cancel ordering/races/restart/closed SQLite checks. Unit/scripted replies chỉ chứng minh guard; proof runtime riêng bên dưới. |
| `node --test tests/accounting/ui/mini-source-identity.test.cjs` | **PASS — 17 tests, 15,69s**, trong repo Git tổng hợp dưới Temp. |
| Strict TypeScript mini harness | **PASS**, lệnh chính xác ở delta UI. |
| UI explicit source `f1bfc4f0fd12e8bd586e5ebdded6cf9e176b9913` | **PASS — 24,8s**, final 999/excluded1/invalid0, ledger999/200, original SHA nguyên. Đây là source đã có trong lane, không phải designation candidate cuối/native. |
| CSV 1.000 dòng, immediate Cancel | **BLOCKED — CHECKPOINT_WINDOW_MISSED**. Thấy500, worker dừng khi đã parse1.000; functional import/export vẫn đúng. Không đổi kết quả này thành PASS. |
| CSV bounded 5.000 dòng, final harness | **PASS**. Thấy500, Cancel dừng tại1.500/5.000; sau restart vẫn1.500/CANCELLED. Resume cùng job, generation1→2, parse5.000; hash prefix/receipt được giữ. |
| Frozen sidecar/GUI native/build `.exe`/clean Windows | **NOT RUN trong delta lane** — chưa được giao artifact05; build/packaging thuộc điều phối/05. Không thay binary cũ vào proof mới. |
| 50k/500k/1m | **NOT RUN** — slot lớn chưa cấp. Gate frozen final candidate + valid CoordinatorSlot vẫn chặn trước khi tạo output/fixture. |

Ca bounded mới có ID riêng `csv-checkpoint-5000`, được điều phối cho phép để tạo cửa sổ checkpoint quan sát được: 5.000×8=40.000 data cells, 5 invalid amount, 5 cặp trùng/10 warning flags. Keep all có chủ ý; 4.995 dòng lần đầu / `624374.95` VND; sửa5 rồi đạt5.000 / `625024.95`. CSV export thật đối soát5.000 dòng/40.000 ô/tổng tiền/hash. Closed final DB có5.000 staged/distinct source,5.000 published/lineage/distinct targets và2 PUBLISHED attempts. Đây là ca chức năng bounded, không suy ra tốc độ cho50k–1m hoặc máy sạch.

## Lệnh và evidence

Từ worktree trên, Python dependency pinned lấy từ interpreter sẵn có nhưng child PYTHONPATH luôn trỏ vào backend của worktree mới:

```powershell
& 'C:\Users\NC\.codex\worktrees\cafe-fin-accounting\cafe_fin\.venv\Scripts\python.exe' -m pytest tests/accounting/desktop_delivery -q
& 'C:\Users\NC\.codex\worktrees\cafe-fin-accounting\cafe_fin\.venv\Scripts\python.exe' -m ruff check tests/accounting/desktop_delivery
& 'C:\Users\NC\.codex\worktrees\cafe-fin-accounting\cafe_fin\.venv\Scripts\python.exe' -m ruff format --check tests/accounting/desktop_delivery
node --test tests/accounting/ui/mini-source-identity.test.cjs
& 'C:\Users\NC\.codex\worktrees\cafe-fin-accounting\cafe_fin\.venv\Scripts\python.exe' -m tests.accounting.desktop_delivery.runner --mode source --workload csv-checkpoint-5000 --output-root C:/Users/NC/AppData/Local/Temp/cafe-fin-accounting-cancel-checkpoint-5000-20261108-002
```

Output root trên đã tồn tại; tái chạy cần tên mới. Không tự chạy50k/500k/1m. Frozen bounded chỉ chạy sau khi có candidate manifest/source SHA được duyệt bằng các flag hiện hữu; không bỏ gate identity vì ca nhỏ.

- Final bounded result: `C:\Users\NC\AppData\Local\Temp\cafe-fin-accounting-cancel-checkpoint-5000-20261108-002\result.json`, SHA256 `75b052b9722d0ebec72348b16c6b71ca2cdba8adb5479bb463acdf078bec850a`. Scope source, closed=true; receipt/prefix và counts ghi trong result. Derived CSV SHA256 `d36780b03f666cfd2d87099efc0f3273b88c9f3b90888a509f41c1b940e037d3`.
- Lượt5k đầu cũng PASS, dừng ở1.000 thay vì1.500: `C:\Users\NC\AppData\Local\Temp\cafe-fin-accounting-cancel-checkpoint-5000-20261108-001\result.json`; giữ evidence riêng, không thay thế final result.
- Ca1k bị missed: `C:\Users\NC\AppData\Local\Temp\cafe-fin-accounting-cancel-checkpoint-20261108-001\result.json`; giữ BLOCKED.
- UI result/ảnh/nguồn tổng hợp ngoài Git nằm ở đường dẫn đầy đủ trong delta UI; ảnh ledger đã mở kiểm. Sidecar UI dừng sạch, port1424 không còn listener.

## Files và giới hạn bàn giao

Delta chỉ nằm dưới `tests/accounting` và `docs/handoffs/accounting`: source-identity helper/declaration/17 tests và UI wiring; checkpoint controller/22 tests, runner/bulk fixture docstring, parse resume evidence, transport bounded expected-status handling; workload plan revision `.3` và handoff. Không commit DB/CSV/XLSM/ảnh/raw result/token. Không thay data root người dùng/CRM/Docker volume.

Plan JSON có7 workload, CLI có6 ID (XLSX native là checklist riêng). Nhánh 5k được cấp quyền riêng, không mở gate chung cho kích thước khác. Guard approval không tự chứng minh người chỉ định có thẩm quyền; frozen vẫn cần manifest thực từ điều phối/05. Mọi FAIL/BLOCKED cũ giữ nguyên. Chưa có nghiệm thu final-source native, installer hoặc Windows sạch; không gọi production-ready.
