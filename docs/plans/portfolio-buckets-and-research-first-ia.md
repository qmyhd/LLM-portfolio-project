# Portfolio Buckets + Research-First IA — Implementation Plan

> **Status (2026-05-20): All six phases shipped to production.**
>
> Shipped:
>
> - **Phase 0** — `schema/069_account_buckets.sql` adds `accounts.bucket` enum, `schema/070_risk_cache_bucket.sql` adds bucket to `portfolio_risk_cache` PK, `schema/071_analysis_cache_bucket.sql` adds bucket to `stock_analysis_cache` PK.
> - **Phase 1** — `src/bucket.py` helpers + `?bucket=` filter on every data endpoint (positions, movers, sparklines, risk, orders, activities, trades, stock profile, OHLCV overlay, stock activities, chat). Uses LEFT JOIN so legacy orphan-account rows still surface when no bucket filter is set. `src/analysis/orchestrator.py` `get_portfolio_risk` bucket-aware; cache keyed by bucket.
> - **Phase 2** — `PATCH /connections/{id}/bucket` backend endpoint + Settings UI dropdown with optimistic update.
> - **Phase 3** — Sidebar split into Research / Portfolio groups; `/page.tsx` is the new research home (ideas feed + quick-jump tiles); positions/orders/activity moved under `/portfolio/*` via `git mv`; permanent redirects in `next.config.mjs` keep old URLs working.
> - **Phase 4** — `BucketContext` + `BucketProvider` + `useBucket` + `withBucket`; `BucketSwitcher` tab strip (self-wrapped in Suspense); URL is source of truth via `?bucket=`; portfolio layout and stock-detail layout both wrap children in the provider; all data hooks read the bucket and include it in SWR keys. `BucketBadge` on filtered stock pages, `stockHref()` helper propagates bucket through links.
> - **Phase 5** — `/portfolio/equity-curve?days=&bucket=` endpoint reads `position_snapshots`. New `<EquityCurveCard>` on `/portfolio` landing renders a daily-equity area chart via lightweight-charts with 1M/3M/6M/1Y/ALL tabs. Empty state explains the nightly pipeline when snapshots are sparse.
> - **Phase 6** — Migration 071 extends `stock_analysis_cache` PK to include `bucket`. `get_stock_analysis(bucket=...)` threads through `_check_cache`, `_compute_analysis`, `_refresh_analysis`, `_cache_result`. `_assemble_input` aggregates position context across (bucket-scoped) accounts (replacing the previous arbitrary `LIMIT 1` pick), and the portfolio-value denominator for the risk agent's position-sizing math is bucket-scoped too. Frontend `AnalysisPanel` + `RiskCard` refetch on bucket change.
>
> Companion fixes shipped alongside the bucket work:
>
> - **B1** (high) — Trade P/L now uses historical weighted-avg basis at-time-of-trade (`_compute_historical_basis` walk) instead of current avg_cost. Fixes "every old SELL on a closed-out position shows null/wrong P/L" and "BUY unrealized uses portfolio avg instead of lot price".
> - **B2** (high) — SnapTrade webhook handler now backgrounds `_handle_event` via `BackgroundTasks` so the 15-30s sync doesn't trip SnapTrade's webhook retry threshold.
> - **B3** (high) — `stocks.py` order-count + OHLCV trade-marker queries used `status = 'filled'` (lowercase) against uppercase column data, always returning 0. Fixed to `UPPER(status) IN ('EXECUTED', 'FILLED')`.
> - **B4** (medium) — `avgSentimentScore` was declared but never computed; now returns all-time + 30d + 7d windowed AVGs.
> - **B5** (medium) — Trade-feed dedup key switched from amount (different in activities vs orders) to units + side (matches across sources).
> - **B6** (medium) — Per-stock vs recent trades inconsistency.
> - **B7** (medium) — `refine_idea(apply=True)` now runs inside a `transaction()` block with `pg_advisory_xact_lock` so double-click during the 3-pass refine can't race.
> - **B8** (medium) — `snaptrade_collector` reconcile Guard 3 now fails closed when the sync-timestamp check itself errors (was failing open with `except: pass`).
> - **F1-F7** UI fixes: BlossomTradeCard neutral SELL when P/L unknown, TradeCard amount-color removed, PanelGroup direction prop, conditional ellipsis, Analytics inside SplashGate, IdeasPanel error state, dead PositionCard removed.
> - **Discord bot** — `!portfolio <bucket>` accepts any of the five bucket names alongside the existing winners/losers/limit filters.



## Vision

Separate the site into two top-level concerns:

1. **Research** (the main focus) — ideas feed, stock research, analysis, watchlist.
2. **Portfolio** (a tab) — positions, trades, P/L, risk, broken down by *bucket*: long-term, swing, day, other.

A "bucket" is a strategy classification on each connected SnapTrade account. The current Robinhood account gets assigned to one bucket; future accounts (more Robinhood, IBKR, etc.) get tagged when connected.

---

## Data model

Single new column on `accounts`:

```sql
ALTER TABLE accounts ADD COLUMN bucket text NOT NULL DEFAULT 'other'
  CHECK (bucket IN ('long_term', 'swing', 'day', 'retirement', 'other'));
CREATE INDEX accounts_bucket_idx ON accounts(bucket);
```

- `long_term` — taxable buy-and-hold (e.g., current Robinhood)
- `swing` — multi-day to multi-week positions
- `day` — intraday
- `retirement` — IRA / Roth IRA / 401k — tax-advantaged, separated for tax planning
- `other` — uncategorized / mixed / fallback for new connections

**Crypto:** folded into whichever bucket the holding account belongs to (no separate bucket). The existing `_CRYPTO_SYMBOLS` frozenset in `market_data_service.py` already identifies crypto positions; UI work will badge them distinctly within each bucket.

Stored on `accounts`, not on `activities`/`orders`/`positions`, because:
- Bucket is a property of the **account**, not the trade.
- Querying positions/trades filtered by bucket = single JOIN to `accounts`, no per-row data backfill.
- If a SnapTrade account ever needs to span buckets, we revisit (per-trade tagging is a Phase 7 if it becomes a real need).

Stored on `accounts`, not on `activities`/`orders`/`positions`, because:
- Bucket is a property of the **account**, not the trade.
- Querying positions/trades filtered by bucket = single JOIN to `accounts`, no per-row data backfill.
- If a SnapTrade account ever needs to span buckets, we revisit (per-trade tagging is a Phase 7 if it becomes a real need).

---

## Phasing — each phase is independently shippable

### Phase 0 — Schema migration

**Goal:** add the `bucket` column with no behavior change.

**Deliverables:**
- `schema/069_account_buckets.sql` — `ALTER TABLE` + index + CHECK constraint with the five enum values.
- Run `python scripts/deploy_database.py` on prod (or run the migration SQL directly in Supabase SQL editor).
- One-time assignment SQL for current accounts (Robinhood → `long_term`, Roth/IRA → `retirement`). The migration includes commented-out templates; user runs them after reviewing actual account names with `SELECT id, name, institution_name FROM accounts;`.
- `schema/060_baseline_current.sql` is NOT edited (per its header note: "Never edit this file once applied; create a new 06N_*.sql migration instead").

**Acceptance:**
- `SELECT bucket, COUNT(*) FROM accounts GROUP BY bucket` returns expected rows.
- All existing queries still work (column has a default, no code references it yet).

**Effort:** ~30 min. **Risk:** very low — purely additive.

---

### Phase 1 — Backend bucket filtering

**Goal:** every endpoint that returns position/trade/activity data accepts an optional `?bucket=<name>` query param. Default = all buckets (backward compat).

**Touchpoints (single helper + per-endpoint plumbing):**

New helper in `src/db.py` or a new `src/bucket.py`:
```python
def bucket_filter_clause(bucket: str | None, alias: str = "acc") -> tuple[str, dict]:
    """Returns (SQL fragment, params) to AND into a query joining accounts."""
    if not bucket or bucket == "all":
        return "", {}
    return f" AND {alias}.bucket = :bucket ", {"bucket": bucket}
```

Endpoints to update (each gets a `bucket: str | None = Query(None)` param):
- `app/routes/portfolio.py` — `/positions`, `/movers`, `/sparklines`, `/risk`
- `app/routes/orders.py` — `/`
- `app/routes/activities.py` — `/`
- `app/routes/trades.py` — `/trades/recent`, `/stocks/{ticker}/trades`
- `app/routes/stocks.py` — `/stocks/{ticker}` profile (per-bucket breakdown)

**Cache key updates:**
- `portfolio_risk_cache` PK currently is just user/portfolio scope. Needs a `bucket` column added so per-bucket risk doesn't collide. New migration: `schema/070_risk_cache_bucket.sql`.
- `stock_analysis_cache` doesn't need bucket (it's per-stock, not per-portfolio scoped) unless the multi-agent analysis starts using bucket-scoped portfolio context — defer until Phase 6.

**Acceptance:**
- `curl /portfolio/positions?bucket=long_term` returns subset; no bucket = full set.
- `/portfolio/risk?bucket=swing` computes risk on swing positions only.
- Existing frontend (Phase 0-1 inclusive) still works because the param is optional.

**Effort:** ~3-4 hours. **Risk:** medium — many endpoints, must audit each query that joins `accounts`. The deleted-account exclusion pattern (already widespread) is the template.

---

### Phase 2 — Settings UI for bucket assignment

**Goal:** UI to assign / change a bucket on a connected account.

**Backend:**
- New endpoint `PATCH /accounts/{account_id}/bucket` in `app/routes/connections.py` (or new file). Body: `{"bucket": "long_term"}`. Validates enum, updates `accounts.bucket`.

**Frontend:**
- New section in `/settings` page: "Account Buckets".
- Lists each row in `/connections` with a dropdown for bucket.
- BFF route at `app/api/accounts/[id]/bucket/route.ts` proxying the PATCH.
- Optimistic UI update; toast on error.

**Acceptance:**
- Change bucket in Settings → backend persists → reloading other pages picks up the new value.
- Manual SQL backfill from Phase 0 is no longer needed for new accounts.

**Effort:** ~2-3 hours. **Risk:** low.

---

### Phase 3 — Research-first nav

**Goal:** restructure the top nav so Research is the home and Portfolio is a tab. **No bucket filter yet — that's Phase 4.** Phase 3 is just the IA shuffle.

**New top nav:**
```
Research (home, /)
Stocks (/stocks/[ticker])
Portfolio (/portfolio)   <- replaces /positions as a destination
Activity (/activity)
Settings (/settings)
```

**Page changes:**
- New `app/page.tsx` content: ideas feed (latest parsed ideas), watchlist preview, recent stocks-with-news widget. Replaces the current portfolio-centric dashboard.
- The current dashboard widgets (movers, top positions, recent trades) move to `app/portfolio/page.tsx` as the new portfolio landing.
- `app/positions/page.tsx` → moves to `app/portfolio/positions/page.tsx` (or absorbed into `/portfolio`).
- `app/orders/page.tsx` → kept or merged into `/activity`.

**Acceptance:**
- Visiting `/` shows research content, not positions.
- All existing portfolio/positions/orders functionality reachable under `/portfolio/*`.
- No backend changes in this phase.

**Effort:** ~3-4 hours. **Risk:** medium — touches routing, breadcrumbs, links from emails/Discord bot (audit for hardcoded `/positions` etc.).

---

### Phase 4 — Bucket switcher in Portfolio

**Goal:** bucket filter on every Portfolio sub-page, sticky across navigation.

**Frontend:**
- `app/portfolio/layout.tsx` — adds a bucket tab strip / chip row above all `/portfolio/*` pages.
- Active bucket lives in URL: `/portfolio` (all), `/portfolio/long-term`, `/portfolio/swing`, `/portfolio/day`, `/portfolio/other`. URL is source of truth.
- All BFF routes under `app/api/portfolio/*`, `app/api/trades/*`, `app/api/orders/*`, `app/api/activities/*` pass the active bucket to the backend.
- Bucket also propagates to `/stocks/[ticker]` via URL param `?bucket=`, so the per-account breakdown becomes per-bucket when arriving from a portfolio view.

**Acceptance:**
- Click "Long-term" chip → positions list refetches with `?bucket=long_term`.
- URL is shareable and reload-stable.
- Stock detail page shows bucket-scoped position breakdown when arrived from a bucket view.

**Effort:** ~3-4 hours. **Risk:** medium — URL state + SWR cache key management.

---

### Phase 5 — Per-bucket sparklines and equity curves

**Goal:** show each bucket's performance separately on the portfolio landing page.

**Backend:**
- `position_snapshots` table (already exists — added in migration 068) needs to be queryable per-bucket. Either:
  - Add `bucket` column to `position_snapshots` and backfill from `accounts.bucket` at snapshot time; OR
  - Compute per-bucket at query time by JOINing `accounts`.
- The JOIN approach has no migration but recomputes on every read. Snapshot column wins if you'll query this on every page load. **Default: JOIN at query time** unless perf becomes an issue.
- New endpoint: `/portfolio/equity-curve?bucket=<name>&days=<n>` returns time-series of bucket market value.

**Frontend:**
- New `EquityCurve` chart component on `/portfolio` landing showing one line per bucket (or stacked).
- Per-bucket sparklines on the dashboard.

**Acceptance:**
- Each bucket has its own equity line.
- Toggling buckets on/off in the chart legend works.

**Effort:** ~4-6 hours. **Risk:** low-medium — per the retroactive labeling decision, we JOIN `position_snapshots` against current `accounts.bucket`. No schema change, no backfill ambiguity. Caveat: reassigning an account rewrites that bucket's historical curve from one render to the next, by design.

---

### Phase 6 — Bucket-aware risk + multi-agent analysis

**Goal:** risk metrics and multi-agent analysis can be scoped to a bucket.

**Backend changes:**
- `portfolio_risk_cache` PK includes `bucket` (migration from Phase 1 covers this).
- `src/analysis/risk.py` accepts a bucket filter when building the position set.
- `src/analysis/orchestrator.py` propagates bucket through to `AnalysisInput`, including the portfolio-context section that's fed to the multi-agent consensus.
- `/stocks/{ticker}/analysis?bucket=swing` returns analysis where the portfolio-context reflects only swing-bucket holdings.

**Acceptance:**
- HHI, VaR, correlation displayed per bucket on `/portfolio/{bucket}`.
- Multi-agent narrative on the stock page changes when bucket switches (because the portfolio context the LLM sees changes).

**Effort:** ~4-5 hours. **Risk:** low-medium — analysis system already takes structured input; adding bucket filter is local.

---

## Decisions (resolved 2026-05-19)

1. **Current account assignments** — Robinhood → `long_term`. Existing Roth/IRA accounts → `retirement`. New connections default to `other` until tagged in Settings.
2. **Crypto** — folded into the holding account's bucket. UI labels crypto distinctly via the existing `_CRYPTO_SYMBOLS` frozenset; no separate bucket.
3. **Reassignment is retroactive.** All historical queries JOIN to `accounts.bucket` (current value) — there is no per-snapshot/per-trade bucket history. Moving an account from `long_term` to `swing` re-labels all of its past data immediately. Simpler and matches user intent. Consequence: `position_snapshots` does **not** get a `bucket` column.
4. **Bot commands** — deferred. Easy to add `!positions <bucket>` etc. post-Phase 4 if useful.

---

## Effort + risk summary

| Phase | Goal | Effort | Risk |
|-------|------|--------|------|
| 0 | Schema migration | ~30m | Very low |
| 1 | Backend bucket filtering | 3-4h | Medium |
| 2 | Settings UI | 2-3h | Low |
| 3 | Research-first nav | 3-4h | Medium |
| 4 | Bucket switcher | 3-4h | Medium |
| 5 | Per-bucket sparklines/equity | 4-6h | Medium |
| 6 | Bucket-aware risk/analysis | 4-5h | Low-Medium |

Total: ~20-26h of focused work. Phases 0-2 give you a working bucket model with no UI dependency. Phase 3 alone is the "research-first" half. Phases 4-6 are progressive polish.

---

## Recommended ship order

1. **Phase 0** alone (30 min) — DB ready, Robinhood account tagged. No user-visible change yet.
2. **Phase 1 + 2** as a unit (~5-6h) — backend filtering + Settings UI. You can manually use the URL `?bucket=` param to verify before any frontend filter.
3. **Phase 3** (~3-4h) — research-first nav. Site feels different even without buckets in the UI.
4. **Phase 4** (~3-4h) — bucket switcher visible. The vision lands.
5. **Phase 5 + 6** as polish, in either order.

Each ship is a separate PR; CI deploys via auto-deploy on `main`. Bot commands and email/Discord links audited at Phase 3 ship.
