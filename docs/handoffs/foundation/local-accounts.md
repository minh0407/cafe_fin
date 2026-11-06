# Local account listing for Admin management

`GET /api/v1/users` requires the local app session, a logged-in user and current
`core.manage` (Admin) permission. The service revalidates the captured principal
inside the same explicit readonly SQLite snapshot used for count and rows.
No Google/cloud identity or approval workflow is added.

Query parameters:

- `page`: integer >=1, default 1.
- `page_size`: integer 1..500, default 50.
- `search`: username substring, maximum 128 characters, default empty. `%`, `_`
  and backslash are literal characters, not wildcard operators. SQLite's usual
  ASCII case-insensitive matching applies; no accent-insensitive normalization.
- `role`: optional `admin` or `operator`.
- `active`: optional boolean. Omit it to include active and disabled accounts.

Stable ordering is username ascending, then ID ascending. Filters apply before
count and pagination; out-of-range pages return empty items with the filtered total.

```json
{
  "items": [{
    "id": "11111111-1111-4111-8111-111111111111",
    "username": "local-operator",
    "role": "operator",
    "version": 1,
    "active": true
  }],
  "total": 1,
  "page": 1,
  "page_size": 50
}
```

The typed response is `UserPageDTO`, containing only existing `UserDetailDTO`
fields. Passwords, hashes, credentials, sessions, permissions and private DB fields
are excluded from the listing projection. The public service equivalent is
`AuthService.list_users(principal, *, page=1, page_size=50, search='', role=None,
active=None)`; it performs its own authorization and input validation.

Existing `POST /api/v1/users` creation and `PATCH /api/v1/users/{id}` role/active
updates are unchanged. PATCH still requires `expected_version`/`request_key`,
invalidates affected sessions and prevents disabling/demoting the last active
Admin. No password reset, schema/dependency/migration or UI changes are added here.

## Validation

PASS: 14 focused regressions in 18.24 seconds, including 9 new listing cases.
Scoped Ruff check, format check and Git whitespace checks pass. The existing
Starlette/httpx deprecation warning remains.

```powershell
.venv/Scripts/python.exe -m pytest tests/core/test_user_listing.py tests/core/test_auth_jobs.py tests/core/test_api_sidecar.py -q -p no:cacheprovider
.venv/Scripts/python.exe -m ruff check backend/cafe_fin/core/auth.py backend/cafe_fin/core/api.py backend/cafe_fin/core/http_types.py tests/core/test_user_listing.py
```

The checks cover 401/403, public response/OpenAPI fields, stable paging, literal
wildcards/backslash/Unicode search, active/role filters, invalid query bounds,
large out-of-range pages, disabled/demoted Admin after request capture, and the
unchanged last-Admin guard. All accounts and credentials are synthetic. The
concurrency probe creates a real account through a second physical SQLite writer
connection between count and row retrieval; the first result keeps one consistent
snapshot, and a new request sees the new account. No fake counts or read-only DB
substitutes are used. Native installer/UI account flows were not rerun in this
backend-only increment; the coordinating UI work consumes the exact path/shape
documented above.
