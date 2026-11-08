# Records — desktop delivery harness, 08/11/2026

Baseline được giao: `eab8c96b851f039de515083189f4301cc09437c0`, docs-only successor
của `828d575b4a3c7b18ffafd8e2665a9d79b54ea403`. Worktree riêng:
`C:\Users\NC\.codex\worktrees\cafe-fin-records-desktop-20261108\cafe_fin`, branch
`codex/cafe-fin-records-desktop-20261108`. Không thay worktree lane cũ.

## Phạm vi

Fixture và harness chỉ ở `tests/records/desktop/**`; tài liệu ở handoff records.
Không đổi API, migration, business rule, UI, core, desktop runtime hoặc installer.
Không build binary, không dùng Docker volume/DB/Excel thật, không push hoặc release.

`scenario.py` dùng HTTP adapter có `request(method, path, data=None, params=None)`;
path tương đối dưới `/api/v1/records`. Cùng scenario chạy được qua TestClient thật
và sidecar HTTP thật. Expected balances và từng bước có trong
[desktop-fixture.md](desktop-fixture.md).

`runner.py` tạo thư mục mới duy nhất ngoài Git, bootstrap Admin tổng hợp trong
root mới có dấu/khoảng trắng, chạy scenario, dừng sidecar sạch, mở lại root với
`initialize=false`, đăng nhập lại và so sánh toàn bộ stock DTO trừ cutoff. Không
nhận data root có sẵn. Password/token ngẫu nhiên chỉ ở bộ nhớ/private pipe/HTTP
local, không vào report. HTTP không dùng proxy môi trường. Child market network
luôn tắt qua `CAFE_FIN_MARKET_NETWORK=0`; đây không phải kiểm thử WAN bị ngắt ở OS.

## Chạy source

Từ worktree đã cài dependency theo `uv.lock`:

```powershell
$env:CAFE_FIN_MARKET_NETWORK = '0'
.venv/Scripts/python.exe -m pytest tests/records/desktop -q
.venv/Scripts/python.exe tests/records/desktop/runner.py --output-parent "$env:TEMP/cafe-fin-records-evidence"
.venv/Scripts/ruff.exe check tests/records/desktop
```

Runner in đường dẫn `report.json` và trả exit code 0 chỉ khi scenario, khởi động
lại và hai lần shutdown đều PASS. JSON/DB/runtime logs ở root tổng hợp ngoài Git;
không commit chúng. Report ghi source HEAD, tracked-worktree status, hash harness,
OS/architecture/CPU, loại bằng chứng, thời điểm và số dư. Kiểm tra source có thể
chạy trước commit; hash harness xác định chính xác file đã chạy.

## Frozen sidecar — chỉ chạy khi có đúng artifact

05/điều phối cấp executable và receipt từ **chính build**. Không tự tạo receipt
cho binary không rõ nguồn bằng cách lấy hash rồi gắn source SHA mong muốn.
Nếu manifest của kit có schema khác, cần trích receipt tối thiểu từ manifest
đã xác minh và giữ đối chiếu với manifest/build gốc; không sửa claim source.
Schema receipt version 1:

```json
{
  "schema_version": 1,
  "source_commit": "<40 lowercase hex, exact checkout HEAD>",
  "sidecar": {
    "filename": "<exact basename.exe>",
    "bytes": 123,
    "sha256": "<64 lowercase hex from the source-matched build>"
  }
}
```

Ví dụ lệnh với đường dẫn placeholder, không phải artifact hiện có:

```powershell
.venv/Scripts/python.exe tests/records/desktop/runner.py `
  --sidecar D:/CafeFinKit/cafe-fin-sidecar.exe `
  --attestation D:/CafeFinKit/records-sidecar-attestation.json `
  --output-parent "$env:TEMP/cafe-fin-records-evidence"
```

Gate kiểm exact HEAD, tracked source sạch, filename, bytes và SHA256 trước khi
thực thi. Hash receipt cũng được ghi. Receipt là bằng chứng của người build mà
harness tin cậy; đối chiếu file không tự chứng minh executable đã được compile
từ source đó. Frozen child loại Python/Node/dev PATH và PYTHONPATH/PYTHONHOME/
VIRTUAL_ENV. Không dùng việc Python trên máy dev chạy source để gọi frozen PASS.

Launcher Windows đặt tiến trình mới vào Job Object riêng trước khi cho chạy,
để timeout hoặc parent thoát sớm vẫn dọn được child của frozen one-file sidecar.
Policy từ chối tạo/gắn job thì fail closed; không dùng fallback để né policy.
Chỉ đóng pipe sau khi cleanup cây tiến trình và reader hoàn tất có giới hạn.

## Giới hạn nghiệm thu

- Source HTTP, frozen HTTP, native GUI và máy Windows sạch/PC2 là các bằng chứng
  riêng. Browser hoặc TestClient không thay native GUI acceptance.
- Harness không kiểm tray/startup/single-instance/controller/installer của lane00/05.
- Không dùng giá nhân xô tổng hợp làm nguồn thật. Scenario dùng giá tươi nhập tay
  và bảng bán riêng; trạng thái network-disabled không chứng minh nguồn thật hết
  BLOCKED. Không gọi WAN hoặc Telegram thật.
- Không có benchmark lớn hoặc tuyên bố production-ready trong đợt bàn giao này.
- Frozen smoke chờ source-matched artifact; nghiệm thu GUI chờ SHA/artifact cuối
  do điều phối chỉ định. Không có artifact được suy diễn từ CI build SUCCESS.

## Kết quả

| Kiểm tra | Trạng thái | Bằng chứng/giới hạn |
|---|---|---|
| `.venv/Scripts/python.exe -m pytest tests/records --ignore=tests/records/desktop -q` | PASS | 238 tests, 144.54s, Windows dev; SQLite file thật, WAN gate0. |
| Artifact attestation mismatch/hash guards | PASS | 8 tests; file giả không thực thi, không phải frozen smoke. |
| `.venv/Scripts/python.exe -m pytest tests/records/desktop -q` | PASS | 16 tests, 14.55s: 2 ngày scenario tích hợp (có ranh giới UTC/VN), root/parameter guards, 8 attestation tests, 3 Windows process-tree tests. |
| Source sidecar HTTP qua `runner.py` | PASS | 22 checks, stock70.001/19.111kg, restart/login mới giữ stock, hai lần shutdown sạch; không dùng TestClient cho lượt này. |
| `.venv/Scripts/ruff.exe check tests/records/desktop`, `ruff format --check tests/records/desktop`, `git diff --check` | PASS | 6 Python files. |
| Frozen source-matched sidecar | NOT RUN | Chưa nhận artifact/receipt từ05/điều phối khớp source. |
| Final native GUI, Windows sạch/PC2, installer/offline/tray | NOT RUN | Chờ candidate/artifact cuối và môi trường nghiệm thu. |
| Live market | NOT RUN | Không gọi mạng trong lượt fixture; trạng thái nguồn thật BLOCKED không được thay bằng fixture. |
| Build frontend/Rust/NSIS | NOT RUN | Không sửa product/UI/runtime;05 giữ slot build installer. |

Không có migration hoặc thay đổi interface production. Dependency warning có sẵn:
FastAPI/Starlette khuyến nghị httpx2 cho TestClient; không đổi root dependency ngoài
allowlist chỉ để làm mất warning.

Lượt HTTP source đầu: `2026-11-08T11:02:22` đến `11:02:33` UTC,
HEAD `eab8c96`, harness chưa commit nhưng SHA256 từng input có trong report.
Report ngoài Git:
`C:\Users\NC\AppData\Local\Temp\cafe-fin-records-evidence\records-desktop-el_62hk4\report.json`.
Máy đo thực: Windows11 build26200, AMD64, 16 logical CPUs, Python3.12.16. Đây là
mini functional smoke, không dùng thời gian này để hứa hiệu năng import lớn.
