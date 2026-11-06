# Records: bằng chứng kiểm thử backend candidate

Worktree: `C:\Users\NC\.codex\worktrees\cafe-fin-records\cafe_fin`.
Baseline: `cafe-fin-foundation-ready-v1`, peeled
`e668355c227322994902f7e2e38ed7ffb19ff647`.

Tất cả fixture tạo data root mới trong pytest temporary directories. Không dùng
source/DB cũ, dữ liệu doanh nghiệp, network service hoặc SQLite in-memory.
Các endpoint chạy qua FastAPI thật, app-session và tài khoản local thật,
SQLAlchemy, core writer và SQLite file/WAL. Native desktop không được mock rồi
ghi là đã nghiệm thu; kiểm thử UI/native được bàn giao riêng.

## Kết quả của nhóm test này

```powershell
.\.venv\Scripts\python.exe -m pytest tests/core tests/records -q -o faulthandler_timeout=30
# Final sau toàn bộ fix: 155 passed, 1 warning in 64.19s (86 core +69 records).
.\.venv\Scripts\python.exe -m pytest tests/records -q -o faulthandler_timeout=20
# PASS: 67 passed, 1 warning in 33.08s
# Trước bổ sung guard transaction identity và hai case commit/rollback rồi BEGIN mới.
.\.venv\Scripts\python.exe -m pytest tests/records/test_records_shared_snapshot.py -q -o faulthandler_timeout=20
# PASS sau fix transaction identity: 11 passed, 1 warning in 5.01s
.\.venv\Scripts\python.exe -m pytest tests/records --collect-only -q
# 69 cases cuối; đã bao gồm trong final155 phía trên.
.\.venv\Scripts\python.exe -m ruff check tests/records
# PASS: All checks passed!
.\.venv\Scripts\python.exe -m compileall -q tests/records
# PASS
git diff --check -- tests/records
# PASS
```

Runtime: Python 3.12.16, SQLite 3.53.1, SQLAlchemy 2.1.8, Windows phát triển.
Một warning có sẵn: Starlette TestClient deprecates httpx integration.
Không sửa dependency hoặc tắt warning để làm pass.

| File | Cases | Bằng chứng chính |
| --- | ---: | --- |
| `tests/records/test_records_api.py` | 34 | CRUD, nhiều vai trò, ngừng sử dụng, cân đầy/rỗng và tịnh trực tiếp, nullable weights, precision/overflow/float validation, nhập→xuất→sản xuất, dòng trùng, edit/delete/cancel/backdate/restore, retry/version, draft/post, summary cutoff/coverage, lọc/phân trang, chuyển kho, công nợ tổng lớn, Operator tự ghi, biên nửa đêm VN, giới hạn nguồn sản xuất, OpenAPI typed |
| `tests/records/test_records_history_security.py` | 20 | UPDATE/DELETE/OR REPLACE bị chặn trên revisions/movements/references/lines, master tham chiếu không xóa được, thứ tự cùng ngày ổn định, thu hồi quyền lúc lệnh đang chờ và trước replay, 4 bridge revalidate quyền, cutoff khi xóa/khôi phục, sắp lại dòng giữ tham chiếu inactive |
| `tests/records/test_records_transactions.py` | 4 | Hai connection tranh stock, audit failure rollback, reopen/replay bền vững, SQL persistence integer/null đúng scale |
| `tests/records/test_records_shared_snapshot.py` | 11 | Borrowed readonly connection, cùng snapshot với synthetic source probe, không mở reader khác, quyền trên từng read, ownership khi lỗi, write/no-BEGIN/ended/closed guards, commit/rollback rồi BEGIN mới không hồi sinh provider cũ |

## Bằng chứng tồn âm và rollback

Test cạnh tranh tạo `Database` và `WriteCoordinator` thứ hai, cùng trỏ một file
SQLite WAL. Connection đầu giữ `BEGIN IMMEDIATE`; connection thứ hai thực sự
thử `BEGIN IMMEDIATE` và phải chờ khóa. Hai physical DBAPI connection IDs khác
nhau được ghi nhận trong test. Sau khi nhả khóa, xuất 7 kg từ 10 kg đầu tiên
commit; yêu cầu xuất 7 kg còn lại nhận `STOCK_NEGATIVE`. Số dư còn 3 kg và ledger
chỉ chứa một nhập, một xuất. Đây không phải test chỉ dùng chung một queue Python.

Các test sửa giảm/xóa/hủy/đổi ngày nhập, backdated issue và restore issue chụp
toàn bộ bảng `records_*`, `core_audit`, `core_requests` trước thao tác. Khi bị
chặn, dữ liệu, phiên bản, lịch sử, ledger và receipt đều bằng snapshot trước đó.
Có nhập bù sau mốc âm để chứng minh kiểm toàn chuỗi lịch sử, kể cả nhập bù cùng
ngày nhưng có order key sau phiếu xuất. Error chỉ đúng related entry/ngày.

Sản xuất cộng gộp nhiều dòng tiêu thụ cùng chiều tồn; đầu ra cùng sản phẩm không
tự tài trợ nguyên liệu của chính phiếu. Tổng đầu ra không vượt tổng đầu vào;
hao hụt và đúng bằng đầu vào đều lưu hợp lệ. Chuyển kho cân bằng theo sản phẩm.

Sửa hợp lệ giữ `order_key`, append revision và ledger mới, nhưng current ledger
chỉ lấy phiên bản hiệu lực. Xóa/khôi phục không tạo tác động hai lần. SQL triggers
giữ bất biến cả lịch sử, dòng cân/hàng, references và movement, kể cả OR REPLACE.

## Kiểu số, thời gian và bridge

SQL trực tiếp kiểm `typeof(...)='integer'`: gross/tare/net/quantity lưu scale
1.000, tiền scale 100. Dòng cân tịnh trực tiếp giữ gross/tare NULL; draft chưa có
kg giữ quantity NULL. JSON và tổng hợp giữ chuỗi decimal. Công nợ hai giá trị
int64 tối đa cộng chính xác thành `184467440737095516.14` mà không float.

Bridge trả đúng các DTO core, read không đổi domain/audit/receipt. Snapshot trước
sửa và tại ba mốc trước xóa/đang xóa/sau khôi phục tái dựng đúng tồn và công nợ.
Cutoff UTC và cutoff tương đương +07:00 cho cùng kết quả. Biên 17:00 UTC/ngày
Việt Nam được kiểm với timestamp hợp lệ, sai ngày và thiếu múi giờ. Coverage luôn
`entered_records_only`; không tự tạo bảng hoặc giao dịch kế toán.

OpenAPI sinh từ app thật có typed request/response cho records CRUD/history,
stock và receivables; trọng lượng nullable/string, saved DTO không lộ command
request_key/expected_version, security vẫn app session + local user.

## Bridge dùng chung snapshot với caller

`RecordsReadProvider(runtime, principal).bind_connection(conn)` hoặc constructor
`connection=conn` dùng nguyên connection chỉ đọc đã có SQLite `BEGIN` do caller
mở. Tests khóa `runtime.reader` bằng hàm fail: bốn method của core protocol và
`inventory_breakdown` đều chỉ dùng connection đã nhận và revalidate quyền trên
connection đó mỗi lần. Không commit, rollback hoặc đóng connection của caller.

Một Database/WriteCoordinator thứ hai cập nhật phiếu qua public RecordsService.
SQLAlchemy commit event cập nhật synthetic probe trên chính write connection và
trước DBAPI commit. Bởi vậy revision records và probe được công bố nguyên tử.
Provider bound cùng truy vấn probe ở transaction cũ vẫn thấy tồn/công nợ/marker
cũ sau writer commit; provider và reader mới thấy cả số liệu và marker mới.
Cutoff cho phép revision mới, nên kết quả cũ là bằng chứng SQLite snapshot,
không phải lọc revision mới bằng cutoff.

Write connection, query_only chưa có SQLite BEGIN thật, transaction đã commit/
rollback và connection đã đóng đều bị từ chối. Kết thúc transaction rồi BEGIN
lại trên cùng connection không hồi sinh bound provider cũ; bind provider mới
mới được đọc. Các lỗi validation, thiếu reference và quyền bị thu hồi giữ nguyên
lifetime/transaction caller để caller còn sử dụng lại được với principal hợp lệ.

Đây là chứng minh records cùng một nguồn SQL tổng hợp dùng chung snapshot,
**chưa phải kiểm tích hợp thực với lane accounting hoặc reporting Source.capture**.

## Giới hạn bằng chứng

Nhóm này chỉ xác nhận backend records trên nền trong worktree riêng.
Browser flow, root wiring liên module, native Tauri GUI và Windows sạch không
được chứng minh bởi các backend cases này. Native installer/release acceptance giữ
gate riêng của điều phối. Không commit hoặc áp migration vào runtime chung.
