# Fixture records cho bàn giao desktop 08/11/2026

Baseline đúng của lượt này: `eab8c96b851f039de515083189f4301cc09437c0`.
Worktree: `C:\Users\NC\.codex\worktrees\cafe-fin-records-desktop-20261108\cafe_fin`.
Branch: `codex/cafe-fin-records-desktop-20261108`.

Hai file của nhóm fixture: `tests/records/desktop/scenario.py` và
`tests/records/desktop/test_scenario.py`. Không đổi source ứng dụng, core, registry,
migration, dependency hoặc UI. Parent lane giữ launcher/runner, kiểm sidecar,
attestation và báo cáo artifact trong các file riêng.

## Giao diện dùng chung cho source và frozen HTTP

```python
from tests.records.desktop.scenario import exercise

result = exercise(
    api,
    occurred_on="2026-11-08",
    request_prefix="records-desktop",
)
```

`api` chỉ cần method đồng bộ
`request(method, path, *, data=None, params=None)` trả response có `status_code`
và `json()`. Path tương đối trong records, ví dụ `parties`, `entries`,
`market/processed`; adapter thêm `/api/v1/records/`, app session và user auth.
Scenario có helper success riêng, không yêu cầu adapter cung cấp `call`. Adapter
phải gửi được JSON body của DELETE và không tự đổi payload/key khi retry.

Caller khởi tạo **data root tổng hợp mới**, đặt `CAFE_FIN_MARKET_NETWORK=0` trước
khi backend khởi động, hoàn tất health/auth rồi mới gọi scenario. Scenario không
biết credential, đường dẫn DB hoặc loại executable. Nó từ chối root đã có dữ
liệu records trước khi thêm dữ liệu; farm code cố định F801 cũng ngăn chạy lại
nhầm vào root cũ. Không dùng scenario để reset hoặc kiểm trên dữ liệu vận hành.

`occurred_on` là ngày nghiệp vụ canonical từ năm 2000; mọi chứng từ hiệu lực nằm
cùng ngày này. `occurred_at` tương ứng 00:30 Việt Nam, tức 17:30 UTC ngày trước,
để không vô tình phân loại theo UTC date. Các thử backdate/đổi ngày bị từ chối
nằm ngoài ngày, không để lại tác động tồn. Test có ngày 01/01 để kiểm qua năm.

Kết quả là dict JSON-serializable: `fixture_version`, `coverage`, `occurred_on`,
`occurred_at_utc`, `request_prefix`, `ids`, `expected_balances`,
`observed_balances`, `checks`, `price_snapshot_proof`, `market`, `dashboard`,
`limitations`. Không có password/session/access token, raw HTML, địa chỉ DB hoặc
header auth. Mỗi check có `name`, `status='PASS'`, `details`. Nếu một bất biến
không đạt, scenario raise AssertionError ngay, không trả PASS một phần.

## Dữ liệu và số đối chiếu

Fixture tạo farm F801, một survey Grade5 và công ty tổng hợp có MST/liên hệ.
Tên, giấy phép, email `fixture@example.invalid` và thông tin farm đều là dữ liệu
kiểm thử. Có hai hàng hóa và hai vị trí riêng:

| Hàng / vị trí | Nhập | Xuất bán | Tiêu thụ sản xuất | Thu hồi sản xuất | Tồn cuối |
| --- | ---: | ---: | ---: | ---: | ---: |
| Quả tươi kiểm thử / Kho tươi kiểm thử | 100.125 | 10.001 | 20.123 | 0.000 | **70.001 kg** |
| Hạt chế biến kiểm thử / Kho thành phẩm kiểm thử | 0.000 | 0.000 | 0.000 | 19.111 | **19.111 kg** |

Hao hụt sản xuất đã nhập: 1.012 kg. Cân vào ghi đầy 1100.250 / rỗng 1000.125,
tịnh 100.125; cân ra ghi tịnh trực tiếp 10.001, đầy/rỗng giữ null. Cân và đơn mua/
bán đều không tạo ledger. Nhập kho đầu tiên lưu nháp rồi người dùng/command post
mới ghi sổ; sau xuất và sản xuất có đúng bốn movements hiệu lực.

`expected_balances` và `observed_balances` cùng hình dạng:

```text
raw:       {product_id, warehouse_id, closing_kg: "70.001"}
processed: {product_id, warehouse_id, closing_kg: "19.111"}
```

IDs được trả riêng để parent kiểm sau restart hoặc dẫn tới hồ sơ. Root runner
có thể chụp stock-balances cả năm, bỏ trường cutoff khi so sánh trước/sau đóng
và mở lại; tất cả effectives đều nằm trong occurred_on của fixture.

## Giá mua, giá bán và nguồn thị trường

- Bảng mua quả tươi nhập tay, Grade5 10000.00 VND/kg. Preview Grade4→1 lần lượt
  9000.00 / 8100.00 / 7290.00 / 6561.00, công thức đúng từng bước.
- Bảng bán riêng cho hàng tươi: flat 20000.00 VND/kg. Khi mới chỉ có bảng mua,
  lookup sale phải PRICE_NOT_FOUND, không lấy mua làm giá bán.
- Sau khi lưu đơn mua 100.125 kg và đơn bán 10.001 kg, bảng mua được sửa thành
  11000.00 và bảng bán thành 21000.00. Lookup mới phải thật sự trả các giá mới;
  sửa diễn giải đơn cũ vẫn giữ snapshot/version1 và giá 10000.00 / 20000.00.
  `price_snapshot_proof` giữ cả snapshot cũ và quote mới để đối chiếu.
- Không tạo bảng giá chế biến thủ công hoặc HTML/giá nguồn giả. Với gate mạng 0,
  GET/POST check của nguồn nhân xô phải NETWORK_DISABLED, attempts=0, không
  board/snapshot nguồn và không có bảng purchase_processed. Hàng thành phẩm của
  fixture chỉ có lượng sản xuất tổng hợp; nó không phải báo giá nhân xô thật.
  Lượt này không tuyên bố nguồn live hoạt động hoặc đổi BLOCKED thành thành công.

Dashboard cuối có một farm, một survey, một công ty, một đơn vào và một đơn ra.
Period: inbound 100.125 kg, outbound 10.001 kg; sản xuất không cộng thành mua/bán
lần nữa. Giá trị đơn bán 200020.00 VND theo snapshot cũ, cash_in/cash_out đều
0.00 vì chưa ghi thu/chi. Đây là giá trị đơn và dữ liệu đã nhập, không gọi là
doanh thu, tồn thực tế hoặc toàn bộ sổ kế toán doanh nghiệp.

## Rollback và chống ghi lặp

Scenario kiểm replay cùng payload/key cho tạo nhập nháp và post: không thêm
phiếu hoặc ledger. Payload khác dùng lại key cũ phải conflict; expected_version
cũ phải conflict. Các trường hợp STOCK_NEGATIVE có bằng chứng trước/sau bằng
toàn bộ list chứng từ, lịch sử từng hồ sơ đã tạo, ledger và balance công khai:

- Xuất vượt 0.001 kg và hai dòng tiêu thụ trùng scope vượt tổng tồn.
- Sửa phiếu xuất vượt tồn; giảm phiếu nhập; xóa/hủy nhập; chuyển nhập sau xuất;
  backdate xuất trước nguồn nhập.
- Xóa xuất bán rồi ghi xuất tạm 80.002 kg. Khôi phục xuất bán cũ bị chặn. Xóa
  xuất tạm và khôi phục xuất bán hợp lệ trả đúng tồn cuối ban đầu. Phiếu tạm vẫn
  còn lịch sử và deleted_at, không xóa dấu vết.

Public state chỉ bỏ timestamp cutoff do mỗi lần đọc tạo mới; không bỏ version,
recorded_at, trạng thái, history hoặc movement. Mỗi lần từ chối lưu hash public
state và cờ unchanged trong check. Vì frozen HTTP không đọc DB riêng, bằng chứng
này không tự khẳng định đã so raw core_audit/core_requests trên binary. Source
pytest bổ sung kiểm các request_key bị từ chối không có receipt; tạo/post replay
mỗi key chỉ có một receipt trong SQLite file/WAL thật.

## Kết quả nhóm fixture

Python 3.12.16 / SQLite 3.53.1, Windows phát triển. Pytest dùng Runtime mặc định
với toàn registry records/contracts/accounting/reporting thật, FastAPI/TestClient
auth thật, data root mới ở pytest Temp. Password/token chỉ sinh ngẫu nhiên trong
test, không lưu trong mã hoặc kết quả. Transport market bị đặt fail nếu có tải;
không dùng fake market HTML hoặc mock API để báo PASS.

```powershell
.\.venv\Scripts\python.exe -m pytest tests/records/desktop/test_scenario.py -q -o faulthandler_timeout=30
# PASS: 5 passed, 1 warning in 15.69s
.\.venv\Scripts\python.exe -m ruff check tests/records/desktop/scenario.py tests/records/desktop/test_scenario.py
# PASS
.\.venv\Scripts\python.exe -m ruff format --check tests/records/desktop/scenario.py tests/records/desktop/test_scenario.py
# PASS
```

Hai full scenario dates, từ chối root không rỗng và hai parameter preflight cases.
Một Starlette/httpx TestClient deprecation warning có sẵn. Không sửa dependency
hoặc tắt warning. Launcher/frozen HTTP, restart, native GUI/installer và Windows
sạch là bằng chứng riêng do parent/packaging cung cấp; không suy từ năm tests này.

## Các bước GUI nhỏ cho lane 05

1. Dùng artifact và source manifest do điều phối freeze. Mở app từ shortcut,
   chọn một thư mục thử mới, tạo tài khoản local bằng GUI. Giữ password riêng,
   không đưa vào screenshot/report. Chưa có artifact thật thì ghi NOT RUN.
2. Trong Farm tạo F801 và survey Grade5. Tạo công ty khách hàng có tên, MST và
   người liên hệ như dữ liệu tổng hợp trên; tạo hai hàng/hai kho theo bảng.
3. Chọn cùng một ngày thử. Nhập bảng mua tươi Grade5 10000.00, xem đủ năm Grade;
   nhập sale riêng cho hàng tươi 20000.00. Nguồn nhân xô trong chế độ test mạng
   tắt phải ghi NETWORK_DISABLED, không giả APPLIED.
4. Ghi cân vào đầy/rỗng và cân ra tịnh trực tiếp. Mở tồn: vẫn chưa có stock.
   Tạo đơn vào/ra theo kg, farm/công ty và daily quote ở trên; tồn vẫn chưa đổi.
5. Sửa hai bảng giá thành 11000.00/21000.00 rồi mở/sửa diễn giải đơn cũ: chi tiết
   vẫn chỉ rõ giá/snapshot cũ. Không bấm lấy lại giá mới để thay snapshot thử.
6. Lập nhập kho nháp gắn đơn mua và cân, chọn hàng/kho, ghi sổ. Lập xuất 10.001
   gắn đơn bán. Ghi sản xuất 20.123 ra /19.111 vào, không QR/QC/phê duyệt ẩn.
7. Xem tồn 70.001/19.111 và dashboard tiền 0.00, giá trị đơn bán 200020.00. Thử
   xóa/hủy phiếu nhập hoặc xuất quá tồn: phải báo lỗi cụ thể, số đã ghi còn nguyên.
8. Đóng/mở lại qua tray, thoát thật và mở lại shortcut để đối chiếu cùng data root
   và số liệu; ghi bằng chứng GUI/lifecycle/sidecar riêng. Không gọi browser hoặc
   TestClient là native GUI PASS, không lấy build NSIS làm Windows sạch PASS.

Generated DB/JSON/ảnh và manifest kết quả giữ ngoài Git. Nhóm này không push,
merge, tạo tag hoặc tự phát hành artifact.
