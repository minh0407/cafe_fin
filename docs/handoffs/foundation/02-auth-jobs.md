# Foundation increment 02 — local credentials and durable jobs

Incremental candidate on the worktree/branch in `01-core.md`; not READY.

`AuthService` uses Argon2id local password hashes, one-time first-admin setup, Admin/Operator permission checks, bounded login attempts, memory-only expiring bearer sessions, logout/restart invalidation, versioned account enable/role changes and protection for the final active admin. Account creation is idempotent; the credential binding in request hashing also uses Argon2 to avoid creating a fast password-guess oracle. Credentials and tokens are excluded from audit. Permissions are re-read on each authentication. No Google OAuth or cloud auth.

`JobService` persists immutable payload JSON, states WAITING/RUNNING/COMPLETED/FAILED/CANCELLED/RECOVERABLE, phase, counts, checkpoint, retry count and sanitized error code. Accounting owns its additional domain import state (`contracts.ImportJobState`); it must integrate transition checks with these generic execution states. Registration uses `JobHandler(run,resumable)`. Submission uses core idempotency; manual resume is limited to three execution attempts. Startup changes abandoned RUNNING to RECOVERABLE and does not auto-replay them.

`JobContext.commit_chunk` commits effect+receipt+checkpoint+counts atomically; repeated chunk with the same content returns its saved JSON result and never reruns effect. `check_cancelled` is cooperative. CPU/file/network work stays outside writer. `finalize(effect)` puts final publication and COMPLETED in the same writer transaction, so cancellation cannot claim to undo an already-published final result. Module jobs should use this for final import publication and coordinate their attempt state in that transaction. `JobRunner.close` waits for a cooperative boundary and explicitly fails on timeout.

Migrations: `core_auth` v1 (`core_users`) and `core_jobs` v1 (`core_jobs`, `core_job_receipts`). Boot must register both tuples before services start. `Database.backup_to` now closes sqlite source/target handles explicitly, necessary before Windows directory renames.

Actual validation on Windows 11 / Python 3.12.16 / SQLite 3.53.1:

- PASS: `.venv\Scripts\python.exe -m pytest tests/core/test_auth_jobs.py -q`: 3 passed. Includes Admin/Operator checks, credentials excluded from audit, request replay/conflict, logout/restart/session revocation, final-admin safeguard, chunk receipt retry/conflict, rollback and finalization/cancel boundary.
- PASS: actual subprocess `os._exit(23)` after committed effect. New process preserves checkpoint, reports RECOVERABLE, explicit resume completes without duplicate effect.
- PASS combined core/import/stock suite: 25 passed in 3.14s; scoped Ruff PASS.
- NOT RUN at this increment: HTTP enforcement and sidecar/native lifecycle (next increment), production module jobs, physical power loss, installed Windows-clean smoke and million-row import.

No automatic retry of effects without checkpoint/receipt, no runtime database or real account data in Git.
