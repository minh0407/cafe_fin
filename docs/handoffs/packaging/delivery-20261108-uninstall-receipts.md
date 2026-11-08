# Delta05 — startup uninstall và notice receipt

Worktree: `C:\Users\NC\.codex\worktrees\cafe-fin-packaging-delivery\cafe_fin`.
Branch: `codex/cafe-fin-packaging-delivery-20261108`. Delta bắt đầu ngay sau
`20a6df0c34d1cf876d55d8ee3ae4b190314501bf`; điều phối chỉ lấy commit delta mới.
Không merge candidate/root vào lane này. Runtime550edd4 và handoff foundation
được đọc để khớp contract, không sửa/import runtime hoặc Cargo/capability.

## Hành vi

- POSTUNINSTALL chỉ mở HKCU Run, giá trị cố định `CafeFin`. So sánh REG_SZ và byte
  UTF16LE chính xác với `"$INSTDIR\${MAINBINARYNAME}.exe" --startup-v1`, gồm đúng
  một NUL cuối. Khác case/path/flag/type, thiếu/thừa/embedded NUL đều giữ nguyên.
  Không canonicalize/strip prefix để nhận thêm alias. Path spelling khác runtime
  và INSTDIR sẽ được giữ, thay vì đoán quyền sở hữu.
- Query, so sánh, delete và commit qua registry transaction; lỗi/timeout/conflict
  thì rollback/giữ giá trị. Không có fallback delete không transaction, không tạo
  key, không xóa Run key hoặc giá trị khác. Giữ registers/flags của NSIS caller.
- Bỏ qua `/UPDATE` để giữ startup opt-in. Không tự bật startup khi cài. Hook chạy
  sau bước Tauri kiểm app đã dừng và thực hiện uninstall.
- Phát hiện template CLI2.12.4 mặc định còn xóa mù giá trị `${PRODUCTNAME}`
  (`Cafe Fin`, khác `CafeFin`). Dùng custom template đúng bản đó, chỉ thay block
  này bằng hai comment. Test dựng ngược template và kiểm SHA upstream chứng minh
  không đổi phần khác. MIT license và source/patch receipt đi kèm notices. Khi
  đổi CLI phải review/rebase template; test pin version sẽ không im lặng bỏ qua.
- Full sidecar build gọi refresh frontend/Rust notices trước NSIS. Sau backend
  notice/inventory mới, ghi build-inputs.json: HEAD, sidecar hash, lock/recipe
  input hashes và tám notice output hashes. Collector bắt buộc đủ chín file,
  từ chối proof thiếu/stale/lệch source/bytes và code packaging chưa commit.
  `-SkipBuild` không tạo seal mới. Đây là build-input evidence, không phải chứng
  minh cryptographic rằng một EXE tùy ý được build từ source; CI phải dùng fresh
  locked environment và thu đúng output của lượt build thành công.
- Assembler có installer thật sẽ ghi TRIAL_KIT_NOT_RELEASE_ACCEPTED và chỉ rõ
  file để cài thử. Kit thiếu installer vẫn PREPARATION_ONLY. Không đặt thêm bước
  xin phép cho trial đã được người dùng giao; PC2/relink chưa chạy vẫn NOT RUN.

## Kết quả tại máy này

PASS: `.venv/Scripts/python.exe -m pytest tests/packaging_delivery -q` → **34 passed,
1 skipped**. Trong số PASS có chín ca thiếu required notice, bốn ca proof stale,
thay notice bytes, collector/source guards và template/hook wiring.

PASS: `.venv/Scripts/python.exe -m ruff check scripts/packaging tests/packaging_delivery`;
Ruff format các file Python đổi; compileall packaging/tests; PowerShell AST parse
build-sidecar.ps1 và refresh-notices.ps1; `git diff --check`.

NOT RUN: native NSIS compile/probe/real registry behavior (ca opt-in bị skip),
new full sidecar/installer build, GUI/offline/PC2/upgrade/uninstall/relink. Không
retry lỗi AppControl4551, chạy probe EXE ở path khác hoặc thay policy. Không sửa
startup registry thật. Artifact/source-material đã bàn giao trước giữ nguyên.

## Lệnh điều phối chạy trên permitted CI

Sau build NSIS thành công, Tauri đã có compiler/cache. Không chạy bước này trên
host local đang bị AppControl chặn; không cần bật startup thật. Workflow do root
quản lý, delta này không sửa `.github/**`.

```powershell
$compiler = @(
  "$env:LOCALAPPDATA/tauri/NSIS/makensis.exe",
  "$env:LOCALAPPDATA/tauri/NSIS/Bin/makensis.exe"
) | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1
if (-not $compiler) { throw 'NSIS compiler from the successful bundle is missing.' }
$env:CAFE_FIN_TEST_MAKENSIS = (Resolve-Path -LiteralPath $compiler).Path
uv run --frozen python -m pytest tests/packaging_delivery/test_startup_cleanup.py -q
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
```

Probe biên dịch trực tiếp macro production, chỉ dùng một leaf ngẫu nhiên
`HKCU\Software\CafeFinPackagingTest-<uuid>`; không đọc/ghi Run. Nó kiểm 12 raw-value
cases (exact mới xóa), missing key/value, giữ OtherEntry và Unicode/non-BMP path.
Cuối ca chỉ xóa leaf riêng đó. CI PASS cũng không thay native app/PC2 acceptance.

Thu candidate bằng candidate_receipt.py như patch retention trước, không dùng
allow-missing-installer trên CI trial. Cần full build từ HEAD candidate cuối;
không copy seal từ eab8c96 hay tự reseal notices sau khi NSIS đã đóng gói. Root
có payload proof để đối chiếu notices thực được nhúng; giữ cả build-inputs.json.

## Nguồn primary đã đối chiếu

- [Tauri CLI2.12.4 template](https://raw.githubusercontent.com/tauri-apps/tauri/tauri-cli-v2.12.4/crates/tauri-bundler/src/bundle/windows/nsis/installer.nsi): include hook trước defines; POST hook sau uninstall; UpdateMode; block xóa PRODUCTNAME.
- [Tauri bundler](https://raw.githubusercontent.com/tauri-apps/tauri/tauri-cli-v2.12.4/crates/tauri-bundler/src/bundle/windows/nsis/mod.rs): custom template vẫn render cùng data và cung cấp utils/FileAssociation includes.
- [NSIS System](https://nsis.sourceforge.io/Docs/System/System.html): UTF16 buffers, pointer/in-out parameters, register/flag preservation.
- [RegOpenKeyTransactedW](https://learn.microsoft.com/en-us/windows/win32/api/winreg/nf-winreg-regopenkeytransactedw) và [CompareStringOrdinal](https://learn.microsoft.com/en-us/windows/win32/api/stringapiset/nf-stringapiset-comparestringordinal): mở key hiện có trong transaction và so sánh binary với explicit lengths.

Không migration hoặc thay interface runtime/domain. Build interface mới: frontend
locked node_modules phải có trước full sidecar build (CI hiện đã npm ci); chín
notice files và seal đúng source là bắt buộc khi collect. Không push/upload/release,
không gửi chat khác, không sửa dữ liệu thật/CRM cũ/Docker volume.
