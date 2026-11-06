# Empty destination stays unconfigured before any attempt

Independent review of `92eb15a` found that an OA with a credential but an empty
GMF group could create local output correctly, then catch-up promoted its
UNCONFIGURED delivery to WAITING using credential presence alone. Dispatch began
an attempt and reached OfficialGMF.verify with an empty group. Manual retry had
the same promotion gap.

## Fix

- `credential_ready` now requires **OA + group + OS credential presence**. Catch-up
  cannot promote a row merely because a credential exists; local auto-generation
  remains independent and still creates its selected report/files.
- Manual retry reads readiness outside the writer, validates the configuration
  version in the transaction, and retains UNCONFIGURED/ZALO_UNCONFIGURED when
  target/credential configuration is missing. It preserves historical attempts
  and receipts rather than resetting them or creating an external attempt.
- Dispatch checks readiness and the selected row's immutable OA/destination
  before claiming SENDING. A legacy WAITING row with incomplete configuration
  returns to UNCONFIGURED with an ordinary audit transition, no attempts increment
  and no ATTEMPTS preflight row. Token/refresh/verify/upload/send are not called.
- The defense also covers a legacy empty pinned destination when the current
  configuration has since become complete. It never retargets that old payload.
  UNKNOWN/SENT retry restrictions, actor authorization and immutable pins remain.

No migration, frontend, shared service, adapter/target or dependency change.
Canonical/local report files and snapshot/hash/version remain available. Missing
configuration is not a transport failure or proof that a send was attempted.

## Validation

```powershell
.\.venv\Scripts\python.exe -m pytest tests/reporting/test_incomplete_delivery.py tests/reporting/test_sender.py tests/reporting/test_daily_generation.py tests/reporting/test_date_contract.py tests/reporting/test_process_crash.py tests/reporting/test_review_recovery.py tests/reporting/test_windows_credentials.py tests/reporting/test_local_exports.py -q
.\.venv\Scripts\python.exe -m ruff check backend/cafe_fin/reporting tests/reporting
.\.venv\Scripts\python.exe -m ruff format --check backend/cafe_fin/reporting tests/reporting
```

PASS **62 focused cases, 26.19s**, including eight new cases. Actual SQLite/TXT/
FileStore outputs exercise empty OA, empty group and both absent, catch-up,
manual retry from UNCONFIGURED/FAILED, legacy WAITING repair, and real
Runtime.start recovery/startup JobRunner dispatch after reopening. Each asserts
attempts=0, zero ATTEMPTS rows, saved local-file SHA, one report/capture, and no
access_token/verify/send/upload/request calls. Tests use the real OfficialGMF
verify implementation behind instrumentation; its request boundary is blocked
so a regression cannot make a WAN request.

The supplied independent `probe_schedule_empty_destination.py` was copied to a
new temp script with only its import ROOT changed to this worktree. PASS result:

```json
{"generation":"COMPLETED","delivery":"UNCONFIGURED","error":null,"destination":"","attempts":0,"network_calls_stubbed":[],"reports":1}
```

Ruff/format/whitespace PASS. Full core suite and frontend/browser build were NOT
RUN again for this increment: no core/frontend code changed, and the selected
suite covers the sender/daily/retry/restart/receipt/date/local-file behaviors at
risk. Prior full-suite/UI evidence remains historical as recorded in their
handoffs; it is not presented as a new full run. All fixtures synthetic; no live
Zalo send. No push, merge, READY tag or additional feature was made.
