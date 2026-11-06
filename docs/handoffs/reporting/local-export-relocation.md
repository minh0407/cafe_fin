# Human report copies after move and restore

The reporting activation hook now recreates human PDF/XLSX/TXT files in the new
root from immutable canonical exports, before core recovery/startup/workers. Core
backup remains reference-only: no core/private ORM dependency or migration was
added. Snapshot/hash, canonical FileStore identity/bytes, source root and backup
artifacts are preserved. This corrects the case where a copied DB said READY but
the new `reports/CafeFin-...` file was absent.

Worktree: `C:\Users\NC\.codex\worktrees\cafe-fin-reporting\cafe_fin`.
Branch: `codex/cafe-fin-reporting-20261106`. Owner module/test/docs only, no push.

## Order and copy semantics

1. Existing `restore_quarantine` runs first. Its activation-ID receipt transaction
   now also invalidates all existing LOCAL_EXPORTS projections to PENDING with
   `LOCAL_EXPORT_RELOCATED`, clears the old verified timestamp and audits the
   count under the actual current Admin. This applies to move and restore; move's
   sender/schedule configuration is still unchanged. Restore's quarantine of
   UNKNOWN/outbox/daily/settings stays before any worker or network opportunity.
2. The hook calls `repair_local_exports(actor, context)` synchronously. It checks
   current `core.manage` and the public core-bound ActivationContext. It keyset
   pages canonical EXPORTS by ID, at most 100 receipts in memory. Each reader
   closes before copying, and the existing export/render lock covers one file.
3. `ensure_local_copy(..., permission='core.manage')` validates the saved report,
   pinned canonical receipt and deterministic `safe_key`. It revalidates the
   captured Admin in claim/finalization writer transactions. Canonical content is
   copied outside the writer via FileStore.export: exclusive publication, no
   replacement, streaming size/SHA verification. Existing exact bytes are reused.
   No source factory, renderer, credential store or provider is called by repair.
4. Core recovery/startup follows only after this finite pass. Healthy copies are
   READY, hash-verified and already exist before recovery. No asynchronous job,
   new scheduler, privileged service principal or new UI approval is introduced.

Guard receipt replay does not invalidate a later successful copy again. Copy
reconciliation itself remains idempotent through the immutable export receipt,
hash/size and existing attempt compare-and-set; matching READY files require no
new copy/attempt. Legacy canonical exports without a local projection are also
materialized. The existing Export buttons remain the normal manual retry path.
The public owner helper can reconcile a bound candidate again with a current
Admin; it accepts no arbitrary path and does not release core admission.

Ordinary file IO failure/conflict is recorded as FAILED/CONFLICT and the pass can
continue with other files, leaving accounting/CRM usable after activation. A
reference failure before claim leaves the invalidated projection PENDING rather
than carrying a copied READY timestamp. A user file with different bytes is never
overwritten or deleted. Existing fixed-code system failure bookkeeping may mark
an interrupted claimed copy FAILED after revocation; it grants no file access or
READY state. Source/canonical data is never repaired by rewriting it.

Revoked/stale Admin authority stops repair and activation remains held. A hard
interruption also leaves pending/claimed copies honest. A subsequent current
Admin can verify/reuse completed bytes and repair remaining copies. The existing
core partial-activation boundary still applies: after intent without completion,
core remains FAILED_HELD or DORMANT/ACTIVATION_REPLAY_REQUIRED. Owner file repair
does not complete/reopen core activation or add a disposition API.

## Validation

Six new real SQLite/FileStore/prepare/dormant/activation tests cover:

- Actual move and restore with all three exported formats. Source human files
  exist, target files initially do not, then every target hash matches before
  jobs recovery. Page size is forced to 2 for three receipts; rendering is denied.
  Writer authorization still runs during the file-copy callback, proving the IO
  is outside a writer transaction. Same-ID guard/copy replay makes no extra copy.
- IO interruption and a preexisting unknown target file. Other formats complete,
  failed format is visibly FAILED/CONFLICT without a stale verified timestamp;
  retry reuses completed formats and never replaces the unknown bytes. Only the
  synthetic file owner resolves its own conflict in the test.
- A fault after physical publication, before READY: close/reopen with a fresh
  Admin reuses the first file and creates remaining copies, while core remains
  dormant. This is injected interruption with real DB/filesystem effects, not a
  claim of native kill/journal/process-exit acceptance.
- Revocation after physical copy prevents READY and stale-Admin replay. Another
  current Admin repairs the copies; audit records that actual Admin.

All cases hash source data files/DB and restore backup artifacts before/after,
plus the candidate's unchanged original manifest. The Windows process-lock byte
is excluded because the live lease deliberately denies reads. Snapshot/canonical
bytes are checked independently. Instrumented stores/providers show no credential
or provider call in these local-only cases.

```powershell
.venv/Scripts/python.exe -m pytest tests/reporting/test_restore_guard.py tests/reporting/test_local_exports.py tests/reporting/test_sender.py tests/reporting/test_daily_generation.py -q -p no:cacheprovider
.venv/Scripts/python.exe -m ruff check backend/cafe_fin/reporting tests/reporting/test_restore_guard.py
.venv/Scripts/python.exe -m ruff format --check backend/cafe_fin/reporting tests/reporting/test_restore_guard.py
git diff --check
```

PASS: **56 scoped cases in 38.71s** across restore guard, local exports, sender
and daily generation; Ruff lint/format and Git whitespace. The new six-case subset
also passed independently in 7.96s.
Environment: Windows 11 / Python 3.12.16 / SQLite 3.53.1, synthetic data only.
NOT RUN for this follow-up: full suite, benchmark, build/browser, native wire and
four-module acceptance; the coordinator owns the strengthened actual wire probe.

Activation duration now includes hash/copy of the paged export history; it is
finite but not benchmarked for a large archive. No speed/native timeout guarantee
is claimed. Later external edits/deletions remain checked by normal export retry;
a READY timestamp attests the last verification. Core orphan/reconcile policy and
cross-version restore verification are unchanged.
