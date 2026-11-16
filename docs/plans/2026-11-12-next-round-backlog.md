# Next round backlog (set 11/12/2026)

This is the single list for the next round of work on LLM-portfolio, covering both repos. Work it top to bottom
unless Qais reorders it. New requests get appended under **Inbox** at the bottom, then sorted into a workstream.

## Progress board

Update this table whenever a section changes state. Status is one of: not started, designing, design approved,
building, in review, live.

| Section | Status | Last update | Notes |
|---|---|---|---|
| A. Roles, privacy, options, cost | building | 11/13 | **Plan 1 of 4** (roles, sign-in approval, password accounts, Users page, Discord alerts) is built and reviewed in both repos on `feat/roles-approval` (backend `8bf2ce9`, 976 tests; frontend `e958701`, 152 tests). Rollout with Qais is next (plan Task 12). **Plans 2 to 4** (%-only view, AI cap, options) not started. No guest or family approvals until Plans 2 and 3 are live |
| B. Prices and numbers | not started | 11/13 | Bug list captured. Two root causes found: the stock profile refresh has written nothing since 7/22 (confirmed again after the 11/13 nightly run), and `ohlcv_daily` dates are one day early |
| C. Ideas, tags, sentiment, analysis | not started | 11/12 | Sentiment gauge and parsing ideas added 11/12 |
| D. Layout and performance | not started | 11/12 | |
| E. Housekeeping | not started | 11/12 | |
| F. Research attribution | not started | 11/12 | The parse is done, so this is unblocked |
| G. Trade story charts | not started | 11/12 | New on 11/12; needs its own design |

Order agreed 11/12: A → B → C → D → G, with E and F slotted in between.

## What Claude can reach (checked 11/12)

| System | Access | Notes |
|---|---|---|
| Supabase (`hlpboklskvnwotsgeetv`) | Yes: SQL, migrations, advisors, logs | |
| Vercel (`llm-portfolio-frontend`, team `team_BoIg8njrOp4XAFfV2iFA1mKO`) | Yes: deployments, build and runtime logs, env var names | Never decrypt values unless asked |
| GitHub (both repos) | `git fetch` and `git push` over HTTPS only | No `gh` CLI and the GitHub connector fails, so Qais opens and merges PRs in the browser |
| EC2 box | No direct access | Port 22 is blocked on Qais's network and there's no AWS CLI. Qais runs commands in the browser terminal. Merges to main deploy on their own through Actions |
| AWS Secrets Manager (`qqqAppsecrets`) | No | Qais edits it in the AWS console |
| Live API and site | Outside checks only (curl) | |

## State at 11/12 close

- The hardening branches are merged and live: backend PR #79 (`459417f`), frontend PR #21 (`0f86fbe`, Next 14.2.35).
  Verified from outside: every `/api/*` route redirects to login without a session, including dotted paths.
- EC2 has `ENVIRONMENT=production` in `/etc/llm-portfolio/llm.env`, and nginx allows PATCH.
  Backups of both are `*.bak-20261112`.
- The nightly timer is re-enabled (next run 11/13 at 1 AM). The 11/12 catch-up run cleared the parse backlog
  (625 ideas from 175 messages).
- Bucket switching **saves correctly** (it survives F5). What's wrong is that the dashboard doesn't refresh
  after a bucket change. See B8.
- Access: Qais's network blocks outbound port 22, so use the browser EC2 Instance Connect terminal.
  Key `~/.ssh/llm-ec2` (ed25519) is authorized on the box and works from other networks.

## A. Roles, privacy, options, cost (decided, needs a design first)

Write a short design spec, have Qais review it, then plan and build it. Fable is suggested for the design and the review.

1. **Approval gate**
   - A new Google sign-in gets role `pending` and sees no data.
   - An owner-only **Users page** lists users and sets their role (approve to family or guest, or revoke).
   - A role change takes effect right away; the 24h JWT role cache doesn't hold it back (review L4).
2. **Credentials accounts**
   - Three accounts: `dev` (owner, full numbers), `family` and `guest`.
   - Store hashed passwords (bcrypt/argon2), not plaintext in `AUTH_USERS`.
   - Compare in constant time, and rate-limit login attempts.
   - Remove the `admin:changeme` example. Only qaisme100@gmail.com is owner (review M2).
3. **%-only view for family and guest** (they see the same thing), stripped on the server (review C2)
   - **Shown:** % of portfolio, % P&L, price levels on trades and positions.
   - **Not shown:** $ values, share quantities, notionals or account balances, on any endpoint.
   - It's always the real holdings, never a demo.
   - Covers `/portfolio`, `/orders`, `/activities`, `/trades`, `/stocks/*/trades` and the equity-curve "Value $" series.
4. **Options**
   - Exclude them from P&L and trade lists for everyone.
   - The dev view gets a separate **Options** tab or section, kept out of the main totals.
5. **OpenAI daily cap**
   - Enforced in the backend and tunable through env vars.
   - Starting values: **2,000/day for the pipeline**, and **500/day for the app** (unless Qais sets a different app number), resetting at midnight ET.
   - When the cap is hit, fail softly with a clear message.
   - `analysis?refresh=true` becomes owner-only (review M1).

## B. Prices and numbers (bugs seen 11/12)

**Root causes found 11/12 (database checks, not yet fixed):**

- **`stock_profile_current` hasn't been written since 7/22/2026.** All 506 rows carry that date.
  - This is why the NVDA header shows a July price ($207 close then) with 0.00% today, and why the mention counts lag.
  - The nightly "Stock Profile Refresh" step either fails or writes nothing. Read its log after the 11/13 1 AM run:
    `journalctl -u nightly-pipeline.service --since "01:00" | grep -iA5 "stock profile"`.
  - Likely fixes B1, part of C2, and the stale stats on stock pages.
- **`ohlcv_daily` dates are one day early.** There are 13,942 rows dated on Sundays (first 2025-02-02) and none
  for the following Fridays. The recent rows are dated 11/5, 11/8, 11/9, 11/10 where the trading days were
  11/6, 11/9, 11/10, 11/11.
  - Probably a UTC-to-date conversion in the Databento backfill.
  - It affects "today's change", the day-by-day return series, chart alignment, and where the trade and note markers
    will land in section G.
  - Fix the loader, then shift the existing rows by one day in a migration. Check a few closes against a known source first.

1. The NVDA header shows **$204.64, +$0.00 (0.00%) today**, while the chart shows about $165.
   Total return (+90.37%) is probably computed from the stale price. Find the price source for the header and for "Your position".
2. The dashboard header % disagrees with the chart %:
   - the header showed +58.05% for "1W" while the chart said +15.63% YTD;
   - "+62.68% all time" sits next to "all-time −4.18%".
   Two different "all-time" definitions are shown side by side.
   Pick one per label, or label them clearly: "repriced holdings" vs "cost basis".
3. The Long-term tab sometimes shows the All tab's header (223 positions, all-time −4.18%) instead of Long-term's
   (209 positions, −9.35%). The bucket filter isn't applied, or a race between requests shows stale data.
4. The return series jumps about 20% in a single day in early May 2026.
   Likely a split, a bad price or a ticker mismatch in the repriced series. Find the symbol behind it.
5. Some 1Y and YTD return charts briefly end in July. A stale cache or a series that loaded halfway.
6. Share formatting:
   - ASML shows "Bought **0.0000** shares @ $1,414.24"; fractional shares need more precision;
   - "1 shares" should be "1 share".
   For family and guest, share counts are hidden anyway (A3).
7. Activity stops at "100 trades". Paginate or load more.
8. After a bucket change in Settings, the dashboard keeps the old numbers. Invalidate the SWR/cache on save.
9. Robinhood **Checking, Credit Card and Savings** are listed as investment accounts with buckets.
   Exclude non-brokerage account types, or give them a "Cash" bucket outside the portfolio.
   Also decide whether to hide the two "Deleted" old connections.

## C. Ideas and analysis

1. The NVDA **Ideas tab says "No ideas found"** while the page counts 53 mentions (10 in the last 30 days).
   Check the query or join behind the Ideas tab against `discord_parsed_ideas`.
2. **The Analysis tab is stale and contradicts itself:**
   - it was computed 11/2, model `gpt-5-mini-fallback`;
   - Fundamental and Valuation say "no data";
   - Sentiment says neutral (0%) while the page shows a 64% bull bar.
   Fix the sentiment feed into the agent, the fundamentals source and the refresh cadence.
3. **Idea tags are often inaccurate or not useful.** Review the parser's tag taxonomy and prompt against a sample
   of today's 625 ideas. Propose better tags, then re-tag. Re-tagging spends OpenAI money, so ask first.
4. **Rethink parsing and tagging as a whole** (Qais, 11/12: "try different ways to improve our parsing and idea
   tagging and overall process, allowing for more innovative use of the notes I'm leaving").
   - Test a few approaches side by side on the same sample of messages and score them. Don't just tweak the prompt.
   - Candidate uses for the notes:
     - link each note to the trades it led to (feeds section G);
     - track a thesis per stock over time;
     - "what I said vs what happened" scoring;
     - open questions and to-dos pulled out of notes.
5. **Sentiment score and gauge** (Qais, 11/12).
   - Today the score is a raw count of bullish, bearish and neutral ideas (`app/routes/sentiment.py`), with no weighting for recency, source or conviction.
   - The Analysis tab's sentiment agent read 0% while the bar showed 64% bull.
   - Design a real score: recency decay, source credibility tiers, conviction, and a minimum sample size.
   - Make it update when new ideas are parsed.
   - Make the gauge show what's behind the number: sample size, time window, trend.

## D. Layout and performance

1. On the stock page, **Recent Trades scrolls inside its own box**, and the page can't scroll past it. Fix the
   overflow and height so the page scrolls normally.
2. **Slow loading sometimes.** BRK.B showed skeletons for a long time (stats, header).
   Profile the slow endpoints: OpenBB/yfinance calls, missing caching, and calls that run one after another instead of in parallel.
4. **Make the whole site look special, polished and professional** (Qais, 11/12: "special and exquisite and
   professional looking"). A design pass across pages, not only the home page: type, spacing, colour, charts,
   empty and loading states.
5. **Mobile.** Some visitors (recruiters, clients, family) will open the site on a phone. Every page a guest can
   reach must work at phone width: no sideways scrolling, tables that reflow, charts that fit, touch-sized
   controls. Check each new page (pending, Users, Options) on a phone-width preview before merge.
3. **The home page is bland.** Redesign it after B is fixed, so it shows correct numbers.
   Ideas: today's movers, top positions by % of portfolio, new ideas, upcoming earnings for holdings.
   Use the frontend-design skill. The page has to work in the %-only view as well.

## E. Housekeeping (smaller, slot between items)

- **Security group:**
  - SSH is open to `0.0.0.0/0` on `ec2-rds-1`.
  - Narrow it to the EC2 Instance Connect prefix list (`pl-0e4bcff02b13bef1e`) plus GitHub Actions. Note: GitHub's IP ranges are large; alternatives are a self-hosted runner or SSM.
  - Remove the stale `108.28.23.175/32` rule if it isn't Qais's.
- **EC2 updates:** 91 updates are pending, 5 of them security. Patch in a quiet window. Don't do-release-upgrade.
- **Frontend:**
  - `npm audit` shows 11 issues (1 critical). The real fix is Next 15 plus next-auth stable.
  - Move the CSP from Report-Only to enforce once no violations show up.
- **Backend:**
  - Run `pip-audit`.
  - Untrack `.claude/settings.local.json`.
  - Make the `/auth/google` rate limiter use the real client IP (review L2).
- **Discord:** add the 9 extra finance channels to `LOG_CHANNEL_IDS` in Secrets Manager, then restart the bot.
- **GitHub Actions:** an `ubuntu-latest` → Ubuntu 26 notice. Pin `ubuntu-24.04` if anything breaks.

## F. Research attribution (parse is done, ready)

- Run `data/research/citrini-state-of-themes-2026-11-04-attribution.sql`.
- Write the equivalent attribution fixes for the Hannibal and neocloud research.

## G. Trade story charts (new 11/12, needs its own design)

Qais's idea: for each trade above a small dollar threshold ("$2-3"; confirm the exact number, since it exists to skip
dividend reinvestments and tiny fractional buys), build a chart of the stock on one or two time frames with:

- **Note markers:** a dot wherever he posted a message about the stock, with a short preview. Clicking it shows the full message or a summary.
- **A trade callout:** a marker at the moment the trade happened. Clicking it shows that trade.
- **Earlier trades:** smaller markers for previous buys and sells in that stock.

Open points for the design:
- Is it interactive in the app (most likely, on the stock page and from a trade row), or also a shareable image?
- Which time frames?
- What the %-only roles see: price levels yes; share counts and $ no.
- Depends on C1 (ideas linked to tickers correctly) and B1 (correct prices).

## Standing rules

- Commit only when Qais says go. Never push or merge for him unless he asks.
- Never loosen the Robinhood read-only guards.
- Never commit `data/security-review-2026-11-10.md`. It contains an exploit recipe.
- Ask before anything that spends OpenAI money on purpose: re-parsing, re-tagging, backfills.
- Work in `C:\github\dev\...` only, never the old OneDrive copy.
- When a step needs Qais at a terminal, say which terminal (PowerShell on the PC, or the browser server terminal), where, and which language.

## Inbox (new requests land here first)

-

## Checked 11/13 (after the first nightly run since the restart)

- The 1 AM run on 11/13 worked for snapshots (11/13 saved), prices (through the row dated 11/11) and parsing.
- **The stock profile refresh still wrote nothing:** `stock_profile_current` is unchanged since 7/22 (0 of 506 rows
  updated). So that step is broken, not just interrupted. It is the first thing to fix in section B.

## Carried out of the Plan 1 build (11/13)

Found by reviewers during the roles build and deliberately left for later. Each belongs to the section named.

- **Plan 2 (%-only view):**
  - A guest whose access is revoked mid-session sees error panels instead of being sent to the waiting page. No
    data reaches them. Fix: refresh the session (`update({})`) before navigating, and use one 403 message in
    both places; changing the text alone causes a reload loop.
  - The "Value $" toggle still shows for guests and returns 403.
  - Decide per route what is safe to cache again. This build removed Vercel caching from 28 routes for safety
    (news, filings, fundamentals, management and transcript were cached for an hour). Time the stock page first.
- **Plan 3 (AI cap):** guests can trigger a paid analysis on a cache miss; chat has no daily allowance yet. So the
  "no guest or family approvals" rule holds until Plan 3 as well.
- **E (housekeeping):**
  - Rate limiting by real visitor IP at the edge. Today a flood of the login form at 60 a minute blocks password
    logins while it lasts, and `/auth/google` shares one bucket. Google sign-in for the owner is unaffected by the first.
  - A password reset doesn't end that account's existing sessions (24 hours). "Revoke access" does.
  - `callbackUrl` isn't validated after a password sign-in (predates this build).
  - Emails are written to Vercel logs in `auth.ts` (predates this build).
  - Real accounts lock on 5 cumulative failures with no time window; the shadow lock for unknown names needs 5
    within 15 minutes. Align them.
- **Small polish, any time:** a new password account shows "Last seen just now" before it has signed in; creating
  an Owner account has no confirm step; form inputs lack `aria-invalid`; no notice when a Google sign-in is
  bounced because the backend was down; stale "gets 503" comments in `auth.ts`.
- The full list of deferred minor findings from every task review is in the build ledger,
  `.superpowers/sdd/2026-11-12-roles-approval-plan/progress.md` (local, not in git). Copy what still matters
  into this file before deleting that folder.

## Found 11/16 while verifying state before the rollout

- **A test wrote one row to the live database.** `app_users` has a row `qais@example.com`, provider `google`,
  `provider_user_id` `google-123`, role `owner`, created 11/12 22:35 UTC, id `750c6a5f-a585-4313-ac2a-59ad4edc1069`.
  - Cause: during the build, `app/auth.py` started importing `execute_sql` at module level, so five tests in
    `tests/test_content_sources_auth.py` that patched `src.db.execute_sql` stopped intercepting it and ran against
    the real database (the local `.env` holds the real database URL and `DISABLE_AUTH=true`). The tests were
    repointed in the same task, so it happened once.
  - Nobody can sign in as it (that would need a Google token for a made-up account id), but it is a bogus owner.
    **Delete it before migration 080** (waiting for Qais's okay on 11/16). Checked: no other table got rows from tests.
- **Before any further build (Plan 2 onward): make it impossible for tests to reach the real database.** Add an
  autouse guard in `tests/conftest.py`, like the Discord one: fail any test that calls the real `execute_sql` or
  opens a real connection, unless it is marked `integration`. Check the two fixtures added in this build too.

## Rollout log, Plan 1 (11/16)

- Stray test row deleted; flag `APP_USER_LEGACY_OK=1` added on the server (backup `llm.env.bak-20261116`);
  migration 080 applied and verified; backend merged (PR #80) and deployed; frontend merged and live.
- Qais signed in with Google on the new build: dashboard loads, Users and access shows him as Owner and the two
  old accounts waiting. He confirmed the pages look right.
- **Qais, 11/16, for section D:** "I really want to juice up and make our UI more special and unique." Treat the
  design pass as a priority within D, not polish: a distinctive visual identity across the whole site, not only
  the home page.
- The server shows "System restart required" (pending OS updates). Reboot in a quiet window with the E updates.
- 11/16: flag removed and API restarted (four settings left, healthy, no legacy warning after restart).
- **11/16, seen right after the API restart (to fix early, before Plan 2):** the first dashboard load took a long
  time, `/api/portfolio` logged one 504 from the backend (21:07 UTC), and the Users page showed "Couldn't load
  users". Minutes later the API answered `/health` in under 0.2 s.
  - Likely cause: after a restart the first `/portfolio` request is slow (cold price lookups) and runs blocking
    work inside an `async` handler, which freezes the server's single worker. While it is frozen the role check
    every request now depends on (`/auth/me`, 5-second timeout in the frontend) fails, so unrelated pages error.
  - Fixes to weigh: move the blocking portfolio work off the event loop (same pattern as chat); let the frontend
    reuse the last confirmed role for a short time when the lookup fails (for example 2 minutes), instead of
    failing at once; a second API worker; warm the portfolio cache at startup.
  - This also bears on Qais's "slow loading" complaint in D: with caching removed from 28 routes, every page
    view now reaches the single-worker backend.
- **11/16, fixed:** Approve, Revoke and Decline on the Users page answered 200 but changed nothing.
  `src/db.py` only committed statements whose first word was a write keyword, and those statements start with
  `WITH` (to lock the owner rows), so they were rolled back. Fixed on branch `fix/commit-cte-writes`.
- **Found by the review of that fix (pre-existing, for E):**
  - `SELECT pg_advisory_xact_lock(...)` is sent through `execute_sql` in `src/channel_processor.py:313` and
    `scripts/nlp/ingest_batch.py:343`. Each call runs on its own throwaway connection, so the lock is released at
    once and **protects nothing**. Use the `transaction()` context manager in `src/db.py` so the lock and the work
    share one transaction.
  - The per-connection `SET statement_timeout` / `SET lock_timeout` in `get_sync_engine` may be lost on a
    connection whose first use is a rolled-back read (psycopg2 runs the SET inside that first transaction).
    Verify on Postgres; the role-change statement relies on `lock_timeout`.
  - `retry_on_connection_error` retries on any SQLAlchemy error, including integrity errors. Narrow it to
    connection errors.
- **Lesson for every later plan:** route tests that mock `execute_sql` can't catch a statement that never commits.
  Add an `integration`-marked test per write path that runs against a throwaway Postgres (a Supabase branch) and
  checks the change is visible from a fresh connection.
