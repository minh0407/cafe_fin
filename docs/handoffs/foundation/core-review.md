# Core review và regression fixes

Các thay đổi dưới đây nằm trong lane foundation, chỉ dùng dữ liệu tổng hợp. Không sửa runtime/API/main trong lượt review này; root tích hợp các consumer đó.

## Writer, jobs và auth

- `Database.read()` bật SQLite `query_only=ON` trên connection riêng dùng NullPool. Reader/report không thể vô tình ghi ngoài serialized writer. Migration và writer vẫn dùng connection ghi riêng.
- `JobRunner` retry riêng lỗi `WRITER_BUSY` khi claim và finish với backoff 50 ms. Finish của job đã claim vẫn chờ ghi trạng thái bền vững khi app đang đóng. Không bỏ final state khi writer tạm đầy.
- Lỗi không phải backpressure dừng runner và đặt `runner.error_code`: mã CoreError hoặc `JOB_RUNNER_FAILED` cho exception khác. Không trả traceback, payload hoặc text exception. Runtime health cần coi runner chết/error_code là degraded. Không retry lỗi lập trình vô hạn.
- Runner kiểm cancellation trước khi gọi handler. Việc commit/finalize vẫn kiểm lại cancellation trong writer transaction theo contract hiện có.
- Login reserve mỗi attempt bằng `(monotonic timestamp, unique object)` để giới hạn brute force đồng thời; login thành công gỡ đúng reservation. Tám login thành công không làm khóa đăng nhập như tám lần sai.

## Migration signature và thứ tự

`core/modules.py` cung cấp:

```python
schema_checksum(metadata, statements=()) -> str  # SHA-256 lowercase hex
```

Helper compile SQLite CREATE TABLE và CREATE INDEX, sort theo tên bảng/index, kèm các SQL statements bổ sung theo thứ tự khai báo. Trigger SQL của import được tách thành `IMPORT_TRIGGER_STATEMENTS`; chính tuple đó vừa được apply vừa được hash. Không đọc source runtime, nên dùng được trong frozen sidecar.

Các migration thật `core`, `core_auth`, `core_jobs`, `core_files`, `core_imports` đều khai báo checksum explicit. `ModuleRegistry.register` từ chối migration thiếu checksum hoặc không phải 64 ký tự SHA-256 hex. `Database.migrate` giữ fallback name hash cho utility/dummy tests không đi qua module registry; production Runtime phải dùng các migration explicit nêu trên.

Module mới đăng ký ví dụ:

```python
MIGRATIONS = (Migration(
    "sample", 1, "initial sample tables", schema_v1.create_all,
    checksum=schema_checksum(schema_v1),
),)
```

Với ALTER/data migration, đưa chính SQL statements vào chữ ký và apply cùng tuple. Sau baseline, giữ nguyên metadata/SQL của migration lịch sử; thêm version mới. Không dùng metadata hiện hành đang thay đổi để tính lại chữ ký v1 đã áp dụng. Chữ ký phát hiện code/migration schema khác với registry đã ghi; đây không phải cơ chế chống sửa DB thủ công hoặc hash toàn bộ dữ liệu.

Runner migration sort version tăng dần **trong mỗi namespace**, giữ namespace theo thứ tự xuất hiện đầu tiên mà registry đã sắp dependency. Tuple `(parent v2,parent v1,child v2,child v1)` áp dụng `parent v1→v2`, rồi `child v1→v2`; regression có ALTER và foreign-key insert thật để chứng minh thứ tự.

Chữ ký explicit mới sẽ khác DB tổng hợp được tạo bởi candidate cũ chỉ hash name. Chưa có foundation baseline; dùng data root tổng hợp mới cho smoke mới, không nới checksum guard hoặc sửa DB thật để làm test pass.

## Không tự tạo DB thay thế

`Database(path, *, create=True)` hỗ trợ bootstrap explicit một lần. Runtime mở root đã cấu hình phải gọi `create=False`; root triển khai call site này.

- Engine dùng SQLite URI `mode=rw`, percent-encode đường dẫn, giữ Unicode/khoảng trắng và các ký tự `%`, `#`, `&` chính xác.
- Khi DB bị rename/delete sau startup, kết nối sau thất bại thay vì tạo DB rỗng tại đường dẫn cũ.
- `create=False` từ chối DB không tồn tại (`DATABASE_MISSING`), tệp 0 byte hoặc DB SQLite không có core registry (`DATABASE_INVALID`). Không bootstrap các bảng Cafe Fin lên DB không nhận diện.
- `backup_to` cũng mở nguồn bằng URI `mode=rw`; nguồn mất không tạo một DB nguồn rỗng hoặc snapshot giả.

## Bằng chứng

`tests/core/test_review_edges.py` có 15 regression cases thực dùng SQLite/file/thread/process, gồm ba lỗi đầu đã chạy FAIL trước sửa. Thử đường dẫn và rename/delete chạy trên Windows 11 thực, không mock filesystem. Signature của các migration thật được đối chiếu giữa process hiện tại và subprocess Python mới.

Lệnh cuối:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/core -q
.\.venv\Scripts\python.exe -m ruff check backend/cafe_fin/core/modules.py backend/cafe_fin/core/db.py backend/cafe_fin/core/auth.py backend/cafe_fin/core/jobs.py backend/cafe_fin/core/storage.py backend/cafe_fin/core/imports.py tests/core/test_review_edges.py
```

PASS: 51 tests toàn core, 13.13 giây; Ruff PASS. Có một warning deprecation từ FastAPI/Starlette TestClient về httpx; không có test fail. Runtime: Python 3.12.16, SQLite 3.53.1, SQLAlchemy 2.1.8 trên Windows 11 Pro 10.0.26200.

Các kết quả này không thay nghiệm thu bộ cài/Windows sạch, mất điện vật lý hoặc benchmark import triệu dòng.
