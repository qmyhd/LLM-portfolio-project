# AI-Assisted Stock Profiling — Design Spec

- **Date:** 2026-06-01
- **Status:** Design — revised after adversarial review; pending user review
- **Project:** B of 2 (sibling project: percent-first portfolio)

> **Frontend path note:** the Next.js app is nested at
> `…\LLM-portfolio-frontend\frontend\src\…`. All frontend paths below use `frontend/src/…`.
>
> **Naming note:** to avoid collision with the existing auto-stats table `stock_profile_current`,
> type `StockProfileCurrent`, and hook `useStockProfile`, the NEW artifacts are named
> **`stock_thesis_profiles`** (table), **`ThesisProfile`** (type), **`useThesisProfile`** (hook).
> The user-facing word stays "Profile."

## Goal

A system to go through each stock individually and build a structured, AI-co-authored research
**profile** (thesis dossier) per stock, while tracking the **actual realized trades over time** for
that stock. Complements Project A: A presents portfolio-level *current-basket* performance; B
records *actual realized* per-stock history plus the user's thesis.

## Locked decisions

1. **Profile core — thesis-led dossier** (conviction, bull/bear, catalysts, levels/target, horizon,
   tags) co-authored with AI, with the actual trade track-record as a factual panel alongside.
2. **Workflow — per-stock tab + review queue, sharing one editor.**
3. **AI mode — hybrid:** AI auto-fills factual/data sections; AI interviews the user for the
   subjective parts.
4. **Universe — holdings first, add any ticker on demand.**
5. **Interview — adaptive:** tailored 3–5 questions; 0–2 smart follow-ups when an answer is thin or
   contradicts the data.
6. **Keying — per `(symbol, bucket)`, where `bucket` is a USER-SET strategy label** chosen at
   profile creation (NOT silently derived from `accounts.bucket`).
7. **Delete = archive** (`status='archived'`); no hard-delete in v1.
8. **Staleness = 90 days** (`PROFILE_STALE_DAYS = 90`).
9. **Revision history = full in v1** (table + append-on-save + a history-list UI).

## Bucket semantics — pinned down (revised after review)

`bucket` is a property of the **account** (`accounts.bucket`, `text NOT NULL DEFAULT 'other'`,
5 concrete values) and is **mutable + retroactive** — `PATCH /connections/{id}/bucket` re-labels all
of that account's historical positions/trades instantly. Given that:

- **The profile's `bucket` is the user's chosen strategy label**, set at creation, stored on the
  profile row. It is a concrete value ∈ {`long_term`,`swing`,`day`,`retirement`,`other`}.
- **The track-record panel** attributes trades via the live `accounts.bucket` join (the existing
  data path). **Known limitation (documented):** within a *single* account, a swing vs long-term
  thesis for the same ticker cannot have *separate* track records — trades are not tagged per-trade,
  only per-account-bucket. The thesis text is still independent and useful.
- **Reconciliation on reassignment:** profiles are NOT silently orphaned when an account's bucket
  changes. The queue surfaces affected profiles with a **"re-bucket"** action, and the **"all"**
  read view always lists every profile for the symbol regardless of current holdings.
- **Orphan rows** = a position/order/activity whose `account_id` matches no `accounts` row (there is
  no "null-bucket account" — `accounts.bucket` is NOT NULL). To include them under `other`, the new
  queue/track-record queries use `LEFT JOIN accounts … COALESCE(acc.bucket,'other') = :bucket`
  (the default `bucket_filter_sql` clause `acc.bucket = :bucket` would exclude them).
- **Manual-add** of a not-held ticker: the user picks the bucket (default = active bucket, else
  `long_term`).
- **"all"** is a read view only; never a write target.

## Data model — `schema/072_stock_thesis_profiles.sql`

### `stock_thesis_profiles`
- **`id` SERIAL PRIMARY KEY**, plus **`UNIQUE (symbol, bucket)`** (so `id` is a valid FK target —
  a bare SERIAL under a composite PK is NOT unique and would break the revisions FK).
- `symbol` VARCHAR(20) (UPPER), `bucket` **`text NOT NULL CHECK (bucket IN
  ('long_term','swing','day','retirement','other'))`** — 5 concrete values, **excludes `'all'`**.
  (Mirrors migration 069's `accounts.bucket`, the correct *write-target* precedent. NOTE: 070/071
  caches use a CHECK that *includes* `'all'` with DEFAULT `'all'`; do **not** copy those here, or an
  `'all'` row could be persisted in violation of the write guard.)
- `thesis` TEXT, `conviction` SMALLINT CHECK (1..5), `conviction_rationale` TEXT.
- `bull_case` TEXT, `bear_case` TEXT, `catalysts` JSONB, `risks` JSONB.
- `levels` JSONB (`{entry,target,stop}` numeric prices — factual, allowed under Project A).
- `horizon` `text`, `tags` TEXT[], `status` `text` (`draft`/`active`/`archived`).
- `ai_autofill_json` JSONB, `interview_json` JSONB, `model_used` `text`, `data_sources` TEXT[].
- `created_at`, `updated_at` (trigger), `reviewed_at` TIMESTAMPTZ (drives staleness).
- Indexes: `UPPER(symbol)`, `(bucket)`, `(reviewed_at)`. **RLS enabled.**
- Writes guarded by a **deterministic** per-(symbol,bucket) advisory lock — NOT Python's built-in
  `hash()` (randomized per process; the codebase uses it only as a fallback). Use e.g.
  `lock_key = int.from_bytes(hashlib.sha256(f"{symbol}:{bucket}".encode()).digest()[:8], "big") & 0x7FFFFFFFFFFFFFFF`.

### `stock_thesis_profile_revisions` (v1)
- `id` SERIAL PK, `profile_id` INT REFERENCES `stock_thesis_profiles(id)`, `symbol`, `bucket`,
  `snapshot_json` JSONB, `conviction` SMALLINT, `created_at`. **One row appended on every save**, so
  the full thesis/conviction history is captured from day one. Index `(profile_id, created_at DESC)`.

## Backend — `app/routes/profiles.py` (root-mounted, no prefix)

Mount like `trades.py`: root router, full paths spelled out, registered **after** `stocks.py` so the
specific `/stocks/{ticker}/profile*` routes resolve ahead of `stocks.py`'s `GET /{ticker}` catch-all.
All endpoints bucket-aware via `validate_bucket` + `bucket_filter_sql`.

- `GET /profiles?bucket=&queue=1` — list profiles (summary). `queue=1` → prioritized queue of
  `(symbol, bucket)` items: **holdings without a profile → stale (>90d) → recently-changed**, then
  user-added tickers, then **orphaned profiles** flagged for re-bucketing. Held pairs derived via
  `positions LEFT JOIN accounts … COALESCE(acc.bucket,'other')`.
  - **Stale** = `reviewed_at` older than `PROFILE_STALE_DAYS` (90).
  - **Recently-changed** = a new trade/activity in that `(symbol, bucket)` since `reviewed_at`.
- `GET /stocks/{ticker}/profile?bucket=` — fetch the `(symbol,bucket)` profile; `bucket=all` →
  list across buckets.
- `GET /stocks/{ticker}/profile/revisions?bucket=` — the saved-snapshot history for the
  `(symbol,bucket)` profile (powers the history-list UI).
- `POST /stocks/{ticker}/profile/autofill?bucket=` — assemble data sections (no thesis):
  - **track record** ← new `compute_stock_track_record(symbol, bucket)` (see below).
  - **catalysts** ← `openbb_service.get_company_news`.
  - **consensus** ← `analysis/orchestrator.py`. **Cost note:** on a *cold* cache (the queue's primary
    "holdings without a profile" case) this runs the full **5-agent + consensus LLM** pipeline, not a
    free cache read. Call with `refresh=False` (tolerate stale) and run autofill **async with a
    loading state**.
  - **risk** ← `analysis/risk.py`.
  - **ideas digest** ← built from the **`chat.py` query** (`dpi.primary_symbol` + LEFT JOIN
    `discord_messages` for author/created_at). Do **not** use the orchestrator's idea fields (broken
    — see "Bugs discovered, now fixed").
  - Never raises; degrades to partial on any source failure.
- `POST /stocks/{ticker}/profile/interview?bucket=` — 1 LLM call → 3–5 tailored questions tagged to
  fields; adaptive sub-mode (given prior answers + track record) → 0–2 follow-ups, `[]` when satisfied.
- `POST /stocks/{ticker}/profile/synthesize?bucket=` — merge answers + autofill into the structured
  thesis using the **3-pass refine *structure*** from `ideas.py` (refine → reflect for hallucinated
  levels / unsupported claims / conviction-thesis mismatch → re-refine). Returns an editable draft;
  never auto-saves.
- `PUT /stocks/{ticker}/profile?bucket=` — save/update (advisory lock; **append a revision row**; set
  `reviewed_at = now`). `bucket` must be concrete.
- `DELETE /stocks/{ticker}/profile?bucket=` — **archive** (set `status='archived'`); no hard-delete.

### LLM model config
Define explicit env vars `OPENAI_MODEL_PROFILE_LIGHT` / `OPENAI_MODEL_PROFILE_SYNTH` rather than
inheriting another module's defaults. (Note: `ideas.py` refine actually defaults to `gpt-4o-mini`,
and `consensus.py` escalates to `gpt-5` not `gpt-5.1` — `ideas.py` is reused as a *structural* 3-pass
pattern, not a model source.) Default light = `gpt-5-mini`, synth escalates to `gpt-5` on conflict.
All calls behind `hardened_retry`.

### `compute_stock_track_record(symbol, bucket)` — largely NEW code (not drop-in reuse)
`_enrich_trade` / `_compute_historical_basis` exist but only compute *per-trade* basis & P/L, and the
activities+orders merge/dedup/basis-refetch logic is **inlined inside the route handlers**
(`get_stock_trades`, `get_recent_trades`). This helper must (1) **extract** that trade-assembly into a
shared function, and (2) **add** the aggregate math that does not exist anywhere today: # trades, win
rate, avg hold days, best/worst, entry quality (vs 30d low/high), current position (qty + % weight),
first/last trade date. **Documented edge:** a SELL whose acquiring BUY is in another bucket (transfer
/ retroactive relabel) has no matching basis in the filtered set → its realized P/L is *omitted, not
zero*; assert this in the bucket-scoped test.

## Frontend

- **Profile tab** — add a tab to `frontend/src/components/stock/StockHubContent.tsx`; new
  `frontend/src/components/stock/ProfilePanel.tsx`. Renders a saved profile (thesis, conviction
  meter, bull/bear, catalysts, risks, levels, tags + track-record panel + **revision history list**)
  or a **"Build profile"** CTA.
  - **Bucket resolution for the Build/save flow (writes need a concrete bucket):** on the common stock
    entry path `useBucket()` is often `null`/`all`. Rule: if the symbol is held in exactly one bucket,
    auto-resolve to it; otherwise (or when `null`/`all`) present a **bucket picker** before
    autofill/synthesize/save. Reads under `all` show the per-bucket list.
  - **Revision history** — a collapsible list in `ProfilePanel` from
    `GET /stocks/{ticker}/profile/revisions`, showing prior snapshots (date, conviction, thesis) so
    the user can see how the thesis evolved.
- **Profiles workspace** — `frontend/src/app/profiles/page.tsx` + `frontend/src/app/api/profiles/*`
  proxy routes (+ `/api/stocks/[ticker]/profile/*`, incl. `/revisions`). Queue + progress + the same
  editor one `(symbol,bucket)` at a time, with **Skip / Save & Next**.
- **Types** — add `ThesisProfile`, `ProfileRevision`, `ProfileAutofill`, `InterviewQuestion`,
  `TrackRecord` to `frontend/src/types/api.ts`.

## Trade-tracking panel — "actual trades over time"
Per `(symbol, bucket)`, from `compute_stock_track_record`: # trades, realized P/L **as % only**
(see cross-project rule), win rate, avg hold days, best/worst, current position (qty + % weight),
entry quality, first/last trade date, plus buy/sell markers on the OHLCV chart (existing overlay).

### Cross-project consistency rule (resolves an A↔B contradiction)
Project A hides realized/unrealized P/L **$** on the stock page; this panel therefore shows realized
P/L **as a percentage only** (it does not reintroduce P/L$). Factual per-trade *notional* $ and price
remain (consistent with A). This makes the dollar policy uniform across both projects on the stock page.

## Out of scope
Project A; fully-automated profiles without review; streaming/conversational interview; multi-user /
sharing; revision **diffing** UI (v1 shows a history list, not field-level diffs).

## Bugs discovered in existing code — fixed as part of this work
1. **Orchestrator ideas query** (`orchestrator.py`) selects `ticker`/`created_at`/`author` from
   `discord_parsed_ideas`, which has `primary_symbol`/`parsed_at`/`author_id` — wrapped in
   try/except, so it silently yields zero ideas (degraded sentiment signal). **Fix:** repoint to the
   real columns (the `chat.py` pattern: `primary_symbol` + LEFT JOIN `discord_messages`).
2. **`account_balances` has no `total_value` column** (only `cash`, `buying_power`), yet the risk
   orchestrator does `SELECT SUM(total_value) FROM account_balances` — silently caught, falls back to
   equity-only market value. **Fix:** compute the portfolio total from a real source (positions equity
   ± the cash/buying_power columns as appropriate) so the $ VaR scaling is correct; Project A's VaR%
   display reads the percentage directly regardless.

## Testing
- **Backend** (`pytest -m "not openai and not integration"`): `compute_stock_track_record` math
  (realized P/L %, win rate, avg hold, entry quality), incl. multi-account, bucket-scoped, and the
  transferred-lot omission edge; orphan `account_id` under `other` via COALESCE; profile CRUD +
  deterministic advisory lock + **revision append on every save**; composite `UNIQUE(symbol,bucket)`;
  queue ordering (no-profile → stale@90d → changed) & bucket scoping incl. orphaned-profile
  reconciliation; autofill assembly with mocked services (graceful partial); interview/synthesis with
  mocked OpenAI (live variants marked `openai`); both bug-fixes regression-tested;
  `scripts/verify_database.py --verbose` for the migration.
- **Frontend:** ProfilePanel states (empty / building / draft / saved); revision history list
  renders prior snapshots; bucket picker when context is `null`/multi-bucket; queue Save & Next;
  interview form submit; `all` list view.

## Open items for review
- Manual-add bucket default (`long_term` vs the active bucket when viewing `all`).
