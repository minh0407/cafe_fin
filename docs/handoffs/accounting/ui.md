# Bàn giao giao diện kế toán

- Worktree: `C:\Users\NC\.codex\worktrees\cafe-fin-accounting\cafe_fin`.
- Branch: `codex/cafe-fin-accounting-20261106`.
- UI subtask không commit/push theo yêu cầu điều phối. Không sửa registry, dependency, shared API hoặc file của lane khác. Không có migration UI.
- Dùng React 19 và `react-data-grid` `7.0.0-beta.64` đã pin; không thêm dependency.

## Tích hợp của điều phối

`frontend/src/features/accounting/index.ts` xuất `accountingFeature: FeatureModule`, route `/accounting`, permission `accounting.read`. Thay stub kế toán trong `frontend/src/app/registry.tsx` bằng export này:

```ts
import { accountingFeature } from '../features/accounting';
// Trong defineModules([...]): accountingFeature
```

Backend cần đăng ký `accounting.module.module_manifest()` ở registry chung. Harness thật đăng ký manifest trong Runtime riêng của test; không thay registry sản phẩm.

Quyền giao diện: `accounting.read` xem; `accounting.write` CRUD/xóa mềm/import/export; `accounting.configure` tạo sổ/schema; `accounting.restore` khôi phục. Admin hoặc `*` có đầy đủ. Backend vẫn là nơi kiểm quyền và phiên bản.

## Hành vi đã triển khai

- Sổ phân trang, ID cột ổn định, đổi tên hiển thị, thứ tự/kiểu/required/editable/precision/scale/choices/formula/freeze và min/max/max_length. Ngữ nghĩa ngày/thu/chi hoặc chiều+số tiền, tiền tệ, cột nhóm/so trùng/khóa nghiệp vụ có lựa chọn cột và JSON nâng cao. Cho sổ rỗng; không đoán ngữ nghĩa tiền.
- Grid server paging 200 dòng, search/sort/filter toàn tập trong hash URL, bộ tạo điều kiện lọc, vùng Shift+click/Shift+phím, TSV có quote/newline, clipboard tối đa 500 ô/100.000 ký tự. Native drag fill và nút điền vùng đều qua preview, chỉ tác động trang đã tải. Resize và freeze cột. Không chuyển tiền sang JavaScript Number.
- Nháp tối đa 500 ô thay đổi, lịch sử 20 bước, chỉ trong trang/actor/sổ hiện tại. Save cần xác nhận; hiển thị kết quả từng dòng. Thành công cập nhật baseline/version; dòng lỗi giữ nháp. Conflict hiển thị lúc tải/bản nháp/hiện tại qua GET row ID, không tự ghi đè. Thêm dòng giữ request key khi retry cùng intent. Xóa mềm/khôi phục kiểm version và quyền; có `deleted=true` để tìm lại dòng đã xóa.
- Hints required/choice/syntax/scale/length không làm tròn; backend quyết định validation đầy đủ. Lỗi nguồn có tọa độ, tooltip và điều hướng. Trước/sau thu chi là chuỗi chính xác từ backend, tách đơn vị tiền, có cờ dự kiến.
- Guard beforeunload và rời hash route. Listener một lần lúc import feature được đăng ký trước listener shell để shell không unmount nháp trước khi hỏi. Đổi actor/generation xóa nháp, editor, selection và cache actor cũ; request loop cũ dừng trước khi gửi lệnh tiếp theo bằng actor mới. Query cache `gcTime: 0`, key có actor/generation, sổ, schema/data revision và tham số trang/bộ lọc khi thích hợp.
- Import upload gốc qua core FileStore, profile CSV/XLSX/XLSM/sheet/header/range có cấu hình, mapping theo ID cột, lưu/dùng lại hồ sơ. Job được liệt kê theo trang 50, đóng/mở lại không mất patch đã lưu/job. Staging trang 200, nguồn gốc/typed/patch riêng, patch chỉ gửi ô editable thay đổi và expected row revision.
- Validate toàn job; lỗi/ứng viên trùng có paging; lựa chọn keep/skip từng ứng viên và mặc định cho phần chưa quyết định. Confirm pin exact staging/mapping/decision revisions + validation token + `valid_rows_only`; không gửi triệu ID. UI phân biệt pending durable và published; chỉ khi published count tăng mới tự tải lại sổ/tổng. Cancel/resume theo trạng thái worker, không coi pending là nhập thành công.
- Tải gốc giữ tên/đuôi tệp, hiển thị SHA-256/byte. Xuất sổ CSV/XLSX là job dẫn xuất; xuất toàn lỗi còn mở qua job riêng, tải lỗi trang hiện tại TSV tối đa 100 cũng có nhãn rõ. Không thay tệp macro gốc hoặc cam kết fidelity đầy đủ.

Các file UI chính: `AccountingPage.tsx`, `WorkbookGrid.tsx`, `ImportWorkspace.tsx`, `SchemaEditor.tsx`, `drafts.ts`, `navigation.ts`, `client.ts`, `types.ts`, `accounting.css`, `index.ts` dưới thư mục feature accounting.

## Kiểm chứng

Chạy từ worktree root:

```powershell
npm --prefix frontend run typecheck
frontend/node_modules/.bin/playwright test --config=tests/accounting/ui/playwright.config.ts
frontend/node_modules/.bin/playwright test --config=tests/accounting/ui/real.config.ts
```

- PASS TypeScript strict, không skip module errors.
- PASS 9 test helper/browser mock: TSV quoted multiline và chuỗi tiền lớn; từ chối vượt page/500 ô/read-only atomically; encode search/filter punctuation; hint scale; preview/undo/redo/save version; conflict so sánh; reopen import/pin token; guard hash và actor/cache/permission; native drag-fill + explicit range fill không ghi trước preview/save.
- PASS 1 luồng browser thật, dùng HTTP/auth/CORS/SQLite/FileStore/serialized writer/job runner thật. Không intercept API: tạo sổ và schema revision bằng UI; thêm tiền chuỗi lớn; upload CSV tổng hợp 3 dòng; mapping; patch staging; validate 1 lỗi; xuất toàn lỗi qua job; tải original kiểm SHA-256 bằng byte; confirm 2 hợp lệ; đóng/mở job; sửa lỗi rồi validate/confirm tiếp chỉ thêm 1 dòng; tổng sổ có đúng 4 dòng kể cả dòng manual; sửa tiền bằng bàn phím/version; xóa/hiện deleted/khôi phục; export CSV giữ tiền chính xác và loại raw lỗi.
- Harness thật chỉ thay entry module phía browser để mount feature trong provider chuẩn và bootstrap một tài khoản tổng hợp. `serve.py` dùng production sidecar main với Runtime subclass đăng ký accounting. Dùng allowed origin `http://127.0.0.1:1420`; không đổi policy CORS hoặc mock API. Config từ chối port bận, không giết/reuse server lane khác. Config mock dùng 1447.
- Ảnh QA từ dữ liệu tổng hợp được render ở `frontend/test-results/accounting-real/real-real-accounting-API-s-0c1b5-e-errors-and-derived-export/accounting-real.png` (test output, không commit).
- `npm --prefix frontend run build` PASS ở baseline registry hiện tại; registry chưa wiring accounting nên bundle sản phẩm đầy đủ phải chạy lại sau tích hợp. Browser harness thật đã tải/biên dịch thực sự feature, không chỉ typecheck.

## Giới hạn còn lại / tích hợp

- Shared `ApiError` hiện bỏ `error.details`. UI đã đọc optional `details.issues` khi có, đồng thời có hints chuỗi cơ bản và nguồn lỗi staging. Điều phối cần patch shared constructor/pass-through như `shared-change-request.md` để hiển thị mọi chi tiết backend cho validation trực tiếp trên dòng sổ.
- NOT RUN bộ cài/native Tauri/WebView2/đóng cửa sổ Windows; browser tests không thay release gate native.
- Không lấy fixture CSV nhỏ làm bằng chứng hiệu năng 50k/500k/1m. Các benchmark lớn/kill-resume là bằng chứng backend/điều phối riêng; UI chỉ giữ page và vùng có giới hạn. Không tuyên bố thời gian import triệu dòng hoặc production-ready.
- Nháp chưa save không bền qua crash/đăng xuất; guard bảo vệ rời trang thông thường. Patch staging đã save và job là dữ liệu bền phía backend.

## Delta bridge v2: ý nghĩa chỉ tiêu và công thức mẫu

- SchemaEditor thêm hai lựa chọn tùy chọn `semantics.metric_meanings.income` / `expense`: `cash_receipts`, `cash_payments`, `cash_receipt_deposits`, `cash_payment_deposits`, `noncash_offsets`, `other`. Mặc định chưa phân loại (`undefined`), clear xóa trường tương ứng; không suy ý nghĩa từ tên/ID cột. Chiều không khai báo vẫn giữ nguyên trạng thái vắng mặt, không tự thêm chiều hay số 0.
- Cảnh báo phần chưa phân loại giải thích ảnh hưởng chỉ tiêu dòng tiền báo cáo ngày; không chặn lưu cấu hình hoặc CRUD sổ.
- Help công thức phân biệt mẫu cột sổ cùng dòng dùng `A{row}` / `B{row}` với phạm vi nguồn tệp. Mẫu tham chiếu cố định/chéo dòng bị backend từ chối `FORMULA_BOOK_SCOPE`.
- Delta chỉ sửa SchemaEditor và handoff. PASS `npm --prefix frontend run typecheck`; kiểm tra code các nhánh mặc định/clear không thêm ý nghĩa hoặc chiều khác. Không lặp toàn bộ E2E dữ liệu cho thay đổi cấu hình nhỏ này; kết quả browser trước đó giữ nguyên phạm vi chứng minh.

## Harness UI trên sổ đã công bố 1.000.000 dòng — PREPARED, NOT RUN

Đã chuẩn bị `tests/accounting/ui/bulk-real.spec.ts`, `bulk-real.config.ts` và cấu hình Vite cô lập `bulk-vite.config.mts`. **Không chạy, không typecheck/build/khởi động server cho bộ bulk trong khi benchmark CSV đang frozen/chạy.** Chỉ test files và tài liệu thay đổi ở lượt chuẩn bị này; frontend/backend giữ nguyên. Config mock hiện chọn rõ `drafts.spec.ts` và `workspace.spec.ts` để không vô tình thu thập bulk test.

Điều phối chuẩn bị clone tổng hợp riêng **sau khi benchmark nguồn đã đóng Runtime**. Ưu tiên core backup/restore; nếu dùng SQLite backup thì nguồn phải đóng, sao chép marker/data files đầy đủ sang thư mục mới, dùng DB độc lập (không hard link), kiểm digest DB/entry nguồn trước và sau clone. Tuyệt đối không reset mật khẩu benchmark gốc. Runner hiện tại dùng `secrets.token_urlsafe(24)` cho `benchmark-admin`, không có mật khẩu cố định được công bố. Có thể tạo tài khoản admin tổng hợp mới, có audit, chỉ trên clone qua public AuthService, rồi cung cấp credential clone cho harness. Bước tạo clone/tài khoản do điều phối thực hiện riêng; harness không tự clone hoặc sửa credential.

Yêu cầu đầu vào:

- Clone dưới `%TEMP%\cafe-fin-bulk-ui-<unique>\...`, không phải original/operational root. `realpath`, containment, file identity và hard-link count được kiểm trước khi khởi động.
- Result JSON của CSV nguồn có `status='PASS'`, `fixture.rows=1000000`, `final_reconciliation.published_rows=1000000`, và `method.data_root` trỏ vào `%TEMP%\cafe-fin-frozen-20261106...`. Lượt skip phần sửa lỗi chưa đủ 1m published sẽ bị từ chối.
- UUID sổ đã được đối chiếu; username/password tài khoản **clone** có quyền xem và sửa để kiểm preview (không bấm Save).
- Port 1420 trống. Config luôn `reuseExistingServer:false`, không giết hoặc dùng lại listener khác.

Lệnh **chỉ chạy sau khi điều phối xác nhận benchmark đã kết thúc và clone sẵn sàng**:

```powershell
$env:CAFE_FIN_BULK_READY = '1'
$env:CAFE_FIN_BULK_ROOT = "$env:TEMP\cafe-fin-bulk-ui-<unique>\data"
$env:CAFE_FIN_BULK_RESULT = "$env:TEMP\cafe-fin-frozen-20261106-<run>\<csv-1m-result.json>"
$env:CAFE_FIN_BULK_BOOK = '<UUID sổ 1m trên clone>'
$env:CAFE_FIN_BULK_USERNAME = '<tài khoản tổng hợp chỉ trên clone>'
$env:CAFE_FIN_BULK_PASSWORD = '<mật khẩu tổng hợp của clone>'
$env:CAFE_FIN_BULK_CODE_COLUMN = 'code' # tùy chọn; mặc định code
frontend/node_modules/.bin/playwright test --config=tests/accounting/ui/bulk-real.config.ts
```

Harness mở **clone** bằng `serve.py`, `initialize:false`; login bằng giao diện auth/API production. Chỉ native invoke bootstrap được thay. Không intercept/mock API hoặc thay response/module sản phẩm. HTML test qua Vite giữ React Root handle công khai để unmount/clear shell trước khi mount AccountingPage thật với QueryClient đo được; không có grid/cache thứ hai ẩn trong phép đo.

Các assertion chuẩn bị:

- API/GUI thấy đúng total 1.000.000; mỗi response, page/cache hiện tại và counter dòng UI tối đa 200. Qua Pagination tới trang 2, giữa và cuối; filter bằng mã lấy từ trang cuối trên toàn tập, rồi bỏ filter; `gcTime:0` chỉ giữ tối đa một page rows sau chuyển trang.
- Paste hai dòng từ dòng cuối trang đã tải bị từ chối toàn bộ; paste 501 ô bị từ chối. Không lưu nháp hoặc gọi mutation accounting. Cuối lượt kiểm data/schema revision, total và nội dung trang cuối không đổi.
- Đo latency loopback HTTP/body đọc thật cho trang đầu, offset cao, exact indexed filter và search trên toàn tập; lưu bytes và returned row count. Không gửi yêu cầu triệu dòng.
- CDP `Runtime.getHeapUsage` + `Memory.getDOMCounters` lấy mẫu 250ms bắt đầu trước mount feature; ghi sampled peak JS heap, DOM counters, cache/page/UI loaded counters. `SystemInfo.getProcessInfo` lấy ID/CPU, **không phải memory**; Windows `Get-Process` đọc WorkingSet64/PeakWorkingSet64/PrivateMemorySize64 tại checkpoint cho Chromium và sidecar.
- Hash/size/mtime DB nguồn frozen trước/sau **lượt UI** phải giữ nguyên. Harness không mở Runtime/auth nguồn và không xóa clone hoặc nguồn. Bằng chứng bất biến trong bước clone trước đó vẫn thuộc điều phối.

Output khi được chạy: `frontend/test-results/accounting-bulk-real/.../bulk-real-metrics.json` và `bulk-real-ui.png`; không chứa credential. JS heap không phải RSS toàn renderer/browser/backend; sampled maximum không phải peak allocation tuyệt đối; RSS process có thể đếm lặp shared pages. Không ép GC để làm số đo nhỏ. Đây là Chromium/Vite development harness, chưa chứng minh native WebView2/release bundle. Latency không mang nghĩa cold-disk-cache hoặc cam kết tốc độ. **Chưa có kết quả PASS/FAIL hoặc số memory/latency thực tế cho bộ bulk ở lượt chuẩn bị này.**

## Delta ngày nghiệp vụ bao gồm hai mốc / cặp trùng trong tệp

- Khoảng ngày date-only của summary và preview import là `from_on <= ngày <= through_on`, gồm cả hai mốc. UI ghi “Đến hết ngày (bao gồm)” và cho chọn `from_on == through_on` để xem một ngày. Khoảng đảo/ngày trống không gọi summary; CRUD không bị chặn.
- Ngày/năm mặc định được lấy bằng `Intl.DateTimeFormat` với `timeZone: 'Asia/Ho_Chi_Minh'`, cùng một lần xác định ngày mặc định cho đầu năm và hết hôm nay; không phụ thuộc ngày/năm máy ở gần nửa đêm Việt Nam. ImportWorkspace nhận cùng range này, không tự dùng ngày 01/01 năm sau làm mốc cuối. Quy tắc UTC timestamp half-open không thay đổi.
- Review nghi trùng hiển thị riêng JSON `file_matches` (“Ứng viên trong cùng tệp”) và `matches` (“Ứng viên trong sổ đã công bố”), giữ lựa chọn keep/skip rõ ràng.
- PASS typecheck và 3 test mục tiêu: mốc nửa đêm/năm Việt Nam, request summary cùng ngày và hiển thị cặp trùng trong tệp. Không chạy bulk/real 1m cho delta này.

## Delta clipboard lớn qua staging backend

- Paste bình thường vẫn giới hạn 500 ô/100.000 ký tự trên trang đang tải. Paste nhỏ vượt trang và fill vượt trang vẫn bị từ chối; không tự chuyển thành ghi đè hay coi ô chưa tải là trống.
- Khi vượt ngưỡng clipboard bình thường, grid chỉ parse đến giới hạn để phát hiện và chuyển nguyên chuỗi sang một `File` CSV UTF-8 (giới hạn **100 MiB theo byte**), không tạo mảng toàn bộ nguồn/dòng trong React hoặc gửi JSON row/ID list. Nội dung raw và CRLF/quote giữ nguyên; đây là CSV dùng **delimiter tab, header_row=0**, không phải đổi tên một định dạng chưa hỗ trợ thành TSV.
- Người dùng thấy lựa chọn rõ **“Đưa clipboard lớn vào lượt nhập mới”** hoặc **“Bỏ clipboard”**. Chọn tạo lượt mới mở ImportWorkspace với File/profile đã điền, mapping trống để review. Chưa upload, chưa patch job cũ, chưa publish; người dùng tiếp tục bấm “Lưu gốc và tạo job”, mapping → validate → confirm qua API hiện có. Cùng lựa chọn hoạt động khi đang xem staging, luôn tạo batch mới thay vì sửa các dòng chưa tải.
- Draft hiện tại phải save/discard trước khi chuyển. File/candidate là tối đa một nguồn raw có giới hạn, không phải một triệu row trong state/cache. Đổi actor/sổ hoặc discard/đóng có xác nhận xóa nguồn clipboard chưa gửi khỏi bộ nhớ; patch/job đã lưu vẫn bền và original FileStore không bị xóa.
- PASS strict typecheck. PASS mock/helper mục tiêu: 501 ô đòi lựa chọn rõ, upload body bytes đúng, create-job chỉ chứa file ID/profile/key; không JSON rows/IDs; staging page có giới hạn, không tự publish; staging paste tạo lựa chọn batch mới; discard làm nút upload disabled; draft và actor isolation; paste nhỏ off-page tiếp tục bị chặn; đúng 500 ô có newline cuối vẫn được parse.
- PASS real HTTP/auth/FileStore/jobs flow mở rộng **23,6 giây** (tổng suite 25,5 giây), chạy trước timed 1m: paste **1.000 dòng** từ grid → lựa chọn → CSV/tab/header0/UTF8 → lưu gốc; download bằng bytes khớp nguyên clipboard; mapping ban đầu `{}`; mapping/validate 1.000 dòng, mỗi staging response/UI page 200, published vẫn 0, sổ vẫn đúng 4 dòng ban đầu. Đây là bằng chứng luồng clipboard nhỏ có staging thật, không phải benchmark 1m.
- Không sửa backend/runner hoặc thêm dependency. Không chạy bulk UI 1m trong lượt này; vẫn chờ CSV1m/XLSX và clone riêng như gate ở trên.

## Helper clone + Admin tổng hợp cho bulk UI — PREPARED, NOT RUN

Đường dẫn: `tests/accounting/ui/prepare_bulk_clone.py`. Chỉ chuẩn bị script trong khi Frozen033 CSV1m còn chạy; **không gọi script, không hash DB, không mở SQLite/Runtime nguồn, không clone và không khởi động browser ở lượt chuẩn bị này**. Script chưa được chạy/smoke-test; chưa có clone hoặc credential mới nào được tạo bởi lượt này. Không sửa backend hoặc benchmark runner frozen.

Sau khi điều phối xác nhận result **PASS**, CSV Runtime/process đã đóng và không có phép đo timed khác bị ảnh hưởng bởi I/O clone, chạy từ accounting worktree:

```powershell
$env:PYTHONPATH = Join-Path (Get-Location) 'backend'
$env:CAFE_FIN_BULK_PASSWORD = '<mật khẩu MỚI tổng hợp, 10..128 ký tự, chỉ dùng trên clone>'
$prepared = & .\.venv\Scripts\python.exe tests/accounting/ui/prepare_bulk_clone.py `
  --result "$env:TEMP\cafe-fin-frozen-20261106-<Frozen033 run>\<csv-1m-result.json>" `
  --runtime-closed --username bulk-ui-admin | ConvertFrom-Json
if ($LASTEXITCODE -ne 0 -or $prepared.status -ne 'PASS') { throw 'Clone preparation failed; do not start bulk UI.' }
. $prepared.activate
```

`--book <UUID>` tùy chọn nếu không chỉ có duy nhất một sổ đúng 1m dòng; `--root <thư mục MỚI dưới Temp\cafe-fin-bulk-ui-*\...>` tùy chọn, mặc định script tự tạo parent bằng `mkdtemp`. Không dùng root đã có dữ liệu. `--code-column code` là mặc định. Giữ **cùng** `CAFE_FIN_BULK_PASSWORD` trong shell để login browser sau này. Mật khẩu không nằm trong argv, JSON report, stdout hoặc env-activation file; script không in token/password hash.

Các kiểm tra và thao tác chuẩn bị khi thật sự được gọi:

1. Từ chối ngay nếu result chưa PASS hoặc fixture/final reconciliation chưa đủ 1.000.000 published. Source path phải nằm dưới Temp `cafe-fin-frozen-20261106...`; clone phải dưới Temp `cafe-fin-bulk-ui-*`, độc lập storage/file identity, không hard link.
2. Giữ OS lock byte 0 của `.instance.lock` đã tồn tại trong source để chứng minh Runtime không còn giữ lock và ngăn Runtime hợp tác mở lại trong lúc copy. Handle chỉ lock/unlock, không ghi/truncate/create lock file. WAL nguồn phải vắng hoặc rỗng; script không checkpoint hay sửa nguồn để vượt gate.
3. Ghi SHA-256/size/mtime_ns DB nguồn trước; dùng SQLite URI `mode=ro&immutable=1` và API `backup()` sang DB mới. Không mở Runtime hoặc writer trên nguồn. Kiểm integrity/foreign keys của DB clone; tạo đủ LAYOUT và copy marker cùng mọi immutable file được `core_files` tham chiếu, đối chiếu size/SHA-256. Không copy WAL/shm/lock/log đang hoạt động.
4. Stream digest từng dòng của accounting books/schema/entries (batch đọc 256; không giữ triệu dòng), so sánh nguồn với clone. Tạo Runtime **clone** nhưng không gọi `Runtime.start`, nên không chạy/recover job.
5. Đọc public fields của một active Admin từ **clone**, dựng trusted Principal cho bootstrap được giao, gọi public `runtime.auth.create_user(..., role='admin')`. Không sửa/reset user cũ; so snapshot xác nhận credential/user cũ nguyên vẹn và chỉ thêm một user. Kiểm audit create, public login/authenticate của user mới rồi logout. Browser sau đó vẫn login bình thường qua HTTP auth production.
6. Đóng clone Runtime, so digest accounting clone trước/sau auth; kiểm result JSON không đổi và DB nguồn SHA-256/size/mtime_ns trước/sau trùng hoàn toàn. Không xóa source hay clone khi lỗi; partial clone/report FAIL được giữ cho điều phối kiểm tra.

Khi PASS, stdout trả `clone_root`, `book_id`, username, đường dẫn `clone-preparation.json` và `activate-bulk-env.ps1` trong parent clone. Dot-source activation file đặt chính xác `CAFE_FIN_BULK_ROOT`, `CAFE_FIN_BULK_RESULT`, `CAFE_FIN_BULK_BOOK`, `CAFE_FIN_BULK_USERNAME`, `CAFE_FIN_BULK_CODE_COLUMN`, `CAFE_FIN_BULK_READY=1`; password vẫn lấy từ env đã đặt. Chỉ sau các gate CSV/XLSX và quyền chạy UI của điều phối mới gọi riêng lệnh Playwright bulk đã nêu; helper không tự khởi động browser.

### Kiểm tra tĩnh sau baseline033 PASS, chưa được cấp heavy slot

- PASS `python -m py_compile tests/accounting/ui/prepare_bulk_clone.py`; PASS Ruff sau sửa thứ tự import trong đúng helper (không sửa backend/runner).
- PASS strict TypeScript compile ba file bulk spec/config/Vite config. Sửa annotation `ViteDevServer` trong config test để tránh implicit-any; không đổi hành vi.
- PASS parse-only embedded browser module bằng esbuild; không thực thi module hoặc khởi động Vite/browser.
- PASS `playwright test --config=tests/accounting/ui/bulk-real.config.ts --list`: đúng một test bulk được nhận diện; list-only không chạy test, server, clone hoặc auth.
- PASS frontend `npm run build` (bao gồm typecheck). Shared registry vẫn thuộc điều phối; bundle hiện tại chưa chứng minh feature accounting được đăng ký trong sản phẩm, như caveat build ở trên. Warning chunk >500 kB của baseline vẫn có.
- **NOT RUN** helper trên dữ liệu thật/clone, SQLite backup/hash trên baseline, migration2 của clone, bootstrap Admin, browser hoặc phép đo 1m UI. Chờ điều phối release heavy slot sau full backend regression; Frozen033 source evidence chưa bị mở/sửa bởi lane UI.
