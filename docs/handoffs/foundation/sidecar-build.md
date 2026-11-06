# Windows sidecar build

Current final candidate: backend source commit
`976475c1df7b78eb7e7e9a32105e9f1d79945994`, executable SHA-256
`ef636343329730d3b0cc6a73f9f6c72c55d0121fb149a75b0ec1baac324f357e`,
33,008,864 bytes. Build, archive/native inventory and expanded frozen runtime
smoke PASS on the developer Windows host. Final details are below; an earlier
hash's Application Control block is retained as distinct historical evidence.
Clean-Windows installer acceptance, DOCX visual/print and iconv provenance
remain unresolved gates.

`desktop/scripts/build-sidecar.ps1` uses the repository's locked Python 3.12
venv and PyInstaller 6.22.3. It refuses an absent backend entrypoint, a different
Python major/minor, unsupported SQLite or a different PyInstaller version.
It does not substitute a placeholder binary to satisfy Tauri's externalBin.

Developer command from repository root:

```powershell
powershell -ExecutionPolicy Bypass -File desktop/scripts/build-sidecar.ps1
```

Use PowerShell 7 (`pwsh`) or Windows PowerShell. The optional `-Python` argument
selects an already-synchronized developer environment; it is not an application
user setup requirement. `-SkipBuild` checks that environment and generates the
notices without claiming a binary build.

The spec produces a onefile Windows x64 console binary at
`desktop/binaries/cafe-fin-sidecar-x86_64-pc-windows-msvc.exe`. `console=True`
preserves stdin/stdout IPC. Tauri must start it with `CREATE_NO_WINDOW` and piped
stdin/stdout, rather than use `--noconsole`, which removes the streams needed for
the internal token handshake. Tokens must never be command-line arguments.

The spec includes Cafe Fin assets, Noto font/OFL/notices, python-docx templates,
tzdata, runtime dependency metadata, argon2/_cffi, lxml/Pillow native modules and
uvicorn dynamic modules. ReportLab DarkGarden example fonts, commercial
rlextra/pyRXP and the development PDF verifier are excluded. Onefile extraction
is runtime-managed, so packaged code must locate assets relative to `__file__`.

The script generates `desktop/notices/backend.txt` from the exact installed
distribution metadata/license files and font notices. It adds ten native
upstream license sources with fixed SHA-256 hashes; the source inventory is
`desktop/notices/native-license-sources.json`. Downloads are cached under the
ignored `build/native-notices` directory. A missing/corrupt source causes an
explicit build failure, rather than dropping a notice. Tauri's `notices/*`
resource pattern must include these outputs. No operational files, DBs or
credentials are included.

The script pins the native-notice inventory to Python 3.12.16, Python Standalone
Builds 20261026, OpenSSL 3.5.9, lxml 6.1.1 compiled against libxml2 2.11.9 and
libxslt 1.1.45. A runtime upgrade must deliberately update the inventory.
Authoritative build-version provenance is
https://raw.githubusercontent.com/astral-sh/python-build-standalone/20261026/pythonbuild/downloads.json .

| Native component | Source used for its license |
| --- | --- |
| libffi 3.8.0 | PBS release 20261026 `LICENSE.libffi.txt`, MIT |
| OpenSSL 3.5.9 | PBS release 20261026 `LICENSE.openssl-3.txt`, Apache-2.0 |
| SQLite 3.53.1 | PBS release 20261026 `LICENSE.sqlite.txt`, public domain |
| liblzma 5.8.4 | PBS release 20261026 `LICENSE.liblzma.txt`, 0BSD |
| bzip2 1.0.8 | PBS release 20261026 `LICENSE.bzip2.txt`, bzip2 license |
| zlib 1.3.2 / Windows zlib-ng 2.2.4 dependency | PBS release 20261026 `LICENSE.zlib.txt` and `LICENSE.zlib-ng.txt` |
| libxml2 2.11.9 | https://raw.githubusercontent.com/GNOME/libxml2/v2.11.9/Copyright |
| libxslt/libexslt 1.1.45 | https://raw.githubusercontent.com/GNOME/libxslt/v1.1.45/Copyright |
| VCRUNTIME140/140_1, actual version 14.44.35211.0 | Microsoft Visual C++ Runtime 2015-2022 EULA, official license DOCX downloaded and extracted as text |
| Pillow 13.0.0 codecs | Exact wheel's license inventory includes libavif 1.4.2, libjpeg-turbo 3.2.0, libwebp 1.6.0 and related notices |

Microsoft license sources are
https://visualstudio.microsoft.com/license-terms/vs2022-cruntime/ and
https://learn.microsoft.com/en-us/visualstudio/releases/2022/redistribution .
The official DOCX source hash is pinned in the build script. The files are
release runtimes; debug/nonredistributable MSVC runtime files are not included.
Redistribution must satisfy the terms of the distributor's valid Visual Studio
license; a free Community/Build Tools installation does not remove those terms.

PyInstaller initially discovered `ucrtbase.dll` from an unrelated Codex runtime
directory on the host PATH. The final spec removes that DLL and API-set DLLs.
Windows 11 supplies its OS UCRT and always uses it, as documented at
https://learn.microsoft.com/en-us/cpp/windows/universal-crt-deployment . This
keeps unrelated host DLLs out of the application. VCRUNTIME140/140_1 remain
bundled from the pinned Python Standalone distribution.

After building, the script writes `desktop/notices/sidecar-native-inventory.json`
with executable hash/size and each packaged DLL/PYD name/hash. It verifies that
the archive includes the DOCX default template and excludes DarkGarden and
host UCRT/API-set files.

## Remaining native license evidence

The lxml Windows wheel reports the `iconv` compiled feature. Its `etree.pyd`
imports no separate iconv DLL and exports only `PyInit_etree`; the implementation
appears statically linked. Official lxml `buildlibxml.py` references GNU
libiconv. The exact iconv build version, corresponding native source and
relinking artifacts/rights have not been established from the wheel metadata.
This is an explicit distribution gate: do not describe the package notices as
release clearance. LGPL can be used commercially when its obligations are met;
an unexplained BSD label for the top-level lxml package is insufficient evidence.
No dependency/stack change was made to bypass this question.

## Actual frozen executable checks

Build and smoke ran on Windows 11 Pro 10.0.26200 with Python 3.12.16 / SQLite
3.53.1 / PyInstaller 6.22.3 and hooks-contrib 2026.9. The smoke child had only
Windows/System32 in PATH, no PYTHONPATH/PYTHONHOME/VIRTUAL_ENV, a temporary cwd,
and CREATE_NO_WINDOW. Its selected data root contained Vietnamese characters
and spaces, transmitted as raw UTF-8 over stdin.

Preliminary build/smoke PASS: frozen handshake, missing/bad boot token rejection,
loopback health, sidecar-token/user/origin guards, local admin setup using the
bundled Argon2 native binding, server grid paging (500 rows), DOCX/PDF generation
and download hashes, orderly shutdown. Embedded SQLite DLL version was checked
directly as 3.53.1, not inferred from the development Python. The frozen PDF was
rendered using bundled Poppler and visually inspected: one page, Vietnamese
glyphs and table readable, no clipping/overlap. DOCX was structurally reopened;
DOCX visual/open/print without Office remains NOT RUN because bundled LibreOffice
is unavailable.

This is a frozen executable smoke on a developer Windows host. It does not
replace installing the NSIS package on clean Windows without development
dependencies. That clean-machine/installer gate remains NOT RUN.

Proof files are outside Git at
`%TEMP%\cafe-fin-frozen-proof-778rr5k3\frozen-document.{docx,pdf}` and
`frozen-page-1.png`. Final rebuild after the sample-module freeze and expanded
receipt/restart smoke will be recorded below by this lane or the root handoff.

### Later build and Windows Application Control block

The later build includes `core/example.py`, the actual synthetic workbook
adapter, openpyxl 3.1.5 / defusedxml 0.7.1 and removes host UCRT/API-set DLLs.
PyInstaller build and packaged inventory verification PASS. The generated
notices cover 36 installed distributions plus the ten pinned native license
sources; the executable archive contains 51 DLL/PYD files. The build command
was again `powershell -ExecutionPolicy Bypass -File desktop/scripts/build-sidecar.ps1`.

Executable SHA-256 at this checkpoint:
`23c12fef5afbc195acf41b82c78fec3d0f767e257fb725941dc2d7998018b3e8`.

Launching the expanded frozen smoke failed before the sidecar entrypoint:
`OSError: [WinError 4551] An Application Control policy has blocked this file`.
This executable's runtime result is **BLOCKED**, not PASS. The previous frozen
document smoke belongs to an earlier binary and cannot establish the runtime
behavior of this hash. Expanded receipt/restart/example tests did not run.

Read-only host evidence: Code Integrity Operational events 3077 and 3033 at
2026-11-06 19:46:47 Asia/Bangkok identify this executable as failing Enterprise
signing-level/code-integrity requirements, policy ID
`0283ac0f-fff1-49ae-ada1-8a933130cad6`. Authenticode status is `NotSigned`.
No security policy, trust store, Defender setting, filename or binary content
was changed to bypass that control. Signing/trust requirements and a permitted
test environment must be resolved before current-binary runtime acceptance.

The root may need another build for genuine final source fixes in jobs/auth;
its executable hash and actual runtime/installer results must supersede this
checkpoint explicitly. Repacking only to evade the host policy is not a test.

### Final candidate from the frozen backend source

Source commit: `976475c1df7b78eb7e7e9a32105e9f1d79945994`, which includes the
actor/generation-fencing/recursive-trigger fixes, module example, typed HTTP
responses and actual 10,000-row synthetic XLSX adapter. Before and after build,
`git diff --quiet 976475c1df7b78eb7e7e9a32105e9f1d79945994 -- backend` passed.
No Python source was edited by the packaging subtask.

One final build was performed to package those genuine source fixes, using
the same build script and output filename. There was no repacking, renaming,
policy modification, trust-store change or retry to evade Application Control.
The final executable was permitted to start and the expanded smoke completed
successfully. This outcome supersedes runtime acceptance for the final hash
only; the earlier deny events remain evidence for their own hash.

| Final candidate evidence | Result |
| --- | --- |
| Executable | `desktop/binaries/cafe-fin-sidecar-x86_64-pc-windows-msvc.exe` |
| SHA-256 | `ef636343329730d3b0cc6a73f9f6c72c55d0121fb149a75b0ec1baac324f357e` |
| Size | 33,008,864 bytes |
| Native inventory | PASS, 51 DLL/PYD entries with hashes in `desktop/notices/sidecar-native-inventory.json` |
| Embedded SQLite | PASS, extracted packaged DLL reports 3.53.1 |
| Missing/bad boot fields and wrong protocol | PASS, structured BOOT_PROTOCOL_INVALID |
| Native-style stdio launch | PASS, CREATE_NO_WINDOW, raw UTF-8 Vietnamese root with spaces, Windows/System32-only PATH, temporary cwd, no development Python environment variables |
| Local auth/security | PASS, health/session token/origin/user guards, bundled Argon2 setup and later login |
| Module registration/migration/example | PASS, create/read and idempotent replay of a Unicode sample note |
| Actual workbook grid paging | PASS, page 2 has exactly 500 items beginning at stable row ID 501 |
| Document API | PASS, DOCX and PDF generated, downloaded bytes match recorded hashes |
| Receipt replay | PASS, same request key returns identical file IDs/hashes in-process and after backend restart |
| Second frozen process | PASS, existing root rejected with DATA_ROOT_LOCKED |
| Restart persistence | PASS, local user/sample note persist; new sidecar token rejects the old token |
| Shutdown | PASS, orderly zero exit and empty stderr |
| Final PDF extraction/visual | PASS, Vietnamese text and shared snapshot identity checked; Poppler produced one page, inspected without clipping, glyph loss or overlap |
| Final DOCX structure | PASS, reopened with python-docx and shares the PDF snapshot identity; this is not visual/open/print acceptance |

Final proof directory outside Git:
`%TEMP%\cafe-fin-frozen-proof-teuq7uxt`. It contains
`frozen-document.docx`, `frozen-document.pdf` and `final-page-1.png`.
DOCX SHA-256:
`7cdcbdb3bc6f0e2764952c9446995420051b800b3d9ee1ce25cb0c8fda2e1f88`.
PDF SHA-256:
`82348a92e275b6ea46fa4a40147c52e727d073377b26c94287cf8ffe9b22e8a9`.
Snapshot SHA-256:
`4fdbb1ccade9fe86b9b02915bf9c8c5a1f06faafebf9c8ac9916efc9e5be0b1d`.

The smoke driver is outside the repository at
`%TEMP%\cafe-fin-frozen-sidecar-smoke.py`. Root owns committing source and
reviewable notices. The executable and proof data remain ignored/outside Git;
no commit, push, merge, release or READY tag was made by this subtask.
