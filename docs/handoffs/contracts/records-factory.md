# Per-request records bridge factory

Contracts manifest now accepts the additive keyword:

```python
module_manifest(records=None, *, records_factory=None)
# records_factory: Callable[[Runtime, Principal], RecordsReadBridge]
```

Coordinator integration, using only records' public module interface:

```python
from cafe_fin.records.module import RecordsReadProvider
contracts_manifest(records_factory=RecordsReadProvider)
```

The existing records=synthetic_bridge form still works. Supplying both forms
raises ValueError during registration instead of silently choosing one.

Each contracts source request first passes contracts.read and records.read, then
constructs a new provider from that request's Runtime and captured current
Principal. The provider/Principal is not stored in a global or module cache. The
same typed PartyDTO/WeighingDTO HTTP response remains unchanged; source copying
is still explicit and never writes records.

Provider construction is lazy: manual draft CRUD, preview, templates, exports
and attachment/history operations do not initialize the optional records factory.
An absent, unavailable or permission-denied records source therefore cannot turn
manual contracts into a mandatory records workflow. Source errors retain the
core envelope/status and UI can offer manual entry.

No records implementation was copied/cherry-picked into this lane. Root owns
registry wiring and integration against actual RecordsReadProvider. The lane's
factory regressions use typed synthetic providers with real HTTP/auth/SQLite.
Picker UI and bounded list search are delivered in a separate reviewable commit.

## Validation

The original typed static bridge/snapshot-preservation case and both manual
purchase/sale cases passed after the change. Dedicated factory regressions PASS:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/contracts/test_records_factory.py -q
# 10 passed in 7.94s; one existing Starlette/httpx warning.
.\.venv\Scripts\python.exe -m ruff check backend/cafe_fin/contracts/module.py tests/contracts/test_records_factory.py
.\.venv\Scripts\python.exe -m ruff format --check backend/cafe_fin/contracts/module.py tests/contracts/test_records_factory.py
# PASS.
```

Cases cover eight concurrent requests across two actors and both source types,
exact runtime/current principal and independent providers, nested typed DTOs,
fresh roles/versions/logout/disabled sessions, records.read denied before factory,
three source-only failure modes, unchanged static/unavailable compatibility and
ambiguous configuration rejection. An exploding factory is never invoked during
manual CRUD/preview/export/download/delete/restore. Source reads create no domain
rows, write receipts or audit mutations. Actual records integration is NOT RUN in
this lane checkout. No migration, DTO or dependency change is required.
