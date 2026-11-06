# Actual private-wire restore regression

New isolated test: `tests/core/test_maintenance_restore_protocol.py`. It reuses
the existing real Child/envelope/login transport helpers without patches and
boots the actual default registry. Source migrations and real HTTP operations
prove records, contracts, accounting and reporting are all present.

One synthetic workflow covers source Admin login/source identity, original CSV
upload, inventory receipt, independent cash-book row, manual contract and saved
report/TXT canonical export. It enables local-only scheduling with empty OA/group
and no configured credentials, then queues an UNCONFIGURED delivery. No outbound
send or connection-check endpoint is invoked.

The private wire creates a verified online backup, then quiesces and prepares a
restore from that backup into the fixed new target. Source closes with matching
CLOSED plus observed exit 0; its old root and canonical files remain present.
Target starts explicitly negotiated DORMANT. Business HTTP is denied before
activation, source token is rejected and a fresh target Admin login activates.

The actual default reporting on_activate sets restore review required, disables
sender/auto generation and changes the restored delivery to UNKNOWN with
RESTORE_REVIEW_REQUIRED, without attempts. Real core audit and owner receipt each
occur once. Records/accounting/contract/report data, canonical file IDs/hash/size,
downloaded original bytes and the original backup manifest hash are preserved.

After an explicit target Admin local-only re-enable, two private status calls,
duplicate activation and clean close/restart retain the reviewed settings/version.
There remains exactly one quarantine audit/receipt; no resuspension or guard
reexecution changes the Admin choice. The restarted child also closes with CLOSED
plus exit 0.

PASS: **1 case in 7.18 seconds**. Scoped Ruff lint/format and Git whitespace
checks pass. Evidence XML/log is outside Git as `restore-wire-20261107.{xml,txt}`
in the session visualization directory.

```powershell
.venv/Scripts/python.exe -m pytest tests/core/test_maintenance_restore_protocol.py -q -p no:cacheprovider
.venv/Scripts/python.exe -m ruff check tests/core/test_maintenance_restore_protocol.py
```

This is Python sidecar + HTTP + SQLite + canonical FileStore evidence, not native
executable/GUI, cross-version migration restore, clean-client installation,
power-loss, external send, credential-value or benchmark acceptance. No product,
existing test, config/dependency, native or UI file was edited. The concurrent full
backend run had already collected before this new case; this focused result is
reported separately rather than included in its total.
