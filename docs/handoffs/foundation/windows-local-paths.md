# Windows local disk aliases at the core boundary

The native CI failure reproduced in core: Rust fs::canonicalize returns a valid
local disk path such as `\\?\C:\CafeFinData`, while DataRootService previously
classified any leading double backslash as remote. Simply allowing that prefix
was insufficient: a verbatim path reaching Database produced SQLite URI authority
`%3F` and failed before startup.

`core/local_paths.py` now supplies one shared disk-path representation. Only an
explicit verbatim ASCII drive-absolute form is mapped to its ordinary drive
spelling, after lexical validation and before pathlib can collapse components.
This is not a generic UNC/device prefix strip. Storage/root/file-export paths,
activation canonical identity and backup source/destination use that common form.
Backup create/verify/restore/move now consume the validated preflight return;
overlap comparisons no longer compare a verbatim path to an ordinary spelling.

Actual UNC and verbatim UNC remain denied. Device/object-manager/Volume GUID paths,
drive-relative paths, ADS, dot/parent components, trailing dot/space, invalid Win32
characters and reserved DOS device components are rejected. Reparse detection uses
lstat attributes before resolution, including junctions and other reparse tags;
fixed/removable-drive and OneDrive guards remain enforced. Cloud environment and
selected path aliases pass through the same canonical representation.

The fingerprint formula remains exactly
`SHA256(normcase(str(canonical_location(path))))`. Existing ordinary-path bytes,
root UUIDs, activation markers and receipts are not rewritten, and there is no
dual-hash compatibility fallback. Normal and valid verbatim disk aliases now
produce that same original ordinary-path fingerprint and acquire the same root
lock. The full path is retained rather than truncated. Actual paths beyond 260
characters, including Unicode, were exercised on the current Windows runtime with
LongPathsEnabled=1; no registry or policy setting was changed.

New focused Windows coverage: **24 PASS in 7.16 seconds**, zero skips. It includes
real long-path Runtime/SQLite/FileStore export/backup/restore/move, marker and
legacy-fingerprint equality, mixed-alias overlap refusal, both cloud alias
directions, a real junction, and lexical network/device/hazard rejection before
filesystem resolution. An unpatched Python child boots from a verbatim root,
performs backup with ordinary-spelling receipt replay, then move and restore
through verbatim destinations/sources with dormant activation and CLOSED/exit 0.

```powershell
.venv/Scripts/python.exe -m pytest tests/core/test_windows_local_paths.py -q -p no:cacheprovider
```

Combined focused regression: **91 PASS in 56.21 seconds**, zero errors, failures
or skips. This includes the new Windows tests, existing storage, source identity,
maintenance operations/activation, private-pipe protocol and human-copy restore
workflow. Scoped Ruff lint/format and Git whitespace checks pass.

Final ordering hardening: resolve_key checks candidate/parent reparse attributes
before resolved containment, matching root preflight ordering. An actual local
junction plus spies on resolved_local_path and Path.resolve proves both ordinary
and verbatim callers are denied without either resolve function being called.
No WAN target/probe is used and allowed-key rules are unchanged. Focused rerun:
**33 PASS in 8.28 seconds** (Windows alias tests plus existing storage), zero skips;
scoped Ruff lint/format and whitespace checks pass. The earlier 91-case result
predates this ordering-only change and was not repeated.

```powershell
.venv/Scripts/python.exe -m pytest tests/core/test_windows_local_paths.py tests/core/test_storage.py tests/core/test_source_identity.py tests/core/test_maintenance_operations.py tests/core/test_activation.py tests/core/test_maintenance_protocol.py tests/core/test_maintenance_restore_protocol.py -q -p no:cacheprovider
```

XML/log evidence lives outside Git in the session visualization directory as
`windows-local-paths-20261107.{xml,txt}` and
`windows-local-paths-regression-20261107.{xml,txt}`. No full backend suite, native
executable/build, benchmark, network send, credential values, schema migration,
dependency, native or UI change is part of this patch.
The ordering rerun is `windows-local-paths-ordering-20261107.{xml,txt}`.
