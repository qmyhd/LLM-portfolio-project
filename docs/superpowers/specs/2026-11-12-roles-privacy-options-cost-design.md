# Roles, %-only guest view, options split, OpenAI cap — Design

- **Date:** 2026-11-12
- **Status:** Design, waiting for Qais's review
- **Repos:** `LLM-portfolio-project` (FastAPI backend) and `LLM-portfolio-frontend` (Next.js on Vercel)
- **Backlog section:** A in `docs/plans/2026-11-12-next-round-backlog.md`

## Why

Qais wants to show the site to recruiters, clients, prospects, friends and family. They should see his real
portfolio and how he thinks, without learning how much money is in it. Today any Google account can sign in and
becomes a `viewer`, and the dollar amounts are only hidden in the browser: the API still sends them (security
review 11/10, finding C2). There is also no spending limit on OpenAI calls, and option trades distort the stock
P&L and trade lists.

## Goals

1. Nobody sees data until Qais approves them.
2. Approved visitors (guest, family) see percentages and price levels only. Dollar amounts and share counts never
   leave the server for them.
3. Qais (owner) keeps a full view with real numbers.
4. Options are out of the main P&L and trade lists for everyone. Qais gets a separate Options tab.
5. A daily ceiling on OpenAI calls that a normal day never hits and a runaway loop can't pass.

## Non-goals

- The backend verifying a signed user token from the frontend (review finding H3). The frontend stays the only
  caller and is trusted through the master key.
- Email alerts, two-factor login, self-service password reset.
- Different views for guest and family. They have identical permissions today; the two labels exist so they can
  diverge later.
- Hiding dollar amounts that appear inside the text of Qais's own notes (see "Known gap").

## Anti-goals (failure even if it "works")

- A guest can get a dollar amount, share count or account balance from any endpoint, including by opening
  devtools or calling `/api/*` directly.
- A demo or fake portfolio is shown to anyone.
- Qais gets locked out of his own site, or sees the redacted view for more than a few minutes during rollout.
- The nightly pipeline stops on a normal day because of the cap.

## Decided by Qais

| Topic | Decision |
|---|---|
| Sign-in | Google sign-in, then wait for approval. Plus username/password accounts: one for him ("dev", full access), family, guest |
| Owner | Only qaisme100@gmail.com (through `OWNER_EMAILS`), plus the dev password account |
| Guest and family view | Same view. % of portfolio, % P&L, price levels. No $, no share quantities. Always the real portfolio |
| Where redaction happens | On the server |
| Notes | Guests and family see everything: idea cards **and** raw Discord messages, unmasked, with exact percentages (risk accepted, see "Known gap") |
| AI for guests and family | A small daily allowance of chats per account |
| Approval alert | A Discord message from the bot |
| Existing 2 viewers | Set back to pending |
| Options | Out of P&L and trades for everyone; owner gets a separate Options tab, kept out of the main totals |
| OpenAI cap | 2,000 calls/day is "a good starting point" |
| Users page | Small, owner-only |

## Claude's calls (check these)

1. **Roles are `pending`, `guest`, `family`, `owner`.** `viewer` and `editor` go away. No editor accounts exist.
2. **The backend decides the role, not the browser session.** The frontend forwards the signed-in user's id; the
   backend looks the role up in `app_users`. This makes approval and revocation take effect without a new sign-in.
3. **Trade size for guests is shown as a % of the portfolio's value today**, e.g. "Bought NVDA @ $165.36 · 0.04% of
   portfolio". Historic portfolio totals aren't reliable enough to use the value on the trade date.
4. **Dividend and fee amounts are hidden for guests.** The row still shows ("Dividend received · MSTY · Nov 5").
5. **Settings → Brokerage Connections is owner-only**, including reading it. Account names and sync details aren't
   for guests.
6. **Cap numbers:** pipeline 2,000/day, app 500/day, guest and family chat 10/day per account. All three are
   settings, changeable without a code change.
7. **`analysis?refresh=true` is owner-only.** Guests read the saved analysis.
8. **The dev password account may hold the owner role**, with a longer minimum password (14 characters).
9. **Password accounts are created and reset by the owner on the Users page.** The `AUTH_USERS` setting on Vercel
   is retired.
10. **The owner's historic "Value $" curve is left as is**, even where past snapshots included option value.
    Options are excluded from totals going forward. Cash is left alone, even though it reflects option premiums;
    only the owner sees cash-based totals.
11. **Guests never trigger an analysis run.** They get the saved analysis for a stock, however old, or "not
    analysed yet". Only chat spends their allowance.
12. **The cap covers every paid model call, Gemini included** (`journal_generator.py` calls Gemini first). The
    settings keep their `OPENAI_` names.
13. **Guests may use the bucket tabs** (Long-term, Swing, and so on). Account ids, account names and the
    `account_id` filter are owner-only.
14. **Options tab, first version, is built from what's already stored:** option orders (`option_*` columns) and
    option activities. Open option positions need a new SnapTrade option-holdings sync; include it only if the
    builder confirms SnapTrade returns them for these Robinhood accounts, otherwise list it as a follow-up.
    Assignment and exercise: the resulting share trades count as normal stock trades.

## Known gap (accepted)

Raw Discord messages are shown word for word, and guest percentages stay exact. If a note says "put $500 into
NVDA", a guest reads that. Matched to that trade's `tradePct`, one such note gives the total portfolio value, and
every position's dollar size follows from its percentage. Qais was shown this on 11/12 and chose to accept it over
masking note text or rounding percentages. Don't add masking or rounding without asking him.

The same acceptance does **not** extend to anything the system generates. Broker description strings, cached
analysis text and AI answers must not carry sizes to guests (Part 4).

---

## Part 1 — Roles and who can do what

| Capability | pending | guest | family | owner |
|---|---|---|---|---|
| See any data | no | yes | yes | yes |
| Portfolio, positions, trades, stock pages, ideas, raw notes, research, timeline | no | %-only | %-only | full |
| "Value $" chart, Options tab, Settings → Connections, Users page, debug | no | no | no | yes |
| AI chat | no | 10/day | 10/day | within the app cap |
| Refresh analysis, capture or edit ideas, edit profiles, curation, watchlist edits, sync | no | no | no | yes |

- `app_users.role` gets a CHECK constraint for the four values. Migration sets every `viewer` to `pending`.
- Role order for `hasRole`: pending 0, guest 1, family 1, owner 3. Unknown values rank 0.
- A missing role in an old session is treated as `pending` (today it's treated as viewer).

## Part 2 — Sign-in and approval

**Google.** Unchanged up to the backend call. `POST /auth/google` creates new users as `pending`. An `OWNER_EMAILS`
match still becomes owner.

**Username and password.**
- Stored in `app_users` with `provider = 'password'`, `provider_user_id = <username>`, and a new `password_hash`
  column (argon2id or bcrypt; builder's choice).
- New `POST /auth/password` verifies a login and returns the user. It does the hash work even when the username
  doesn't exist, so timing doesn't reveal which usernames are real.
- Lockout: 5 failed tries for a username locks it for 15 minutes. A global limit protects the endpoint as a whole.
- NextAuth's Credentials provider calls this endpoint. `AUTH_USERS` parsing is deleted.

**Pending experience.** A pending user who signs in lands on a "Waiting for approval" page: a short message, a
"Check again" button and "Sign out". Every other page redirects there and every `/api/*` route returns 403.

**Approval alert.** When a new pending user is created, the backend posts to a Discord channel through the Discord
REST API with the existing bot token: name, email, and a link to the Users page. The channel id is a new secret,
`APPROVAL_ALERT_CHANNEL_ID`. A failed post never blocks the sign-in. At most 20 alerts a day.

**Freshness.**
- The frontend forwards `X-App-User: <app_users.id>` on every backend call (added in `backendFetch`, taken from the
  session).
- The backend resolves the role from the database, cached for at most 30 seconds.
- Result: revoking or demoting someone cuts off data within 30 seconds, whatever their browser session says.
- "Check again" refreshes the browser session's role so the pages unlock right after approval.
- A request with no `X-App-User`, or an unknown id, is treated as `pending` and gets nothing. Exceptions: `/health`,
  `/webhook/*`, `/auth/*`.
- Local development with `DISABLE_AUTH=true` acts as owner.

## Part 3 — Users page (owner only)

Route `/settings/users`, linked from Settings. Backend routes under `/users`, all owner-only.

- **List:** name, email or username, sign-in type, role, last seen, AI chats used today. Pending users on top with a count.
- **Actions:**
  - approve as guest or family;
  - change between guest and family;
  - revoke (back to pending);
  - delete.
- **Password accounts:** create (username, role, password), reset password. The password is typed by Qais and never shown again.
- **Guard rails:**
  - the owner role can't be granted to a Google account here (that's `OWNER_EMAILS`);
  - the owner can't revoke or delete himself;
  - at least one owner must remain.
- Shows today's OpenAI usage against the caps (Part 6).

## Part 4 — %-only view for guest and family

**Principle.** One place in the backend decides what a non-owner may receive. Every number in every response model
is classified as *public* (price levels, percentages, counts) or *private* (dollar sizes, share counts, balances).
For a non-owner, private fields are returned as `null`. The classification must be exhaustive: a test fails when a
numeric field has no classification, so a field added later can't leak by default.

**What's private** (non-exhaustive; the builder completes it from the models):

| Area | Private (null for guests) | Stays |
|---|---|---|
| Positions | quantity, equity, openPnl, dayChange ($) | averageBuyPrice, currentPrice, openPnlPercent, dayChangePercent, portfolioDiversity, weekChangePct |
| Summary | totalValue, totalEquity, totalCost, unrealizedPL, dayChange, cashBalance, buyingPower, cryptoValue, cryptoPnl | all percentages, positionsCount; `assetBreakdown` becomes shares of 100% |
| Trades, activities, orders | units, amount, fee, totalShares, marketValue, realizedPnl, unrealizedPnl, totalQuantity | price, side, type, date, symbol, portfolioPct, realized/unrealized P&L %, new `tradePct` |
| Stock page | currentPositionQty, currentPositionValue, unrealizedPnl, avgOrderSize | avgBuyPrice, unrealizedPnlPct, order counts, all market data |
| Chart trade markers | quantity | price, side, date |
| Movers | quantity, equity | prices and percentages |
| Equity curve ("Value $") | whole endpoint is owner-only | |
| Recon and debug data | whole payload is owner-only | |

**Anything without a typed model is deny-by-default.** Field marking can't see these, so each needs an explicit
allowlist of what a guest receives (found in the 11/12 builder check):

- **Cached JSON with no response model:** `/portfolio/risk` and `/stocks/{t}/analysis*` (`app/routes/analysis.py`).
  - The risk blob has `var_95_1d` in dollars next to `var_95_1d_pct`; dividing them gives the portfolio value.
  - The analysis blob's `data_sources` text includes "Portfolio positions (N shares…)" and is stored in `stock_analysis_cache`.
  - Redact on read, so old cache rows are covered too.
- **Bare dicts:** `ThesisProfile.trackRecord` carries `currentQty`.
- **Strings with sizes baked in:** broker `description` fields on trades and activities ("1.000 units of NVDA @
  $123.00"). Guests get a description rebuilt from public fields, or none.
- **Account structure:** `Position.accountId` and the `account_id` filter.

**Frontend caching.**
- 22 route handlers cache backend responses for 30 to 3600 seconds, and Next keys that cache on request headers.
- So `requireRole` must confirm the user's current role with the backend (cached at most 30 seconds) **before** any
  cached fetch is served. Otherwise a revoked user keeps getting a stored 200.
- Cached entries must never be shared between an owner view and a redacted view.

**New field `tradePct`:** the trade's dollar amount divided by the portfolio's value today, as a percentage. It's
computed on the server, so guests never receive the two inputs.

**AI chat.** The prompt context for a non-owner is built from the same redacted data, so the model never sees
sizes and can't repeat them.

**Frontend.**
- Money fields become nullable in the types. Components show the % form when the $ value is null.
- For guests the UI hides the "Value $" toggle, the Options tab, Settings → Connections, the Users page and every write button.
- The chat box shows how many chats are left today.
- The browser-side `hideSizes` logic stays as a second layer and switches to the new role names.

## Part 5 — Options

- **One shared definition of "this row is an option"** for positions, orders and activities, replacing the
  separate checks in `trades.py` and elsewhere. The builder should first measure how options show up in each table
  today (asset type, `option_type` column, description text).
- **Excluded for every role** from:
  - positions and portfolio totals;
  - unrealized and realized P&L;
  - the return series;
  - movers;
  - recent trades, activity, orders and stock-page trades;
  - chart trade markers.
- **Owner-only Options tab** on the portfolio page, backed by `/options/*` routes:
  - open option positions;
  - option trade history;
  - simple totals: premium paid and received, realized P&L on closed contracts.
  - These numbers are never added into the main totals.
- The 11/04 design plans `app/routes/options.py` for the covered-call tool. These routes live in the same file.

## Part 6 — OpenAI daily cap

- **One door.** Every paid model request in the backend, bot and scripts goes through a single module that counts
  before it calls. A test fails if an OpenAI or Gemini client is created anywhere else. Known call sites today:
  `chat.py`, `profiles.py`, `ideas.py` (3), `consensus.py`, `openai_parser.py`, `journal_generator.py` (Gemini,
  then OpenAI), `run_batch.py`, `batch_backfill.py`.
- **Counting.**
  - A small table keeps calls per day, per scope (`app`, `pipeline`) and, for chat, per user.
  - The increment and the limit check happen in one database statement.
  - The day rolls over at midnight America/New_York.
  - Batch jobs count one per request inside the batch.
- **Limits (settings with these defaults):** `OPENAI_DAILY_CAP_PIPELINE=2000`, `OPENAI_DAILY_CAP_APP=500`,
  `OPENAI_GUEST_DAILY_CHATS=10`.
- **When a limit is hit.**
  - App: a 429 with a plain message ("Daily AI limit reached, resets at midnight ET").
  - Pipeline: the batch stops cleanly, logs it, and posts one Discord alert.
  - Nothing retries in a loop.
- **Visibility.** Today's counts appear on the Users page.

## Part 7 — Proof it works (required tests)

1. **Role matrix:** every backend route is called as pending, guest, family and owner. Pending gets 403 everywhere
   except auth. Guest and family get 403 on every write except chat.
2. **No-leak contract:** every GET route is called as guest against seeded data with known dollar values. The
   response body must contain no private field with a value, and none of the seeded dollar numbers anywhere in the text.
3. **Classification is exhaustive:** a numeric response field with no public/private mark fails the test run.
4. **Options:** seeded option rows never appear in main endpoints, for any role. They appear in `/options/*` for the owner only.
5. **Cap:** the limit holds under concurrent calls. The pipeline stops cleanly. The "one door" test passes.
6. **Login:** lockout after 5 failures. Unknown username takes the same time as a wrong password.
7. **Frontend:** `check-route-guards.mjs` is updated for the new roles. Guest and pending flows are checked on a
   Vercel preview before merge.

## Rollout

- Database migration first (additive: new column, table, constraint, viewers to pending).
- The plan must order the two deploys so that no step exposes dollar data to a non-owner, and Qais sees the
  redacted view for a few minutes at most. Likely order: the frontend starts sending `X-App-User` first, then the
  backend starts enforcing it.
- **Qais's manual steps:**
  1. Add `APPROVAL_ALERT_CHANNEL_ID` to the AWS secret.
  2. After go-live, create the dev, family and guest accounts on the Users page.
  3. Delete `AUTH_USERS` and `ALLOWED_EMAILS` on Vercel.

## Left to the builder

- Hash algorithm, cache implementation, table and column names, file layout.
- How the public/private classification is expressed in code.
- The exact way the browser session picks up a new role after "Check again".
- The visual design of the pending page and Users page, following the app's existing style.
