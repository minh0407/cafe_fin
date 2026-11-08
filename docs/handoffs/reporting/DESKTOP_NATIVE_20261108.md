# Reporting — desktop test harness, 08/11/2026

## Checkout và phạm vi

- Worktree: `C:\Users\NC\.codex\worktrees\cafe-fin-reporting-desktop\cafe_fin`
- Branch: `codex/cafe-fin-reporting-desktop-20261108`.
- Baseline được điều phối giao: `eab8c96b851f039de515083189f4301cc09437c0`.
  Code sản phẩm giống candidate `828d575b4a3c7b18ffafd8e2665a9d79b54ea403`;
  phần thêm ở baseline coordination là OWNERSHIP/prompt desktop. Thông tin CI
  Windows42344896417 SUCCESS do điều phối cung cấp, không phải lần chạy của lane này.
- Checkout reporting cũ và các commit riêng được giữ nguyên. Không push, merge,
  di chuyển tag READY hoặc nhắn chat khác.
- Chỉ thêm tests và handoff reporting. Không đổi sản phẩm, UI, dependency,
  migration, API, lifecycle Tauri hoặc đăng ký thêm scheduler.

## Sản phẩm bàn giao

`tests/reporting/native_probe.py` khởi động entrypoint sản phẩm nguyên trạng bằng
private stdin/stdout pipe và gọi API loopback có session + local authentication.
Chế độ mặc định dùng Python của runner và **source trong checkout này**. Biến
`CAFE_FIN_REPORTING_TEST_SIDECAR` chọn frozen EXE có sẵn, không truyền argument
cho EXE và không chèn patch/clock/transport/registry vào child. Phải cung cấp
`CAFE_FIN_REPORTING_TEST_SIDECAR_SHA256` từ artifact đã review; sai hash thì từ chối
chạy. Hash này kiểm đúng file đã chọn, không tự chứng minh provenance/source SHA.

Harness không mở browser/WebView, không gọi connection-check hoặc endpoint tick.
Nó đợi một job `foundation.sample` mới hoàn tất để drain finite startup dispatch
trước khi bật lịch. Mỗi lần boot dùng request key mới, tránh nhầm receipt job cũ
với barrier mới. Private shutdown phải exit 0; kill chỉ dùng cleanup khi thất bại
và không được tính PASS. Đây không phải bằng chứng maintenance CLOSED/tray Exit.

`tests/reporting/test_native_delivery.py` có bốn ca chạy được trên source hoặc
frozen sidecar:

1. Chu kỳ production 60 giây thật, registry đầy đủ, không UI. Nhập qua API owner
   lượng `12.345 kg` và tiền sổ độc lập `10.01`; kiểm snapshot atomic/Decimal,
   SAVED, PDF/XLSX/TXT, hash canonical và bản local/download giống byte. Sửa bản
   ghi owner lên `13.345 kg` sau capture không thay snapshot/export; reopen không
   thêm report/outbox hoặc thay pin/hash.
2. Startup catch-up khi thiếu cả nhóm/token.
3. Cùng catch-up nhưng đã có numeric group ID tổng hợp, thiếu token. Cả hai ca
   sửa **cursor reporting của DB tổng hợp đã đóng** lùi hai ngày để dựng fixture
   gián đoạn. Child nguyên trạng đánh dấu hai ngày cũ MISSED_NO_SNAPSHOT, không
   bịa snapshot/outbox quá khứ; chỉ tạo ngày hiện tại. Đây là persisted-state
   fixture, không phải đã đợi máy tắt hai ngày hoặc đổi đồng hồ Windows.
4. API sidecar ghi token tổng hợp vào Windows Credential Manager thật; controller
   độc lập đọc đúng namespace root UUID/bot, reopen còn token. Có token nhưng
   thiếu nhóm vẫn lưu local, UNCONFIGURED, zero attempt. Tạo backup bằng private
   maintenance API rồi quét file dữ liệu/backup/stdout/stderr không có token.
   Cuối test xóa **đúng một key tổng hợp**, không enumerate credential thật.

Các ca UNCONFIGURED kiểm riêng state/attempts/receipt và bảng attempts phân trang;
không coi việc tạo file local là đã gửi Telegram. PDF chỉ kiểm đọc/extract text;
XLSX chỉ kiểm cấu trúc/read-only/no formula. Không ghi visual QA PASS từ các check này.

`tests/reporting/test_desktop_transport_recovery.py` có bốn ca **source integration**:
registry sản phẩm đầy đủ cùng public read bridges; chỉ inject memory secret và
fake Telegram transport tại factory reporting trong test. Không đưa fake vào
production/frozen EXE. Kiểm SENT với cặp receipt đúng nhóm, UNKNOWN sau text POST,
UNKNOWN sau document POST có text receipt, và FAILED khi mạng lỗi ở preflight.
Lưu/xuất cả ba định dạng vẫn được khi fake lỗi mạng đã bật. Sau restart, mạng
giả phục hồi và gọi lại callback reporting không gửi lặp, không sửa receipt/file.
Callback lặp trong bốn ca này là gọi trực tiếp; bằng chứng nhịp 60 giây thật nằm
ở ca process riêng, không rút ngắn interval để gọi là nhịp production.

## Module giá và giới hạn lịch

Tất cả child đặt chế độ production có sẵn `CAFE_FIN_MARKET_NETWORK=0`; giá vẫn
enabled nhưng trạng thái NETWORK_DISABLED, attempts 0, không tạo bảng/giá giả.
Registry vẫn có `records.market` 10 giây và `reporting.tick` 60 giây trên cùng
PeriodicRunner tuần tự. Không tạo scheduler thứ hai hoặc heartbeat trang Báo cáo.

Đường mất mạng với registry mới được kiểm. Nguồn giá WAN/challenge/chậm chưa được
nghiệm thu ở lane này: callback tuần tự có thể làm reporting chờ callback trước.
Source transport giá có deadline 8 giây; đó là quan sát code, không phải benchmark
WAN hoặc cam kết báo cáo chạy chính xác ở giây 60 trong mọi điều kiện.

## Cách chạy và ghi evidence

Runner phát triển cần Python/dependencies pytest/httpx/pypdf/openpyxl của repo.
Đây là công cụ nghiệm thu, không phải dependency phải cài trên PC người dùng app.
DB, backup, exports và XML evidence đều ở thư mục temp ngoài Git. Không đặt token
thật vào biến môi trường/command line, không dùng bot/nhóm thật trong các ca này.

Source (đặt cwd vào worktree nêu trên; xóa hai biến chọn frozen nếu shell đã có):

```powershell
$env:PYTHONPATH = Join-Path $PWD 'backend'
& $python -m pytest tests/reporting --override-ini junit_family=xunit1 --junitxml="$env:TEMP\cafe-fin-reporting-desktop-source.xml" -q
& $python -m ruff check backend/cafe_fin/reporting tests/reporting
& $python -m ruff format --check backend/cafe_fin/reporting tests/reporting
git diff --check
```

Frozen sau khi điều phối giao source SHA/artifact cuối:

```powershell
$env:CAFE_FIN_REPORTING_TEST_SIDECAR = 'C:\approved-artifact\cafe-fin-sidecar.exe'
$env:CAFE_FIN_REPORTING_TEST_SIDECAR_SHA256 = '<sha256 từ manifest đã review>'
& $python -m pytest tests/reporting/test_native_delivery.py --override-ini junit_family=xunit1 --junitxml="$env:TEMP\cafe-fin-reporting-desktop-frozen.xml" -q
```

Không dùng đường dẫn ví dụ như một artifact hiện có. Đối chiếu manifest source
SHA/checksums với candidate điều phối trước khi chạy; không tự rebuild/đổi tên
EXE hoặc thay policy nếu hệ thống từ chối thực thi. JUnit ghi execution_mode,
Windows, controller Python, market mode, elapsed timer, snapshot/export hash và
hash EXE (khi frozen).
Không lấy kết quả source làm packaged PASS.

## Kết quả của đợt này

**PASS** full reporting regression: `411 passed, 1 warning in 288.23s`. Bao gồm
tám ca mới (bốn process + bốn source fake-transport) và các regression reporting
đã có: transport, crash/recovery, UNKNOWN, retry/cooldown, restore và credential.
Lệnh thực tế dùng XML ngoài Git:
`C:\Users\NC\AppData\Local\Temp\cafe-fin-reporting-desktop-20261108-source.xml`.
Nhịp production quan sát trong run này: **62.391 giây từ lúc spawn process**
(gồm thời gian boot), telemetry reporting runs1/failures0. Không đổi interval60.

**PASS** lần cuối bốn ca process: `4 passed in 87.55s`, gồm assertion xác nhận
edit owner thật sự thành công và metadata snapshot/export hash. XML:
`C:\Users\NC\AppData\Local\Temp\cafe-fin-reporting-desktop-20261108-native-source.xml`.
Timer ở lần này là **61.984 giây từ spawn**; cả bốn testcase có execution_mode
source và đủ snapshot/PDF/XLSX/TXT SHA256. **PASS** Git staged diff whitespace check.

**PASS** Ruff check và Ruff format check trên toàn bộ reporting backend/tests
(43 file đã định dạng); không thêm dependency để né warning. Một warning hiện
có là StarletteDeprecationWarning từ `fastapi.testclient` dùng `httpx`, không
suppress hoặc tự đổi shared dependency trong lane.

Máy chạy Windows 11 Pro
10.0.26200 build26200, Intel Core i5-14400F (10 cores/16 logical), RAM31.79 GiB;
controller Python3.12.16/SQLite3.53.1. Toolchain Python được tái dùng từ `.venv`
của checkout reporting cũ nhưng PYTHONPATH/child source trỏ checkout mới. Interpreter:
`C:\Users\NC\.codex\worktrees\cafe-fin-reporting\cafe_fin\.venv\Scripts\python.exe`.

Các gate còn lại: **NOT RUN** frozen EXE đúng candidate cuối, installer/clean
Windows, thu về tray/ẩn/reopen từ startup/Exit/sleep-wake, single instance/orphan,
visual PDF và font trên artifact cuối, Telegram live với đích được giao. Chưa có
artifact cuối/đích gửi thật. Không bật startup của máy phát triển; không dùng
Docker/CRM cũ, dữ liệu thật hoặc thay policy bảo vệ. Không tuyên bố production-ready.

Frontend build/UI regression: **NOT RUN** trong increment chỉ thêm test này;
không có frontend/product source thay đổi. Build installer/cargo thuộc slot05/00,
không chạy tại lane reporting.

Interface impact/migration: **không có**. Điều phối có thể tích hợp độc lập commit
test này trước khi freeze artifact rồi chạy bốn ca process bằng EXE cuối. Lane
không sửa lifecycle và chưa cần đề nghị shared interface mới.
