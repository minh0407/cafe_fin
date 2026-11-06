# Đăng ký job và startup recovery của module

Đã bổ sung interface tối thiểu để lane thêm job/recovery hook qua manifest thay vì sửa core Runtime. Không có autodiscovery từ thư mục hoặc nạp plugin tùy ý.

`ModuleManifest` giữ các trường migration/router/permissions/dependencies hiện có và thêm:

```python
job_handlers: Mapping[str, JobHandler]  # mặc định rỗng, snapshot immutable khi tạo manifest
on_startup: Callable[[Runtime], None] | None  # mặc định None, hook đồng bộ
```

Tên job phải bắt đầu bằng `module.id + '.'` và có hậu tố. Registry kiểm handler là `JobHandler` có callable run. Runtime merge các handler này với `foundation.sample` và từ chối collision; module không ghi đè job core. Hook/module definitions là code tin cậy được điều phối đăng ký explicit.

Ví dụ module-owned `module.py`:

```python
def reconcile(runtime: Runtime) -> None:
    # Đọc module-owned attempts/checkpoint, sau khi core đã đánh dấu jobs dở.
    with runtime.reader() as conn:
        references = load_own_job_references(conn)
    for reference in references:
        status = runtime.jobs.status(reference.job_id)
        reconcile_own_attempt(runtime.writer, reference, status)

def run_import(context: JobContext, payload: dict) -> None:
    # Payload tham chiếu immutable snapshot; không chứa toàn bộ workbook.
    # Ghi ngắn qua context.commit_chunk, công bố qua context.finalize.
    ...

def module_manifest() -> ModuleManifest:
    return ModuleManifest(
        'sample', '/sample',
        permissions=('sample.read', 'sample.write'),
        migrations=MIGRATIONS,
        router=router,
        job_handlers={'sample.import': JobHandler(run_import, resumable=True)},
        on_startup=reconcile,
    )
```

Điều phối thêm manifest vào registry; không cần sửa core Runtime/JobService cho loại job mới. Module tự giữ migration có checksum và bảng prefix riêng. Router được API core gắn theo prefix/quyền module; hook không phải một API public nhận đường dẫn hoặc thực thi mã từ workbook.

Thứ tự boot:

1. Constructor khóa data root, chạy core/module migrations theo dependencies và tạo public services.
2. `Runtime.start()` gọi `jobs.recover_interrupted()`.
3. Chạy `on_startup(runtime)` theo thứ tự module dependencies, trước worker thread.
4. Khởi động runner. Recovery core được runner gọi lại; lần thứ hai không đổi WAITING/RECOVERABLE jobs của hooks.

Hook có `runtime.reader()` (read-only Connection context), `writer`, `files`, `auth`, `jobs`, cùng các services Runtime hiện có. Hook phải đồng bộ, idempotent theo dữ liệu bền vững và không giữ transaction trong lúc CPU/file/network dài. Hỏng hook phải propagate lỗi, không báo startup thành công; worker chưa được chạy. Tự resume job là lựa chọn rõ của module/hook dựa vào checkpoint và khả năng idempotency, không mặc định chạy lại mọi job.

`tests/core/test_module_registration.py` có một module tổng hợp tự khai báo migration/router/job/recovery hook chỉ qua constructor `ModuleRegistry`. Test lưu một job RUNNING, đóng/mở Runtime, chứng minh hook thấy RECOVERABLE trong lúc runner chưa chạy, dùng reader/writer/files/auth/jobs, resume job thành COMPLETED và đọc effect qua HTTP router được bảo vệ. Đóng/mở lần nữa giữ nguyên job/effect bền vững. Các test khác kiểm frozen handler map, prefix/type, collision core, dependency hook order và hook lỗi không khởi động worker.

Lệnh kiểm tra:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/core/test_module_registration.py -q
.\.venv\Scripts\python.exe -m pytest tests/core -q
.\.venv\Scripts\python.exe -m ruff check backend/cafe_fin/core/modules.py backend/cafe_fin/core/runtime.py tests/core/test_module_registration.py
```

PASS: 4 module-registration tests; toàn core 66 tests trong 19.67 giây, một deprecation warning FastAPI/Starlette TestClient về httpx; Ruff PASS. Không thay schema/API/entrypoint/registry hoặc dependency trong lượt bổ sung này.

## Ranh giới HTTP cho module jobs

Job registration không mở một API nhận raw payload tùy ý. HTTP core `POST /api/v1/jobs` và các endpoint generic cancel/resume chỉ phục vụ job proof `foundation.sample`. Với job module đã đăng ký, cả Admin và Operator đều nhận `MODULE_JOB_ENDPOINT_REQUIRED` nếu dùng các endpoint generic này. Không thể bỏ qua module validator, confirmation snapshot hoặc quyền riêng bằng `jobs.write` và một dict payload.

Lane phải cung cấp endpoint trong router của module, dùng DTO/input validation rõ ràng, kiểm permission phù hợp, xác minh snapshot/confirmation và state transitions rồi gọi `runtime.jobs.submit/cancel/resume` với authorizer trong transaction. Core JobService vẫn là service dùng chung cho code module tin cậy; không phải boundary public thay thế các bước này.

HTTP generic `GET /api/v1/jobs/{id}` yêu cầu `jobs.read`; job module còn yêu cầu `{kind-prefix}.read`. Ví dụ job `sample.privileged` cần `sample.read`, nên Operator mặc định không xem được status đó. Admin có thể xem status theo quyền nhưng vẫn không mutate job qua generic endpoints. `foundation.sample` giữ quyền jobs.read/write cho Operator để chạy proof.

`tests/core/test_api_job_boundaries.py` chạy 3 cases PASS, Ruff PASS trên API thực qua TestClient: registered privileged module job không được generic submit/cancel/resume kể cả Admin, các lời gọi bị chặn không tạo job hoặc thay trạng thái, Operator thiếu sample.read bị chặn status, trusted module service vẫn chạy job đến COMPLETED, và Operator vẫn generic submit/cancel/resume/read `foundation.sample` đến COMPLETED. Các test dùng worker/thread/SQLite thật và snapshot tổng hợp.
