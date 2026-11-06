# Foundation candidate để Điều phối review

Repo: `https://github.com/minh0407/cafe_fin.git`. Baseline duy nhất:
`cafe-fin-spec-v1` → `5925d43964e99033efe3146ae4d84902dd284df3`.

Worktree riêng: `C:\Users\NC\.codex\worktrees\cafe-fin-foundation-build\cafe_fin`.
Branch: `codex/cafe-fin-foundation-20261106-build`. Không sửa checkout điều phối,
không push/merge, không tạo tag READY. Candidate có code dùng được và bằng chứng
thực; **native release acceptance còn các mục chưa đạt** ở phần cuối tài liệu này.

Code candidate đã đóng: `7e03d2555f9551c90e5f2ba3f131a3af1b4d4980`.
Handoff/inventory/ADR commit sau chỉ bổ sung bằng chứng, không đổi code.
Điều phối sở hữu việc tách development/API baseline và release acceptance theo
`docs/adr/20261106_COORDINATION_GATES.md` (được merge từ checkout điều phối);
tài liệu này không tự mở lane hoặc tự quyết định tag.

## Kết quả từ source tracked sạch

Git archive của đúng `7e03d25` được giải nén vào
`C:\Users\NC\AppData\Local\Temp\cafe-fin-close-7e03d25-ea1050c9249248f7bb7e9e10909dede4\source`.
Tạo `.venv` mới bằng `uv sync --locked`, `npm ci` mới trong snapshot; không dùng
file untracked hoặc editable import từ worktree triển khai.

| Kiểm tra | Kết quả thực |
| --- | --- |
| Toàn core trong archive | PASS86 tests /40.30s |
| Ruff + Python compileall | PASS |
| npm ci/audit | PASS,0 vulnerabilities tại thời điểm chạy |
| TypeScript và Vite build | PASS,932.79KB JS/gzip305.06KB |
| Browser suite với real API | PASS10 tests /9.7s, Chromium158 |
| Repro API độc lập | File409 trước headers; export receipt503/retry; os._exit86 sau DOCX/restart; startup lỗi không ready đều PASS |
| Session generation | 12 late-response cases và cache/draft actor-change UI PASS trong browser suite |
| Frozen sidecar source3fd4aa0 | Build/smoke PASS trên host Windows phát triển; embeddedSQLite3.53.1; rawupload2,097,421bytes/hash/replay sau restart PASS |
| Native Rust | cargo check PASS; NSIS release BLOCKED4551, không có installer/GUI acceptance |

Backend và dependency tree của `7e03d25` giống đúng source
`3fd4aa0edb91189f2f5a81f7c0ef3f658daf8fb3` đã đóng gói, kiểm bằng git diff.
Executable local ignored `desktop/binaries/cafe-fin-sidecar-x86_64-pc-windows-msvc.exe`:
33,017,856bytes, SHA256
`b9377e8a173a92eac8827a4a73bdf503d185cdb8cc40151f498babfe98384ecb`.
Binary không được commit/publish. Native inventory mới có51 DLL/PYD với hash.
Details/codefreeze/proof paths và native license source chain ở sidecar-build.md.

Cảnh báo còn tồn tại: một Starlette/httpx TestClient deprecation warning;
Vite chunk>500KB. Không tắt warning để báo pass hoặc suy tốc độ app từ số test.
Số test là tổng hợp rủi ro; không thay bằng chứng Windows sạch, full import hoặc
domain nghiệp vụ chưa triển khai.

## Phần đã triển khai

```text
backend/cafe_fin/
  __main__.py           IPC UTF-8, socket loopback động, lifecycle sidecar
  registry.py           Điểm đăng ký manifest do Điều phối sở hữu
  core/
    amounts.py time.py  Decimal strings, scaled int64, tổng lớn, ngày Việt Nam
    db.py modules.py    WAL, reader chỉ đọc, writer bounded, migrations/checksum
    auth.py audit.py    Local Argon2, quyền/version, session memory, audit
    jobs.py             Durable states, generation fencing, receipt/checkpoint
    imports.py          Immutable manifest/attempt, claims, pending, atomic publish
    contracts.py        DTO và read bridge, coverage/cutoff, parties đa vai trò
    stock_guard.py      Prefix tồn theo ngày/order_key/id, rollback khi tồn âm
    storage.py backup.py Root local/lock, immutable files, snapshot/verify/restore/move
    renderers.py assets/ DOCX/PDF cùng snapshot, font/notice
    api.py http_types.py Endpoint auth/security/typed schema/error/paging
    example.py          Module ghi chú tổng hợp chứng minh registry/CRUD/version
    workbook_spike.py   Workbook tổng hợp thật, read-only, page500
frontend/src/
  app/                  Wizard, local login, shell, registry và module stubs
  shared/               Memory API session, grid, document spike, shared types
desktop/                Tauri 2, commands/CSP, sidecar build, lockfiles/notices
tests/core/             DB/thread/process/filesystem/API/regression tests tổng hợp
docs/adr/               Quyết định library/spike và gate giấy phép
```

Không triển khai domain records/accounting/contracts/reporting production.
Các màn stub nói rõ chưa triển khai. Không QR, theme toggle, ca trưởng, phê
duyệt nhiều người, Google OAuth, Zalo sender giả hoặc migration CRM cũ.

## Public interfaces cho các lane

- [Core và writer](01-core.md), [auth/jobs](02-auth-jobs.md),
  [fix review/migrations](core-review.md), [actor/lease/REPLACE fencing](auth-job-fencing.md).
- [Import attempts, DTO bridges, stock guard](import-contracts.md).
- [Storage/backup/renderers](storage-render.md).
- [API/IPC/workbook proof](03-api-spikes.md), [OpenAPI candidate](openapi-v1.json).
- [Download/export/startup recovery](api-recovery.md), [original file transfer](file-transfer.md),
  [frontend session fencing](session-fencing.md).
- [Module job/startup registration](module-registration.md).
- [Frontend và desktop](frontend-desktop.md), [native evidence](native-build-evidence.md),
  [sidecar build/smoke/giấy phép native](sidecar-build.md).
- [ADR library và giới hạn](../../adr/0001-foundation-runtime-and-spikes.md).

Lane export `ModuleManifest` từ thư mục mình, migrations có namespace và checksum,
router, `job_handlers` và hook phục hồi `on_startup` khi cần. Điều phối thêm
manifest ở `backend/cafe_fin/registry.py` và feature ở frontend registry. Không
cần sửa core để thêm migration/job/hook. Handler/hook là source tin cậy đã đăng
ký; không autodiscover/nạp mã từ data root hoặc workbook.

Bridge DTO/Protocol đã có tên/field/meaning ở core.contracts; concrete provider
thuộc public module của records/accounting, không private ORM. Coordinator bind
provider/export module khi tích hợp. `IdempotencyService` của thiết kế được hiện
thực tích hợp trong WriteCoordinator.execute để receipt và business mutation
không bị tách transaction; BusinessTime tương ứng helpers core.time.

Reader là context chỉ đọc. Writer nhận callback SQLAlchemy Connection, sở hữu
transaction, rollback và request receipt. Mutation API phải đưa
`authorize=lambda conn: auth.authorize(conn, principal, permission)` vào transaction,
kể cả khi trả idempotent receipt. Không giữ writer lúc parse/render/network.
Background job nhận immutable input và generation lease; dùng commit_chunk cho
effect+receipt+checkpoint, finalize cho công bố+COMPLETED cùng transaction.

Module phải có typed endpoint của mình để validate/quyết định/confirm trước khi
gọi JobService. Generic HTTP submit/cancel/resume chỉ dành foundation.sample;
không cho `jobs.write` phát arbitrary module payload hoặc bỏ qua confirm/quyền.
Status module job còn kiểm quyền `<module>.read`. API core không thay validator,
snapshot/COW staging hoặc transition machine nghiệp vụ của accounting.

Import pending chỉ hiện khi attempt PUBLISHED; lane phải dùng visibility_predicate
cho list/detail/CRUD/count/sum/export/report. Chống retry theo job/source-row khác
với người dùng cố ý nhập nội dung giống trong một job mới. Stock guard kiểm mọi
prefix của scope cũ/mới trong cùng mutation transaction, gồm backdate/edit/delete.

## Schema candidate

Namespace v1: core, core_auth, core_jobs, core_files, core_imports, example.
Registry từ chối schema mới hơn/thiếu migration/đổi checksum; sort version trong
namespace và giữ dependency order. Schema/checksum core_jobs đã thay đổi trong
candidate trước baseline để thêm generation: dùng data root tổng hợp mới cho
candidate cũ, không chỉnh checksum DB hoặc tự nâng dữ liệu vận hành. Sau READY,
mọi thay đổi phải append migration, giữ immutable historical DDL/signatures.

## Dev và build Windows

Máy build dùng Python 3.12 có SQLite đã sửa WAL, Node và Rust/MSVC/Windows SDK.
Máy người dùng mục tiêu không cần các công cụ này. Runtime đã thử: Python
3.12.16/PBS20261026/SQLite3.53.1, Node24.21.0, Rust1.99.1, SDK10.0.26100.0.

```powershell
uv sync --locked --python <Python-3.12.16-path>
.\.venv\Scripts\python.exe -m pytest tests/core -q
.\.venv\Scripts\ruff.exe check backend tests/core scripts/export_openapi.py
npm --prefix frontend ci
npm --prefix frontend run typecheck
npm --prefix frontend run build
$env:CAFE_FIN_REAL_API='1'
npm --prefix frontend test
pwsh -File desktop/scripts/build-sidecar.ps1
# Trong desktop, sau khi nạp environment MSVC:
..\frontend\node_modules\.bin\tauri.cmd dev
..\frontend\node_modules\.bin\tauri.cmd build --bundles nsis --ci
```

`frontend` cần `npx playwright install chromium` lần đầu. Native helper/SDK path
và các lệnh chạy thật được ghi trong native evidence; không phụ thuộc helper
trong checkout điều phối để source app hoạt động. Release hiện bị host AppControl
chặn. Không lặp đổi tên/output/repack để né policy.

Opt-in frozen test có thể chạy sau khi binary được build:

```powershell
$env:CAFE_FIN_TEST_SIDECAR=(Resolve-Path desktop/binaries/cafe-fin-sidecar-x86_64-pc-windows-msvc.exe).Path
.\.venv\Scripts\python.exe -m pytest tests/core/test_api_sidecar.py::test_sidecar_real_loopback_unicode_second_instance_and_restart -q
```

Helper test dùng Windows/System32-only PATH và bỏ Python development env cho
child. Đây là kiểm executable trên máy phát triển, không phải máy Windows sạch.

## Phần còn lại để Điều phối phân gate và nghiệm thu

Bảng này phân biệt code/interface, native release và phần lane sau. Không coi
NOT RUN là PASS; không bắt module production phải tồn tại trong foundation.
Theo ADR điều phối, baseline phát triển freeze code/API đã review và tracked test
pass; installer/clean-client là release gate, không phải điều kiện bắt module
chờ môi trường release mới viết code. Chỉ Điều phối quyết định và tạo tag mở lane.
Native clean acceptance vẫn phải có trước
phát hành sản phẩm và không được suy từ cargo check/browser/frozen host smoke.

| Gate | Kết quả và điều kiện còn thiếu |
| --- | --- |
| Native compile | PASS cargo check; release/NSIS BLOCKED4551 trên generated Rust DLL/build script, có CodeIntegrity3033/3077 |
| Installer và GUI thực | Chưa tạo installer; chưa thử shortcut, native folder dialog/GUI lifecycle hoặc clean-Windows không dev dependencies |
| DOCX visual/mở/in | Chưa đạt: bundled LibreOffice chưa có; không thay bằng cấu trúc XML/reopen |
| PDF local | Render/extract/hash/visual và frozen generation PASS; mở/in từ GUI trên máy sạch chưa thử |
| License native | Nguồn/notice exact đã thu thập; iconv trong lxml wheel chưa đủ provenance/source/relink evidence để chốt phân phối |
| Data-root move | Core snapshot/restore/move candidate giữ links/hash và nguồn cũ PASS; chưa ghép/kiểm native controller quiesce → đổi config → relaunch end-to-end |
| Storage failures | ENOSPC được inject để kiểm rollback, không phải lấp đầy ổ vật lý; DACL deny/ổ tháo thật/mất điện vật lý chưa thử |
| WAN offline | Core không gọi WAN và không dùng navigator.onLine; chưa cắt WAN vật lý để nghiệm thu GUI/frozen install |
| Module nghiệp vụ | Chưa triển khai theo ownership; công thức production/undo import/500k/1m benchmark thuộc lane accounting, không suy từ spike10k |

Documents skill bắt buộc: "never use the user's installed desktop LibreOffice
even if the bundled version fails". Nguồn đã đọc:
[Documents SKILL.md](C:/Users/NC/.codex/plugins/cache/openai-primary-runtime/documents/26.1104.11149/skills/documents/SKILL.md).
QA thực đã gọi renderer và nhận FileNotFoundError thiếu soffice; vì thế DOCX
visual giữ NOT RUN, không giao một DOCX mẫu như bản đã nghiệm thu layout.

Các file dữ liệu/proof/binaries ở Temp hoặc ignored; Git chỉ chứa source,
fixtures/generator tổng hợp, fonts và notices được phép phân phối cùng các gate
license đã nêu. Điều phối review/tích hợp và quyết định tag development baseline
theo ADR của mình; native/library release gates vẫn giữ rõ NOT RUN/BLOCKED cho
đến khi có bằng chứng. Candidate này không tự công bố READY hoặc production-ready.
