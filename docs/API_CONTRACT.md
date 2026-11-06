# Hợp đồng tích hợp giữa các module cafe_fin

Đây là contract thiết kế v1. Foundation cụ thể hóa bằng models/types và test schema trước tag foundation; mọi đổi ngữ nghĩa sau đó cần điều phối duyệt và cập nhật tất cả consumer. Không tự coi endpoint mới chưa có code là đã chạy được.

Điều phối bổ sung [read bridge revision 2](handoffs/foundation/read-bridge-v2.md) sau baseline: phân loại biến động kho và ý nghĩa chỉ tiêu tiền là optional typed fields. Các lane áp commit cập nhật do điều phối cung cấp; không đổi tag foundation hoặc tự sửa shared types. Đây là phiên bản DTO read bridge, không đổi prefix REST `/api/v1`.

## Quy ước chung

- REST local `/api/v1`, loopback session auth; file native qua IPC allowlist hoặc file ID. Không đưa absolute file path bất kỳ từ client vào hàm đọc tệp.
- Entity: `id` UUID string, `version` integer, `created_at`/`updated_at` UTC ISO, `created_by`/`updated_by`, `deleted_at` nullable khi áp dụng. `occurred_on` là ngày nghiệp vụ `YYYY-MM-DD`, `recorded_at` là thời điểm nhập; `physical_actor` là dữ liệu mô tả riêng.
- Sửa/xóa gửi `expected_version`. Lệnh tạo/ghi/import confirm gửi `request_key`; server gắn key với canonical payload và actor/action phù hợp. Conflict không dùng 200 giả thành công.
- Tiền và kg JSON là Decimal string, đọc/ghi qua core Amount helpers; scale/miengia theo ARCHITECTURE. Empty, zero và thiếu dữ liệu khác nhau.
- Khoảng ngày nghiệp vụ `from_on`/`through_on` bao gồm cả hai đầu; một ngày có `from_on == through_on`. Query timestamp UTC tương ứng dùng `[00:00 ngày đầu Việt Nam, 00:00 sau ngày cuối Việt Nam)`. Producer và báo cáo dùng cùng nghĩa này; không truyền ngày cuối exclusive dưới tên `through_on`.
- Danh sách: `page`, `page_size` tối đa 500, `search`, `sort`, `filters` có schema validate. Trả `items`, `total`, `page`, `page_size`; truy vấn lớn có cursor/range endpoint riêng. Lọc/sort thực hiện trên toàn bộ tập ở server.
- Lỗi: `error.code`, `error.message`, `error.field_errors[]`, `error.details`, `request_id`. Mỗi field error có `field`, `code`, `message`; không trả stack trace hoặc secret.
- Audit đổi dữ liệu ở cùng transaction, có before/after, actor, entity, action và thời điểm. Soft delete không làm biến mất các tệp xuất hoặc lineage import.

## Services core foundation cung cấp

| Interface | Ý nghĩa |
|---|---|
| DataRootService | Đường dẫn chuẩn và kiểm containment; chọn/mở/đổi data root qua quyền native |
| FileStore | put/read/export theo file ID, hash, immutable original, metadata; không public raw directory |
| WriteCoordinator | Transaction ghi ngắn, busy timeout/backpressure; không mở transaction qua UI/network |
| AuditService | Ghi thay đổi cùng transaction; truy lịch sử có phân trang |
| JobService | Job ID, state, phases, progress counts, checkpoint, cancel/resume và event/status polling |
| IdempotencyService | request key cùng payload trả kết quả cũ; khác payload conflict |
| BackupService | Snapshot DB+tệp nhất quán, manifest, verify và restore vào root mới |
| ModuleRegistry | Backend module.py register và frontend feature index.ts theo manifest/type ổn định |
| Amount/BusinessTime | Decimalstring/scale chính xác và ngày giờ VN thống nhất |

Core là owner của session/auth/settings data root/jobs/files/backup APIs. Module chỉ gọi public services, không duplicate file/auth/job runners.

## Namespace của module

| Module | API prefix | Nội dung |
|---|---|---|
| records | `/records` | `/parties`, `/products`, `/weighings`, `/entries`, `/stock-movements`, `/stock-balances`, `/receivables` |
| contracts | `/contracts` | CRUD hợp đồng, templates, versions, exports, attachments và preview |
| accounting | `/accounting` | books, schemas, rows, source-files, import-jobs, staging rows, mapping, validation, confirm, errors, exports |
| reporting | `/reporting` | daily reports, snapshots, local exports, schedules, delivery config, attempts và sender status |

Foundation có thể tạo router/interface stub rõ NOT_IMPLEMENTED để smoke shell, không dùng stub cho nghiệm thu module. Shared OpenAPI export thực tế được freeze tại tag foundation và bổ sung additive theo module; mọi endpoint dùng chung đổi tên phải phối hợp.

## DTO read bridge không làm ghi chéo module

- `records.lookup_party(id)` trả PartyDTO: id/version/type/name/tax_code/address/contacts/bank_details/representative theo quyền; không tự ghi vào hợp đồng.
- `records.get_weighing(id)` trả WeighingDTO: id/version/code/occurred_on/party_id và lines với product_id/description/gross_kg/tare_kg/net_kg/quantity_source/note. Nullable đúng nghĩa; không suy kg thiếu thành 0.
- `records.inventory_summary(from,to)` và `records.receivable_summary(as_of)` trả dữ liệu tổng hợp có `coverage='entered_records_only'`, cutoff và số liệu Decimal strings.
- `accounting.book_summary(book_id,from,to)` chỉ trả chỉ tiêu có mapping hợp lệ, coverage/validation flags; không auto diễn giải arbitrary text thành tiền.
- Contracts nhận embedded PartyInput và WeightLineInput thủ công độc lập. `source_refs[]` tùy chọn chứa type/id/version; snapshot là bản hợp đồng người dùng đã xác nhận lưu, không đọc live khi tải lại bản xuất.
- Reporting chỉ dùng DTO/services read-only này, không viết bảng stock/accounting/contracts. Link trong tin gửi không trỏ localhost hoặc file path.

Tên hàm Python có thể được foundation chuẩn hóa trong type contract nhưng giữ các trường và ý nghĩa; lane không import service private rồi đoán field.

## Contract import accounting

Job state chính: `UPLOADED`, `PARSING`, `READY_FOR_MAPPING`, `VALIDATING`, `READY_FOR_CONFIRM`, `COMMITTING`, `PARTIALLY_COMMITTED`, `COMPLETED`, `CANCELLED`, `FAILED`, `RECOVERABLE`. State và phase không đồng nhất; foundation cùng lane accounting phải có transition test thực tế.

Staging row có `row_id`, `source_sheet`, `source_row`, `revision`, raw values, edited values, typed values và `issues[]`. Issue có sheet/row/column/cell, code, severity, message, suggestion. Các sửa đổi không được thay số dòng nguồn.

Confirm pin `job_id`, `staging_revision`, `mapping_revision`, `decision_revision`, `validation_token`, `mode='valid_rows_only'`, `duplicate_decisions`, `request_key`. Server xác minh chính xác tập row và choices; không tin boolean client `is_valid`.

Mỗi confirm tạo `attempt_id` với staging/mapping snapshot bất biến hoặc copy-on-write và saved selection manifest. Mỗi chunk có ID, source-row range hoặc set, count/hash và committed marker cùng transaction với pending rows. Một transaction ngắn cuối cùng đặt attempt PUBLISHED sau kiểm tập/counts; mọi query sổ/report/CRUD dùng predicate hiển thị chung, không cho pending rows hiện như đã nhập. Core/lane phải kiểm điều này ở integration tests.

Identity `(job_id, source_row_id)` theo nguồn ổn định không tạo lặp khi retry hoặc sửa lỗi để nhập tiếp; row đã published giữ target ID. Có bảng claim/receipt attempt kiểm soát retries và concurrent attempts cho cùng source row. Sửa dòng chưa nhập tạo revision mới cho lượt xác nhận sau, không sửa snapshot của worker đang chạy. Sửa dòng đã nhập dùng CRUD/version riêng, không tự nhập thêm bản thứ hai.

Counts: source rows, validated, valid, invalid, potential duplicates, conflicts, excluded, staged_committed_rows, published_rows, pending. Quy tắc đếm có test, hiển thị rõ tập giao nhau nếu issue là cờ phụ; không cộng các nhãn chồng lấn thành tổng sai. Chọn dòng lớn bằng manifest phía server, không gửi triệu ID trong confirm.

Kết quả phân biệt đã ghi pending, đã công bố, lỗi và phần chờ; lỗi sau chunk đã commit không được nói rollback toàn file hoặc nói pending là đã nhập thành công. Undo batch kiểm version của row đã sửa sau import và chỉ ra conflict, không xóa bừa.

## Giấy phép và công thức

Foundation spike ghi license/version của grid và evaluator trong ADR. Lane accounting chỉ thêm dependency đã được duyệt hoặc gửi đề xuất thay đổi shared manifest. Không dùng formula result cache để giả là đã tính lại; unsupported, circular reference và range quá lớn có code lỗi riêng. Không chạy VBA, external link, arbitrary script hoặc network formula.
