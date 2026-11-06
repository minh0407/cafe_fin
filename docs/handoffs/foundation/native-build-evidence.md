# Native build evidence — 06/11/2026 (ICT, UTC+07)

Machine: Windows 11 Pro 10.0.26200 x64, RAM 34.138.931.200 byte; MSVC BuildTools 2026 `14.51.36231`, Windows SDK `10.0.26100.0`, Rust `1.99.1`, Node `24.21.0`, npm `11.19.0`. Installed WebView2 reported by `tauri info`: `156.0.4314.58`. This is a development machine, not clean Windows.

Workspace: `C:\Users\NC\.codex\worktrees\cafe-fin-foundation-build\cafe_fin`.

## PASS: native cargo check

Working directory `desktop`; command:

```powershell
cmd.exe /d /s /c 'call "C:\Users\NC\Desktop\UNILA{\cafe_fin\.local-runtime\tools\native\native-env.cmd" && cargo check --locked'
```

The helper was read only and loaded `C:\Program Files\Microsoft Visual Studio\18\BuildTools\Common7\Tools\VsDevCmd.bat -no_logo -arch=x64 -host_arch=x64` and Rust PATH. No change to the coordination checkout or Windows policy was made.

Initial Rust diagnostic E0283 on navigation plugin generic type was fixed by declaring `tauri::plugin::Builder::<tauri::Wry, ()>`. Rerun completed with exit0, `Finished dev profile [unoptimized + debuginfo] ... in 1.22s` after cached dependency compilation. This proves native compile/typecheck and build-script prerequisites; it does not prove GUI executable launch or installer success.

## FAIL/BLOCKED: release + NSIS build

Working directory `desktop`; command:

```powershell
cmd.exe /d /s /c 'call "C:\Users\NC\Desktop\UNILA{\cafe_fin\.local-runtime\tools\native\native-env.cmd" && ..\frontend\node_modules\.bin\tauri.cmd build --bundles nsis --ci'
```

The first attempt exposed an actual hook cwd issue: Tauri runs beforeBuildCommand from application root, so `npm --prefix ../frontend` failed ENOENT. Fixed both beforeDevCommand and beforeBuildCommand to `npm --prefix frontend ...`. Rerun frontend build PASS, 930.91KB/gzip304.61KB JS. Tauri configuration now uses WebView2 `offlineInstaller` and NSIS currentUser.

Release compilation was then blocked by **Windows Application Control policy**, error4551:

```text
could not execute process ...\desktop\target\release\build\anyhow-fa8f5a6063919863\build-script-build (never executed)
An Application Control policy has blocked this file. (os error 4551)

...\desktop\target\release\deps\serde_derive-b0de8db8c7d3cc09.dll:
LoadLibraryExW failed: An Application Control policy has blocked this file. (os error 4551)
```

Read-only Windows log confirmation:

```powershell
Get-WinEvent -FilterHashtable @{LogName='Microsoft-Windows-CodeIntegrity/Operational'; StartTime=(Get-Date).AddMinutes(-15)} -MaxEvents 12
```

Events 3033/3077 at 19:39:34–19:39:37 ICT reported that rustc.exe attempted to load unsigned/generated release DLLs which did not meet Enterprise signing level requirements. Policy ID `{0283ac0f-fff1-49ae-ada1-8a933130cad6}`. Affected DLLs included serde_derive, cssparser_macros and zerofrom_derive in `desktop\target\release\deps`.

No policy was disabled and no alternate output was selected to evade enforcement. No NSIS installer or final GUI executable was produced by this attempt. No installer was run and no application registration/shortcut was created. A read-only check found no existing Cafe Fin entry under HKCU uninstall entries. After the final sidecar input freeze, the coordinator requested one standard final-input confirmation build, recorded below.

### Final-input confirmation: FAIL/BLOCKED, exactly one attempt

At 20:00 ICT on 06/11/2026, after backend freeze `976475c1df7b78eb7e7e9a32105e9f1d79945994` and rebuilt genuine sidecar, the coordinator explicitly requested exactly one standard NSIS attempt using the final packaging input. Source, build profile, output path, trust settings and command were unchanged. Sidecar SHA-256 before and after was:

```text
EF636343329730D3B0CC6A73F9F6C72C55D0121FB149A75B0EC1BAAC324F357E
```

The same command above ran once. Frontend hook PASS930.91KB/gzip304.61KB; release compilation FAIL exit1 on:

```text
...\desktop\target\release\deps\serde_derive-b0de8db8c7d3cc09.dll:
LoadLibraryExW failed: An Application Control policy has blocked this file.
(os error 4551) (retried 5 times)
error: could not compile `serde` (lib) due to 1 previous error
```

The five retries were compiler-internal DLL load retries, not additional build attempts by the agent. New read-only CodeIntegrity events3033/3077 at **20:00:13 ICT** confirmed the same DLL failed Enterprise signing requirements under the same policy ID. No further build attempt followed. No NSIS `.exe` appeared in `desktop/target/release/bundle/nsis`; no silent installation or GUI launch was attempted. The final sidecar input hash remained unchanged.

**Remaining gate:** authorized resolution of the host trust policy, or an approved build/test environment that can run the normal Rust build artifacts. Then rebuild the final frozen sidecar, run Tauri NSIS build with its hash captured, install/test on Windows, exercise actual native folder picker/handshake/lifecycle and clean-Windows Word/PDF/grid. The development-browser tests below do not satisfy those native/clean-machine gates.

This is a release gate under coordinator-owned
`docs/adr/20261106_COORDINATION_GATES.md`. It does not replace the independently
reviewed tracked-code/API/browser requirements for a development baseline.
Only coordination publishes that baseline tag; no native result is promoted to
PASS by the policy split.

## PASS: browser + real sidecar API

```powershell
# frontend, Python .venv already synchronized from lockfile
$env:CAFE_FIN_REAL_API='1'
npx playwright test tests/real-api.spec.ts
```

PASS1test/5.1s, Chromium158.0.8127.18. The test spawned the real Python sidecar on a dynamic loopback port, initialized synthetic temporary data, used real app-session/CORS/auth endpoints to create and log in admin, generated both documents through the real API, downloaded each with authenticated fetch, and compared content SHA-256 with response metadata and PDF/ZIP signatures. It then loaded a server page500, checked source coordinate `Tổng hợp!D2`, verified <40 DOM rows, switched to page2, and logged out. Test data was outside Git and removed after orderly shutdown.

Only the native `invoke` bridge was stubbed to inject the actual sidecar session into the browser. The test does not instantiate Tauri, exercise a native folder dialog, prove Windows file association/printing, or replace the installer test.

Latest recheck against frozen backend `976475c1df7b78eb7e7e9a32105e9f1d79945994`: `CAFE_FIN_REAL_API=1 npm test` PASS5tests/8.6s. This includes the real workbook projection's source-file ID/hash, 10.000-row projection note, actual D2 `EXACT_TEXT_AMOUNT` issue, page2, and real DOCX/PDF hashes. The first recheck exposed only an obsolete test assertion for the previous sample tooltip sentence; the test now checks the coordinate/code and server-supplied issue message. Frontend build PASS930.91KB/gzip304.61KB. The only subsequent release attempt was the explicitly requested final-input confirmation documented above; it remained blocked.

## License distribution

`desktop/notices/frontend.txt`: notices from 146 installed locked npm packages. `desktop/notices/rust.txt`: notices from 279 reachable Windows-target Cargo packages, including build dependencies conservatively. Native notices include MIT/Apache/BSD/ISC/Zlib/Unicode and unmodified MPL2.0 packages (cssparser/cssparser-macros/dtoa-short/option-ext/selectors); each crate notice includes the exact immutable version source-download URL. `resources: ["notices/*"]` includes these in the bundle. No evaluation, enterprise grid or paid key is used.
