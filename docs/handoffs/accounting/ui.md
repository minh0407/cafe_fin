# Bàn giao giao diện kế toán

Follow-up export P2 đã được root xác nhận bằng worker thật và sửa riêng tại
endpoint cùng snapshot qua seam core2fb38e3. Regression race/auth4 PASS,
core/public API33 PASS, importlib12 PASS; real browser flow25,9s PASS, có nút tải
và bytes export đúng. Không sửa UI polling. Xem export-status-snapshot.md;
những ghi nhận inference/lỗi trước đó bên dưới giữ đúng bối cảnh lịch sử.

Trạng thái mới nhất: UI trên sổ đã lưu 1 triệu dòng **PASS** với backend
`3aa8c47`; shared DateInput13, accounting mock17 và real1000 cũng PASS trên cổng
test1424. Xem **Actual UI1m PASS — attempt004** bên dưới để lấy số đo/phạm vi.
Các phần PREPARED/NOT RUN và lỗi trước đó được giữ như lịch sử, không thay cho
kết quả mới nhất và không bị đổi nhãn thành PASS.

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

## Clone033 thực tế và hold trước DateInput adoption

- Khi được điều phối release slot, chạy helper trên `C:\Users\NC\AppData\Local\Temp\cafe-fin-final-033e900-683b8f62fae848e1a7aa50259e323a6f\1m\result.json` (PASS, 1m published). Chỉ mở rộng guard helper/harness cho **đúng prefix đã được chỉ định này**, không mở rộng sang operational roots.
- **PASS clone preparation**: `C:\Users\NC\AppData\Local\Temp\cafe-fin-bulk-ui-pjc6fjl4\clone-preparation.json`; clone root `...\data`, sổ `80ed30ef-f2f4-478a-90bb-d0a4d37adae2`. Original DB **6.017.572.864 byte**, SHA-256/size/mtime conserved; independent SQLite backup/integrity/foreign keys, immutable files và streamed accounting digests đều được đối chiếu. Admin mới chỉ trên clone được audit/login xác minh; user/credential cũ không đổi; helper không start job runner. Backend tại lúc clone là frozen `8b70f1ffbee4a30ceaa5a3c8458fd78f84c8d08a` với migration2 áp dụng chỉ trên clone.
- Auto-chain đã bắt đầu Playwright ngay trước khi steering HOLD mới đến. Đã dừng cây process Playwright/Vite/Chromium thuộc đúng lượt đó; kiểm tra không còn `serve.py` Python hoặc listener1420. **Lượt bulk bị ngắt, không có kết quả PASS/measurement đầy đủ để sử dụng.** Conservation PASS của helper vẫn được giữ. Password được tạo trong environment và đã clear khi orchestration thoát; muốn reuse clone cần tạo thêm một Admin tổng hợp mới qua public AuthService trên clone, không reset account cũ hoặc nguồn.
- Host được chia sẻ với chat/backend/browser khác. Slot heavy chỉ điều phối trong chat này; không chứng minh máy yên tĩnh hoặc CPU/I/O độc quyền. Kết quả UI sau này phải ghi là latency/memory quan sát trong môi trường shared host, chưa phải native/release benchmark.

## DateInput adoption ngoài grid — CODE/TESTS PREPARED, chưa chạy khi XLSX đo

- Đọc và dùng contract `docs/handoffs/foundation/date-input.md` từ shared pick được duyệt. Summary from/through, conditional date filter và DATE trong modal thêm dòng dùng shared DateInput DD/MM/YYYY; grid date projection và parser/mapping/backend giữ nguyên.
- Parent state giữ đúng chuỗi raw invalid/incomplete (ví dụ `31/02/2026`), không khôi phục old ISO hoặc chuyển optional invalid thành null/empty. Summary cần nonempty + `isDateInputValueValid` hai đầu rồi mới so thứ tự; manual `refresh()` và queryFn cũng guard, không chỉ `enabled`. Preview import guard query và render, không để tổng cũ hiện khi kỳ raw invalid.
- Date filter builder guard trước Add; JSON Apply và direct hash URL được validate trước row network, kể cả manual refresh. New-row optional null/clear hợp lệ nhưng nonempty invalid chặn; required date còn yêu cầu nonempty. Có lỗi theo tên cột và disabled submit + handler guard. Whole-book export không có period payload và vẫn dùng được khi summary period sai.
- Chuẩn bị regressions DD/MM: raw draft giữ qua blur; summary tự động/manual/preview không query hoặc dùng cached totals khi invalid; correction gửi ISO mới; whole-book export độc lập; optional valid→invalid và clear→invalid không gửi oldISO/empty; required blank/invalid không gửi; date filter builder/JSON/directURL không gửi raw date. Chưa chạy các test mới trong lúc XLSX benchmark giữ slot; không ghi PASS trước khi được release.

### Gate frontend DateInput sau XLSX exit

- PASS frontend build + strict typecheck (registry bundle caveat giữ nguyên).
- PASS shared DateInput **11/11**, 11,4 giây, gồm locale/timezone và strict Form required/optional.
- PASS toàn bộ lane helper/mock browser **17/17**, 23,4 giây, gồm ba regression adoption mới. Một helper test Node được bỏ vì import AntD ES locale qua Node gây lỗi collection; validation thực tế được kiểm trong browser/Vite, không sửa shared component hoặc đổi logic để né lỗi.
- Có guard bổ sung: raw invalid trong date-filter builder không cho Apply dùng lại tag ISO cũ; JSON Apply/direct URL vẫn được guard riêng. Parent đã commit frontend adoption riêng tại `a82476e`; shared pick `ef29e46` giữ riêng.
- Chưa chạy realAPI/1m UI trong lúc parent chốt numeric-filter rewrite. Giá trị latency/memory sắp đo chỉ là quan sát shared-host, không phải CPU/I/O độc quyền.

### Reuse clone với Admin mới sau HOLD

Helper test-only `tests/accounting/ui/add_bulk_clone_admin.py` được chuẩn bị để reuse clone đã PASS, không copy lại 6GB và không reset password. PASS py_compile/Ruff; **chưa thực thi bootstrap bổ sung**. Khi được parent release real/bulk slot, giữ password mới chỉ trong environment rồi chạy:

```powershell
$env:PYTHONPATH = Join-Path (Get-Location) 'backend'
# Generate a new synthetic password into env without printing it.
$env:CAFE_FIN_BULK_PASSWORD = 'Bulk-' + [Convert]::ToBase64String([Security.Cryptography.RandomNumberGenerator]::GetBytes(32))
$reused = & .\.venv\Scripts\python.exe tests/accounting/ui/add_bulk_clone_admin.py `
  --preparation "$env:TEMP\cafe-fin-bulk-ui-pjc6fjl4\clone-preparation.json" `
  --runtime-closed --username '<tên Admin tổng hợp MỚI chưa có trên clone>' | ConvertFrom-Json
if ($LASTEXITCODE -ne 0 -or $reused.status -ne 'PASS') { throw 'Retained clone bootstrap failed.' }
. $reused.activate
```

Helper yêu cầu original preparation PASS, original DB vẫn đúng SHA/size/mtime đã ghi, clone accounting digest vẫn đúng snapshot, clone/WAL đã đóng và DB độc lập file identity. Chỉ thêm một user mới qua public AuthService + audit/login verification trên clone, không start runner, kiểm user/credential cũ và accounting data không đổi. Xuất report/activation riêng; original `clone-preparation.json` giữ nguyên. Chưa khởi động browser tự động; chỉ chạy lệnh bulk riêng sau backend freeze/test-green của parent.

## Lượt thực tế trên freeze9a và blocker text filter

- Real API flow (gồm clipboard 1.000 dòng) **PASS 20,9 giây**, tổng 22,6 giây, trên backend freeze `9a52f023e96cf6d7a06e4f0fdda6efabf60fc4d7` và DateInput adoption `a82476e`. Không mock API.
- Reuse clone/Admin bootstrap PASS, source DB SHA/size/mtime và streamed accounting data được bảo toàn; user/credential cũ không đổi. Report bổ sung giữ riêng trong private Temp clone, không chứa password.
- Lượt bulk đầu không mount được do **harness** dùng hai URL module React Query (`?import&v=...` và `?v=...`). Đã giữ console/pageerror, blank screenshot và trace trước fix trong private Temp; lỗi thực tế là `No QueryClient set`. `vite-ignore` một mình không giải quyết được. Sửa test-owned entry thành **một static Vite module**, eager import App/AccountingPage/providers/session rồi dùng lexical mount/token factory. Narrow real-clone login smoke **PASS 2,1 giây**. Cũng sửa locator Card title (text, không phải heading). Không đổi feature/shared/backend để sửa harness.
- Static entry preload AccountingPage/dependencies trước lúc mount feature: **không** đo cold module load hoặc lazy bundle. Post-login trace không được bật; secret/password/token không đưa vào metrics/docs/console. Artifact trước login được giữ riêng, fixture-only.
- Lượt actual CODE case sau bootstrap fix **FAIL**, không hạ chuẩn thành numeric-only: exact CODE text filter trên toàn dataset vượt deadline **60.000 ms** trước khi mount grid. Direct first page: **6.126,7 ms**, **200/1.000.000 dòng**, **167.125 byte**. Direct trang **5000**: **6.915,8 ms**, **200/1.000.000 dòng**, **167.887 byte**. Failed-probe elapsed riêng chưa được capture ở lượt này; chỉ deadline cấu hình được biết. Label là whole-dataset text filter, không tuyên bố dùng numeric index.
- Raw failure metrics/screenshot/context và annotation deadline được giữ ở private Temp `cafe-fin-bulk-ui-pjc6fjl4/ui-attempt-002-code-filter-timeout`. Source DB conservation cuối lượt **PASS**; không có pageerror. Chưa có cache/heap/grid measurement đầy đủ vì CODE probe dừng trước feature mount. Các lượt bị ngắt/blank/timeout đều **NOT PASS**, không được dùng làm nghiệm thu UI1m.
- Parent HOLD để sửa text/date cell filter query bằng semijoin và chạy targeted/full tests. Backend9a không còn là freeze cuối cho CSV/UI tiếp theo. Orchestrator giữ credential trong environment tại retry gate; sidecar đã thoát, không còn listener1420, không gọi API/browser khác trong lúc chờ.
- Windows memory measurement được sửa để ghi cả venv launcher và actual Python descendants qua parent graph, không gọi RSS launcher là RSS backend runtime. Chỉ số từng process có shared pages, không được cộng thành unique RAM. Host không được chứng minh CPU/I/O độc quyền; mọi latency/memory về sau là quan sát shared-host Chromium/Vite, chưa phải native WebView2/release.

## Cổng test độc lập sau shared DateInput busy-context patch

- Toàn bộ accounting mock/real/bulk/bootstrap config dùng cố định `http://127.0.0.1:1424` qua `tests/accounting/ui/harness-origin.ts`; Vite CLI, bulk Vite config, readiness URL, browser base URL và sidecar/request Origin cùng cổng. `strictPort` và `reuseExistingServer:false` từ chối collision; không chiếm/reuse listener của lane khác. Production desktop/dev1420, CSP và core ALLOWED_ORIGINS không sửa.
- `serve.py` là **test-only Origin adapter**: thêm đúng loopback origin1424 vào hai alias allowlist trong process test (`core.api` và `__main__`), không wildcard/ENV origin tùy ý. Production ScopeGuard, exact Origin/CORS, auth, FileStore, jobs và real HTTP vẫn chạy. Đây là adapter browser harness, không chứng minh production/native origin1424 được phép.
- Config lane `tests/accounting/ui/shared-date.config.ts` chạy nguyên shared consumer13 cases trên1424, không sửa shared manifest/config. Lệnh sau khi parent RELEASE: `frontend/node_modules/.bin/playwright.cmd test --config tests/accounting/ui/shared-date.config.ts`; mock/real/bulk dùng config riêng cùng thư mục, chạy tuần tự.
- Chuẩn bị tĩnh: Python compile/Ruff **PASS**, strict TypeScript harness **PASS**, Playwright `--list` shared13 và bulk1 **PASS**. **Chưa chạy browser/API** vì parent đang HOLD cho backend text/date filter targeted/full tests; credential retry gate giữ nguyên. Shared consumer13 và lane runtime checks cần chạy sau RELEASE trên shared patch `545d75e`.

## RELEASE trên backend text filter freeze3aa8

- Backend/runner freeze `3aa8c47e4a0301abc64dae1d4fc90a2258b9eed4`, shared DateInput `545d75e`, accounting date adoption `a82476e`: shared consumer **13/13 PASS 12,3 giây**, accounting mock **17/17 PASS 24,2 giây**, frontend strict typecheck và production build **PASS** (còn baseline chunk warning >500k; registry do coordinator sở hữu).
- Real API flow hiện tại trên1424 **PASS 21,1 giây**, tổng22,9 giây, gồm schema/exact CRUD, repair/partial publish/resume/export và raw clipboard1000rows với paged staging200/no auto-publish. Test-only exact1424 Origin adapter được dùng; production allowlist/CSP/manifests không đổi.
- Bulk attempt003 **FAIL do test locator**, dù backend CODE exact filter và search đã trả1row. Playwright nhắm hidden accessibility `role=option` của AntD virtual Select thay vì menu item nhìn thấy; screenshot đã inspect có grid trang5000, total1m và dropdown Mã đang mở, pageerrors rỗng. Giữ nguyên metrics/context/screenshot riêng ở private Temp `ui-attempt-003-ant-select-locator`. Sửa chỉ locator trong test để chọn text chính xác bên trong visible dropdown, không sửa product/backend. Không dùng lượt FAIL làm nghiệm thu; full CODE case được chạy lại nguyên scope.

## Actual UI1m PASS — attempt004, backend freeze3aa8

Full case `bulk-real.spec.ts` **PASS, exit0, 1,8 phút** trên freeze `3aa8c47e4a0301abc64dae1d4fc90a2258b9eed4`, DateInput accounting `a82476e` và shared busy-context `545d75e`. Case giữ CODE text filter trên toàn bộ1m, không thay bằng numeric-only. Browser/auth/API/FileStore/job machinery thật; không API mock/interception. Native bootstrap được thay bằng test-only invoke adapter, AccountingPage mount bằng static test-owned Vite entry, exact loopback1424 Origin adapter như mô tả trên.

Nguồn là **baseline033 đã hoàn tất và Runtime CLOSED**, không phải CSV measurement mới trên3aa8: result `C:\Users\NC\AppData\Local\Temp\cafe-fin-final-033e900-683b8f62fae848e1a7aa50259e323a6f\1m\result.json`, original data cùng thư mục `data` (DB6.017.572.864 byte). Chỉ phục vụ clone độc lập `C:\Users\NC\AppData\Local\Temp\cafe-fin-bulk-ui-pjc6fjl4\data`, book `80ed30ef-f2f4-478a-90bb-d0a4d37adae2`. Helper đã kiểm streamed accounting digest trước/sau tạo synthetic Admin trên **clone**, snapshot user/credential cũ không đổi; không mở Runtime/auth trên nguồn. Lượt UI kiểm source SHA256/size/mtime trước/sau **khớp** (SHA256 `a363e109f8d5ec05cbb11aa6a100852ed1f886742a657988ba433e88363b4247`), schema/data revision và final last-page rows không đổi, **0 domain mutation requests**, pageerrors rỗng. Không tuyên bố đã stream lại toàn bộ clone digest sau lượt UI; bằng chứng UI read-only là những invariant vừa nêu.

| Probe HTTP thật trên clone | Thời gian đọc response | Dòng trả về / tổng | Response byte |
| --- | ---: | ---: | ---: |
| First page, page_size200 | 6.150,3 ms | 200 / 1.000.000 | 167.125 |
| Trang5000, page_size200 | 6.787,1 ms | 200 / 1.000.000 | 167.887 |
| Exact CODE filter toàn sổ | 6.388,8 ms | 1 / 1 | 925 |
| Search toàn sổ theo CODE | 6.974,2 ms | 1 / 1 | 925 |
| Final trang5000, sau UI read-only | 6.770,2 ms | 200 / 1.000.000 | 167.887 |

- Browser jump trang2/2500/5000 lần lượt **6.997,0 / 6.997,1 / 6.980,8 ms**. Sáu browser row responses đều200, page_size yêu cầu200, tối đa200items và167.887byte; không tải toàn bộ1m rows về UI.
- Snapshot tại first/page2/page2500/page5000/filter/filter-removed: **1 row query có data**, **12 tổng queries**, cache/UI tối đa**200rows**; DOM grid tối đa**19rows** kể cả header. Filter từ target trang cuối có cache/UI1row và DOM2rows. Bỏ filter quay về1m total/200loaded, vẫn1 cached row page. Paste nhỏ vượt trang bị chặn nguyên vùng; clipboard501cells hiện explicit new-import choice rồi discard, không upload/mutation. Fill bounded có gate mock17; không tuyên bố thao tác fill thực tế trong case1m.
- **201 JS heap samples**, interval250ms và checkpoints quanh feature navigation, sampled maximum **38.937.228 byte**. Đây là sampled JS heap sau module preload, không phải exact allocation lifetime peak/full RAM; không đo toàn lifetime app hoặc native process. Eager static module đã tải App/AccountingPage/deps trước feature mount, không phải cold/lazy bundle timing.
- Windows process snapshots tại **first page** và **after navigation/filter**: actual Python **child PID30408**, RSS97.288.192 →97.267.712byte, OS `PeakWorkingSet64`159.899.648byte tại hai checkpoints. Venv **launcher PID15220** riêng, RSS4.923.392byte; không gọi launcher là runtime. Renderer PID49572 RSS201.416.704 →215.048.192byte, OS process peak tại checkpoints201.416.704 →215.863.296byte. Browser/GPU/network/conhost counters riêng có trong raw metrics; không cộng RSS các process thành unique RAM. OS peak là process counter đến checkpoint, không chứng minh peak cả lifetime từ start đến shutdown; checkpoint cuối trước final metadata/page probes và source hash.
- Host quan sát: Windows10.0.26200 x64, Intel i5-14400F,16logical CPU,34.138.931.200byte physical RAM, Node24.21.0, Chromium158.0.8127.18, viewport1600×1100. Host chia sẻ workload với chats khác; CPU/I/O không pinned/exclusive. Không cold-disk-cache claim, speed promise, native Tauri/WebView2/release claim hoặc numeric-index proof từ CODE text probe.
- Screenshot cuối **đã mở và inspect**: grid thật, total1.000.000/loaded200, page1 sau bỏ filter; không blank/error overlay. Orchestrator session66480 kết thúc0 và clear generated password; owned sidecars**0**, listener1424**0** sau cleanup. Heavy slot đã trả parent; không chạy thêm browser/API/build/heavy checks trong các CSV measurement tiếp theo.

Artifact synthetic/private giữ ngoài repo tại `C:\Users\NC\AppData\Local\Temp\cafe-fin-bulk-ui-pjc6fjl4`:

- PASS hiện tại: `ui-attempt-004-pass\bulk-real-metrics.json`, `ui-attempt-004-pass\bulk-real-ui.png` (bản output đồng thời ở `frontend/test-results/accounting-bulk-real/bulk-real-persisted-millio-6be6d-age-and-full-data-filtering/`, không stage/commit artifacts).
- FAIL backend9a exact CODE >deadline60.000ms: `ui-attempt-002-code-filter-timeout\bulk-real-metrics.json`, `bulk-failure.png`, `observed-failure.json`; **không** đổi nhãn FAIL hoặc bịa failed elapsed riêng chưa được capture ở lượt đó. First/high-page6.126,7/6.915,8ms của lượt9a chỉ thuộc context FAIL đó.
- FAIL locator AntD trên3aa8: `ui-attempt-003-ant-select-locator\bulk-real-metrics.json`, `bulk-failure.png`, `error-context.md`. Metrics lượt đó tách khỏi PASS hiện tại.
- Bootstrap histories: `ui-attempt-001-failure.json`, `bootstrap-before-fix\`, `bootstrap-vite-ignore-failure\`, `bootstrap-static-module-wrong-role-assertion\`, `bootstrap-static-module-pass\`. Actual pre-fix React Query exception/console/trace giữ riêng; post-login trace không bật. Credentials/token không in console/metrics/docs; source values fixture-only.
- Clone preparation/auth audit evidence: `clone-preparation.json`, `clone-admin-760ac5a2835b40bb.json`; credential-free activation/report riêng, không reset account nguồn hoặc credential cũ.

Gates cuối: shared13 PASS12,3s; accounting mock17 PASS24,2s; strict frontend TC/build PASS; real1000 PASS21,1s (22,9s total); full actualUI1m PASS1,8min. Các FAIL trước vẫn giữ nguyên, frontend feature/backend/runner không đổi để sửa harness. Những thay đổi harness/helper/docs đang bàn giao vẫn **unstaged/uncommitted** để parent review/chốt riêng (frontend DateInput adoption đã được parent commit riêng như ghi trên).

## SchemaEditor P2 — command cố định khi mất ACK

Root xác nhận P2 từ browser/backend thật tại `C:\Users\NC\AppData\Local\Temp\cafe-fin-schema-review-c90be6801b8c4941bef15cb9b34ca153\evidence.json`: POST tạo sổA đã commit nhưng ACK mất; controls vẫn cho đổiA→B, lần Save tiếp theo tạo request_key/body mới và thành2books. Bản sửa chỉ thuộc `frontend/src/features/accounting/SchemaEditor.tsx`, không đổi backend/schema/import math hoặc UI component khác.

- Trước await đầu tiên, freeze một command gồm method/path/**serialized body** (columns/semantics lồng nhau, expected_version nếu PATCH và request_key). Synchronous in-flight ref chặn resubmit đồng thời. Retry không build lại từ mutable form/props và không đổi key; same-book refetch/version update không reset command đang uncertain.
- Khi đang gửi hoặc chưa xác nhận kết quả, khóa toàn bộ AntD inputs/selects/checkboxes/numbers, thêm/xóa/đổi thứ tự cột, JSON và modal cancel/X/mask/Escape. Hiện **Thử lại cùng yêu cầu** với lời giải thích giữ nguyên command. Chỉ allowlist rejection validation/conflict rõ ràng giải phóng chỉnh sửa; local JSON/input validation trước tạo command không khóa; transport/invalid response/unknown server failure tiếp tục uncertain.
- Generation/open/book epoch guard chặn old onSaved/onClose và mọi chỉnh sửa/cancel của scope cũ. Actor reset clear command/draft rồi **unmount/retire editor cũ**, không gọi callback cũ; chỉ fresh open epoch mới mở editor của actor mới. Unmount có chủ đích vì AntD giữ hidden modal child DOM khi chỉ open=false. Late response/finally không thay busy/error/callback của editor mới. Response onSaved làm đổi generation cũng không gọi old onClose tiếp theo.
- Hai Input **Giá trị chiều thu / Giá trị chiều chi** ghi income_value/expense_value theo chuỗi người dùng nhập; không suy diễn/default. Advanced semantics JSON được thu gọn mặc định bằng details; ordinary direction mapping không cần nhập JSON.

Focused command: `frontend/node_modules/.bin/playwright.cmd test --config tests/accounting/ui/schema.config.ts` trên dedicated1424, reuseExistingServer:false. Static test-owned module/session bootstrap; production SchemaEditor/api/auth/HTTP thực. **11/11 PASS21,9 giây** lượt cuối, gồm9mock +2real synthetic isolated DB. Real case chỉ forward actual API response, rồi drop **ACK sau HTTP200 đã commit** ở lần đầu; retry dùng response thật, không substitute response/body hoặc mock database.

| Real lost-ACK case | Sau commit trước retry | Sau exact retry | Request observations |
| --- | --- | --- | --- |
| POST create | 1book, version1, schema_revision1 | vẫn1book/version1/revision1 | 2HTTP attempts, cùng method/path/raw body/key; 1Saved +1Closed callback |
| PATCH schema | seed1→version2/schema_revision2 | vẫn1book/version2/revision2 | 2HTTP attempts, expected_version1 không đổi; cùng method/path/raw body/key; 1Saved +1Closed callback |

Mock regressions còn kiểm same-book version props đổi99 không làm đổi frozen expected_version3; attempted synthetic edit/double-submit không tạo command mới; definitive422/409 cho sửa và key mới; local JSON invalid không gọi API; unknown500 giữ lock; late generation/open response không callback/không leak payload; uncertain PATCH actor reset không mang target/body cũ vào new POST. Test harness dùng stable footer và actual loading class vì AntD có thể giữ exiting loading-icon trong accessible name; không sửa product để sửa locator.

Gates sau thay đổi: standard accounting mock **17/17 PASS24,5 giây**, strict frontend TC/build và strict harness TypeScript **PASS** (baseline bundle warning/registry caveat vẫn như trước), existing real1000 normalflow rerun **PASS21,7 giây** (23,7 giây total), gồm normal create/schema update, CRUD/version/delete/restore, partial import/repair/resume, export/download, clipboard1000 source/paging200/no auto-publish. Không rerun UI1m/CSV/XLSX cho component-only delta này.

**Giữ lại một normalflow FAIL riêng, không xóa bằng rerun PASS:** lượt đầu sau Schema P2 dừng ở export, alert hiển thị COMPLETED nhưng chưa có download action (25,6giây, failed5s visibility gate). Snapshot/context giữ tại `C:\Users\NC\AppData\Local\Temp\cafe-fin-schema-normal-export-failure-72bde80f984840408c7ee947bfc0d4e8`. Failed attempt chưa capture raw export response. Read-only review gợi ý race export_status đọc exports.file_id trước, rồi jobs.status qua reader khác có thể mới hơn; **đây là inference**, không tuyên bố đã capture raw COMPLETED/null. Rerun chỉ thêm response observation/failure screenshot vào test (không API interception/substitution); lần PASS capture2 COMPLETED responses đều có file_id hợp lệ. Parent được báo riêng; chưa sửa backend hoặc AccountingPage ngoài authorized component.

Schema-specific new files cho commit riêng của parent: `tests/accounting/ui/schema.config.ts`, `schema-vite.config.mts`, `schema-fixture.ts`, `schema.spec.ts`, `schema-real.spec.ts`; thêm observation-only delta ở existing `real.spec.ts`. Artifacts synthetic ngoài tracked source: `frontend/test-results/accounting-schema/schema-real-real-create-co-171d8-nother-book-schema-revision/schema-real-evidence.json` và `schema-real-real-patch-com-a24f1-nother-book-schema-revision/schema-real-evidence.json`; raw strings cho phép đối chiếu exact replay. `schema-real-confirmed.png` đã inspect: modal đóng đúng, chỉ còn callback counters1/1 của harness; không phải UI design/native proof. Initial test locator failures được giữ riêng tại private Temp `cafe-fin-schema-retry-attempt1-9ff1b28d6bf84d4ea4ebb1ada5e55014`, không tính PASS. Worktree backend HEAD khi các gates chạy là `831202301cb96ffdb6537bf9eb760b4e69f81ba2`; frontend SchemaEditor delta chưa commit. Không stage/commit code/doc/artifacts từ lane.
