# SDD ledger — plan: docs/superpowers/plans/2026-11-12-roles-approval-plan.md

Spec: docs/superpowers/specs/2026-11-12-roles-privacy-options-cost-design.md
Backend repo C:\github\dev\LLM-portfolio-project, branch feat/roles-approval, branch base 11ac6aa
Frontend repo C:\github\dev\LLM-portfolio-frontend (app in frontend/), branch feat/roles-approval, branch base 0f86fbe
Briefs: task-N-brief.md in this folder. Shared constraints: constraints.md. Reports: task-N-report.md.
Backend python: .venv/Scripts/python -m pytest. Frontend: run npm from frontend/.

## Pre-flight scan

| Pair / task | Produces vs consumes | Finding |
|---|---|---|
| T2 -> T3 | Viewer, resolve_viewer, ROLE_RANK | consistent |
| T3 -> T5 | enforce_access sets request.state.viewer; /users owner-only by prefix | consistent |
| T2 -> T4, T5 | invalidate_viewer | consistent |
| T4 -> T6 | _notify_new_pending no-op filled by T6 | consistent |
| T4 -> T8 | /auth/password, /auth/me, /auth/google shapes | consistent |
| T5 -> T11 | /users API shapes | consistent |
| T7 -> T8, T9, T10 | AppRole change breaks requireRole('viewer'/'editor') call sites until T9 | CONFLICT with T7 step 4 "tsc clean" |
| T8 -> T9, T11 | requireRole return shape {session, role} vs existing callers that use the returned session | CONFLICT risk |
| T9 -> T10 | both touch role rules; T10 owns middleware | consistent |
| T3 conftest autouse OWNER vs T2 tests | T2 tests call resolve_viewer directly | consistent |
| T1..T11 self-check | each task's tests match its code | no internal contradictions found |

Ruling: T7's "tsc clean" applies to files T7 owns; type errors confined to src/auth.ts, src/middleware.ts, src/lib/api-client.ts and src/app/api/** are expected until T8-T10 and must be listed in T7's report — the role rename cannot compile across files owned by later tasks — if wrong, T7 hides a real type error until T10's build.
Ruling: requireRole keeps returning the session object (with session.user.role overwritten by the fresh role), not {session, role} — existing handlers use the return value as a session — if wrong, callers needing the role read session.user.role, a one-line difference.
Ruling: backend lane (T1-T6) and frontend lane (T7-T11) run in parallel, one implementer per repo — separate repos cannot conflict and the lanes meet only at written API contracts — if wrong, a contract mismatch shows up at the whole-branch review or the preview.
Ruling: plan executed without a separate plan sign-off from Qais — he approved the design and said "proceed", cannot evaluate signatures, and controls every merge and deploy in Task 12 — if wrong, local branch commits are discarded at no cost.
Ruling: branches made in place (no worktree) — frontend needs its node_modules and both trees were clean — if wrong, switch back with git checkout.

## Progress
Task 1: dispatched (sonnet), BASE 11ac6aa (backend)
Task 7: dispatched (sonnet), BASE 0f86fbe (frontend)
Task 1: implementer DONE_WITH_CONCERNS at e605c8d; resumed with additions before review
Ruling: migration 080 also widens the provider CHECK to ('google','password') and keeps email NOT NULL UNIQUE with '<username>@local' for password accounts — the plan missed the existing provider constraint from migration 075 — if wrong, password account inserts fail at Task 4/5 and the migration needs another statement.
Ruling: accepted implementer's reorder (drop CHECK before UPDATE) and re-run-safe UPDATE predicate — the brief's order fails against the old CHECK — no cost.
Note: baseline has pre-existing failures in tests/test_chunk_indexing.py (3); triage regression test being baselined.
Task 7: implementer DONE_WITH_CONCERNS at 0152ea9 (touched TopBar.tsx outside file list; 73 tsc errors all in T8-T10 files); review dispatched
Task 1: fix round 0 additions done at 85c49da; review dispatched (range 11ac6aa..85c49da)
Task 1: minor (deferred): ILIKE '%role%' / '%provider%' constraint match is loose; tighten to '(role = ANY' / '(provider = ANY'
Task 1: minor (deferred): migration not wrapped in a transaction (apply_migration runs it in one; confirm at Task 12)
Task 1: note for Task 12: run migration twice on a Supabase branch or confirm second run is a no-op
Task 1: complete (commits 11ac6aa..85c49da, review clean)
Task 2: dispatched (sonnet), BASE 85c49da (backend)
Task 7: lockfile checked by controller: 0 changed, 0 removed, 83 added (vitest only) — ⚠️ resolved
Task 7: fix round 1/5 dispatched (ChatWidget "editor access" string + sweep, canChatFor, test additions) — implementer hit usage limit mid-round; resumed
Task 2: implementer hit usage limit mid-task; resumed
Task 7: fix round 1/5 (4 addressed, 0 open; commits 0152ea9..c26641e)
Task 7: minor (deferred): ChatWidget "waiting for approval" hint flashes while the session is loading (canChat false then)
Task 7: complete (commits 0f86fbe..c26641e, review clean)
Task 8: dispatched (sonnet), BASE c26641e (frontend)
Task 2: implementer DONE at 1e4d979 (741 pass, 4 baseline failures); review dispatched
Task 2: review — Important: unbounded cache. ⚠️ uuid binding: controller confirmed app_users.id is uuid (Supabase schema check 11/12); fix adds CAST(:id AS uuid)
Task 2: fix round 1/5 dispatched (cache sweep + cap 5000, CAST, invalidation counter, 5 test additions); FIX_BASE 1e4d979
Task 2: minor (deferred): resolve_viewer is async but does a blocking DB call on cache miss (accepted by design; one query per user per 30s)
Task 2: fix round 1/5 (4 addressed, 0 open; commits 1e4d979..a04e401)
Task 2: complete (commits 85c49da..a04e401, review clean)
Task 3: dispatched (sonnet), BASE a04e401 (backend)
Task 8: implementer DONE_WITH_CONCERNS at 33d9787 (30 tests pass; 70 tsc errors in api/** and middleware only); review dispatched (opus)
Task 8: review Approved (opus). ⚠️ tsc: controller ran tsc, no errors outside src/app/api/** and src/middleware.ts. ⚠️ password-not-trimmed consistency: carried into Task 4/5/11 dispatches.
Task 8: minor (deferred): update() bypasses the role cache every call (client can loop /auth/me); add a short floor
Task 8: minor (deferred): owner who signed in while backend was down gets 503 forever until re-login; add "sign out and back in" hint or retry
Task 8: minor (deferred): auth() decoded twice per request (requireRole + backendFetch)
Task 8: minor (deferred): concurrent freshRole misses not merged
Task 8: minor (deferred): /auth/me body id not cross-checked against requested id
Task 8: minor (deferred): session-role tests: no Authorization assertion, no timeout/bad-JSON test, unstubAllEnvs not in afterEach
Task 8: minor (deferred): no unit tests for auth.ts jwt/authorize branches
Task 8: complete (commits c26641e..33d9787, review clean)
Task 9: dispatched (sonnet), BASE 33d9787 (frontend)
Task 3: implementer DONE_WITH_CONCERNS at b173b28 (34 new tests; full suite 772 pass); review dispatched (opus)
Task 3: review (opus) Needs fixes — Critical: ?refresh=t/y bypass (policy truthy list narrower than pydantic bool); Important: audit_ec2.sh EXPECT_CODE unused; coverage-test exemption lacks path boundary
Ruling: refresh fails closed in backend AND frontend — a refresh is requested unless the param is absent or one of ""/0/false/no/off/f/n; repeated params: any non-falsy wins — my original 1/true/yes/on list was narrower than pydantic's bool parsing — if wrong, an owner-only 403 on an odd refresh value, which is harmless.
Task 3: ⚠️ guest-readable responses may carry options or dollar fields — known, owned by Plans 2 and 4; rollout rule stands: no guest/family approvals until Plan 2 is live
Task 3: fix round 1/5 dispatched; FIX_BASE b173b28
Task 9: running implementer sent the fail-closed refresh rule (helper refreshRequested in src/lib/roles.ts)
Task 9: implementer DONE_WITH_CONCERNS at b7cbaf0 (2 commits; fail-closed refresh applied; 50 tests; 70 handlers OK; tsc errors only in middleware.ts); review dispatched
Task 9: note for backlog D (performance): revalidate removed from news/filings/fundamentals/management/transcript and portfolio routes; Plan 2 decides caching per route
Task 9: review Needs fixes — Important: ohlcv route cached with owner's order markers; activities forwards raw refresh; guard script satisfiable by comments/misordered calls; marker comment disables cache check
Task 9: fix round 1/5 dispatched; FIX_BASE b7cbaf0
Task 3: fix round 1/5 (6 addressed, 0 open; commits b173b28..2e14bcb)
Task 3: minor (deferred): test_debug_router_carries_enforce_access reloads app.main and rebinds module-level app; could confuse tests holding the old object
Task 3: complete (commits a04e401..2e14bcb, review clean)
Task 4: dispatched (sonnet), BASE 2e14bcb (backend)
Task 9: fix round 1/5 (5 addressed, 0 open; commits b7cbaf0..0e38ce4)
Task 9: minor (deferred): comment stripper can be confused by a regex literal with an unmatched quote
Task 9: minor (deferred): BEFORE_GUARD only matches a parameter named *request (not req)
Task 9: minor (deferred): .delete('refresh') not tied to the forwarded params object; WHOLE_QUERY lacks Array.from(searchParams)
Task 9: minor (deferred): stray " *  * Mirrors" line in guard script header
Task 9: minor (deferred): caching rule doesn't cover Cache-Control headers, unstable_cache, dynamic='force-static'
Task 9: complete (commits 33d9787..0e38ce4, review clean)
Task 10: dispatched (sonnet), BASE 0e38ce4 (frontend)
Task 10: implementer DONE_WITH_CONCERNS at 58a8c18 (tsc clean, 76 tests; build fails on 3 unused-var lint errors left by Task 9); review dispatched
Task 9: post-completion lint fix dispatched to Task 9 implementer (unused searchParams in portfolio/risk, analysis/risk, analysis/technical) — build must be green before Task 11
Task 10: review Approved. ⚠️ browser look of /pending at 375px and 1280px: to be checked on the Vercel preview in Task 12
Task 10: minor (deferred): "Check again" button uses disabled while checking; keyboard focus is lost — use aria-disabled
Task 10: minor (deferred): middleware-rules tests lack static-file-when-pending, encoded/trailing-slash chat, DELETE chat, /_next/data cases
Task 10: minor (deferred): comment that the /_next/ exclusion also covers /_next/data (safe only while there is no pages router)
Task 10: minor (deferred): middleware chat exception allows every mutating method, backend allows POST only (handlers re-check; tighten to POST)
Task 10: complete (commits 0e38ce4..58a8c18, review clean)
Task 11: waiting on Task 9 lint fix (build green) before dispatch
Task 4: implementer DONE_WITH_CONCERNS at adf923c (822 pass); resumed before review with a required change
Ruling: GET /auth/me is exempt from rate limiting; /auth/password limiter keyed per username — the frontend calls /auth/me before every API request and a shared 20/min bucket would 503 the owner on a normal page load — if wrong, /auth/me is an unthrottled (but API-key-gated, single indexed query) endpoint.
Ruling: Task 8 minors "concurrent freshRole misses not merged", "/auth/me id cross-check" and "update() cache floor" are promoted to a required fix before Task 11 — parallel page-load requests on a cold instance would each call the backend — if wrong, a small amount of extra code.
Ruling: fifth failed login returns 423 (not 401) — brief was silent — no cost.
Task 9: lint fix done at 3b8c38a (lint, check:routes, tsc, 76 tests, build all green) — reviewed as part of the whole-branch review (3 deleted unused lines)
Task 8: follow-up fix dispatched to Task 8 implementer (in-flight merge, id cross-check, cache bound, refreshRole 5s floor, test additions); FIX_BASE 3b8c38a
Task 4: change done at 050fbbf (825 pass); review dispatched (opus), range 2e14bcb..050fbbf
Task 8: follow-up fix done at 64ced0c (87 tests, tsc/lint/build green); scoped re-review dispatched
Task 8: follow-up fix round (5 addressed, 0 open; commits 3b8c38a..64ced0c)
Task 8: minor (deferred): forgetRole(id) doesn't cancel an in-flight lookup; a role read just before approval can be cached up to 30s
Task 11: dispatched (sonnet), BASE 64ced0c (frontend)
Task 4: review (opus) Approved, with two plan-mandated Important items for the controller to rule on
Ruling: username-existence oracle (423 only for real usernames) is fixed with an in-memory shadow lock so unknown names answer 423 after 5 failures too — the plan's "unknown usernames are never locked" leaked which names exist — if wrong, a little extra in-memory state.
Ruling: password owner account can be held locked 15 minutes at a time by anyone who knows the username — accepted — the owner's Google sign-in has no lockout; Task 6 adds a Discord alert when an account locks — if wrong, the dev password account is unusable during an attack, Google still works.
Ruling: /auth/google limiter stays per client IP (effectively one shared bucket behind nginx) — real-client-IP forwarding is backlog E (review L2) — if wrong, a determined attacker completing 20 Google sign-ins a minute can 429 Google sign-in for everyone until they stop.
Task 4: fix round 1/5 dispatched (shadow lock, /auth 422 without input echo, test fixes, requirements section, viewer in tests); FIX_BASE 050fbbf
Task 4: note for Task 12: prove the lockout SQL against real Postgres (temp table or Supabase branch): 5 failures -> locked; failure while locked -> unchanged; expiry -> count 1
Task 4: minor (deferred): wrong-password path does one more DB round-trip than unknown-username path (timing)
Task 4: fix round 1/5 (7 addressed, 0 open; commits 050fbbf..343e200)
Task 4: minor (deferred): shadow-lock sweep is O(10,000) under the lock once the map is full
Task 4: minor (deferred): slow-probe distinguisher — real accounts lock on 5 cumulative failures (no window), shadow lock needs 5 within 15 minutes; align by resetting the real count after 15 minutes without a failure
Task 4: complete (commits 2e14bcb..343e200, review clean)
Task 11: implementer hit usage limit mid-task (uncommitted work present in frontend tree); resumed 11/13
Task 5: dispatched (sonnet), BASE 343e200 (backend)
Task 11: implementer DONE_WITH_CONCERNS at 623a476 (tsc/lint/check:routes 75/112 tests/build green; not viewed in a browser); review dispatched
Task 11: review Needs fixes — Important: focus not returned after confirm; avatar URL unvalidated; revalidation error blanks the list. ⚠️ CSP: vercel.json has a Report-Only CSP with img-src 'self' data: blob: https: (not enforcing yet; backlog E)
Task 11: fix round 1/5 dispatched; FIX_BASE 623a476
Task 5: implementer DONE_WITH_CONCERNS at 8fa7812 (883 pass); review dispatched (opus)
Ruling: PATCH on your own row to its current role returns 400 (self rule first), not a no-op 200; password reset on your own row is allowed — implementer's calls, accepted — no cost.
Task 5: note for Task 12: prove the last-owner guard SQL (WITH owners ... FOR UPDATE) on real Postgres
Task 11: fix round 1/5 (7 addressed, 0 open; commits 623a476..e45ad66)
Task 11: minor (deferred): Avatar `failed` flag never resets if avatarUrl changes while mounted
Task 11: minor (deferred): confirm panel not closed on success (relies on the row unmounting)
Task 11: minor (deferred): UsersTable track() reports an error on the row when the action succeeded but the list refresh threw
Task 11: note for Task 12: focus behaviour and the 375px layout of /settings/users need a browser check on the Vercel preview
Task 11: complete (commits 64ced0c..e45ad66, review clean)
Frontend lane (Tasks 7-11) complete at e45ad66. Backend lane: Task 5 in review, Task 6 next.
Task 5: review (opus) Needs fixes — Important: password account can be promoted to owner keeping a short password; argon2 hash can reach logs via execute_sql error text
Ruling: PATCH can no longer set role owner on any account; owner password accounts are created only through POST (14-char rule) — the hash can't prove password length — if wrong, the owner deletes and re-creates an account instead of promoting it.
Ruling: hide_parameters=True on the SQLAlchemy engine in src/db.py (shared file) — bound parameters (hashes) must never reach logs — if wrong, DB error logs are less detailed.
Ruling: PATCH/DELETE on a Google row whose email is in OWNER_EMAILS is refused with a message — otherwise the change silently reverts at next sign-in — if wrong, one extra step (edit the secret first).
Task 5: fix round 1/5 dispatched; FIX_BASE 8fa7812
Task 5: minor (deferred): SQL-text assertions match fragments only
Task 5: fix round 1/5 (4 addressed, 0 open; commits 8fa7812..89a8e32)
Task 5: minor (deferred): no-op PATCH on an OWNER_EMAILS row returns 200 while a real change returns 400; cosmetic message ordering
Task 5: complete (commits 343e200..89a8e32, review clean)
Task 6: dispatched (sonnet), BASE 89a8e32 (backend)
Task 4: lockout SQL proven on real Postgres 11/13 (temp tables on Supabase, dropped on commit): 4 failures unlocked, 5th locks, 6th changes no row, first failure after expiry resets the count to 1
Task 6: implementer DONE at 7a6fc25 (939 pass); review dispatched
Task 6: review Needs fixes — Important: unpatched tests can post to the real Discord channel
Task 6: fix round 1/5 dispatched (autouse no-Discord fixture, cap pre-check, truncation order, misconfig warning, email in code span, invisible chars, FRONTEND_URL checks); FIX_BASE 7a6fc25
Task 6: note for Task 12: send one real alert after rollout to confirm the bot can post in the channel and the message renders
Task 6: minor (deferred): shared cap means a burst of fake sign-ins can crowd out a real approval alert for the day (by design)
Task 6: fix round 1/5 (9 addressed, 0 open; commits 7a6fc25..bbe67fa)
Task 6: minor (deferred): em-dashes in app/auth.py comments turned into literal — text (lines ~100, 119, 231)
Task 6: minor (deferred): a daemon alert thread outliving its test could run after the guard is torn down
Task 6: minor (deferred): empty email renders as two backticks
Task 6: complete (commits 89a8e32..bbe67fa, review clean)
All tasks 1-11 complete. Backend head bbe67fa, frontend head e45ad66. Final whole-branch reviews dispatched (fable), one per repo.
Final review (backend, fable): With fixes. Contract check: all endpoints agree, no mismatches. Important: /auth/password has no global cap and hashes on the event loop.
Final fix wave (backend) dispatched to the Task 4 implementer: global cap 60/min, hashing in threadpool behind a limit of 2, docstring, — comments; FIX_BASE bbe67fa
Rollout cautions from final review (for Task 12): (1) check llm.env ends with a newline before appending the flag (tail -n 2); (2) the Vercel preview can't be exercised until the new backend is deployed (old backend has no /auth/me); do preview checks between steps 6 and 7; (3) after the frontend deploy the owner's existing cookie has no user id -> 503 on every API call until he signs out and back in; (4) run steps 6-8 back to back; (5) frontend rollback after step 8 needs the flag put back; (6) apply migration via apply_migration and confirm a second run is a no-op
Final review minor (backend, deferred): password reset doesn't end that account's existing sessions (24h); add a UI line or follow-up
Final review note: "no guest/family approvals" should hold until Plan 3 as well (guests could trigger paid analysis on a cache miss; chat has no allowance yet)
Final review (frontend, fable): With fixes. Contract check agrees. Critical: "Check again" uses update() with no argument (GET; never triggers the role refresh). Important: id-less sessions never heal (every pre-deploy cookie, incl. the owner's); 423/429 shown as wrong password; login form trims the password.
Final fix wave (backend): implementer hit usage limit before committing; resumed 11/13. FIX_BASE bbe67fa.
Final fix wave (frontend) dispatched to the Task 10 implementer (9 items incl. per-user SWR cache and revoked-session redirect); FIX_BASE e45ad66. Report: final-frontend-fix-report.md
Ruling: per-user localStorage cache and sign-out clearing are pulled into this branch (review listed them as "before any guest is approved") — a shared browser could show the owner's cached data — if wrong, slightly less offline caching.
Final review minors (frontend, deferred): "Value $" toggle still shows for guests (Plan 2); 28 routes lost Vercel caching — time the stock page on the preview (backlog D); new password account shows "Last seen just now"; creating an Owner account has no confirm step; inputs lack aria-invalid; emails written to Vercel logs in auth.ts (pre-existing); callbackUrl not validated after password sign-in (pre-existing; backlog E)
Final fix wave (backend) done at 8bf2ce9 (976 pass); scoped re-review dispatched
Final fix wave (backend): re-review clean (5 addressed; commits bbe67fa..8bf2ce9). Backend branch final head 8bf2ce9, 976 tests pass.
Ruling: residual accepted — someone flooding the public login form at 60/min blocks all password logins while it lasts; Google sign-in is separate and unaffected; real fix is per-client-IP limiting at the edge (backlog E) — if wrong, password accounts are unusable during a flood.
Final fix wave (frontend) done at e958701 (152 tests, tsc/lint/check:routes/build green); scoped re-review dispatched (opus)
Final fix wave (frontend): re-review (opus): findings 1-8 addressed; finding 9 (revoked-session redirect) open. No Critical/Important breakage. Frontend final head e958701, 152 tests, tsc/lint/check:routes/build green.
Ruling: finding 9 parked — parked — a revoked guest sees error panels instead of being sent to /pending until they sign in again; no data reaches them (requireRole denies every call) — it was my addition (a final-review Minor), there are no guests until Plan 2, and the skill allows one fix wave; fix in Plan 2 by calling update({}) before navigating and aligning the 403 text — if wrong, a revoked person sees a confusing page.
Final fix wave minors (frontend, deferred): stale "gets 503" comments in auth.ts:22-25, 228-229; no notice when the Google sync fails and the person is signed out on /login; SWRProvider re-renders on session change
Task 5: last-owner guard SQL proven on real Postgres 11/13 (temp tables on Supabase): demote with another owner present -> 1 row; demote or delete the last owner -> 0 rows; guest change -> 1 row. Concurrency (two sessions) reasoned by reviewer, not run.
BUILD COMPLETE 11/13. Backend 8bf2ce9 (976 tests). Frontend e958701 (152 tests). Next: Task 12 rollout with Qais.
