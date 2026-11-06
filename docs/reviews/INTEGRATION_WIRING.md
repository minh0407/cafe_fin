# Default business-module assembly and integration evidence

Coordinator-owned `backend/cafe_fin/registry.py` now registers example, records,
contracts, accounting and reporting. Contracts retains its public
`records_factory=RecordsReadProvider`. Accounting provides its own migration/job
manifest. Reporting receives `actor_source_factory=_report_sources` and a scoped
`WindowsCredentialStore()` adapter. No module or other core/UI file is modified
by this wiring increment.

Each report capture constructs fresh actor-bound public providers:

```python
AtomicSources(
    runtime.reader,
    lambda conn, first, last, *, cutoff: RecordsReadProvider(
        runtime, principal, connection=conn
    ).inventory_summary(first, last, cutoff=cutoff),
    lambda conn, book_id, first, last, *, cutoff: AccountingReadProvider(
        runtime, principal, connection=conn
    ).book_summary(book_id, first, last, cutoff=cutoff),
)
```

Accounting's provider is imported from its supported `accounting.public` path;
records from `records.module`, and the source adapter from `reporting.sources`.
`AtomicSources` begins one real read-only SQLite transaction and passes that exact
connection to both owners. There is no global Admin, cached request principal,
private reporting ORM adapter or inferred cash mapping. Report capture follows
the current shared `CONTRACT_VERSION` (currently 3); optional display names do not
change exact quantities, visibility, scopes or monetary meanings.

The Windows secret-store constructor loads the OS API and reports availability;
an unavailable adapter is not a startup failure. Local reports work while sender
configuration is disabled/unconfigured. No fallback plaintext/env/DB credential
store is added. These tests set no credential values, make no Zalo calls and do
not enable a sender or a daily schedule. One registered 60-second reporting timer
is supplied by the module; wiring does not create another timer or job runner.

## Actual default-registry tests

`tests/integration/test_business_workflow.py` uses the real default Runtime registry,
FastAPI handlers, file-backed SQLite/WAL, owner services and the existing worker.
It does not substitute a fake accounting table/provider.

- Creates real records inventory and independent accounting books/rows. One-day
  and inclusive two-day reporting endpoints, VN-to-UTC bounds, coverage, explicit
  cash receipt/payment meanings and uninterpreted metrics are checked. Production
  categories come from the real records v2/v3 public breakdown.
- Saves/exports a manual contract to real DOCX/PDF and checks downloaded hashes,
  without changing stock or accounting metrics. Manual party/weight input works
  without CRM links; actual contracts source routes read entered records parties
  and weighings (including an Operator request).
- Changes both owner sources after capture and verifies the stored report snapshot
  and hash remain unchanged; a new report sees the changed values.
- Uploads an original CSV, parses/maps/validates through actual accounting jobs,
  then pauses after a **committed pending chunk**. Raw storage contains the rows
  while HTTP lists, the public accounting provider and reporting still show only
  published/manual rows. Cancelling at the safe worker boundary leaves the durable
  attempt hidden, allowing the same worker to produce a CSV export proving pending
  data is excluded. Resume atomically publishes both rows. Fixing the remaining
  invalid source and confirming again produces three published source rows, three
  stable claims and two published attempts, without duplicating the first pass.
  Report totals, CSV rows, stock independence and original-byte preservation are
  checked before pending, during pending and after publication/second pass.
- A real second Database/WriteCoordinator updates records and accounting between
  the two public source reads. The first report retains `10.001 kg / 10.01 VND`;
  the next Operator capture sees `15.003 kg / 15.03 VND`. Both source reads use the
  same physical connection and root transaction, distinct from the writer; the
  observed actor changes from Admin to Operator on the next capture.
- Disabling the Operator after inventory capture still aborts report persistence
  through writer revalidation. No report, preview receipt or report audit survives.
- Simulated OS-adapter unavailability still permits default-registry startup,
  health/settings and local reporting preview with sender unconfigured.

The import pause wraps the real `JobContext.commit_chunk` only to choose race
timing; the actual pending writes, receipt, checkpoint, cancellation, resume and
publication remain owner/core implementations. No second JobRunner is started.

## Validation and remaining gates

PASS: 26 focused integration/boundary regressions in 24.43 seconds, including all
five new default-registry integration cases. Scoped Ruff check, format check and
Git whitespace check pass. The existing Starlette/httpx deprecation warning remains.

```powershell
.venv/Scripts/python.exe -m pytest tests/integration/test_business_workflow.py tests/core/test_module_registration.py tests/core/test_api_sidecar.py tests/accounting/test_public_api.py tests/reporting/test_actor_sources.py -q -p no:cacheprovider
.venv/Scripts/python.exe -m ruff check backend/cafe_fin/registry.py tests/integration/test_business_workflow.py
```

The current project test selection (`tests`) and Windows workflow include the new
integration directory. Evidence XML from this run is outside Git in the session
visualizations directory as `business-wiring-regression-20261107.xml`.

No import-scale benchmark, external send, credential-value test, native
installation or clean Windows acceptance is claimed by this wiring.
Accounting's public provider is a live capture reader; historic reports use their
frozen stored snapshot rather than trying to recreate an old book with a new read.

## Combined-suite test discovery

Pytest uses `--import-mode=importlib`. The root `tests` directory and each Python
test lane (`core`, `records`, `contracts`, `accounting`, `reporting`, `integration`)
are explicit packages. Shared test helpers use `tests.<lane>.<module>` imports,
including reporting conftest imports inside crash-process scripts. Those children
receive the repository root and backend on `PYTHONPATH`; no `sys.path` mutation is
used. Repeated names such as contracts/reporting `test_api.py` and
accounting/reporting `test_process_crash.py` coexist under distinct namespaces.

Run the reporting evidence helper from the repository root as a module (this
supersedes the older direct-script invocation in reporting handoffs):

```powershell
.venv/Scripts/python.exe -m tests.reporting.generate_evidence --named --output "$env:TEMP/cafe-fin-reporting-v3-evidence"
```

The module command passed with synthetic sources and produced PDF, XLSX and TXT
outside Git. An AST comparison of all 26 changed existing Python files verifies
that test bodies/assertions are unchanged except the deliberate subprocess helper
import/PYTHONPATH namespace changes. No test skips or name changes were introduced.

Collect-only PASS: **1017 tests in 1.72 seconds**, no import mismatch or
missing-helper errors. Full-suite PASS: **1017 passed, zero failed/skipped, one
existing Starlette/httpx deprecation warning in 391.82 seconds**. This includes
the real 60-second periodic timer, WAL/process-death recovery and real Windows
credential-store tests already in the suite.

```powershell
.venv/Scripts/python.exe -m pytest --collect-only -q -p no:cacheprovider
.venv/Scripts/python.exe -m pytest tests -q -p no:cacheprovider --junitxml="<outside-git>/backend-full-importlib-20261107.xml"
.venv/Scripts/python.exe -m ruff check tests
```

The collect log, full-run log and JUnit XML are outside Git in the session
visualizations directory (`test-discovery-importlib.txt`,
`backend-full-importlib-20261107.txt`, `backend-full-importlib-20261107.xml`).

`ruff check tests` passes. A broader `ruff format --check tests` reports existing
formatting differences in 15 files after the three updated subprocess expressions
are formatted; four are pre-existing bodies in records files whose imports changed.
These bodies are preserved by this discovery-only change.
