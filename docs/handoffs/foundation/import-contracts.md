# Import primitives, read bridges và stock guard

Phạm vi foundation: các primitive và DTO dùng chung; không có nghiệp vụ kế toán, ledger sản xuất, validation workbook hoặc endpoint import production.

## Public interfaces

`backend/cafe_fin/core/contracts.py` cung cấp DTO Pydantic frozen, strict và `extra='forbid'`, `CONTRACT_VERSION=1`:

- `PartyInput` độc lập với liên kết CRM; `PartyDTO` thêm id/version. `type` là classification của owner, `roles` là tuple nhiều vai trò duy nhất. Contacts, bank accounts và representative là DTO con; consumer phải lọc các trường nhạy cảm theo quyền trước khi trả bridge.
- `WeightLineInput` giữ khác biệt `None` và `"0.000"`; không tự suy hoặc ghi đè net từ gross/tare. Kg của dòng đi qua Amount helper, không nhận float. `WeighingDTO` giữ source date/party và tuple dòng.
- `SourceReference` là type/id/version tùy chọn để lane contracts lưu snapshot. Không đọc live để thay bản xuất cũ.
- `RecordsReadBridge`: `lookup_party`, `get_weighing`, `inventory_summary(from_on,through_on,cutoff=...)`, `receivable_summary(as_of,cutoff=...)`. `AccountingReadBridge.book_summary(...)` riêng. Protocol không cung cấp write method.
- Các summary có cutoff aware datetime được chuẩn hóa UTC, `coverage='entered_records_only'`. Accounting không xuất metric tiền nếu chưa có mapping hợp lệ. Chuỗi tổng hợp tiền/kg có thể vượt int64 nhưng vẫn đúng scale và không chuyển float; Amount helper của giá trị ghi từng dòng vẫn chặn int64.
- `ImportJobState`, `ImportIssueDTO`, `ImportCountsDTO`: counts không cộng các nhãn nghi trùng/xung đột/loại như các tập rời nhau. `pending = staged_committed_rows - published_rows`; published không vượt staged. State/phase của job và state của attempt là hai khái niệm riêng.

## Migration và cách tích hợp

`core/imports.py` export `MIGRATIONS`, namespace `core_imports`, version 1. Core registry phải đưa tuple này vào `Database.migrate(...)` trước khi tạo JobService/readers.

Các bảng:

- `core_import_manifests`: job, pins JSON, expected count, row count, rolling SHA-256, BUILDING/SEALED.
- `core_import_manifest_rows`: ordinal, source-row identity và JSON snapshot bất biến gồm source sheet/row, row revision, raw/edited/typed values.
- `core_import_attempts`: manifest ID duy nhất, job ID, state, expected/staged/published counts, checkpoint, timestamps.
- `core_import_claims`: unique `(job_id, source_row_id)`, target UUID ổn định, attempt/ordinal. Một job mới có thể cố ý nhập một giao dịch nội dung giống; retry/sửa lỗi của job cũ không tạo target thứ hai.
- `core_import_receipts`: attempt/chunk, ordinal start/count, hash và thời điểm commit; unique attempt/start.

SQLite triggers khóa manifest/pins sau seal, cấm sửa/xóa snapshot rows, cấm thay attempt pins, sửa/xóa receipt hoặc sửa claim. Check constraints buộc checkpoint bằng staged count và chỉ attempt PUBLISHED mới có published count.

Mọi method dưới đây nhận SQLAlchemy `Connection` từ `WriteCoordinator.run/execute`, không tự commit và không mở writer lồng nhau:

```python
service = ImportAttemptService()
# Cần validation/COW server-side trước bước này; không tin client is_valid.
manifest_id = writer.run(lambda conn: service.create_manifest(
    conn, job_id=job_id, pins=pins, expected_count=selection_count))
# Lặp từng chunk <=500 từ immutable server-side selection, không gửi triệu ID từ UI.
writer.run(lambda conn: service.append_manifest_chunk(
    conn, manifest_id, expected_start=0,
    rows=[ManifestRow(source_row_id, row_snapshot)]))
fingerprint = writer.run(lambda conn: service.seal_manifest(conn, manifest_id))
# Dùng writer.execute với actor/action/request_key/canonical payload cho endpoint confirm.
attempt_id = writer.run(lambda conn: service.create_attempt(
    conn, manifest_id, fingerprint=fingerprint))
writer.run(lambda conn: service.commit_chunk(
    conn, attempt_id, chunk_id="chunk-0001", start=0, count=1,
    write_pending=accounting_insert_pending))
writer.run(lambda conn: service.publish(conn, attempt_id))
```

`pins` bắt buộc có `staging_revision`, `mapping_revision`, `decision_revision`, `validation_token`, `mapping_snapshot`, `duplicate_decisions`, `mode='valid_rows_only'`. Ba revision là số nguyên dương. Snapshot row bắt buộc giữ `source_sheet`, `source_row` nguyên dương, `revision` nguyên dương, `raw_values`, `edited_values`, `typed_values` dạng mapping. Core copy JSON vào DB; thay object/staging sau đó không đổi snapshot.

Core **không sở hữu staging/validator của accounting**. Accounting phải freeze/COW revision trước khi xây manifest, đối chiếu validation token với đúng tập và choices từ server, và không đọc lẫn các revision staging đang thay đổi. Manifest builder giúp chia nhỏ việc lưu snapshot; seal/confirm/publish không scan hoặc copy toàn bộ tập.

`commit_chunk` chỉ nhận ordinal range, không nhận payload tùy ý của client. Callback `accounting_insert_pending(conn, attempt_id, rows)` nhận tuple `PendingImportRow(source_row_id,target_id,ordinal,snapshot)`. Callback phải ghi đúng một target cho mỗi row, lưu `import_attempt_id`, propagate lỗi và không commit. Callback, claims, receipt, counters và checkpoint nằm trong cùng writer transaction. Core không thể tự kiểm số dòng bảng domain chưa được lane định nghĩa; lane phải có integration test cho invariant này. Retry cùng chunk/range trả cùng target IDs và không gọi callback; dùng chunk ID cho range khác báo conflict.

Các truy vấn accounting sau này phải dùng predicate sau cho **list, detail, CRUD precondition, count/sum, export và report**:

```python
select(accounting_rows).where(
    visibility_predicate(accounting_rows.c.import_attempt_id))
```

`NULL` dành cho dòng nhập tay; attempt pending/failed/cancelled không xuất hiện. Chỉ `publish` khi checkpoint và staged count đủ expected count mới đổi một attempt thành PUBLISHED bằng transaction ngắn. Những attempt đã công bố giữ nguyên khi lượt tiếp theo lỗi.

`set_interrupted(conn,id,'FAILED'|'CANCELLED'|'RECOVERABLE')` giữ pending/claims/receipt. `resume` explicit đưa về PENDING; không publish trực tiếp từ trạng thái dừng. Worker/core job recovery cần gọi primitive này khi phát hiện attempt dở. Hiện không tự cleanup/abandon pending và không nhả claims: giữ dữ liệu để resume an toàn. Muốn dọn bỏ phải có luồng riêng do accounting sở hữu, xác minh và xóa target pending theo chunk, không nhả claim khi target vẫn còn. Không có API undo batch hoặc xóa bản published trong foundation.

## Stock guard

`StockPoint(id,occurred_on,order_key,delta_scaled)` dùng kg scale 3, int64. Records cấp `order_key` một lần và giữ khi chỉnh sửa. Thứ tự toàn phần là `(occurred_on,order_key,id)`; loader phải ORDER BY đúng thứ tự này.

`assert_nonnegative(points,opening_scaled=0,scope='...')` stream các điểm, kiểm int64 ở từng delta và tổng trung gian, chặn prefix âm và báo `related_entry_id`/ngày/scope/số dư. Không chỉ kiểm closing balance.

`guard_stock_mutation(conn,mutation,affected_scopes)` chạy mutation rồi kiểm toàn bộ scope trong cùng writer transaction. Records phải capture hợp của scope cũ/mới trước mutation và tải lại chuỗi đầy đủ cho mỗi warehouse/product bị ảnh hưởng, kể cả edit/delete/backdate/restore/transfer. Audit ghi cùng transaction và lỗi guard phải propagate ra writer để rollback. Foundation không tạo bảng ledger production hoặc thay balances trực tiếp.

## Kiểm chứng thực tế

Máy: Windows 11 Pro 10.0.26200; Python 3.12.16, SQLite 3.53.1, SQLAlchemy 2.1.8, Pydantic 2.14.3 trong `.venv` của worktree. Chỉ dùng DB/rows tổng hợp ở pytest temporary directories.

Lệnh:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/core/test_imports.py tests/core/test_stock_guard.py -q
.\.venv\Scripts\python.exe -m ruff check backend/cafe_fin/core/imports.py backend/cafe_fin/core/contracts.py backend/cafe_fin/core/stock_guard.py tests/core/test_imports.py tests/core/test_stock_guard.py
```

PASS: 17 tests. Các hành vi đã chạy gồm immutable snapshot/trigger, pending visibility list/detail/count/CRUD/join, atomic publish, receipt retry/conflict, callback failure rollback domain/claim/receipt/count/checkpoint, hai attempt cạnh tranh một source identity, claim giữ sau publish, job mới độc lập, failed/cancelled/recoverable cần resume, DTO nhiều vai trò/null/exact aggregate, stock delete/backdate/reduce rollback cả ledger và audit, cùng ngày stable order, int64 intermediate overflow và float rejection.

PASS: test subprocess thật ghi một chunk, `os._exit(17)` không shutdown trật tự, process mới kiểm checkpoint, resume rồi publish đúng hai target không lặp. Đây là crash sau chunk commit; không phải thử mất điện vật lý hoặc kill giữa SQLite fsync.

NOT RUN trong phần này: validator/staging accounting thật, truy vấn module production, import 500k/1m, undo/cleanup pending, toàn bộ state transition accounting job, Windows sạch/bộ cài. Các test primitive không chứng minh các nghiệm thu đó.
