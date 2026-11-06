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

## Bổ sung read bridge v2

Shared contract được điều phối phê duyệt tại source `57a2ed2`, cherry-pick local
`1cd2da5`; `core.contracts.CONTRACT_VERSION=2`. Không đổi migration hoặc interface
ghi trong nhóm bổ sung này. File mới:
`tests/records/test_records_read_bridge_v2.py`.

```powershell
.\.venv\Scripts\python.exe -m pytest tests/records/test_records_read_bridge_v2.py -q -o faulthandler_timeout=20
# PASS: 10 passed, 1 warning in 5.06s
.\.venv\Scripts\python.exe -m ruff check tests/records/test_records_read_bridge_v2.py
# PASS
```

Các cases dùng SQLite file thật, records writer/provider và HTTP router thật:

- Đủ tám thành phần: mua, bán, nguyên liệu/sản phẩm sản xuất có hao hụt, chuyển
  hai kho, điều chỉnh vào/ra; opening trong kỳ vào adjustment_in và có flag
  `opening_entries_in_adjustments`. Mỗi scope có đúng một dòng decomposition,
  tất cả thành phần là chuỗi không âm, khớp received/issued/closing. API giữ cả
  standard v2 và extension `.breakdown` cũ cho desktop.
- Empty summary có version 1/tuple rỗng. Scope chỉ có tồn đầu từ trước kỳ vẫn
  có đủ tám zero đã xác định trong kỳ; sản phẩm chỉ xuất hiện sau through_on
  không bị tạo scope giả. Opening ngoài kỳ không mang flag opening trong kỳ.
- Cutoff tái dựng đúng phiên bản trước/sau sửa, hủy, post lại, xóa và khôi phục;
  hủy/xóa không bị phân loại thành thành phần âm hoặc tác động hai lần.
- Hai chu kỳ nhập hết/xuất hết, mỗi dòng nằm trong int64, cho tổng bought/sold
  `18446744073709551.614` kg trên cùng scope, đối soát chính xác mà không SQLite
  integer SUM overflow hoặc float. Tồn trung gian vẫn không âm và trong miền.
- Bốn trường hợp movement legacy chưa biết type/direction hoặc dấu không khớp
  làm cả breakdown_version/movement_breakdown null với flag
  `inventory_movement_classification_unknown`, kể cả khi scope khác phân loại
  được. Không thay phần chưa biết bằng zero hoặc đoán là mua. Legacy chỉ ở
  trước kỳ được giữ trong opening, không đoán thêm thành phần trong kỳ.
- Provider bound vẫn là concrete class cũ, giữ decomposition của snapshot
  caller khi writer đã sửa phiếu receipt thành adjustment; provider mới thấy
  đúng decomposition mới. Caller connection/transaction còn sống.

Fixture legacy chỉ append synthetic DOCUMENTS/REVISIONS/MOVEMENTS trong DB tạm,
không update/delete lịch sử bất biến hoặc sửa schema. Nó chủ động mô phỏng nguồn
cũ chưa phân loại; không tuyên bố HTTP cho phép tạo entry_type không được hỗ trợ.
Đây là kiểm records producer v2 thực, chưa chứng minh reporting/accounting đã
được ghép liên module. Lượt final do parent lane chạy sau freeze:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/core tests/records -q -o faulthandler_timeout=30
# PASS: 187 passed, 1 warning in 76.74s (108 core +79 records).
.\.venv\Scripts\ruff.exe check backend/cafe_fin/records tests/records
# PASS
.\.venv\Scripts\python.exe -m compileall -q backend/cafe_fin/records tests/records
# PASS
```

Migration và các mutation không thay đổi. Không suy báo cáo/accounting/native
integration PASS từ các tests producer này.

## Bổ sung P2: raw SQL không được hồi sinh snapshot đã bind

File mới `tests/records/test_records_raw_snapshot.py` tái hiện lỗi trước sửa bằng
public SQLAlchemy Connection: raw `ROLLBACK`, writer commit phiếu mới trên một
physical connection khác, rồi raw `BEGIN` vẫn giữ nguyên SQLAlchemy
RootTransaction object. Cutoff là 2030 nên không che revision mới. Regression
đầu tiên RED thật: provider cũ đọc `15.003` kg/`150.03` VND thay snapshot
`10.001` kg/`100.01` VND, với wrapper transaction không thay đổi.

Parent lane thêm connection epoch guard; nhóm test không sửa backend/core hoặc
migration. Sau fix:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/records/test_records_raw_snapshot.py -q -o faulthandler_timeout=20
# PASS: 52 passed, 1 warning in 25.44s
.\.venv\Scripts\python.exe -m ruff check tests/records/test_records_raw_snapshot.py
# PASS
```

Ma trận kiểm public `exec_driver_sql` và `execute(text(...))`, cả bind method và
constructor `connection=...`, với COMMIT/END/ROLLBACK rồi BEGIN mới. Câu SQL có
prefix BOM, semicolon, block/line comments và chữ hoa/thường vẫn làm provider cũ
bị từ chối. Cả bốn method protocol và `inventory_breakdown` phải trả
`READ_ONLY_SNAPSHOT_REQUIRED`; không đóng/rollback connection caller. Bind mới
thấy v2 purchased/closing `15.003` và công nợ `150.03`. Nhiều provider cùng
connection đều bị invalidated, không chỉ instance xử lý lệnh đầu tiên.

Failed BEGIN và SAVEPOINT attempt cũng làm provider cũ invalid theo chính sách
conservative. SQLAlchemy NestedTransaction commit/rollback vẫn giữ RootTransaction
nhưng bị guard nhận biết. Negative controls là SELECT literal, comments và bound
parameters chứa ROLLBACK/BEGIN/COMMIT/END/SAVEPOINT; chúng không được làm mất
snapshot hợp lệ hoặc chặn các read bình thường.

Query-only OFF → actual UPDATE → ON được kiểm với bốn dạng PRAGMA: bare setting,
schema + quoted name, bracket + parentheses và schema + backtick + parentheses;
mỗi dạng chạy bằng cả hai public SQL execution APIs. UPDATE chỉ tác động probe
tổng hợp trong DB tạm và không commit. Dù query_only đã trở lại 1, driver vẫn ở
transaction và RootTransaction wrapper còn nguyên, mọi provider cũ phải bị chặn;
connection và dữ liệu probe chưa commit vẫn thuộc caller.

Hook chứng minh writer khác chỉ đếm UPDATE records_documents của mutation thật,
tránh nhầm transaction idle job worker vào số writer quan sát. Đây là test SQLite
file/WAL thực và public SQLAlchemy APIs; không gọi raw driver_connection.execute.
Không suy rằng mọi khả năng bypass ngoài public Connection đã được kiểm. Parent
lane đã chạy full regression sau freeze, không suy từ focused 52 cases:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/records -q -o faulthandler_timeout=30
# PASS: 131 passed, 1 warning in 61.86s.
.\.venv\Scripts\ruff.exe check backend/cafe_fin/records tests/records
# PASS
.\.venv\Scripts\python.exe -m compileall -q backend/cafe_fin/records tests/records
# PASS
git diff --check
# PASS
```

Một warning nền Starlette/httpx vẫn có. Core/shared/migration/frontend không đổi;
không chạy lại core suite hoặc browser/build cho patch guard backend này. Kết quả
187 core+records và browser v2 trước patch là bằng chứng mốc c82044d riêng.
