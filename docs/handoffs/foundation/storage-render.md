# Storage backup and document renderer handoff

Baseline: `cafe-fin-spec-v1`, commit `5925d43964e99033efe3146ae4d84902dd284df3`.
Implementation worktree: `C:\Users\NC\.codex\worktrees\cafe-fin-foundation-build\cafe_fin`.
This handoff covers foundation services and synthetic document output only.
It does not approve the foundation READY gate or implement contracts/accounting.

## Public services

`storage.DataRootService(path)` is constructed only from a trusted native folder
selection or the native machine configuration. Public REST clients must never
choose arbitrary absolute filesystem paths.

- `initialize()` requires a new/empty local root, checks writing and at least
  256 MiB free, creates the seven specified subdirectories and a format-1 marker.
- `open_existing(require_database=True, writable=True)` refuses a missing root,
  invalid/newer root marker, incomplete layout or missing existing DB. It does
  not replace a missing DB with an empty one. The DB migration runner separately
  checks schema versions before the app starts.
- `database_path` is `database/cafe_fin.db` beneath the root.
- `resolve_key(key)` rejects traversal, absolute paths, drive prefixes, backslash
  aliases, repeated separators, symlinks/junctions and escaping resolved paths.
- `acquire_lock()` / `release_lock()` use a held OS file lock. The file's
  existence alone does not mean another instance is running; process termination
  releases the lock. Call once for the backend lifetime.
- Known OneDrive roots and UNC/network drives are refused. Arbitrary third-party
  sync folders cannot be discovered reliably from a path alone and remain
  unsupported; the native folder wizard must explain this constraint.

`storage.FileStore(root, database, writer, max_bytes=2*1024**3)` exports:

- `put(stream, category, original_name, actor, request_key, media_type=...)`:
  streaming hash and write to a private temporary file, bounded size, fsync,
  then a short writer transaction for atomic rename, metadata, idempotency receipt
  and audit. No parsing, VBA, formulas or external links are executed. Categories
  are workbooks/documents/reports/imports. Stable response is frozen `StoredFile`.
- `get(file_id)` and `read(file_id)` resolve metadata server-side; `read` verifies
  size/hash before yielding a binary stream.
- `export(file_id, trusted_native_destination)` verifies the original and writes
  a new file atomically without replacing an existing destination.
- `reconcile()` reports missing/mismatched file IDs and orphan relative keys.
  It never deletes unknown files. A failure after durable rename but before DB
  commit intentionally leaves an orphan rather than claim a completed upload.
  A replay skips the rename and removes its staging temporary file; it does not
  accumulate unreferenced originals. An optional transactional `authorize` callback
  rechecks a native/API actor immediately before receipt lookup or registration.

Register `storage.MIGRATIONS` at boot. Namespace `core_files`, version 1 creates
`core_files`: UUID ID, hash, size, relative key, category, source name/media type
and UTC timestamp. Modules store its file ID, not absolute paths. Keep original
bytes immutable; edited data and exported projections use new file IDs.

`backup.BackupService(root, database, writer)` provides `create(destination)`,
`verify(backup)`, `restore(backup, new_destination)` and `move(new_destination)`.
Creation invokes SQLite's consistent backup API, then copies the referenced
immutable files outside the serialized writer. Core has no file-deletion API;
future cleanup must respect backup retention. Manifest size/hash and DB
integrity/foreign keys are verified before the candidate directory is renamed.
No raw `.db` copy omits WAL. Native services must show maintenance state while
the backup/move barrier blocks writes; copying a large file set can take time.
Failed operations retain their uniquely named `.partial-*`/`.restore-*` folder
for investigation. Nothing is restored over an existing destination.

Restore and move retain the source root. `move` prepares a verified replacement
at one cutoff; the trusted application controller must quiesce new mutations,
close the old services, switch its machine configuration and relaunch using the
verified destination. The function deliberately does not alter machine config
or delete the old root. End-to-end native move/config-switch remains a gate.
Only DB-referenced stored files are backed up; logs, unknown/orphan files,
in-flight upload-part files and prior backup directories are not promoted into
the restored live store. Reconcile before retiring an old root.

## Document renderer spike

`renderers.DocumentSnapshot` is a frozen tuple-based snapshot of title/subtitle,
label/value fields, prose, table headers and table rows. Scalars are strings;
the renderer does not reinterpret business quantities or calculate money.
It rejects mutable containers and limits row/column/content sizes.
`DocumentRenderer().docx(snapshot)` and `.pdf(snapshot)` independently return
`RenderedDocument(format, content, content_sha256, snapshot_sha256)`. Modules
save the snapshot and each successful output independently; PDF failure need
not discard an existing DOCX. No contract numbering or domain status is added.

PDF is produced directly by the open-source ReportLab toolkit with Noto Sans
TrueType regular/bold embedded. There is no Office/Pango/WeasyPrint dependency,
shell execution, network call or HTML template interpreter. DOCX is generated
by python-docx and references Noto Sans, without font embedding. A viewer can
substitute fonts. DOCX and PDF share content identity, not identical pagination.
Unusually tall table cells can exceed a page; the renderer reports RENDER_FAILED
instead of returning a false successful export. Arbitrary workbook fidelity,
DOCX templates and domain contract layout are outside this foundation spike.

Fonts and copied dependency license notices are in `core/assets`; exact pins,
source revision, hashes, licenses and installer collection requirements are
documented in `core/assets/THIRD_PARTY_NOTICES.md`. Bundle all those assets and
`python-docx/templates`. Audit actual wheel-native dependencies and notices
against the built sidecar before distribution; the main Python package license
alone is not the complete native dependency notice inventory.

## Actual validation on 2026-11-06

Machine: Windows 11 Pro 10.0.26200, approximately 31.8 GiB physical RAM.
Repository venv: Python 3.12.16, SQLite 3.53.1 (contains the WAL-reset fix).
Document visual proof additionally used the resolved Codex bundled runtime
Python with ReportLab 4.4.9/python-docx 1.2.0 and bundled native Poppler.

| Check | Result and evidence |
| --- | --- |
| Scoped backend suite | PASS: `.venv/Scripts/python.exe -m pytest tests/core/test_storage.py tests/core/test_renderers.py -q`, 9 passed |
| Lint/format | PASS: ruff check and format on the three service modules and their two tests |
| Unicode/space data root, original-byte export, request replay/conflict | PASS against actual SQLite/filesystem |
| Second process using same root | PASS: a real Python subprocess receives DATA_ROOT_LOCKED |
| Metadata/audit rollback | PASS: actual SQLite trigger rejects the audit write; metadata and audit both roll back, durable orphan retained for reconciliation |
| Upload size limit and ENOSPC handling | PASS for bounded input and injected stream ENOSPC; this does not prove operation on a physically full drive |
| Live WAL backup/restore/move candidate | PASS: open DB reader, second saved file, snapshot, restore into Unicode root, re-open/migrate DB, verify both file links; source survives move |
| Corrupt backup and overwrite refusal | PASS: changed source bytes fail hash validation; existing restore/export destinations are not replaced |
| DOCX/PDF content/snapshot identity | PASS: python-docx reopen, pypdf text and PDF embedded-font checks |
| PDF visual | PASS: generated one page, rendered by bundled Poppler, visually inspected; Vietnamese accents, table and exact strings readable without clipping/overlap |
| DOCX visual | NOT RUN successfully: actual render_docx.py attempt failed with `FileNotFoundError: LibreOffice soffice.exe was not found on PATH`; bundled LibreOffice is unavailable on this Windows host |
| DOCX opening/printing without Office | NOT RUN; cannot infer from ZIP/XML extraction |
| Physical full disk, denied ACL, actual unplugged drive, power-loss durability | NOT RUN; injected I/O tests are not those hardware conditions |
| Installer/clean Windows/no-Python document smoke | NOT RUN in this service subtask; must run against the bundled sidecar/application |
| Native wizard backup/restore/move configuration swap | NOT RUN; service-level candidate verification is not end-to-end acceptance |

Visual proof files remain outside Git at
`%TEMP%\cafe-fin-foundation-render-proof\vietnamese-spike.{pdf,docx}` and
`pdf-page-1.png`. No operational DB/workbook/document data is committed.
Synthetic snapshot SHA-256:
`4fdbb1ccade9fe86b9b02915bf9c8c5a1f06faafebf9c8ac9916efc9e5be0b1d`.
The PDF SHA-256 from this proof run was
`2b36391bd18aab9bebc387bae2106de4b55af58ddb8db8ba17bd5be95186161f`;
DOCX was `ccf1a2ba8d277413667ee36a512193ab7529be0094296a485d5a2ed87c3d1536`.
Generated document byte hashes can vary with library timestamps; snapshot hash
is the content identity shared across both formats.

No commit, push, merge or READY tag was made by this subtask. Root owns the
candidate commit and final gate report.
