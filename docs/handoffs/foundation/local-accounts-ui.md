# Local account manager UI

Named export `LocalAccountsPage` in `frontend/src/app/LocalAccountsPage.tsx` is
ready for root's settings-route wiring. This task does not edit App, registry,
Playwright configuration, backend or shared API/session/types.

## Behavior and API

- Component-level gate requires a logged-in Admin with `core.manage` or `*`.
  Operator rendering is denied before any user-list request.
- Lists `/users?page=<n>&page_size=50&search=<text>`, with optional `role` and
  `active` filters. Lists are server paged/searchable, with stale-query sequence
  guards and actor/generation remounting.
- Creates username/password/role via POST `/users`. Username is 3–64 characters
  with no surrounding whitespace; password is 10–128 characters and never trimmed.
- Edits only role/active via PATCH `/users/{id}` with the displayed
  `expected_version`. No password reset or username edit is exposed.
- HTTP field errors and request IDs are shown without request bodies or secrets.
  A version conflict requires reload/reopening the account, not automatic overwrite.
- POST/PATCH command JSON is frozen together with its request key before sending.
  Unknown/network/body/server outcomes freeze further mutations and offer explicit
  retry of exactly the same bytes/key. Known validation/conflict/permission errors
  settle the command and allow correction. No automatic mutation replay occurs.
- Passwords and pending commands exist only in component memory. Password input is
  cleared after success or definitive rejection; there is no localStorage,
  sessionStorage, URL, logger or credential persistence in this component.
- Responses are checked against mounted owner/generation before changing UI.
  Changing actor destroys the prior forms and pending-command UI.
- Core revokes target sessions after every successful PATCH. A successful
  self-edit therefore always clears the local session, including a no-op edit.
  If a self-edit response is lost, retry may receive 401 because the original
  operation revoked its token; shared API logs out for reauthentication/reload.
  The UI does not claim such an uncertain operation succeeded.

## Validation

`frontend/tests/local-accounts.spec.ts` mounts the real component independently
of App wiring through Vite and mocks login/user HTTP routes. It covers operator
denial, server paging/search/filter parameters, creation and field errors,
versioned editing/conflict, exact-body uncertain retry, stale list/command
responses across actor changes, password clearing and self-edit logout.

- `npx playwright test tests/local-accounts.spec.ts --workers=1`: **8 PASS**,
  Chromium, including exact-body/key retry for both POST and versioned PATCH.
- `npm run typecheck`: **PASS**.
- Create/edit Forms have distinct names/DOM IDs so role labels focus the correct
  control. Mutation buttons keep stable accessible names while loading.

These tests use the component harness with HTTP/login mocks; they do not claim
coverage of App's settings-route wiring, real account authorization or Windows
acceptance. Root owns those integration gates and the real-api test flow.
