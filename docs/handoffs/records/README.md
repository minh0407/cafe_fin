# Records candidate trên foundation v1

Worktree: `C:\Users\NC\.codex\worktrees\cafe-fin-records\cafe_fin`.
Branch: `codex/cafe-fin-records-20261106`.
Baseline duy nhất: `cafe-fin-foundation-ready-v1` →
`e668355c227322994902f7e2e38ed7ffb19ff647`.

Chỉ sửa bốn vùng ownership records. Không push/merge/tag, không sửa source/DB cũ.
Backend đăng ký qua `cafe_fin.records.module.module_manifest()`. UI export
`recordsModule` tại `frontend/src/features/records/index.ts`. Registry nền vẫn
chưa ghép records; không coi build shell stub là bằng chứng UI nghiệp vụ.

Candidate lane đã hoàn tất trên baseline phát triển, chờ điều phối tích hợp.
Cherry-pick theo thứ tự: backend ledger `3e6f0a9d0ef4d096ae78302a428e4eb479bd60d6`,
snapshot extension `ba60228cf188f65bb76f1c39fe568d4536a0fc2e`, rồi commit UI/handoff
chứa README này. Danh sách đầy đủ file thay đổi ở files.txt.

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

inventory_summary giữ nguyên InventorySummaryDTO foundation. Extension typed
inventory_breakdown trả InventoryBreakdownDTO (subtype, không đổi core), dùng
cùng snapshot để tách receipt/issue/production/transfer/opening/adjustment. Root
có thể bind extension hoặc duyệt additive shared DTO theo shared-change-request.
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

Kết quả final sau mọi fix: `python -m pytest tests/core tests/records -q
-o faulthandler_timeout=30`:155 PASS/64.19s (86 core+69 records), một warning nền
Starlette/httpx. Ruff/compileall/diff check PASS. Browser real API:1 PASS/17.1s
test,18.4s tổng; nhập100.125→xuất10.001→tồn90.124, overdraw rollback, cân/history
không đổi tồn, explicit link và retry keys đều được kiểm. Typecheck và shell
build PASS; feature build riêng12 modules52.50KB/gzip13.50KB PASS. Cảnh báo chunk
shell>500KB vẫn có. Frontend lint không có command/config ở nền nên NOT RUN.
`git apply --check docs/handoffs/records/wiring.patch` PASS trên baseline lane;
chỉ kiểm patch, chưa áp vào file chung.

Native Tauri GUI/installer/Windows sạch và workflow sau root integration chưa
nghiệm thu ở lane này. Browser harness riêng dùng API/DB thật sẽ ghi tách biệt
với native acceptance; không suy native PASS từ Chromium. Không có test trên DB
cũ/production, không gửi mạng hoặc chứng từ thật.

Backend candidate3e6f0a9 còn được kiểm từ `git archive` riêng tại
`%TEMP%/cafe-fin-records-proof-937bf580db744f57955fa9f67ab7d4f1`: import đã xác nhận
trỏ source archive,58 tests PASS/25.48s. Chạy bằng interpreter/dependencies .venv
của lane, không tự nhận đó là dependency install mới trên máy sạch.
