# Delta05 — sửa precondition fixture missing-NUL

Delta sau `76cebf3cba8ef76952a681479c51ee9b5a308562`, cùng branch/worktree
`codex/cafe-fin-packaging-delivery-20261108` tại
`C:\Users\NC\.codex\worktrees\cafe-fin-packaging-delivery\cafe_fin`.
Chỉ đổi test riêng của packaging và tài liệu này; không đổi product/macro,
runtime, installer template/config, notice generation hoặc interface/migration.

## Nguyên nhân và bằng chứng thực

Theo điều phối, CI42454419287 build NSIS thành công nhưng ca missing-nul báo
value đã bị xóa. Fixture cũ dùng RegSetValueExW với create_string_buffer(raw),
không đọc lại dữ liệu trước macro. Đây là thiếu sót của fixture.

Đã tái hiện bằng Python/ctypes trên Windows build26200 trong đúng một leaf
HKCU\Software\CafeFinPackagingTest-<uuid>, rồi xóa leaf ở finally. Không đọc/ghi
Run, không chạy NSIS/compiler/probe EXE, không đổi AppControl hoặc product.
REG_SZ synthetic command chuẩn có124 byte UTF16LE gồm một NUL cuối:

| Ca | Writer | Yêu cầu | RegQueryValueExW thực đọc | Kết quả |
| --- | --- | ---: | ---: | --- |
| exact | RegSetValueExW / NtSetValueKey |124|124| đúng raw |
| missing-nul | RegSetValueExW |122|124| đã thành exact-owned value |
| missing-nul | NtSetValueKey |122|122| đúng raw malformed |
| extra/embedded NUL, odd bytes, empty | cả hai |126/124/123/0|126/124/123/0| đúng raw |

Receipt thật ngoài Git:
`C:\Users\NC\.codex\artifacts\cafe-fin\20261108\startup-registry-normalization-20261108.json`.
Receipt có requested/stored SHA256, byte counts, writer và roundtrip, không có
dữ liệu thật. Quan sát này xác định lỗi fixture trên host26200; không suy rộng
mọi Windows build hoặc lấy nó thay ca NSIS trên runner.

## Thay đổi

- Dùng NtSetValueKey chỉ trong fixture để inject đúng byte count; buffer có kích
  thước chỉ định, không dựa vào NUL mà ctypes tự thêm. NTSTATUS phải success.
- Mỗi lần ghi bắt buộc query lại đúng type và toàn bộ raw bytes. Trong ca native,
  đóng/mở lại handle và assert precondition thêm lần nữa trước khi chạy macro.
  Fixture không tạo đúng byte thì FAIL trước cleanup, không đổi expected hoặc skip.
- Giữ cả12 case, gồm missing-NUL, kỳ vọng chỉ exact mới bị xóa, foreign/OtherEntry
  và missing key/value giữ nguyên. Thêm ca data-only không cần makensis, chạy cả12
  roundtrip bằng cùng writer/query helper. Dọn đúng leaf ngẫu nhiên kể cả khi fail.

## Kiểm thử

PASS: `.venv/Scripts/python.exe -m pytest tests/packaging_delivery/test_startup_cleanup.py -q`
→ **3 passed,1 skipped**: template, hook wiring và actual raw registry roundtrip
(đủ12 case) PASS. Native macro/compiler test bị skip vì không opt-in trên máy
AppControl này. Không gọi đó là native cleanup PASS.

PASS: full `pytest tests/packaging_delivery -q` → **35 passed,1 skipped**;
Ruff check/format và git diff --check. `git diff --name-only 76cebf3 -- backend
frontend desktop scripts pyproject.toml uv.lock` trả rỗng: product/build inputs
không đổi trong delta này.

Chạy trên permitted CI sau NSIS build, dùng compiler đã có từ Tauri cache:

```powershell
$compiler = @(
  "$env:LOCALAPPDATA/tauri/NSIS/makensis.exe",
  "$env:LOCALAPPDATA/tauri/NSIS/Bin/makensis.exe"
) | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1
if (-not $compiler) { throw 'Missing successful-build NSIS compiler.' }
$env:CAFE_FIN_TEST_MAKENSIS = (Resolve-Path -LiteralPath $compiler).Path
uv run --frozen python -m pytest tests/packaging_delivery/test_startup_cleanup.py -q
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
```

Kỳ vọng4 PASS trên CI có opt-in, không skip. Macro production giữ nguyên. Root
quản lý source-tree-unchanged guard/targeted CI và SHA candidate tiếp theo;
không tự reseal source0f72018 hoặc lặp local build. Kit assembly vẫn chờ artifact
và SHA được root chỉ định lại, không ghi đè preparation kit/cache đã có.

Primary docs đã đối chiếu: [RegSetValueExW](https://learn.microsoft.com/en-us/windows/win32/api/winreg/nf-winreg-regsetvalueexw)
yêu cầu length gồm NUL; [RegQueryValueExW](https://learn.microsoft.com/en-us/windows/win32/api/winreg/nf-winreg-regqueryvalueexw)
không bảo đảm string termination; [ZwSetValueKey](https://learn.microsoft.com/en-us/windows-hardware/drivers/ddi/wdm/nf-wdm-zwsetvaluekey)
mô tả explicit DataSize và dùng tên NtSetValueKey khi gọi user mode. Injection
malformed là fixture thử guard, không phải lời khuyên lưu REG_SZ production.
