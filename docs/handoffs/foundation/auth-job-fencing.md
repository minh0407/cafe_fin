# Review bổ sung: job generation, quyền trong transaction và immutable REPLACE

Đã đọc repro do điều phối cung cấp tại snapshot `1062876`, copy/adapt các test tổng hợp vào `tests/core/test_review_auth_jobs_edges.py`. Không sửa snapshot bên ngoài worktree.

## Public interfaces additive

- `Principal.version` mặc định 1; `Principal.public()` trả thêm version và principal đọc từ DB dùng version hiện tại.
- `AuthService.authorize(conn, principal, permission)` kiểm lại tài khoản tồn tại/active, role và version trong **transaction ghi thực sự**, rồi dùng quyền lấy lại từ DB. Principal đã bắt ở request entry không đủ sau khi chờ hashing hoặc hàng đợi writer.
- `WriteCoordinator.execute(..., *, authorize=None)` chạy callback này trước cả tra cứu idempotency receipt. Tài khoản bị thu hồi không lấy lại kết quả cached của mutation cũ.
- `JobService.submit(..., authorize=None)`, `cancel(..., authorize=None)`, `resume(..., authorize=None)` đưa authorizer vào transaction. Mặc định None phục vụ trusted internal services/tests; API/module mutation phải truyền authorizer. Background worker đã nhận một job được xác nhận dùng generation lease và tiếp tục theo snapshot, không kiểm quyền user trong từng chunk.
- `JobContext(..., generation=None)` capture generation hiện tại nếu caller cũ không truyền. Runner luôn truyền generation từ chính claim; module handler dùng context được runner cấp, không tự dựng context mới để thay lease.

Ví dụ module mutation:

```python
writer.execute(
    principal.id, "sample.update", request_key, payload, operation,
    authorize=lambda conn: auth.authorize(conn, principal, "sample.write"),
)
```

Quyền `reporting.write` đã được thêm cho Operator để tạo/xuất báo cáo local. Credential/sender settings vẫn phải dùng quyền quản trị. Không cấp `example.read/write` mặc định cho Operator.

## Generation fencing

`core_jobs.generation` được lưu bền vững và tăng mỗi lần claim. Status trả generation; context giữ giá trị lease của lần chạy. Check cancellation/checkpoint, chunk và finalize đều yêu cầu cùng generation, RUNNING, chưa cancel và chưa stop. Chunk/finalize kiểm lại trong writer transaction.

Worker finish chỉ cập nhật state khi generation còn đúng và state còn RUNNING. Worker cũ không đổi job mới về FAILED/RECOVERABLE/COMPLETED sau chuỗi cancel → recover → resume → claim mới, kể cả khi handler cũ trả về hoặc ném lỗi muộn.

Thay đổi cột generation làm đổi checksum schema jobs v1 trong **candidate trước baseline**. Không có DB vận hành được nâng cấp trong lượt này; data root tổng hợp cũ phải dùng root mới. Không tự sửa checksum registry hoặc mở guard để đọc candidate cũ như schema mới. Sau foundation baseline, mọi thay đổi tương tự cần migration version mới giữ nguyên lịch sử.

## INSERT OR REPLACE và trigger

Mọi engine connection bật `PRAGMA recursive_triggers=ON`; connection nguồn/đích của SQLite backup cũng bật setting này. SQLite REPLACE thực hiện implicit DELETE, nên setting này cần thiết để trigger cấm xóa manifest/row bất biến cũng chặn REPLACE. Trigger SQL hiện có được giữ nguyên, không cần thay API import.

## Kiểm chứng

```powershell
.\.venv\Scripts\python.exe -m pytest tests/core/test_review_auth_jobs_edges.py -q
.\.venv\Scripts\python.exe -m pytest tests/core -q
.\.venv\Scripts\python.exe -m ruff check backend/cafe_fin/core/db.py backend/cafe_fin/core/auth.py backend/cafe_fin/core/jobs.py tests/core/test_review_auth_jobs_edges.py
```

PASS: 7 regression cases mới. Các trường hợp gồm writer capacity 1, stale context chặn check/checkpoint/chunk/finalize, stale finish không đổi generation mới, một admin thu hồi admin khác trong lúc Argon2 hash bị giữ tại barrier, authorizer chặn cached retry/job controls, và `INSERT OR REPLACE` với sealed manifest/sealed row/building row đều bị DB trigger chặn mà không thay snapshot.

PASS: toàn core **61 tests**, 18.95 giây; Ruff PASS. Có một deprecation warning FastAPI/Starlette TestClient về httpx. Các thử nghiệm chạy DB/thread/hash/SQLite thật với dữ liệu tổng hợp trên Windows 11, Python 3.12.16 và SQLite 3.53.1. Đây không phải nghiệm thu Windows sạch, bộ cài hoặc benchmark triệu dòng.
