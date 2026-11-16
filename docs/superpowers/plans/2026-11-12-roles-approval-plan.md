# Roles, Sign-in Approval and Users Page Implementation Plan (Plan 1 of 4)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Nobody sees data until the owner approves them; the backend knows who is calling and what role they hold; the owner manages users and password accounts from a Users page.

**Architecture:** The Next.js route handlers forward the signed-in user's id in an `X-App-User` header. FastAPI resolves that id to a role from `app_users` (cached ≤30 s) and one central policy decides access per route and method. NextAuth's Credentials provider and Google sync both go through backend endpoints; roles live only in the database.

**Tech Stack:** FastAPI, SQLAlchemy `execute_sql` helper, argon2-cffi, httpx, pytest · Next.js 14.2.35 App Router, NextAuth 5.0.0-beta.32, SWR, Tailwind, vitest (new, dev only)

**Spec:** `docs/superpowers/specs/2026-11-12-roles-privacy-options-cost-design.md` (Parts 1, 2, 3, and the role-matrix and login tests of Part 7)

**The four plans for this spec:**

| Plan | Covers | Status |
|---|---|---|
| 1 (this file) | Roles, identity forwarding, sign-in, approval, Users page | ready |
| 2 | %-only view: server-side redaction, `tradePct`, guest UI (spec Part 4) | written when Plan 1 is merged; consumes `Viewer` from Task 2 |
| 3 | Paid-model daily cap, guest chat allowance, guests never trigger analysis (spec Part 6, call 11) | written after Plan 2 |
| 4 | Options split and owner Options tab (spec Part 5) | written after Plan 3 |

**Until Plan 2 is live, the owner must not approve anyone as guest or family:** the API still returns dollar fields.

**Repos and branches:** backend `C:\github\dev\LLM-portfolio-project`, frontend `C:\github\dev\LLM-portfolio-frontend` (app in `frontend/`). Branch name in both: `feat/roles-approval`, cut from `main`.

## Global Constraints

- Roles are exactly `pending`, `guest`, `family`, `owner`. `viewer` and `editor` no longer exist anywhere.
- Rank: pending 0, guest 1, family 1, owner 3. Unknown or missing role ranks 0.
- A backend request with no `X-App-User`, or an unknown id, is treated as `pending`. Exempt paths: `/health`, `/webhook/*`, `/auth/*`.
- `DISABLE_AUTH=true` (local development) acts as owner.
- Role cache lifetime: at most 30 seconds, in both backend and frontend.
- Only `OWNER_EMAILS` grants owner to a Google account. At least one owner must always remain. The owner cannot revoke or delete themself.
- Password rules: 10 to 128 characters; 14 minimum for an owner account. Username: `^[a-z0-9][a-z0-9._-]{2,31}$`, stored lower-case.
- Lockout: 5 failed logins for a username locks it for 15 minutes.
- Approval alerts: at most 20 a day; a failed alert never blocks sign-in.
- Never log passwords, hashes, tokens or the API key.
- Commit only inside the feature branch. Do not push, merge or deploy; the orchestrator and Qais do that.
- Never edit `.env` files, never touch `data/security-review-2026-11-10.md`, never loosen `.claude/hooks/robinhood_readonly_guard.py`.
- Every new page must work at 375 px width: no sideways scroll, tap targets ≥ 40 px.
- Commit messages end with `Co-Authored-By: Claude Fable 5.2 <noreply@anthropic.com>`.

## Review Focus

1. **Backend unreachable while the frontend confirms a role.** Expected: the route returns 503 with "Try again in a moment", never falls back to a role from the cookie. Test in Task 8.
2. **A deleted or revoked user with a live browser session.** Expected: data calls return 403 within 30 seconds. Tests in Task 2 (cache expiry) and Task 8.
3. **Username input with capitals, spaces or an email address.** Expected: trimmed and lower-cased; rejected with a clear message when it doesn't match the pattern. Test in Task 4.
4. **A 5 MB password, or a password of spaces.** Expected: rejected before any hashing happens. Test in Task 4.
5. **An existing pending Google user whose email is later added to `OWNER_EMAILS`.** Expected: owner on next sign-in. Test in Task 4.

---

## File Structure

**Backend — create:**
- `schema/080_roles_and_password_accounts.sql` — roles constraint, password columns, viewers to pending
- `app/identity.py` — `Viewer`, role constants, `resolve_viewer` dependency and its cache
- `app/access.py` — the one access policy, `enforce_access` dependency
- `app/passwords.py` — hashing, verification, password and username rules
- `app/routes/users.py` — owner-only user management
- `src/approval_alert.py` — Discord REST alert
- `tests/test_identity.py`, `tests/test_access_matrix.py`, `tests/test_auth_password.py`, `tests/test_users_api.py`, `tests/test_approval_alert.py`

**Backend — modify:** `app/auth.py`, `app/main.py`, `src/expected_schemas.py`, `src/aws_secrets.py`, `requirements.txt`, `.env.example`, `scripts/audit_ec2.sh`

**Frontend — create (under `frontend/`):**
- `src/app/pending/page.tsx`
- `src/app/settings/users/page.tsx`, `src/components/settings/UsersTable.tsx`, `src/components/settings/PasswordAccountForm.tsx`
- `src/app/api/users/route.ts`, `src/app/api/users/[id]/route.ts`, `src/app/api/users/[id]/password/route.ts`
- `src/lib/session-role.ts` — fresh-role lookup with a 30 s cache
- `src/lib/roles.test.ts`, `src/lib/session-role.test.ts`, `vitest.config.ts`

**Frontend — modify:** `src/types/next-auth.d.ts`, `src/lib/roles.ts`, `src/auth.ts`, `src/lib/api-client.ts`, `src/middleware.ts`, `src/hooks/usePrivacy.ts`, `src/components/providers/AuthProvider.tsx`, `src/app/settings/page.tsx`, `scripts/check-route-guards.mjs`, every `src/app/api/**/route.ts` (role labels only), the 22 files that read `isEditor` / `isViewer`, `package.json`, `.env.example`

---

### Task 1: Migration 080

**Files:**
- Create: `schema/080_roles_and_password_accounts.sql`
- Modify: `src/expected_schemas.py` (the `app_users` entry)
- Test: `tests/test_schema_parser.py` already checks schema files parse; run it

**Interfaces:**
- Produces: `app_users.role` limited to the four roles; new columns `password_hash text NULL`, `failed_login_count int NOT NULL DEFAULT 0`, `locked_until timestamptz NULL`; unique index on `(provider, provider_user_id)` already exists and is relied on.

- [ ] **Step 1:** Write the migration, following `schema/079_*.sql` for style. In this order: `UPDATE app_users SET role='pending' WHERE role NOT IN ('owner')`; drop any existing role CHECK; add `CHECK (role IN ('pending','guest','family','owner'))`; change the column default to `'pending'`; add the three columns; register `080_roles_and_password_accounts` in `schema_migrations`. Every statement must be safe to run twice.
- [ ] **Step 2:** Update `src/expected_schemas.py` for the new columns.
- [ ] **Step 3:** Run `pytest tests/test_schema_parser.py -q`. Expected: pass.
- [ ] **Step 4:** Commit: `feat(db): migration 080, four roles and password accounts`. **Do not apply it to any database.** The orchestrator applies it during rollout (Task 12).

---

### Task 2: Identity — who is calling

**Files:**
- Create: `app/identity.py`, `tests/test_identity.py`

**Interfaces:**
- Produces:
  - `ROLES: tuple[str, ...] = ("pending", "guest", "family", "owner")`
  - `ROLE_RANK: dict[str, int] = {"pending": 0, "guest": 1, "family": 1, "owner": 3}`
  - `@dataclass(frozen=True) class Viewer: user_id: str | None; role: str` with properties `is_owner: bool` and `sees_money: bool` (true only for owner)
  - `async def resolve_viewer(request: Request) -> Viewer` — FastAPI dependency
  - `def invalidate_viewer(user_id: str | None = None) -> None` — clears one entry, or the whole cache
  - `VIEWER_CACHE_SECONDS = 30`
  - `OWNER_VIEWER = Viewer(None, "owner")`, `PENDING_VIEWER = Viewer(None, "pending")`

- [ ] **Step 1: Write failing tests** in `tests/test_identity.py` (patch `app.identity.execute_sql`; patch the module's clock function for expiry):

```python
def test_no_header_is_pending(): ...            # role == "pending", user_id is None
def test_unknown_id_is_pending(): ...           # execute_sql returns []
def test_malformed_id_is_pending_without_db(): ...  # "x'; drop" -> pending, execute_sql not called
def test_known_guest_resolves(): ...            # role == "guest", sees_money is False
def test_owner_sees_money(): ...
def test_cache_hit_skips_db(): ...              # two calls, execute_sql called once
def test_cache_expires_after_30s(): ...         # advance clock 31s, role change picked up
def test_invalidate_drops_entry(): ...
def test_disable_auth_is_owner(): ...           # DISABLE_AUTH=true, no header -> owner
def test_legacy_flag_makes_headerless_owner(): ...  # APP_USER_LEGACY_OK=1, no header -> owner
def test_legacy_flag_does_not_cover_unknown_id(): ...  # header present but unknown -> pending
```

- [ ] **Step 2:** Run `pytest tests/test_identity.py -q`. Expected: fail, module missing.
- [ ] **Step 3:** Implement `app/identity.py`. The header value must be a UUID (`uuid.UUID(value)`); anything else is pending with no query. One query: `SELECT role FROM app_users WHERE id = :id`. Cache is a dict guarded by a `threading.Lock`, with a module-level `_now = time.monotonic` so tests can patch it. `APP_USER_LEGACY_OK` (env, values `1/true/yes`) makes a request with **no** header an owner; it exists only for the rollout window in Task 12 and logs a warning once at import when set.
- [ ] **Step 4:** Run the tests. Expected: pass.
- [ ] **Step 5:** Commit: `feat(api): resolve the calling user and role from X-App-User`.

---

### Task 3: One access policy for every route

**Files:**
- Create: `app/access.py`, `tests/test_access_matrix.py`
- Modify: `app/main.py` (router wiring), `scripts/audit_ec2.sh` (its probes must send no user header and now expect 403; update the expected codes)

**Interfaces:**
- Consumes: `Viewer`, `resolve_viewer`, `ROLE_RANK` from Task 2.
- Produces:
  - `def required_role(method: str, route_path: str, query: Mapping[str, str]) -> str` — pure function, returns `"guest"` or `"owner"`
  - `async def enforce_access(request: Request, viewer: Viewer = Depends(resolve_viewer)) -> Viewer` — raises 403, otherwise returns the viewer and stores it on `request.state.viewer`
  - `GUEST_WRITES: frozenset[tuple[str, str]] = frozenset({("POST", "/stocks/{ticker}/chat")})`
  - `OWNER_ONLY_PREFIXES: tuple[str, ...] = ("/connections", "/users", "/debug", "/options", "/portfolio/equity-curve", "/portfolio/sync")`

**Policy (the whole of it):**
1. pending → 403 `"This account is waiting for approval"`.
2. Path starts with an `OWNER_ONLY_PREFIXES` entry → owner.
3. `GET`/`HEAD`/`OPTIONS` → guest, except a truthy `refresh` query parameter → owner.
4. Any other method → owner, unless `(method, route_path)` is in `GUEST_WRITES` → guest.

`route_path` is the route template (`request.scope["route"].path` with the router prefix), not the raw URL.

- [ ] **Step 1: Write failing tests** in `tests/test_access_matrix.py`:

```python
@pytest.mark.parametrize("method,path,query,expected", [
    ("GET", "/portfolio", {}, "guest"),
    ("GET", "/portfolio/equity-curve", {}, "owner"),
    ("GET", "/connections", {}, "owner"),
    ("GET", "/stocks/{ticker}/analysis", {"refresh": "true"}, "owner"),
    ("GET", "/stocks/{ticker}/analysis", {}, "guest"),
    ("POST", "/stocks/{ticker}/chat", {}, "guest"),
    ("POST", "/portfolio/sync", {}, "owner"),
    ("PUT", "/stocks/{ticker}/profile", {}, "owner"),
    ("DELETE", "/ideas/{idea_id}", {}, "owner"),
])
def test_required_role(method, path, query, expected): ...

def test_every_route_is_covered():
    """Walk app.routes. Every APIRoute outside /health, /webhook, /auth, /docs
    must have enforce_access among its dependencies."""

def test_every_mutating_route_is_owner_or_listed():
    """For each non-GET APIRoute: required_role == 'owner' or the pair is in GUEST_WRITES."""

def test_pending_gets_403_everywhere(client_as): ...   # sample of 6 routes via TestClient
def test_guest_write_is_403(client_as): ...            # PUT profile as guest
def test_guest_chat_is_allowed_through_policy(client_as): ...  # reaches the handler (mock it)
def test_family_matches_guest(client_as): ...
def test_owner_passes(client_as): ...
```

`client_as(role)` is a fixture in this file: a `TestClient` with `resolve_viewer` overridden through `app.dependency_overrides` and `require_api_key` overridden to pass.

- [ ] **Step 2:** Run. Expected: fail.
- [ ] **Step 3:** Implement `app/access.py`, then in `app/main.py` add `Depends(enforce_access)` beside `Depends(require_api_key)` on every `include_router` except auth and webhook. Check the real route templates with a quick script (`for r in app.routes: print(r.methods, r.path)`) and correct the paths in `GUEST_WRITES` / `OWNER_ONLY_PREFIXES` and in the parametrised test if the chat or analysis templates differ.
- [ ] **Step 4:** Run `pytest tests/test_access_matrix.py tests/test_identity.py -q`, then the full suite `pytest -q -m "not openai and not integration"`. Fix any existing test that now needs a viewer by overriding `resolve_viewer` to `OWNER_VIEWER` in `tests/conftest.py` as an autouse fixture (tests in this file override it back).
- [ ] **Step 5:** Commit: `feat(api): central role policy on every route`.

---

### Task 4: Passwords, login and Google sign-in as pending

**Files:**
- Create: `app/passwords.py`, `tests/test_auth_password.py`
- Modify: `app/auth.py`, `requirements.txt` (add `argon2-cffi>=23.1.0`), `.env.example`

**Interfaces:**
- Consumes: `invalidate_viewer` (Task 2).
- Produces in `app/passwords.py`:
  - `USERNAME_RE`, `MIN_PASSWORD = 10`, `MIN_OWNER_PASSWORD = 14`, `MAX_PASSWORD = 128`
  - `def normalize_username(raw: str) -> str` — trims, lower-cases, raises `ValueError("Username must be 3 to 32 characters: letters, numbers, dot, dash or underscore")`
  - `def check_password_rules(password: str, role: str) -> None` — raises `ValueError` with the rule that failed
  - `def hash_password(password: str) -> str`
  - `def verify_password(password: str, stored_hash: str | None) -> bool` — when `stored_hash` is None it verifies against a fixed dummy hash and returns False
- Produces in `app/auth.py`:
  - `POST /auth/password` body `{"username": str, "password": str}` → `AppUserOut` (200), 401 `"Wrong username or password"`, 423 `"Too many attempts. Try again in 15 minutes"`
  - `GET /auth/me` → `{"id": str, "role": str, "email": str, "fullName": str | None}` for the `X-App-User` id; 404 when unknown
  - `POST /auth/google` unchanged in shape; new users get `pending`; a newly created pending user triggers the alert from Task 6 (call it through `app.auth._notify_new_pending(name, email)`, a thin function Task 6 fills in; until then it is a no-op)

- [ ] **Step 1: Write failing tests** in `tests/test_auth_password.py` (patch `app.auth.execute_sql`):

```python
def test_normalize_username_lowercases_and_trims(): ...      # "  Dev.User " -> "dev.user"
def test_normalize_username_rejects_email_and_spaces(): ...   # "a@b.com", "a b", "ab"
def test_password_too_long_rejected_before_hashing(): ...     # 129 chars; hash_password not called
def test_password_of_spaces_rejected(): ...
def test_owner_needs_14_chars(): ...
def test_hash_then_verify_roundtrip(): ...
def test_verify_with_no_hash_is_false_and_still_does_work(): ...  # dummy verify called
def test_login_success_resets_failures(): ...
def test_login_wrong_password_is_401_and_increments(): ...
def test_login_unknown_user_is_401_same_message(): ...
def test_login_locked_after_5_failures_is_423(): ...
def test_login_locked_account_rejects_correct_password(): ...
def test_lock_expires_after_15_minutes(): ...
def test_google_new_user_is_pending(): ...                    # INSERT params/SQL carry 'pending'
def test_google_owner_email_promoted_even_if_pending(): ...
def test_google_new_pending_triggers_notify_once(): ...       # not on later sign-ins
def test_me_returns_role(): ...
def test_me_unknown_is_404(): ...
```

- [ ] **Step 2:** Run. Expected: fail.
- [ ] **Step 3:** Implement. Lockout state lives in the `failed_login_count` and `locked_until` columns, updated in single SQL statements. Password accounts are rows with `provider='password'`, `provider_user_id=<username>`, `email='<username>@local'`. To tell "new" from "returning" in the Google upsert, return `(xmax = 0) AS inserted` from the statement. Replace `'viewer'` with `'pending'` in the upsert. Keep the existing rate limiter on all three endpoints.
- [ ] **Step 4:** Run `pytest tests/test_auth_password.py tests/test_prod_hardening.py -q`. Expected: pass.
- [ ] **Step 5:** Commit: `feat(auth): password accounts with lockout, pending by default, /auth/me`.

---

### Task 5: Users API (owner only)

**Files:**
- Create: `app/routes/users.py`, `tests/test_users_api.py`
- Modify: `app/main.py` (mount at `/users` with both dependencies)

**Interfaces:**
- Consumes: `enforce_access` (Task 3; `/users` is owner-only by prefix), `invalidate_viewer` (Task 2), `app.passwords` (Task 4).
- Produces:
  - `GET /users` → `{"users": [UserRow], "pendingCount": int}`; `UserRow = {id, provider, username|null, email, fullName|null, avatarUrl|null, role, createdAt, lastSeenAt, isSelf: bool}`; pending first, then by `lastSeenAt` descending
  - `PATCH /users/{user_id}` body `{"role": "pending"|"guest"|"family"|"owner"}` → `UserRow`
  - `DELETE /users/{user_id}` → 204
  - `POST /users` body `{"username", "password", "role"}` → `UserRow` (201); 409 when the username exists
  - `POST /users/{user_id}/password` body `{"password"}` → 204; also clears the lockout

**Rules, each with a 400/409 and a plain message:**
- Setting `owner` on a `provider='google'` row → 400 `"Owner access for Google accounts comes from OWNER_EMAILS"`.
- Changing or deleting your own row → 400 `"You can't change your own access"`.
- A change that would leave zero owners → 400 `"At least one owner must remain"`.
- Password reset on a Google row → 400.
- Every successful change calls `invalidate_viewer(user_id)`.

- [ ] **Step 1: Write failing tests** — one per rule above, plus: list ordering and `pendingCount`; create validates username and password through `app.passwords` (owner role needs 14 characters); the stored value is a hash, never the password; `password_hash` never appears in any response; a guest caller gets 403 (through the policy).
- [ ] **Step 2:** Run. Expected: fail.
- [ ] **Step 3:** Implement with bound parameters only. The caller's own id comes from `request.state.viewer.user_id`.
- [ ] **Step 4:** Run `pytest tests/test_users_api.py tests/test_access_matrix.py -q`. Expected: pass (the route-coverage tests must still pass with the new router).
- [ ] **Step 5:** Commit: `feat(api): owner-only user management`.

---

### Task 6: Discord approval alert

**Files:**
- Create: `src/approval_alert.py`, `tests/test_approval_alert.py`
- Modify: `app/auth.py` (`_notify_new_pending` calls it in a background thread), `src/aws_secrets.py` (add `"APPROVAL_ALERT_CHANNEL_ID": "APPROVAL_ALERT_CHANNEL_ID"` and `"FRONTEND_URL": "FRONTEND_URL"` to `SECRET_KEY_MAPPING`), `.env.example`

**Interfaces:**
- Produces: `def send_approval_alert(full_name: str | None, email: str) -> bool` — returns True when Discord accepted the message; never raises.
- `MAX_ALERTS_PER_DAY = 20`

**Behaviour:** `POST https://discord.com/api/v10/channels/{APPROVAL_ALERT_CHANNEL_ID}/messages` with header `Authorization: Bot {DISCORD_BOT_TOKEN}`, timeout 5 s, body:

```
New sign-in waiting for approval
{full_name or "No name"} · {email}
Approve or decline: {FRONTEND_URL or "https://llmportfolio.app"}/settings/users
```

`allowed_mentions` is `{"parse": []}` so a crafted display name can't ping anyone. Name and email are truncated to 100 characters and have backticks and `@` neutralised.

- [ ] **Step 1: Write failing tests** (patch `httpx.post`): sends the right URL, header and text; returns False and makes no request when the channel id or token is missing; returns False on a 403 or a timeout without raising; the 21st alert in a day makes no request; the counter resets on a new day; a name containing `@everyone` is neutralised; the token never appears in a log record (`caplog`).
- [ ] **Step 2:** Run. Expected: fail.
- [ ] **Step 3:** Implement. The daily counter is in-process (one API process).
- [ ] **Step 4:** Run `pytest tests/test_approval_alert.py tests/test_auth_password.py -q`. Expected: pass.
- [ ] **Step 5:** Commit: `feat(auth): Discord alert when a sign-in is waiting`.

---

### Task 7: Frontend roles and test runner

**Files (under `frontend/`):**
- Create: `vitest.config.ts`, `src/lib/roles.test.ts`
- Modify: `package.json` (devDependency `vitest`, script `"test": "vitest run"`), `src/types/next-auth.d.ts`, `src/lib/roles.ts`, `src/hooks/usePrivacy.ts`, the 22 files that read `isEditor` / `isViewer`

**Interfaces:**
- Produces:
  - `export type AppRole = "owner" | "family" | "guest" | "pending"`
  - `Session["user"]` gains `id?: string` (the `app_users.id`); `JWT` gains `appUserId?: string`
  - `ROLE_RANK: Record<AppRole, number> = { pending: 0, guest: 1, family: 1, owner: 3 }`
  - `roleRank(role)` — missing or unknown → 0
  - `hasRole(role, min: AppRole): boolean`
  - `usePrivacy()` returns `{ role, isOwner, isGuestView, hideSizes, canWrite, canChat }` where `isGuestView = !isOwner`, `hideSizes = isGuestView` (true while loading), `canWrite = isOwner`, `canChat = isOwner || role === "guest" || role === "family"` (false while loading)

- [ ] **Step 1: Write failing tests** in `src/lib/roles.test.ts`: missing role ranks 0; `"viewer"` and `"editor"` rank 0; `hasRole("family","guest")` true; `hasRole("guest","owner")` false; `hasRole("pending","guest")` false; `hasRole(undefined,"guest")` false.
- [ ] **Step 2:** Run `npm test`. Expected: fail.
- [ ] **Step 3:** Implement. In components, replace `isEditor` with `isOwner` where it gated a write (use `canWrite`), `isViewer` with `isGuestView`. Chat entry points use `canChat`.
- [ ] **Step 4:** Run `npm test` and `npx tsc --noEmit`. Expected: both clean.
- [ ] **Step 5:** Commit: `feat(roles): four roles in types, helpers and usePrivacy`.

---

### Task 8: Sign-in through the backend, fresh roles, identity header

**Files (under `frontend/`):**
- Create: `src/lib/session-role.ts`, `src/lib/session-role.test.ts`
- Modify: `src/auth.ts`, `src/lib/api-client.ts`, `.env.example`

**Interfaces:**
- Consumes: Task 4's `/auth/password`, `/auth/me`, `/auth/google`; Task 7's types.
- Produces:
  - `src/lib/session-role.ts`: `export async function freshRole(appUserId: string): Promise<AppRole>` — calls `GET {API}/auth/me` with the API key and `X-App-User`, `cache: "no-store"`, 5 s timeout; 30 s in-memory cache per id; 404 → `"pending"`; network error or 5xx → throws `RoleLookupError`
  - `export function forgetRole(appUserId?: string): void`
  - `requireRole(min: AppRole)` in `api-client.ts`: session missing → 401; no `session.user.id` → 403; `freshRole` throws → 503 `"Try again in a moment"`; rank too low → 403; returns `{ session, role }`
  - `backendFetch(path, options)` adds `X-App-User: <session.user.id>` when a session exists (it reads the session itself with `auth()`)

**`src/auth.ts` changes:**
- Delete `getAuthUsers`, `AUTH_USERS` parsing and the plaintext compare.
- Credentials `authorize`: POST `{username, password}` to `/auth/password`; on 200 return `{ id: user.id, name: username, email, role }`; on anything else return null.
- `syncGoogleUserWithBackend` returns `{ id, role } | null`.
- `jwt` callback: store `token.appUserId` and `token.role`. When the Google sync fails, the fallback role is `owner` only if the email is in `OWNER_EMAILS`, otherwise `pending`. When `trigger === "update"` and `token.appUserId` exists, set `token.role = await freshRole(token.appUserId)` after `forgetRole(token.appUserId)`; on error keep the old role.
- `session` callback: copy `token.appUserId` to `session.user.id`.

- [ ] **Step 1: Write failing tests** in `src/lib/session-role.test.ts` (mock `fetch`, fake timers): caches for 30 s; refetches at 31 s; 404 → `"pending"`; 500 → throws; `forgetRole` forces a refetch; an unknown role string from the backend → `"pending"`. Add `src/lib/api-client.test.ts` (mock `@/auth` and `@/lib/session-role`): no session → 401; session without `user.id` → 403; `freshRole` throws → 503 with `"Try again in a moment"` and the cookie's role is not used; cookie says `guest` but `freshRole` says `pending` → 403; `backendFetch` sends `X-App-User` and still refuses `/a/../b`.
- [ ] **Step 2:** Run `npm test`. Expected: fail.
- [ ] **Step 3:** Implement the module, then the `auth.ts` and `api-client.ts` changes.
- [ ] **Step 4:** Run `npm test` and `npx tsc --noEmit`. Expected: clean.
- [ ] **Step 5:** Commit: `feat(auth): backend-verified logins, fresh role check, X-App-User on every call`.

---

### Task 9: Route handlers and the build-time guard

**Files (under `frontend/`):**
- Modify: `scripts/check-route-guards.mjs`, every `src/app/api/**/route.ts` except `auth/`

**Interfaces:**
- Consumes: `requireRole` (Task 8).

**Rules the script enforces:**
- `RANK = { guest: 1, family: 1, owner: 3 }`; a `requireRole` argument outside these three fails the build.
- `GET` → `guest` or higher.
- Any other method → `owner`, except the allowlist `GUEST_WRITES = ["stocks/[ticker]/chat/route.ts:POST"]` → `guest`.
- Every method under `connections/` and `users/` → `owner`.
- A `fetch(` with a `next: { revalidate` option, or `export const revalidate`, in a route file fails the build unless the line carries the comment `// public-market-data`. (Plan 2 decides caching per route; until then nothing user-shaped is cached.)

- [ ] **Step 1:** Update the script and add its self-check: `node scripts/check-route-guards.mjs --self-test` runs the rules against 6 inline sample sources (guest GET ok; `viewer` rejected; non-owner POST rejected; chat POST guest ok; connections GET guest rejected; unmarked `revalidate` rejected) and exits non-zero on any mismatch.
- [ ] **Step 2:** Run `npm run check:routes`. Expected: fail, listing every handler still on `viewer` / `editor`.
- [ ] **Step 3:** Update the handlers: `'viewer'` → `'guest'`, `'editor'` → `'owner'`, chat POST → `'guest'`, connections GET → `'owner'`. For the cached fetches the script flags, mark pure market-data routes (quotes, search, sparklines, OHLCV) with the comment and remove `revalidate` from the rest.
- [ ] **Step 4:** Run `node scripts/check-route-guards.mjs --self-test && npm run check:routes && npx tsc --noEmit`. Expected: `70 API handlers OK` (or the current count) and no type errors.
- [ ] **Step 5:** Commit: `feat(api): route guards for the four roles`.

---

### Task 10: Pending gate and waiting page

**Files (under `frontend/`):**
- Create: `src/app/pending/page.tsx`
- Modify: `src/middleware.ts`, `src/components/providers/AuthProvider.tsx`

**Interfaces:**
- Consumes: `hasRole` (Task 7), `useSession().update` (NextAuth).

**Behaviour:**
- Middleware: a signed-in session whose role ranks 0 is redirected to `/pending` from every page; `/api/*` (except `/api/auth/*`) returns 403 `{ error: "This account is waiting for approval" }`. A session that ranks ≥ 1 visiting `/pending` is redirected to `/`. The mutating-method block in middleware becomes: non-GET `/api/*` needs owner unless the path matches `/api/stocks/<one segment>/chat`.
- `/pending` page, exact copy:
  - Heading: `Waiting for approval`
  - Body: `Thanks for signing in. This is a private site, and the owner approves each account by hand. You'll get in as soon as that's done.`
  - Signed-in line: `Signed in as {email}`
  - Buttons: `Check again` (calls `update()`, then `router.refresh()`; while running shows `Checking…`; if still pending shows `Not approved yet. Try again later.`) and `Sign out`
- Layout: centred card, the app's existing dark theme and tokens (see `src/app/login/page.tsx`), works at 375 px, buttons full-width under 640 px.
- `AuthProvider` comment updated; keep `refetchOnWindowFocus={false}`.

- [ ] **Step 1:** Implement middleware and page.
- [ ] **Step 2:** Run `npx tsc --noEmit && npm run check:routes && npm run build`. Expected: build succeeds.
- [ ] **Step 3:** Run `npm run dev` with a backend on `localhost:8000` if available and open `/pending` at 375 px and 1280 px; otherwise report that the visual check is left for the Vercel preview in Task 12.
- [ ] **Step 4:** Commit: `feat(auth): waiting-for-approval gate`.

---

### Task 11: Users page

**Files (under `frontend/`):**
- Create: `src/app/api/users/route.ts` (GET, POST), `src/app/api/users/[id]/route.ts` (PATCH, DELETE), `src/app/api/users/[id]/password/route.ts` (POST), `src/app/settings/users/page.tsx`, `src/components/settings/UsersTable.tsx`, `src/components/settings/PasswordAccountForm.tsx`
- Modify: `src/app/settings/page.tsx` (owner-only link card "Users and access" with the pending count; the Brokerage Connections section renders only for the owner), `src/types/api.ts` (`AppUserRow`, `UsersResponse`)

**Interfaces:**
- Consumes: Task 5's `/users` API; `requireRole('owner')`, `backendFetch`, `seg` (Task 8).

**Page content:**
- Title `Users and access`. Non-owners who reach the URL see the existing `ReadOnlyNotice` and no data request is made.
- Section `Waiting for approval ({n})` on top, shown only when n > 0. Each row: avatar or initials, name, email, "signed in {relative time}", and buttons `Approve as guest`, `Approve as family`, `Decline` (Decline deletes after a confirm: `Remove {email}? They can sign in again and will be back in this list.`).
- Section `People with access`: name, email or username, a `Google` / `Password` tag, a role select (`Guest`, `Family`; owner rows show a fixed `Owner` tag), last seen, and a menu with `Revoke access` (→ pending), `Reset password` (password rows), `Delete`. The signed-in owner's own row shows `You` and no actions.
- Section `Add a password account`: username, role (`Guest`, `Family`, `Owner`), password, confirm password, with the rules shown under the field (`10+ characters; 14+ for an owner`). Submit `Create account`. On success: `Account created. Share the username and password with them yourself; the password can't be shown again.`
- Errors from the backend are shown as returned (they're written for people).
- The spec's "AI chats used today" column and the day's usage counters are added by Plan 3, which owns that data.
- After every change: SWR `mutate()` on `/api/users`.
- Under 640 px each user is a stacked card; no table scrolls sideways; all controls ≥ 40 px tall.

- [ ] **Step 1:** Implement the three BFF routes (owner on every method; `seg(id)`), then `npm run check:routes`.
- [ ] **Step 2:** Implement the components and page in the style of `src/app/settings/page.tsx` (same Sidebar, TopBar, card and status-tag classes).
- [ ] **Step 3:** Run `npx tsc --noEmit && npm run lint && npm run build`. Expected: clean.
- [ ] **Step 4:** Commit: `feat(settings): owner-only Users and access page`.

---

### Task 12: Rollout (orchestrator and Qais; not a subagent task)

No step here may leave dollar data open to a non-owner or lock the owner out.

- [ ] **1. Whole-branch review** of both branches by a fresh reviewer, plus `pytest -q -m "not openai and not integration"` and `npm test && npm run build` green.
- [ ] **2. Qais pushes both branches** (PowerShell). The Vercel preview builds; the orchestrator confirms it is Ready.
- [ ] **3. Qais, browser server terminal (bash):** add the rollout flag, then restart nothing yet.
  `echo 'APP_USER_LEGACY_OK=1' | sudo tee -a /etc/llm-portfolio/llm.env`
- [ ] **4. Qais adds the secret** `APPROVAL_ALERT_CHANNEL_ID` (and optionally `FRONTEND_URL`) to `qqqAppsecrets` in the AWS console. Orchestrator gives the click path and how to copy a Discord channel id.
- [ ] **5. Orchestrator applies migration 080** to Supabase (`apply_migration`), then checks: roles are only owner/pending; constraint present.
- [ ] **6. Qais merges the backend PR.** Actions deploys. Checks on the box: `/health` 200; site still loads for Qais (old frontend, legacy flag).
- [ ] **7. Qais merges the frontend PR.** Vercel production Ready. Qais signs out and in with Google; dashboard loads; `/settings/users` shows him as Owner and the two old accounts under Waiting.
- [ ] **8. Qais removes the flag and restarts the API** (bash): `sudo sed -i '/^APP_USER_LEGACY_OK=/d' /etc/llm-portfolio/llm.env && sudo systemctl restart api.service`. Site still loads.
- [ ] **9. Proof from outside (orchestrator):** unauthenticated `/api/*` still redirects; a second Google account (Qais's choice) signs in → lands on `/pending`, Discord alert arrives, API calls return 403; approve then revoke it from the Users page and confirm both take effect within 30 seconds. Leave it pending.
- [ ] **10. Qais creates the `dev` owner password account** on the Users page, confirms it signs in, then deletes `AUTH_USERS` and `ALLOWED_EMAILS` in Vercel. **No guest or family account yet** (Plan 2).
- [ ] **11.** Update the progress board in `docs/plans/2026-11-12-next-round-backlog.md`.
