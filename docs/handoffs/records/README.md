# Records candidate trên foundation v1

Worktree: `C:\Users\NC\.codex\worktrees\cafe-fin-records\cafe_fin`.
Branch: `codex/cafe-fin-records-20261106`.
Baseline duy nhất: `cafe-fin-foundation-ready-v1` →
`e668355c227322994902f7e2e38ed7ffb19ff647`.

Thay đổi lane chỉ trong bốn vùng ownership records. Các ngoại lệ shared đã được duyệt:
commit root đã được cho phép cherry-pick: source `57a2ed26bf70b8d6b3c4d2c7a30620d3d6b3033a`
→ local `1cd2da5`, read bridge v2; source DateInput
`6098a1111432995ed5b6be96fd0650af382a15e2` → local `999b2a6` (đúng năm file root).
Patch disabled-context `3aa94c601dbf878f07b46b0902fc71b0f388c40c` → local
`b5cbfa569430c00eab35f8e6f09071c5b98d9a70` (đúng ba file shared/test/doc root).
Read bridge v3 `206a7e30ce702d8064084c90296aed3634ef28b7` → local `7575b28`
(đúng bốn file core/contract/test/doc root).
Không tự sửa core/shared, push/merge/tag hoặc source/DB cũ.
Backend đăng ký qua `cafe_fin.records.module.module_manifest()`. UI export
`recordsModule` tại `frontend/src/features/records/index.ts`. Registry nền vẫn
chưa ghép records; không coi build shell stub là bằng chứng UI nghiệp vụ.

Candidate lane đã hoàn tất trên baseline phát triển, chờ điều phối tích hợp.
Cherry-pick theo thứ tự: backend ledger `3e6f0a9d0ef4d096ae78302a428e4eb479bd60d6`,
snapshot extension `ba60228cf188f65bb76f1c39fe568d4536a0fc2e`, UI/handoff
`e6f3847aa59165803e9ace7ffec9faaf6d3f92d2`, rồi update v2 sau khi root đã có shared
commit nói trên. Root đã sở hữu `57a2ed2` nên không cherry-pick lại local `1cd2da5`.
Danh sách file thuộc lane ở files.txt; không gồm bốn file shared bridge v2 và
năm file shared DateInput do root sở hữu, đã được cherry-pick theo ủy quyền.

## Ledger và dữ liệu

Phiếu lưu immutable revision; JSON snapshot, dòng scaled, refs và movement cùng
transaction với core audit/receipt. Phiên bản effective là revision mới nhất
(hoặc revision mới nhất có recorded_at <= cutoff khi báo cáo lịch sử). Chỉ
revision posted/chưa xóa sinh movement. Sửa/hủy/xóa/restore không xóa bản cũ;
phiên bản mới thay projection effective, không ghi thêm tác động lặp.

Mỗi phiếu có sequence SQLite cấp một lần; order_key zero-pad sequence giữ nguyên
khi retry/sửa/restore. Chuỗi kiểm theo occurred_on/order_key/id foundation; trong
sản xuất/chuyển kho cùng phiếu, out đứng trước in. Cộng gộp theo
product/warehouse/direction trước ghi. Kiểm toàn bộ prefix của hợp scope cũ/mới,
trong BEGIN IMMEDIATE, trước commit. Lỗi thiếu tồn có related_entry_id, ngày,
product/warehouse, shortage_kg và line_numbers; rollback cả revision/ledger/audit/
receipt. Tổng kg sản xuất không vượt nguyên liệu đã ghi; điều chỉnh/tồn đầu cần
ghi lý do/căn cứ. Không tự sinh tồn bù hoặc tiền kế toán.

Kg từng dòng/cân lưu integer scale1000 trong records_lines, tiền thương mại lưu
integer scale100 trong records_revisions.commercial_scaled; nullable giữ NULL.
Ledger delta cũng integer. JSON/public DTO luôn chuỗi chính xác; parser core chặn
float/precision/overflow. Tổng báo cáo dùng Python integers, không SQLite SUM
hoặc float. Đơn vị là thông tin hàng hóa; tồn của mọi hàng luôn được ghi bằng kg.

## API additive

Giữ bảy namespace foundation. CRUD units/warehouses nằm dưới /records/products.
Các collection parties/products/weighings/entries và products/units,
products/warehouses có POST create, GET list, GET detail/history, PUT full replace,
DELETE soft-delete và POST detail/restore. entries thêm POST detail/post,cancel.
Mutation dùng request_key; mọi sửa/command cần expected_version. Admin/operator
dùng quyền records.write, không có bước phê duyệt. Core revalidate actor trong
writer transaction kể cả replay. Typed requests/responses được export OpenAPI.

GET list: page/page_size<=500/search/sort/filters(JSON object). Filters hỗ trợ
from_on/through_on/party_id/entry_type/status/active/include_deleted. Sort cho
code/name/occurred_on/updated_at, dấu '-' giảm dần. Search mã/tên/ghi chú toàn tập,
server paging. GET history có paging, snapshot bất biến từng version.

GET stock-movements có paging và filters from_on/through_on/product_id/
warehouse_id/entry_id/entry_type; chỉ effective ledger. Stock-balances nhận
from_on/through_on, cutoff aware optional; response core inventory fields cộng
breakdown theo entry_type với in_kg/out_kg. Receivables nhận as_of/cutoff.
Khoảng ngày gồm hai đầu, ngày nghiệp vụ Việt Nam. occurred_at optional phải có
timezone và thuộc occurred_on theo Asia/Ho_Chi_Minh. Nó là giờ mô tả, không đổi
thứ tự ledger nền theo ngày/sequence.

Cân luôn manual, direct_net hoặc gross_tare; chỉ gross_tare tính tịnh sau kiểm
đủ hai số. Không lưu số cân thiếu thành0 và không tự thay kho. Chọn cân lập phiếu
là thao tác UI chủ động; không sửa cân hoặc hợp đồng snapshot nguồn.

## Provider đọc và root wiring

`RecordsReadProvider(runtime, principal)` export từ module.py, implement đúng
core RecordsReadBridge: lookup_party/get_weighing/inventory_summary/
receivable_summary. Mỗi lần đọc revalidate records.read và dùng snapshot chỉ đọc.
Không bind global principal hoặc trả private tables cho contracts/reporting.
lookup vẫn đọc source inactive/deleted để lịch sử còn tra được. Hai role có quyền
đọc entered party details dùng cho hợp đồng theo nền; không có tài khoản/secret.

Để reporting capture records+accounting trong cùng SQLite snapshot, dùng public
`RecordsReadProvider(runtime, principal).bind_connection(conn)`; constructor cũng
nhận keyword `connection=conn`. Caller lấy connection từ runtime.reader(), gọi
`conn.exec_driver_sql("BEGIN")` trước khi bind, rồi bind accounting provider vào
chính connection đó. Các bridge method giữ nguyên core DTO và không mở/đóng/
commit/rollback connection của caller. Reader yêu cầu PRAGMA query_only=1 và
SQLite transaction thực đang chạy; kết thúc transaction hoặc đóng connection làm
reader từ chối đọc tiếp với READ_ONLY_SNAPSHOT_REQUIRED. Authorization được đọc
trong cùng snapshot, lúc bind và mỗi lần đọc. Không dùng reader này qua thread
khác hoặc dùng nhiều unbound providers thay cho capture chung.

inventory_summary trả InventorySummaryDTO read bridge v2 với breakdown_version=1
và movement_breakdown đủ tám thành phần cho từng scope. Root/reporting dùng
method chuẩn này, không cần đọc extension/private ORM. Extension inventory_breakdown
giữ local detail theo entry_type cho HTTP tương thích UI cũ; nó cũng chứa fields v2.
Unknown source/type/direction/sign trong kỳ giữ cả hai fields phân loại null và
flag inventory_movement_classification_unknown. Tồn đầu trong kỳ thuộc adjustment_in,
có flag opening_entries_in_adjustments. Xem read-bridge-v2.md để biết mapping,
reconciliation và giới hạn phiên bản decoder.
coverage luôn entered_records_only. Công nợ là signed commercial_amount_vnd
người nhập ghi, không phải tiền thu/chi và không tự đối chiếu accounting;
flags commercial_balances_only/accounting_not_reconciled luôn có.

Patch wiring cụ thể ở `wiring.patch`, chỉ là đề nghị để điều phối áp; lane chưa
sửa registry. Không cần dependency mới; sử dụng lockfile và public core sẵn có.

## Migration và chạy trên dữ liệu mới

`backend/cafe_fin/records/migrations/__init__.py` export MIGRATIONS namespace
records/v1/versioned_records_and_ledger, checksum DDL+triggers qua core helper.
Manifest mang migrations theo. Runtime(ModuleRegistry((module_manifest(),))) sẽ
áp core+records trên data root test mới; runtime chung chờ root wiring. Năm bảng
prefix records_: documents/revisions/lines/references/movements. Revision, dòng,
reference và movement chặn UPDATE/DELETE/OR REPLACE bằng immutable triggers;
FK composite bảo vệ revision lineage. Chưa có DB vận hành nào được migrate.
Sau candidate freeze, mọi thay đổi schema phải append migration mới.

## Kiểm chứng và giới hạn

Chi tiết lệnh/kết quả backend trong tests.md, UI/browser trong ui.md. Dữ liệu test
hoàn toàn tổng hợp, SQLite file/WAL thật trong temp. Dependency riêng worktree
được tạo từ lockfile bằng uv sync --frozen và npm ci --offline --ignore-scripts;
không sửa venv chat khác, package/lockfile hoặc shared config.

Mốc v1 trước shared v2: `python -m pytest tests/core tests/records -q
-o faulthandler_timeout=30`:155 PASS/64.19s (86 core+69 records), một warning nền
Starlette/httpx. Ruff/compileall/diff check PASS. Browser real API:1 PASS/17.1s
test,18.4s tổng; nhập100.125→xuất10.001→tồn90.124, overdraw rollback, cân/history
không đổi tồn, explicit link và retry keys đều được kiểm. Typecheck và shell
build PASS; feature build riêng12 modules52.50KB/gzip13.50KB PASS. Cảnh báo chunk
shell>500KB vẫn có. Frontend lint không có command/config ở nền nên NOT RUN.
`git apply --check docs/handoffs/records/wiring.patch` PASS trên baseline lane;
chỉ kiểm patch, chưa áp vào file chung.

Mốc v2 mới nhất: cùng lệnh core+records đạt187 PASS/76.74s (108 core+79 records),
một warning Starlette/httpx. Focused producer v2:10 PASS/5.06s; browser v2 real
API:1 PASS/19.9s tổng. Build/typecheck, Ruff/compileall/diff đều PASS. Feature
v2 bundle12 modules54.60KB/gzip14.05KB PASS. Không đổi migration/dependency.
Chi tiết semantics và shared commit prerequisite ở read-bridge-v2.md.

Bổ sung QA sau c82044d: borrowed reader theo dõi cả transaction epoch của public
SQLAlchemy Connection, không thể hồi sinh qua raw ROLLBACK/COMMIT/END rồi BEGIN
với cùng RootTransaction wrapper. PRAGMA setting/write-enable cũng vô hiệu hóa
reader cũ. Caller vẫn sở hữu transaction và bind mới đọc được snapshot mới.
Không đổi through_on (bao gồm ngày cuối). Xem raw-snapshot-fix.md và tests.md.
Sau fix:131 records tests PASS/61.86s, gồm52 raw-SQL regression cases. Ruff,
compileall và diff check PASS. Bằng chứng core/browser v2 phía trên là mốc trước
patch guard; không suy là đã chạy lại chúng khi core/UI không đổi.

Sau Windows CI42255278298, test cạnh tranh được sửa để chỉ capture hai command
mục tiêu thay vì mọi BEGIN của engine (gồm JobRunner poll). Không đổi source app,
executor hoặc assertion đúng hai connections.20/20 focused subprocess PASS;
full131 records PASS/64.40s; Ruff/compileall/diff PASS. Chi tiết bằng chứng
unrelated writer, lock, ledger/audit/receipts và lệnh kiểm trong tests.md. CI
recovery do root chạy sau khi cherry-pick patch test riêng.

CI harness bỏ port80 bằng commit riêng1b18f3a3298bf22ee8632b9ec59feb264c52eb18:
Vite/browser dev origin127.0.0.1:1421, strictPort, readiness /records-test,
không reuse/kill service khác. Browser local PASS/19.7s; app production Origin/CSP
không đổi. Xem ui.md để biết test-only bootstrap origin seam và port override.

Sau shared DateInput6098a11, mọi native DATE input trong records đã được thay
bằng controlled DateInput DD/MM/YYYY. Raw draft sai được giữ trong parent/Form;
required Form dateInputRule và non-Form guards chặn mutation/query/refetch khi
ngày sai, không gửi lại ISO cũ. Readback cũng DD/MM/YYYY; transport vẫn ISO,
through_on inclusive, ngày Việt Nam và occurred_at timestamp không đổi.
Browser date regression thực PASS1/20.6s; build/typecheck/feature build PASS.
Root đã có shared6098a11 nên chỉ lấy commit adoption lane, không lấy lại local999b2a6.

Sau disabled-context patch3aa94c6, records consumer flow thực trên1421 tiếp tục
PASS1/22.2s tổng, typecheck và feature bundle PASS80.03KB/gzip21.74KB. Chỉ nhận
shared fix được duyệt và cập nhật bằng chứng; không thêm feature/source lane.
Root đã có source3aa94c6 nên không áp lại localb5cbfa5. Root shared tests giữ1420,
records harness giữ1421; không đổi cổng hoặc production Origin/CSP. Chi tiết ui.md.

Bridge v3 hiện thêm product_name/warehouse_name cho inventory items và component
breakdown, từ đúng master kind/name trong cùng read transaction và cutoff. Lookup
theo batch500 unique IDs, không N+1 theo movement hoặc join làm mất scope khi
master thiếu/ngừng/xóa. Tên không đạt kiểu label trả None; IDs/tổng và bytes/hash
snapshot cũ giữ nguyên. Xem read-bridge-v3.md; root chỉ lấy delta lane sau shared206a7e3.
Focused35 PASS/16.77s; full156 records PASS/70.58s; browser/API/WAL1 PASS/20.0s;
Ruff/compileall/diff PASS. Một warning nền Starlette/httpx vẫn có. Chưa push/merge.

Native Tauri GUI/installer/Windows sạch và workflow sau root integration chưa
nghiệm thu ở lane này. Browser harness riêng dùng API/DB thật sẽ ghi tách biệt
với native acceptance; không suy native PASS từ Chromium. Không có test trên DB
cũ/production, không gửi mạng hoặc chứng từ thật.

Backend candidate3e6f0a9 còn được kiểm từ `git archive` riêng tại
`%TEMP%/cafe-fin-records-proof-937bf580db744f57955fa9f67ab7d4f1`: import đã xác nhận
trỏ source archive,58 tests PASS/25.48s. Chạy bằng interpreter/dependencies .venv
của lane, không tự nhận đó là dependency install mới trên máy sạch.
