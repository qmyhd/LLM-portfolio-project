# AI-Assisted Stock Profiling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a per-`(symbol, bucket)` thesis dossier that the user co-authors with AI (auto-filled data sections + an adaptive interview), surfaced as a Profile tab on the stock page and a prioritized review-queue workspace, with full revision history and an actual-trade track record.

**Architecture:** New `stock_thesis_profiles` + `stock_thesis_profile_revisions` tables (migration 072). A new app-layer `compute_stock_track_record` reuses the importable trade-assembly helpers in `app/routes/trades.py`. A new root-mounted `app/routes/profiles.py` exposes CRUD + queue + autofill/interview/synthesize, reusing `chat.py`'s ideas query, `openbb_service` news, the `orchestrator` consensus, and the `ideas.py` 3-pass refine pattern. Frontend adds a Profile tab, a build-flow `ProfilePanel`, a `/profiles` queue page, proxy routes, and a hook.

**Tech Stack:** Python 3.11 / FastAPI / SQLAlchemy / pytest (backend `c:\Users\qaism\OneDrive\Documents\Github\LLM-portfolio-project`). Next.js 14 / React 18 / TypeScript / SWR (frontend `c:\Users\qaism\OneDrive\Documents\Github\LLM-portfolio-frontend`, app at `frontend/src`).

**Spec:** `docs/superpowers/specs/2026-06-01-ai-stock-profiling-design.md` · **Branch:** `feature/ai-stock-profiling`

---

## Conventions

- **Backend tests:** `pytest tests/ -v -m "not openai and not integration"`. Routes tested with `TestClient` + `DISABLE_AUTH=true`; mock by patching the name as imported into the module (e.g. `app.routes.profiles.execute_sql`). Mock rows expose `._mapping`. Live-OpenAI tests are marked `@pytest.mark.openai`.
- **venv:** `c:\Users\qaism\OneDrive\Documents\Github\LLM-portfolio-project\.venv\Scripts\python.exe` (Python 3.11). Set `PYTHONPATH` to the repo root when running pytest.
- **Frontend:** no JS test runner — verify with `npm run lint` + `npm run build` from `frontend/`.
- **Every commit ends with:** `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`
- **Naming:** table `stock_thesis_profiles`; type `ThesisProfile`; hook `useThesisProfile` (avoids the existing `stock_profile_current` / `useStockProfile`).

## File Structure

**Backend create:** `schema/072_stock_thesis_profiles.sql`, `app/track_record.py`, `app/routes/profiles.py`, `tests/test_track_record.py`, `tests/test_profiles_crud.py`, `tests/test_profiles_queue.py`, `tests/test_profiles_autofill.py`, `tests/test_profiles_interview.py`.
**Backend modify:** `app/main.py` (mount profiles router), `src/analysis/orchestrator.py` (fix 2 bugs).
**Frontend create:** `src/types` additions, `src/app/api/stocks/[ticker]/profile/route.ts` (+ `/revisions`, `/autofill`, `/interview`, `/synthesize`), `src/app/api/profiles/route.ts`, `src/hooks/useThesisProfile.ts`, `src/components/stock/ProfilePanel.tsx`, `src/app/profiles/page.tsx`.
**Frontend modify:** `src/components/stock/StockHubContent.tsx` (add tab), `src/types/api.ts`, `src/hooks/index.ts`.

## Canonical data shapes (referenced by every task)

`stock_thesis_profiles` columns: `id`, `symbol`, `bucket`, `thesis`, `conviction`, `conviction_rationale`, `bull_case`, `bear_case`, `catalysts`(jsonb array), `risks`(jsonb array), `levels`(jsonb `{entry,target,stop}`), `horizon`, `tags`(text[]), `status`, `ai_autofill_json`, `interview_json`, `model_used`, `data_sources`(text[]), `created_at`, `updated_at`, `reviewed_at`.

`ThesisProfile` API model (camelCase): `symbol, bucket, thesis, conviction, convictionRationale, bullCase, bearCase, catalysts, risks, levels, horizon, tags, status, updatedAt, reviewedAt, trackRecord`.

`TrackRecord`: `{symbol, bucket, tradeCount, realizedPnlPct, winRate, avgHoldDays, best, worst, currentQty, currentWeightPct, firstTradeDate, lastTradeDate}`.

---

# Phase 1 — Backend data layer

## Task 1: Migration `schema/072_stock_thesis_profiles.sql`

**Files:** Create `schema/072_stock_thesis_profiles.sql`; Modify the expected-schema list in `scripts/verify_database.py`.

- [ ] **Step 1: Write the migration** (mirrors 062 trigger/RLS + 069 CHECK style)

```sql
-- =======================================================================
-- Migration 072: Stock thesis profiles (AI-co-authored research dossiers)
-- =======================================================================
-- A per-(symbol, bucket) thesis dossier the user builds with AI. `bucket`
-- is the user's chosen strategy LABEL at creation (one of the 5 concrete
-- values — NOT 'all', which is a read-only aggregate view, unlike the
-- 070/071 caches). A surrogate `id` PK keeps the revisions FK simple, with
-- a separate UNIQUE(symbol, bucket) enforcing one profile per pair.

CREATE TABLE IF NOT EXISTS public.stock_thesis_profiles (
    id                    SERIAL PRIMARY KEY,
    symbol                VARCHAR(20) NOT NULL,
    bucket                text NOT NULL
        CHECK (bucket IN ('long_term', 'swing', 'day', 'retirement', 'other')),
    thesis                TEXT,
    conviction            SMALLINT CHECK (conviction BETWEEN 1 AND 5),
    conviction_rationale  TEXT,
    bull_case             TEXT,
    bear_case             TEXT,
    catalysts             JSONB NOT NULL DEFAULT '[]'::jsonb,
    risks                 JSONB NOT NULL DEFAULT '[]'::jsonb,
    levels                JSONB NOT NULL DEFAULT '{}'::jsonb,
    horizon               text,
    tags                  TEXT[] NOT NULL DEFAULT '{}',
    status                text NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft', 'active', 'archived')),
    ai_autofill_json      JSONB,
    interview_json        JSONB,
    model_used            text,
    data_sources          TEXT[] NOT NULL DEFAULT '{}',
    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    reviewed_at           TIMESTAMPTZ,
    CONSTRAINT stock_thesis_profiles_symbol_bucket_key UNIQUE (symbol, bucket)
);

CREATE INDEX IF NOT EXISTS idx_stock_thesis_profiles_symbol
    ON public.stock_thesis_profiles (UPPER(symbol));
CREATE INDEX IF NOT EXISTS idx_stock_thesis_profiles_bucket
    ON public.stock_thesis_profiles (bucket);
CREATE INDEX IF NOT EXISTS idx_stock_thesis_profiles_reviewed_at
    ON public.stock_thesis_profiles (reviewed_at);

CREATE OR REPLACE FUNCTION public.update_stock_thesis_profiles_updated_at()
RETURNS TRIGGER
LANGUAGE plpgsql
SET search_path TO 'public'
AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS stock_thesis_profiles_updated_at ON public.stock_thesis_profiles;
CREATE TRIGGER stock_thesis_profiles_updated_at
    BEFORE UPDATE ON public.stock_thesis_profiles
    FOR EACH ROW
    EXECUTE FUNCTION public.update_stock_thesis_profiles_updated_at();

ALTER TABLE public.stock_thesis_profiles ENABLE ROW LEVEL SECURITY;

-- Revision history: one snapshot appended on every save.
CREATE TABLE IF NOT EXISTS public.stock_thesis_profile_revisions (
    id            SERIAL PRIMARY KEY,
    profile_id    INTEGER NOT NULL
        REFERENCES public.stock_thesis_profiles (id) ON DELETE CASCADE,
    symbol        VARCHAR(20) NOT NULL,
    bucket        text NOT NULL,
    snapshot_json JSONB NOT NULL,
    conviction    SMALLINT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_stock_thesis_profile_revisions_profile
    ON public.stock_thesis_profile_revisions (profile_id, created_at DESC);

ALTER TABLE public.stock_thesis_profile_revisions ENABLE ROW LEVEL SECURITY;

INSERT INTO public.schema_migrations (version, description)
VALUES ('072_stock_thesis_profiles', 'AI-co-authored per-(symbol,bucket) thesis profiles + revisions')
ON CONFLICT (version) DO NOTHING;
```

- [ ] **Step 2: Register the two tables in the verifier's expected schema**

Open `scripts/verify_database.py`, find the EXPECTED_SCHEMAS dict (the structure mapping table name → columns; grep for an existing entry like `"stock_notes"`). Add entries for `stock_thesis_profiles` and `stock_thesis_profile_revisions` mirroring the column lists above, matching the exact format of the neighbouring entries. (If entries are just table-name keys with a column list, add the two keys with their column names.)

- [ ] **Step 3: Apply + verify the migration**

Run (PowerShell, venv active):
```
& .venv\Scripts\python.exe scripts/deploy_database.py
& .venv\Scripts\python.exe scripts/verify_database.py --verbose
```
Expected: `072_stock_thesis_profiles` applied; verify reports both tables exist, no missing tables.

- [ ] **Step 4: Commit**
```bash
git add schema/072_stock_thesis_profiles.sql scripts/verify_database.py
git commit -m "feat(schema): 072 stock_thesis_profiles + revisions tables

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: `compute_stock_track_record` (`app/track_record.py`)

Reuses the importable `_merge_and_dedup` and `_compute_historical_basis` from `app/routes/trades.py` (same app layer — no `src → app` dependency), then adds aggregate math that does not exist anywhere yet.

**Files:** Create `app/track_record.py`; Test `tests/test_track_record.py`.

- [ ] **Step 1: Write the failing test**

```python
from datetime import datetime
from unittest.mock import patch, MagicMock

import pytest


def _row(d):
    r = MagicMock()
    r._mapping = d
    return r


@patch("app.track_record.execute_sql")
def test_track_record_realized_and_winrate(mock_sql):
    # One symbol: BUY 10 @100, SELL 10 @120 (closed, +20%). Then a position row.
    activities = [
        _row({"id": "a1", "symbol": "AAPL", "side": "BUY", "price": 100.0, "units": 10,
              "amount": 1000.0, "fee": 0.0, "executed_at": datetime(2026, 1, 2), "description": None}),
        _row({"id": "a2", "symbol": "AAPL", "side": "SELL", "price": 120.0, "units": 10,
              "amount": 1200.0, "fee": 0.0, "executed_at": datetime(2026, 2, 1), "description": None}),
    ]
    positions = []  # nothing held now
    all_positions = []
    mock_sql.side_effect = [activities, [], positions, all_positions]

    from app.track_record import compute_stock_track_record
    tr = compute_stock_track_record("AAPL", None)

    assert tr["symbol"] == "AAPL"
    assert tr["tradeCount"] == 2
    assert tr["winRate"] == 100.0          # the single closed SELL was profitable
    assert round(tr["realizedPnlPct"], 1) == 20.0
    assert tr["avgHoldDays"] == 30          # Jan 2 -> Feb 1
    assert tr["currentQty"] == 0.0


@patch("app.track_record.execute_sql")
def test_track_record_empty(mock_sql):
    mock_sql.side_effect = [[], [], [], []]
    from app.track_record import compute_stock_track_record
    tr = compute_stock_track_record("ZZZZ", None)
    assert tr["tradeCount"] == 0
    assert tr["realizedPnlPct"] == 0.0
    assert tr["winRate"] == 0.0
```

- [ ] **Step 2: Run → fail**

Run: `pytest tests/test_track_record.py -v` → FAIL (`No module named 'app.track_record'`).

- [ ] **Step 3: Implement `app/track_record.py`**

```python
"""Per-(symbol, bucket) actual-trade track record.

Reuses the trade-assembly helpers in app.routes.trades (merge/dedup +
historical-basis walk) and adds aggregate metrics (win rate, avg hold,
realized return, current position). Bucket is attributed via the live
accounts.bucket join; orphan account_ids fold into 'other' via COALESCE.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.routes.trades import _compute_historical_basis, _merge_and_dedup, _row_to_dict
from src.db import execute_sql

_HIST_LIMIT = 5000


def _parse_dt(v: Any) -> datetime | None:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None


def compute_stock_track_record(symbol: str, bucket: str | None) -> dict[str, Any]:
    """Aggregate realized-trade metrics for one symbol, optionally bucket-scoped.

    `bucket` must already be validated (output of validate_bucket) or None.
    """
    sym = symbol.strip().upper()
    # COALESCE keeps orphan account_id rows under 'other'; bucket_filter_sql's
    # plain clause would exclude them. We inline the COALESCE form here.
    if bucket:
        bclause = " AND COALESCE(acc.bucket, 'other') = :bucket "
        bparams = {"bucket": bucket}
    else:
        bclause, bparams = "", {}

    activities = execute_sql(
        f"""
        SELECT a.id, a.symbol, UPPER(a.activity_type) AS side, a.price, a.units,
               COALESCE(a.amount, 0) AS amount, COALESCE(a.fee, 0) AS fee,
               a.trade_date AS executed_at, a.description
        FROM activities a
        LEFT JOIN accounts acc ON acc.id = a.account_id
        WHERE UPPER(a.symbol) = :symbol
          AND COALESCE(acc.connection_status, 'connected') != 'deleted'
          {bclause}
        ORDER BY a.trade_date DESC
        LIMIT :lim
        """,
        params={"symbol": sym, "lim": _HIST_LIMIT, **bparams},
        fetch_results=True,
    ) or []
    orders = execute_sql(
        f"""
        SELECT o.brokerage_order_id AS id, o.symbol, UPPER(o.action) AS side,
               o.execution_price AS price, o.filled_quantity AS units,
               COALESCE(o.execution_price * o.filled_quantity, 0) AS amount,
               0 AS fee, o.time_executed AS executed_at, NULL AS description
        FROM orders o
        LEFT JOIN accounts acc ON acc.id = o.account_id
        WHERE UPPER(o.symbol) = :symbol
          AND o.status IN ('EXECUTED', 'FILLED') AND o.time_executed IS NOT NULL
          AND COALESCE(acc.connection_status, 'connected') != 'deleted'
          {bclause}
        ORDER BY o.time_executed DESC
        LIMIT :lim
        """,
        params={"symbol": sym, "lim": _HIST_LIMIT, **bparams},
        fetch_results=True,
    ) or []

    acts = [{**_row_to_dict(r), "source": "activity"} for r in activities]
    ords = [{**_row_to_dict(r), "source": "order"} for r in orders]
    merged = _merge_and_dedup(acts, ords)
    _compute_historical_basis(merged)

    # Aggregate realized P/L over SELLs that have a basis.
    realized_pcts: list[float] = []
    wins = 0
    holds: list[int] = []
    # Track first BUY date per running lot for avg-hold (approximate: earliest buy
    # before each sell). Simple approach: pair each SELL with the earliest BUY date.
    buy_dates = sorted(
        _parse_dt(t.get("executed_at"))
        for t in merged
        if (t.get("side") or "").upper() == "BUY" and _parse_dt(t.get("executed_at"))
    )
    first_buy = buy_dates[0] if buy_dates else None

    for t in merged:
        side = (t.get("side") or "").upper()
        basis = t.get("basis_at_trade")
        price = t.get("price")
        if side == "SELL" and basis and price and basis > 0:
            ratio = price / basis
            if 0.1 <= ratio <= 10:  # same split guardrail as _enrich_trade
                pct = (price - basis) / basis * 100
                realized_pcts.append(pct)
                if pct >= 0:
                    wins += 1
                sell_dt = _parse_dt(t.get("executed_at"))
                if sell_dt and first_buy:
                    holds.append((sell_dt - first_buy).days)

    dates = [d for d in (_parse_dt(t.get("executed_at")) for t in merged) if d]
    realized_pnl_pct = round(sum(realized_pcts) / len(realized_pcts), 2) if realized_pcts else 0.0
    win_rate = round(wins / len(realized_pcts) * 100, 1) if realized_pcts else 0.0

    # Current position (bucket-scoped), for currentQty + weight.
    pos = execute_sql(
        f"""
        SELECT SUM(p.quantity) AS qty,
               SUM(p.quantity * COALESCE(p.current_price, p.price)) AS value
        FROM positions p
        LEFT JOIN accounts acc ON acc.id = p.account_id
        WHERE UPPER(p.symbol) = :symbol AND p.quantity > 0
          AND COALESCE(acc.connection_status, 'connected') != 'deleted'
          {bclause}
        """,
        params={"symbol": sym, **bparams},
        fetch_results=True,
    ) or []
    total = execute_sql(
        f"""
        SELECT SUM(p.quantity * COALESCE(p.current_price, p.price)) AS total
        FROM positions p
        LEFT JOIN accounts acc ON acc.id = p.account_id
        WHERE p.quantity > 0
          AND COALESCE(acc.connection_status, 'connected') != 'deleted'
          {bclause}
        """,
        params=bparams or None,
        fetch_results=True,
    ) or []

    pos_d = _row_to_dict(pos[0]) if pos else {}
    cur_qty = float(pos_d.get("qty") or 0)
    cur_value = float(pos_d.get("value") or 0)
    total_value = float(_row_to_dict(total[0]).get("total") or 0) if total else 0.0
    weight = round(cur_value / total_value * 100, 2) if total_value > 0 else 0.0

    return {
        "symbol": sym,
        "bucket": bucket or "all",
        "tradeCount": len(merged),
        "realizedPnlPct": realized_pnl_pct,
        "winRate": win_rate,
        "avgHoldDays": round(sum(holds) / len(holds)) if holds else 0,
        "best": round(max(realized_pcts), 2) if realized_pcts else 0.0,
        "worst": round(min(realized_pcts), 2) if realized_pcts else 0.0,
        "currentQty": cur_qty,
        "currentWeightPct": weight,
        "firstTradeDate": min(dates).isoformat() if dates else None,
        "lastTradeDate": max(dates).isoformat() if dates else None,
    }
```

> Note: this helper inlines the `COALESCE(acc.bucket,'other')` filter (rather than
> `bucket_filter_sql`'s plain `acc.bucket = :bucket`) so orphan account_ids fold
> into `other` — the spec's requirement.

- [ ] **Step 4: Run → pass**

Run: `pytest tests/test_track_record.py -v` → PASS (2 passed). Then `ruff check app/track_record.py tests/test_track_record.py`.

- [ ] **Step 5: Commit**
```bash
git add app/track_record.py tests/test_track_record.py
git commit -m "feat(profiles): compute_stock_track_record aggregate metrics

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

# Phase 2 — Fix the two pre-existing bugs (spec requirement)

## Task 3: Fix the orchestrator's discord_parsed_ideas query

The query at `src/analysis/orchestrator.py` ~lines 182–209 selects `ticker`, `created_at`, `author` from `discord_parsed_ideas` — none exist (the table has `primary_symbol`, `parsed_at`, `author_id`; author/created_at live on `discord_messages`). It's wrapped in try/except so it silently yields zero ideas. Repoint it to the working `chat.py` pattern.

**Files:** Modify `src/analysis/orchestrator.py`. Test `tests/test_orchestrator_ideas_query.py`.

- [ ] **Step 1: Write the failing test** (asserts the query references the real columns)

```python
def test_orchestrator_ideas_query_uses_real_columns():
    import inspect
    import src.analysis.orchestrator as orch
    src = inspect.getsource(orch)
    # The fixed query must use primary_symbol and join discord_messages,
    # and must NOT select the non-existent `ticker` column from dpi.
    assert "dpi.primary_symbol" in src
    assert "LEFT JOIN discord_messages" in src
    assert "UPPER(ticker)" not in src
```

- [ ] **Step 2: Run → fail**

Run: `pytest tests/test_orchestrator_ideas_query.py -v` → FAIL (`UPPER(ticker)` still present).

- [ ] **Step 3: Replace the query** — change the block (orchestrator.py ~182–209) to:

```python
    # 4. Discord parsed ideas (primary_symbol + join for author/date — the
    #    discord_parsed_ideas table has no ticker/created_at/author columns).
    try:
        idea_rows = execute_sql(
            """
            SELECT dpi.direction, dpi.confidence, dpi.labels, dpi.idea_text,
                   dm.created_at, dm.author
            FROM discord_parsed_ideas dpi
            LEFT JOIN discord_messages dm ON dpi.message_id::text = dm.message_id
            WHERE UPPER(dpi.primary_symbol) = :ticker
              AND dm.created_at > NOW() - INTERVAL '30 days'
            ORDER BY dm.created_at DESC
            LIMIT 50
            """,
            params={"ticker": ticker_upper},
            fetch_results=True,
        )
```

(Keep the rest of that block — the loop that consumes `idea_rows` — unchanged; field names `direction`, `confidence`, `labels`, `idea_text`, `created_at`, `author` are preserved.)

- [ ] **Step 4: Run → pass**, then run the existing analysis tests to confirm no regression:

```
pytest tests/test_orchestrator_ideas_query.py tests/test_analysis_orchestrator.py -v -m "not openai and not integration"
```
Expected: pass.

- [ ] **Step 5: Commit**
```bash
git add src/analysis/orchestrator.py tests/test_orchestrator_ideas_query.py
git commit -m "fix(analysis): orchestrator ideas query uses real columns (primary_symbol + join)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

## Task 4: Fix `SUM(total_value) FROM account_balances`

`account_balances` has no `total_value` column (only `cash`, `buying_power`); the orchestrator's portfolio-total query silently falls back to 0. Replace it with an equity-based total from `positions` (the same basis the rest of the risk path uses).

**Files:** Modify `src/analysis/orchestrator.py`. Test `tests/test_orchestrator_total_value.py`.

- [ ] **Step 1: Write the failing test**
```python
def test_orchestrator_does_not_select_total_value_from_balances():
    import inspect
    import src.analysis.orchestrator as orch
    src = inspect.getsource(orch)
    assert "SUM(total_value) FROM account_balances" not in src.replace("\n", " ")
    assert "total_value" not in src or "account_balances" not in src.split("total_value")[0][-80:]
```

- [ ] **Step 2: Run → fail.** Then locate the `SELECT SUM(total_value) FROM account_balances ...` (grep `total_value`) and replace it with a positions-equity total, e.g.:

```python
        total_row = execute_sql(
            f"""
            SELECT COALESCE(SUM(p.quantity * COALESCE(p.current_price, p.price)), 0) AS total
            FROM positions p
            LEFT JOIN accounts acc ON acc.id = p.account_id
            WHERE p.quantity > 0
              AND COALESCE(acc.connection_status, 'connected') != 'deleted'
              {bucket_clause}
            """,
            params=bucket_params or None,
            fetch_results=True,
        )
        total_value = float(_row_to_dict(total_row[0]).get("total") or 0) if total_row else 0.0
```

Match the surrounding variable names actually used in that function (it already computes `bucket_clause`/`bucket_params` and `total_market_value`; if `total_value` was only used to scale VaR$, set it from the positions total above). Confirm by reading the function.

- [ ] **Step 3: Run → pass**, then `pytest tests/ -m "not openai and not integration" -q` to confirm no regression.

- [ ] **Step 4: Commit**
```bash
git add src/analysis/orchestrator.py tests/test_orchestrator_total_value.py
git commit -m "fix(analysis): portfolio total from positions equity (account_balances has no total_value)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

# Phase 3 — Backend profiles route (`app/routes/profiles.py`)

Root-mounted (no prefix), registered AFTER `stocks.py`. All endpoints take `bucket` via `BucketQuery` and `validate_bucket`. Deterministic advisory lock keyed on `(symbol, bucket)` using `hashlib` (NOT Python `hash()`).

## Task 5: Profile CRUD + revisions + router mount

**Files:** Create `app/routes/profiles.py`; Modify `app/main.py`. Test `tests/test_profiles_crud.py`.

- [ ] **Step 1: Write the failing test**
```python
from unittest.mock import MagicMock, patch
import pytest


@pytest.fixture
def client():
    with patch.dict("os.environ", {"DISABLE_AUTH": "true"}):
        from fastapi.testclient import TestClient
        from app.main import app
        with TestClient(app) as c:
            yield c


def _row(d):
    r = MagicMock(); r._mapping = d; return r


@patch("app.routes.profiles.compute_stock_track_record")
@patch("app.routes.profiles.execute_sql")
def test_get_profile_found(mock_sql, mock_tr, client):
    mock_sql.return_value = [_row({
        "symbol": "AAPL", "bucket": "long_term", "thesis": "quality compounder",
        "conviction": 4, "conviction_rationale": None, "bull_case": None, "bear_case": None,
        "catalysts": [], "risks": [], "levels": {}, "horizon": "long_term",
        "tags": ["core"], "status": "active", "updated_at": "2026-06-01T00:00:00+00:00",
        "reviewed_at": "2026-06-01T00:00:00+00:00",
    })]
    mock_tr.return_value = {"symbol": "AAPL", "bucket": "long_term", "tradeCount": 3}
    r = client.get("/stocks/AAPL/profile?bucket=long_term")
    assert r.status_code == 200
    data = r.json()
    assert data["symbol"] == "AAPL"
    assert data["conviction"] == 4
    assert data["trackRecord"]["tradeCount"] == 3


@patch("app.routes.profiles.execute_sql")
def test_get_profile_missing_returns_404(mock_sql, client):
    mock_sql.return_value = []
    r = client.get("/stocks/ZZZZ/profile?bucket=swing")
    assert r.status_code == 404


def test_put_profile_requires_concrete_bucket(client):
    r = client.put("/stocks/AAPL/profile", json={"thesis": "x"})  # no bucket
    assert r.status_code == 400
```

- [ ] **Step 2: Run → fail** (`pytest tests/test_profiles_crud.py -v` → 404 route missing / import error).

- [ ] **Step 3: Implement `app/routes/profiles.py`** (CRUD + revision append; queue/autofill/interview/synthesize added in later tasks — define the router + models here)

```python
"""Stock thesis profile API (AI-co-authored per-(symbol, bucket) dossiers).

Root-mounted router. Endpoints:
- GET    /stocks/{ticker}/profile            fetch a profile (+ track record)
- PUT    /stocks/{ticker}/profile            save/update (append revision)
- DELETE /stocks/{ticker}/profile            archive
- GET    /stocks/{ticker}/profile/revisions  saved-snapshot history
- GET    /profiles                           list / prioritized queue
- POST   /stocks/{ticker}/profile/autofill   assemble data sections
- POST   /stocks/{ticker}/profile/interview  tailored questions (+ follow-ups)
- POST   /stocks/{ticker}/profile/synthesize merge answers+data -> draft thesis
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from typing import Any

from fastapi import APIRouter, HTTPException, Path, Query
from pydantic import BaseModel
from sqlalchemy import text

from app.track_record import compute_stock_track_record
from src.bucket import BucketQuery, validate_bucket
from src.db import execute_sql, transaction

logger = logging.getLogger(__name__)
router = APIRouter()


def _lock_key(symbol: str, bucket: str) -> int:
    digest = hashlib.sha256(f"{symbol}:{bucket}".encode()).digest()
    return int.from_bytes(digest[:8], "big") & 0x7FFFFFFFFFFFFFFF


def _require_concrete_bucket(bucket: str | None) -> str:
    b = validate_bucket(bucket)
    if not b:
        raise HTTPException(
            status_code=400,
            detail="A concrete bucket is required to write a profile (not 'all').",
        )
    return b


class ProfileBody(BaseModel):
    thesis: str | None = None
    conviction: int | None = None
    convictionRationale: str | None = None
    bullCase: str | None = None
    bearCase: str | None = None
    catalysts: list[dict] = []
    risks: list[dict] = []
    levels: dict = {}
    horizon: str | None = None
    tags: list[str] = []
    status: str = "active"
    aiAutofillJson: dict | None = None
    interviewJson: dict | None = None
    modelUsed: str | None = None
    dataSources: list[str] = []


class ThesisProfile(BaseModel):
    symbol: str
    bucket: str
    thesis: str | None = None
    conviction: int | None = None
    convictionRationale: str | None = None
    bullCase: str | None = None
    bearCase: str | None = None
    catalysts: list[dict] = []
    risks: list[dict] = []
    levels: dict = {}
    horizon: str | None = None
    tags: list[str] = []
    status: str = "draft"
    updatedAt: str | None = None
    reviewedAt: str | None = None
    trackRecord: dict | None = None


def _row_to_profile(rd: dict, track_record: dict | None) -> ThesisProfile:
    return ThesisProfile(
        symbol=rd["symbol"], bucket=rd["bucket"], thesis=rd.get("thesis"),
        conviction=rd.get("conviction"), convictionRationale=rd.get("conviction_rationale"),
        bullCase=rd.get("bull_case"), bearCase=rd.get("bear_case"),
        catalysts=rd.get("catalysts") or [], risks=rd.get("risks") or [],
        levels=rd.get("levels") or {}, horizon=rd.get("horizon"),
        tags=list(rd.get("tags") or []), status=rd.get("status") or "draft",
        updatedAt=str(rd["updated_at"]) if rd.get("updated_at") else None,
        reviewedAt=str(rd["reviewed_at"]) if rd.get("reviewed_at") else None,
        trackRecord=track_record,
    )


def _fetch_profile_row(symbol: str, bucket: str) -> dict | None:
    rows = execute_sql(
        """
        SELECT symbol, bucket, thesis, conviction, conviction_rationale, bull_case,
               bear_case, catalysts, risks, levels, horizon, tags, status,
               updated_at, reviewed_at
        FROM stock_thesis_profiles
        WHERE UPPER(symbol) = :symbol AND bucket = :bucket
        """,
        params={"symbol": symbol.upper(), "bucket": bucket},
        fetch_results=True,
    ) or []
    if not rows:
        return None
    return dict(rows[0]._mapping) if hasattr(rows[0], "_mapping") else dict(rows[0])


@router.get("/stocks/{ticker}/profile", response_model=ThesisProfile)
async def get_profile(
    ticker: str = Path(...),
    bucket: str | None = BucketQuery,
):
    b = _require_concrete_bucket(bucket)
    rd = _fetch_profile_row(ticker, b)
    if rd is None:
        raise HTTPException(status_code=404, detail="No profile for this (symbol, bucket)")
    tr = compute_stock_track_record(ticker, b)
    return _row_to_profile(rd, tr)


@router.put("/stocks/{ticker}/profile", response_model=ThesisProfile)
async def put_profile(
    ticker: str = Path(...),
    body: ProfileBody = ...,  # noqa: B008
    bucket: str | None = BucketQuery,
):
    b = _require_concrete_bucket(bucket)
    symbol = ticker.upper()
    lock = _lock_key(symbol, b)
    params = {
        "symbol": symbol, "bucket": b, "thesis": body.thesis,
        "conviction": body.conviction, "conviction_rationale": body.convictionRationale,
        "bull_case": body.bullCase, "bear_case": body.bearCase,
        "catalysts": json.dumps(body.catalysts), "risks": json.dumps(body.risks),
        "levels": json.dumps(body.levels), "horizon": body.horizon,
        "tags": body.tags or [], "status": body.status,
        "ai_autofill_json": json.dumps(body.aiAutofillJson) if body.aiAutofillJson else None,
        "interview_json": json.dumps(body.interviewJson) if body.interviewJson else None,
        "model_used": body.modelUsed, "data_sources": body.dataSources or [],
    }
    with transaction() as conn:
        conn.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": lock})
        row = conn.execute(
            text(
                """
                INSERT INTO stock_thesis_profiles
                    (symbol, bucket, thesis, conviction, conviction_rationale, bull_case,
                     bear_case, catalysts, risks, levels, horizon, tags, status,
                     ai_autofill_json, interview_json, model_used, data_sources, reviewed_at)
                VALUES
                    (:symbol, :bucket, :thesis, :conviction, :conviction_rationale, :bull_case,
                     :bear_case, CAST(:catalysts AS jsonb), CAST(:risks AS jsonb),
                     CAST(:levels AS jsonb), :horizon, :tags, :status,
                     CAST(:ai_autofill_json AS jsonb), CAST(:interview_json AS jsonb),
                     :model_used, :data_sources, NOW())
                ON CONFLICT (symbol, bucket) DO UPDATE SET
                    thesis = EXCLUDED.thesis, conviction = EXCLUDED.conviction,
                    conviction_rationale = EXCLUDED.conviction_rationale,
                    bull_case = EXCLUDED.bull_case, bear_case = EXCLUDED.bear_case,
                    catalysts = EXCLUDED.catalysts, risks = EXCLUDED.risks,
                    levels = EXCLUDED.levels, horizon = EXCLUDED.horizon,
                    tags = EXCLUDED.tags, status = EXCLUDED.status,
                    ai_autofill_json = EXCLUDED.ai_autofill_json,
                    interview_json = EXCLUDED.interview_json,
                    model_used = EXCLUDED.model_used, data_sources = EXCLUDED.data_sources,
                    reviewed_at = NOW()
                RETURNING id
                """
            ),
            params,
        )
        profile_id = row.fetchone()[0]
        # Append a revision snapshot of the saved state.
        conn.execute(
            text(
                """
                INSERT INTO stock_thesis_profile_revisions
                    (profile_id, symbol, bucket, snapshot_json, conviction)
                VALUES (:pid, :symbol, :bucket, CAST(:snap AS jsonb), :conviction)
                """
            ),
            {"pid": profile_id, "symbol": symbol, "bucket": b,
             "snap": body.model_dump_json(), "conviction": body.conviction},
        )
    rd = _fetch_profile_row(symbol, b)
    return _row_to_profile(rd or {}, None)


@router.delete("/stocks/{ticker}/profile")
async def delete_profile(
    ticker: str = Path(...),
    bucket: str | None = BucketQuery,
):
    b = _require_concrete_bucket(bucket)
    execute_sql(
        "UPDATE stock_thesis_profiles SET status = 'archived' "
        "WHERE UPPER(symbol) = :symbol AND bucket = :bucket",
        params={"symbol": ticker.upper(), "bucket": b},
    )
    return {"status": "archived", "symbol": ticker.upper(), "bucket": b}


@router.get("/stocks/{ticker}/profile/revisions")
async def get_revisions(
    ticker: str = Path(...),
    bucket: str | None = BucketQuery,
):
    b = _require_concrete_bucket(bucket)
    rows = execute_sql(
        """
        SELECT r.snapshot_json, r.conviction, r.created_at
        FROM stock_thesis_profile_revisions r
        WHERE UPPER(r.symbol) = :symbol AND r.bucket = :bucket
        ORDER BY r.created_at DESC LIMIT 100
        """,
        params={"symbol": ticker.upper(), "bucket": b},
        fetch_results=True,
    ) or []
    out = []
    for row in rows:
        rd = dict(row._mapping) if hasattr(row, "_mapping") else dict(row)
        out.append({
            "snapshot": rd.get("snapshot_json"),
            "conviction": rd.get("conviction"),
            "createdAt": str(rd["created_at"]) if rd.get("created_at") else None,
        })
    return {"symbol": ticker.upper(), "bucket": b, "revisions": out}
```

- [ ] **Step 4: Mount the router in `app/main.py`** — add `profiles` to the route import block and add this include AFTER the `stocks.router` include (so `/stocks/{ticker}/profile` resolves before the `/{ticker}` catch-all is irrelevant — both are distinct, but register after stocks for clarity), root-mounted like `trades`:

```python
app.include_router(
    profiles.router,
    tags=["Profiles"],
    dependencies=[Depends(require_api_key)],
)
```
(Add `profiles` to `from app.routes import (...)`.)

- [ ] **Step 5: Run → pass.** `pytest tests/test_profiles_crud.py -v` → 3 passed. Then `ruff check app/routes/profiles.py`.

- [ ] **Step 6: Commit**
```bash
git add app/routes/profiles.py app/main.py tests/test_profiles_crud.py
git commit -m "feat(profiles): CRUD + revision history + router mount

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: Prioritized review queue (`GET /profiles`)

**Files:** Modify `app/routes/profiles.py`. Test `tests/test_profiles_queue.py`.

- [ ] **Step 1: Write the failing test**
```python
from unittest.mock import MagicMock, patch
import pytest


@pytest.fixture
def client():
    with patch.dict("os.environ", {"DISABLE_AUTH": "true"}):
        from fastapi.testclient import TestClient
        from app.main import app
        with TestClient(app) as c:
            yield c


def _row(d):
    r = MagicMock(); r._mapping = d; return r


@patch("app.routes.profiles.execute_sql")
def test_queue_orders_no_profile_first(mock_sql, client):
    # Query returns (symbol,bucket,has_profile,reviewed_at,changed) rows.
    mock_sql.return_value = [
        _row({"symbol": "NVDA", "bucket": "long_term", "has_profile": False,
              "reviewed_at": None, "stale": False, "changed": False}),
        _row({"symbol": "AAPL", "bucket": "long_term", "has_profile": True,
              "reviewed_at": "2020-01-01T00:00:00+00:00", "stale": True, "changed": False}),
    ]
    r = client.get("/profiles?queue=1&bucket=long_term")
    assert r.status_code == 200
    items = r.json()["queue"]
    assert items[0]["symbol"] == "NVDA"        # no-profile first
    assert items[0]["reason"] == "no_profile"
    assert items[1]["reason"] == "stale"
```

- [ ] **Step 2: Run → fail.**

- [ ] **Step 3: Implement** — add to `profiles.py`:

```python
PROFILE_STALE_DAYS = int(os.getenv("PROFILE_STALE_DAYS", "90"))


@router.get("/profiles")
async def list_profiles(
    bucket: str | None = BucketQuery,
    queue: int = Query(0, description="1 = return the prioritized review queue"),
):
    b = validate_bucket(bucket)  # may be None ('all' view)
    bclause = " AND COALESCE(acc.bucket, 'other') = :bucket " if b else ""
    bparams = {"bucket": b} if b else {}

    if not queue:
        rows = execute_sql(
            """
            SELECT symbol, bucket, conviction, status, updated_at, reviewed_at
            FROM stock_thesis_profiles
            WHERE status != 'archived'
            ORDER BY updated_at DESC
            """,
            fetch_results=True,
        ) or []
        return {"profiles": [
            {**(dict(r._mapping) if hasattr(r, "_mapping") else dict(r)),
             "updated_at": str((dict(r._mapping) if hasattr(r, "_mapping") else dict(r)).get("updated_at"))}
            for r in rows
        ]}

    # Queue: held (symbol, bucket) pairs LEFT JOIN profiles, prioritized.
    rows = execute_sql(
        f"""
        WITH held AS (
            SELECT UPPER(p.symbol) AS symbol, COALESCE(acc.bucket, 'other') AS bucket
            FROM positions p
            LEFT JOIN accounts acc ON acc.id = p.account_id
            WHERE p.quantity > 0
              AND COALESCE(acc.connection_status, 'connected') != 'deleted'
              {bclause}
            GROUP BY UPPER(p.symbol), COALESCE(acc.bucket, 'other')
        )
        SELECT h.symbol, h.bucket,
               (tp.id IS NOT NULL) AS has_profile,
               tp.reviewed_at,
               (tp.reviewed_at IS NOT NULL
                  AND tp.reviewed_at < NOW() - (:stale_days || ' days')::interval) AS stale,
               EXISTS (
                   SELECT 1 FROM activities a
                   LEFT JOIN accounts acc2 ON acc2.id = a.account_id
                   WHERE UPPER(a.symbol) = h.symbol
                     AND COALESCE(acc2.bucket, 'other') = h.bucket
                     AND (tp.reviewed_at IS NULL OR a.trade_date > tp.reviewed_at)
               ) AS changed
        FROM held h
        LEFT JOIN stock_thesis_profiles tp
          ON UPPER(tp.symbol) = h.symbol AND tp.bucket = h.bucket
          AND tp.status != 'archived'
        """,
        params={"stale_days": PROFILE_STALE_DAYS, **bparams},
        fetch_results=True,
    ) or []

    def _reason(rd: dict) -> str:
        if not rd.get("has_profile"):
            return "no_profile"
        if rd.get("stale"):
            return "stale"
        if rd.get("changed"):
            return "changed"
        return "ok"

    _rank = {"no_profile": 0, "stale": 1, "changed": 2, "ok": 3}
    items = []
    for r in rows:
        rd = dict(r._mapping) if hasattr(r, "_mapping") else dict(r)
        items.append({"symbol": rd["symbol"], "bucket": rd["bucket"],
                      "hasProfile": bool(rd.get("has_profile")), "reason": _reason(rd)})
    items.sort(key=lambda it: _rank[it["reason"]])
    return {"queue": items}
```

- [ ] **Step 4: Run → pass.** `pytest tests/test_profiles_queue.py -v`; `ruff check app/routes/profiles.py`.

- [ ] **Step 5: Commit**
```bash
git add app/routes/profiles.py tests/test_profiles_queue.py
git commit -m "feat(profiles): prioritized review queue (no-profile -> stale -> changed)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: Autofill (`POST /stocks/{ticker}/profile/autofill`)

Assembles data sections (no thesis): track record, news catalysts, 5-agent consensus, risk, ideas digest. Never raises — degrades to partial.

**Files:** Modify `app/routes/profiles.py`. Test `tests/test_profiles_autofill.py`.

- [ ] **Step 1: Write the failing test**
```python
from unittest.mock import AsyncMock, MagicMock, patch
import pytest


@pytest.fixture
def client():
    with patch.dict("os.environ", {"DISABLE_AUTH": "true"}):
        from fastapi.testclient import TestClient
        from app.main import app
        with TestClient(app) as c:
            yield c


@patch("app.routes.profiles.get_stock_analysis", new_callable=AsyncMock)
@patch("app.routes.profiles.get_company_news")
@patch("app.routes.profiles.compute_stock_track_record")
@patch("app.routes.profiles.execute_sql")
def test_autofill_assembles_sections(mock_sql, mock_tr, mock_news, mock_analysis, client):
    mock_tr.return_value = {"symbol": "AAPL", "tradeCount": 5, "realizedPnlPct": 12.0}
    mock_news.return_value = [{"date": "2026-05-01", "title": "Apple WWDC", "url": "u", "source": "s", "text": ""}]
    mock_analysis.return_value = {"overall_signal": "buy", "overall_confidence": 0.62, "summary": "..."}
    mock_sql.return_value = []  # ideas digest empty
    r = client.post("/stocks/AAPL/profile/autofill?bucket=long_term")
    assert r.status_code == 200
    data = r.json()
    assert data["trackRecord"]["tradeCount"] == 5
    assert data["catalysts"][0]["title"] == "Apple WWDC"
    assert data["consensus"]["overall_signal"] == "buy"
    mock_analysis.assert_awaited_once()
```

- [ ] **Step 2: Run → fail.**

- [ ] **Step 3: Implement** — add imports + endpoint to `profiles.py`:

```python
# add near the other imports
from src.analysis.orchestrator import get_stock_analysis
from src.openbb_service import get_company_news


def _ideas_digest(symbol: str) -> list[dict]:
    rows = execute_sql(
        """
        SELECT dpi.direction, dpi.labels, dpi.idea_text, dm.created_at, dm.author
        FROM discord_parsed_ideas dpi
        LEFT JOIN discord_messages dm ON dpi.message_id::text = dm.message_id
        WHERE UPPER(dpi.primary_symbol) = :symbol
        ORDER BY dm.created_at DESC NULLS LAST
        LIMIT 10
        """,
        params={"symbol": symbol.upper()},
        fetch_results=True,
    ) or []
    out = []
    for r in rows:
        rd = dict(r._mapping) if hasattr(r, "_mapping") else dict(r)
        out.append({
            "direction": rd.get("direction"),
            "labels": list(rd.get("labels") or []),
            "text": (rd.get("idea_text") or "")[:200],
            "author": rd.get("author"),
        })
    return out


@router.post("/stocks/{ticker}/profile/autofill")
async def autofill_profile(
    ticker: str = Path(...),
    bucket: str | None = BucketQuery,
):
    b = _require_concrete_bucket(bucket)
    symbol = ticker.upper()
    sources: list[str] = []

    try:
        track_record = compute_stock_track_record(symbol, b)
        sources.append("trades")
    except Exception as e:  # noqa: BLE001
        logger.warning("autofill track record failed for %s: %s", symbol, e)
        track_record = None

    catalysts: list[dict] = []
    try:
        news = get_company_news(symbol, limit=8) or []
        catalysts = [{"title": n.get("title"), "date": n.get("date"),
                      "source": n.get("source"), "url": n.get("url")} for n in news]
        if catalysts:
            sources.append("news")
    except Exception as e:  # noqa: BLE001
        logger.warning("autofill news failed for %s: %s", symbol, e)

    consensus: dict | None = None
    try:
        # refresh=False tolerates stale; cold cache runs the full pipeline.
        consensus = await get_stock_analysis(symbol, refresh=False, bucket=b)
        sources.append("analysis")
    except Exception as e:  # noqa: BLE001
        logger.warning("autofill analysis failed for %s: %s", symbol, e)

    ideas = _ideas_digest(symbol)
    if ideas:
        sources.append("ideas")

    return {
        "symbol": symbol, "bucket": b,
        "trackRecord": track_record,
        "catalysts": catalysts,
        "consensus": consensus,
        "ideas": ideas,
        "dataSources": sources,
    }
```

- [ ] **Step 4: Run → pass.** `pytest tests/test_profiles_autofill.py -v`; `ruff check app/routes/profiles.py`.

- [ ] **Step 5: Commit**
```bash
git add app/routes/profiles.py tests/test_profiles_autofill.py
git commit -m "feat(profiles): autofill assembles track record + news + consensus + ideas

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 8: Adaptive interview (`POST /stocks/{ticker}/profile/interview`)

One LLM call generates 3–5 tailored questions; the adaptive sub-mode (given prior answers + track record) returns 0–2 follow-ups. Mirrors the `ideas.py` JSON-output + `_strip_fences` pattern. Model from `OPENAI_MODEL_PROFILE_LIGHT` (default `gpt-5-mini`, fallback `gpt-4o-mini`).

**Files:** Modify `app/routes/profiles.py`. Test `tests/test_profiles_interview.py`.

- [ ] **Step 1: Write the failing test** (mock OpenAI)
```python
import json
from unittest.mock import MagicMock, patch
import pytest


@pytest.fixture
def client():
    with patch.dict("os.environ", {"DISABLE_AUTH": "true"}):
        from fastapi.testclient import TestClient
        from app.main import app
        with TestClient(app) as c:
            yield c


def _mock_openai(content: str):
    completion = MagicMock()
    completion.choices = [MagicMock(message=MagicMock(content=content))]
    client = MagicMock()
    client.chat.completions.create.return_value = completion
    return client


@patch("app.routes.profiles.OpenAI")
def test_interview_generates_questions(mock_openai_cls, client):
    payload = json.dumps({"questions": [
        {"field": "thesis", "question": "Why do you hold AAPL?"},
        {"field": "sell_trigger", "question": "What would make you sell?"},
        {"field": "conviction", "question": "Conviction 1-5 and why?"},
    ]})
    mock_openai_cls.return_value = _mock_openai(payload)
    r = client.post("/stocks/AAPL/profile/interview?bucket=long_term",
                    json={"autofill": {"trackRecord": {"tradeCount": 3}}, "answers": []})
    assert r.status_code == 200
    qs = r.json()["questions"]
    assert len(qs) == 3
    assert qs[0]["field"] == "thesis"
```

- [ ] **Step 2: Run → fail.**

- [ ] **Step 3: Implement** — add to `profiles.py`:

```python
from openai import OpenAI

_PROFILE_MODEL_LIGHT = os.getenv("OPENAI_MODEL_PROFILE_LIGHT", "gpt-5-mini")
_PROFILE_MODEL_SYNTH = os.getenv("OPENAI_MODEL_PROFILE_SYNTH", "gpt-5-mini")


def _strip_fences(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
    if raw.endswith("```"):
        raw = raw[:-3]
    return raw.strip()


def _chat_json(model: str, system: str, user: str, max_tokens: int = 700) -> dict:
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    completion = client.chat.completions.create(
        model=model,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        max_tokens=max_tokens, temperature=0.3,
    )
    return json.loads(_strip_fences(completion.choices[0].message.content or "{}"))


class InterviewBody(BaseModel):
    autofill: dict = {}
    answers: list[dict] = []  # [{field, question, answer}]


@router.post("/stocks/{ticker}/profile/interview")
async def interview(
    ticker: str = Path(...),
    body: InterviewBody = ...,  # noqa: B008
    bucket: str | None = BucketQuery,
):
    b = _require_concrete_bucket(bucket)
    symbol = ticker.upper()
    follow_up = bool(body.answers)

    if not follow_up:
        system = (
            "You interview an investor to capture the SUBJECTIVE parts of their thesis for a "
            "stock. Given factual data, produce 3-5 targeted questions. Return ONLY JSON: "
            '{"questions":[{"field": "thesis|sell_trigger|conviction|catalyst|risk", '
            '"question": "..."}]}. No markdown.'
        )
        user = f"SYMBOL: {symbol} ({b})\nDATA:\n{json.dumps(body.autofill)[:3000]}"
    else:
        system = (
            "You already asked questions and received answers. Inspect them against the data. "
            "If an answer is thin or CONTRADICTS the track record (e.g. bullish thesis but the "
            "trades show repeated selling), return 1-2 targeted follow-up questions; otherwise "
            'return an empty list. Return ONLY JSON: {"questions":[{"field":"...","question":"..."}]}.'
        )
        user = (
            f"SYMBOL: {symbol} ({b})\nDATA:\n{json.dumps(body.autofill)[:2000]}\n\n"
            f"ANSWERS:\n{json.dumps(body.answers)[:2000]}"
        )

    try:
        result = _chat_json(_PROFILE_MODEL_LIGHT, system, user, max_tokens=600)
        questions = result.get("questions", [])
    except json.JSONDecodeError:
        questions = []
    except Exception as e:  # noqa: BLE001
        logger.error("interview failed for %s: %s", symbol, e)
        raise HTTPException(status_code=502, detail="AI interview failed") from None

    return {"symbol": symbol, "bucket": b, "questions": questions, "followUp": follow_up}
```

- [ ] **Step 4: Run → pass.** `pytest tests/test_profiles_interview.py -v`; `ruff check app/routes/profiles.py`.

- [ ] **Step 5: Commit**
```bash
git add app/routes/profiles.py tests/test_profiles_interview.py
git commit -m "feat(profiles): adaptive interview (tailored questions + follow-ups)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 9: Synthesize (`POST /stocks/{ticker}/profile/synthesize`)

Merges autofill + answers into a structured draft thesis using the 3-pass refine *structure* (refine → reflect for hallucinated levels / unsupported claims / conviction-thesis mismatch → re-refine). Returns an editable draft (never auto-saves).

**Files:** Modify `app/routes/profiles.py`. Test: extend `tests/test_profiles_interview.py` or new `tests/test_profiles_synthesize.py`.

- [ ] **Step 1: Write the failing test**
```python
import json
from unittest.mock import MagicMock, patch
import pytest


@pytest.fixture
def client():
    with patch.dict("os.environ", {"DISABLE_AUTH": "true"}):
        from fastapi.testclient import TestClient
        from app.main import app
        with TestClient(app) as c:
            yield c


def _mock_openai_seq(*contents):
    completions = []
    for c in contents:
        comp = MagicMock(); comp.choices = [MagicMock(message=MagicMock(content=c))]
        completions.append(comp)
    client = MagicMock()
    client.chat.completions.create.side_effect = completions
    return client


@patch("app.routes.profiles.OpenAI")
def test_synthesize_no_issues_single_pass(mock_openai_cls, client):
    draft = json.dumps({"thesis": "Quality compounder.", "bullCase": "services",
                        "bearCase": "china", "catalysts": [{"text": "WWDC"}], "risks": [],
                        "conviction": 4, "levels": {"target": 240}})
    reflect = json.dumps({"issues_found": False, "critique": "ok"})
    mock_openai_cls.return_value = _mock_openai_seq(draft, reflect)
    r = client.post("/stocks/AAPL/profile/synthesize?bucket=long_term",
                    json={"autofill": {}, "answers": [{"field": "thesis", "answer": "compounder"}]})
    assert r.status_code == 200
    d = r.json()["draft"]
    assert d["thesis"].startswith("Quality")
    assert d["conviction"] == 4
```

- [ ] **Step 2: Run → fail.**

- [ ] **Step 3: Implement** — add to `profiles.py`:

```python
class SynthesizeBody(BaseModel):
    autofill: dict = {}
    answers: list[dict] = []


@router.post("/stocks/{ticker}/profile/synthesize")
async def synthesize(
    ticker: str = Path(...),
    body: SynthesizeBody = ...,  # noqa: B008
    bucket: str | None = BucketQuery,
):
    b = _require_concrete_bucket(bucket)
    symbol = ticker.upper()
    base = (
        f"SYMBOL: {symbol} ({b})\nDATA:\n{json.dumps(body.autofill)[:3000]}\n\n"
        f"INVESTOR ANSWERS:\n{json.dumps(body.answers)[:2000]}"
    )
    refine_sys = (
        "Merge the investor's answers with the factual data into a structured thesis. "
        "Use ONLY claims supported by the answers or data — do not invent price targets. "
        'Return ONLY JSON: {"thesis","bullCase","bearCase","catalysts":[{"text"}],'
        '"risks":[{"text"}],"conviction":1-5,"convictionRationale","levels":{"entry","target","stop"},'
        '"tags":[]}. No markdown.'
    )
    reflect_sys = (
        "Critique the DRAFT against the DATA + ANSWERS for: (1) hallucinated levels/targets not "
        "in the answers/data, (2) claims unsupported by the data, (3) conviction that contradicts "
        'the thesis. Return ONLY JSON: {"issues_found": bool, "critique": "..."}.'
    )
    rerefine_sys = (
        "Correct the DRAFT to fix the CRITIQUE while keeping supported content. Same JSON shape "
        "as the refine step. No markdown."
    )

    try:
        draft = _chat_json(_PROFILE_MODEL_SYNTH, refine_sys, base, max_tokens=900)
        reflection = _chat_json(
            _PROFILE_MODEL_SYNTH, reflect_sys,
            base + "\n\nDRAFT:\n" + json.dumps(draft), max_tokens=400,
        )
        reflection_applied = False
        if reflection.get("issues_found"):
            draft = _chat_json(
                _PROFILE_MODEL_SYNTH, rerefine_sys,
                base + "\n\nDRAFT:\n" + json.dumps(draft)
                + "\n\nCRITIQUE:\n" + str(reflection.get("critique", "")),
                max_tokens=900,
            )
            reflection_applied = True
    except json.JSONDecodeError:
        raise HTTPException(status_code=502, detail="AI returned invalid JSON") from None
    except Exception as e:  # noqa: BLE001
        logger.error("synthesize failed for %s: %s", symbol, e)
        raise HTTPException(status_code=502, detail="AI synthesis failed") from None

    return {"symbol": symbol, "bucket": b, "draft": draft,
            "reflectionApplied": reflection_applied, "modelUsed": _PROFILE_MODEL_SYNTH}
```

- [ ] **Step 4: Run → pass.** `pytest tests/test_profiles_synthesize.py -v`; `ruff check app/routes/profiles.py`.

- [ ] **Step 5: Full backend gate.** `pytest tests/ -m "not openai and not integration" -q` (all pass) + `ruff check src/ app/ tests/` (clean).

- [ ] **Step 6: Commit**
```bash
git add app/routes/profiles.py tests/test_profiles_synthesize.py
git commit -m "feat(profiles): synthesize draft thesis via 3-pass refine/reflect

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

# Phase 4 — Frontend

> Verify each task with `npm run lint` + `npm run build` from `frontend/`. Create the frontend branch first: `git checkout -b feature/ai-stock-profiling` in the frontend repo.

## Task 10: Types (`src/types/api.ts`)

- [ ] **Step 1:** Append these interfaces near the other stock types:

```typescript
export interface TrackRecord {
  symbol: string;
  bucket: string;
  tradeCount: number;
  realizedPnlPct: number;
  winRate: number;
  avgHoldDays: number;
  best: number;
  worst: number;
  currentQty: number;
  currentWeightPct: number;
  firstTradeDate: string | null;
  lastTradeDate: string | null;
}

export interface ThesisProfile {
  symbol: string;
  bucket: string;
  thesis: string | null;
  conviction: number | null;
  convictionRationale: string | null;
  bullCase: string | null;
  bearCase: string | null;
  catalysts: Array<{ text?: string; title?: string; date?: string; source?: string; url?: string }>;
  risks: Array<{ text?: string; source?: string }>;
  levels: { entry?: number; target?: number; stop?: number };
  horizon: string | null;
  tags: string[];
  status: string;
  updatedAt: string | null;
  reviewedAt: string | null;
  trackRecord: TrackRecord | null;
}

export interface InterviewQuestion { field: string; question: string }

export interface ProfileAutofill {
  symbol: string;
  bucket: string;
  trackRecord: TrackRecord | null;
  catalysts: Array<{ title?: string; date?: string; source?: string; url?: string }>;
  consensus: { overall_signal?: string; overall_confidence?: number; summary?: string } | null;
  ideas: Array<{ direction?: string; labels?: string[]; text?: string; author?: string }>;
  dataSources: string[];
}

export interface ProfileQueueItem { symbol: string; bucket: string; hasProfile: boolean; reason: string }
```

- [ ] **Step 2:** `npm run lint` → no new errors. **Commit:** `feat(types): ThesisProfile + autofill/interview/queue types`.

## Task 11: Proxy routes

- [ ] **Step 1:** Create `src/app/api/stocks/[ticker]/profile/route.ts` with **GET / PUT / DELETE**, mirroring the notes proxy (`backendFetch`, `authGuard`, `forwardBucket`), forwarding to `/stocks/{ticker}/profile`. GET/PUT/DELETE all forward `?bucket=` via `forwardBucket(request, qs)`; PUT/POST send the JSON body. (Use the verbatim notes/chat proxy patterns — `interface RouteParams { params: Promise<{ ticker: string }> }`, `await authGuard()`, `const { ticker } = await params`.)
- [ ] **Step 2:** Create `src/app/api/stocks/[ticker]/profile/revisions/route.ts` (GET → `/stocks/{ticker}/profile/revisions`).
- [ ] **Step 3:** Create `src/app/api/stocks/[ticker]/profile/autofill/route.ts`, `.../interview/route.ts`, `.../synthesize/route.ts` (each POST → the matching backend path, forwarding bucket + JSON body, mirroring the chat proxy).
- [ ] **Step 4:** Create `src/app/api/profiles/route.ts` (GET → `/profiles`, forwarding `queue` and `bucket` query params).
- [ ] **Step 5:** `npm run lint` + `npm run build` → green. **Commit:** `feat(api): profile proxy routes (crud, revisions, autofill, interview, synthesize, queue)`.

## Task 12: `useThesisProfile` hook

- [ ] **Step 1:** Create `src/hooks/useThesisProfile.ts` mirroring `useStockProfile.ts` (SWR + `withBucket`), fetching `/api/stocks/{ticker}/profile` and returning `{ data, error, isLoading, refresh }`. Tolerate 404 (return `data: undefined`, not an error) so the "Build profile" CTA shows. Add the export to `src/hooks/index.ts`.
- [ ] **Step 2:** `npm run build` → green. **Commit:** `feat(hooks): useThesisProfile`.

## Task 13: `ProfilePanel.tsx` (the build flow)

The panel renders one of: **saved profile view** (thesis, conviction meter, bull/bear, catalysts, risks, levels, tags, track-record panel, revision-history list), or the **build flow** when no profile: `idle → autofilling → interview (form) → review (editable draft) → saving`.

- [ ] **Step 1:** Create `src/components/stock/ProfilePanel.tsx`. Use `useThesisProfile(ticker)` for the saved view; for build, a local state machine:
  - **Bucket resolution:** read `useBucket()`. If `null`, fetch `/api/profiles?queue=1` (no bucket) once to find which buckets hold this symbol; if exactly one, use it; otherwise render a small `<select>` of the 5 buckets the user must pick before "Build". Save/autofill/synthesize all pass the chosen concrete bucket via `withBucket`.
  - **Build:** POST `…/profile/autofill` → store `ProfileAutofill`; POST `…/profile/interview` `{autofill, answers: []}` → render the questions as a form. On submit, POST `…/profile/interview` `{autofill, answers}` for adaptive follow-ups (append if any), then POST `…/profile/synthesize` `{autofill, answers}` → editable draft.
  - **Review:** editable fields (thesis textarea, conviction 1–5, bull/bear, catalysts/risks lists, levels entry/target/stop, tags). **Save** → PUT `…/profile?bucket=` with the `ProfileBody` shape + `aiAutofillJson`/`interviewJson` for provenance, then `refresh()`.
  - **Track record panel:** render `data.trackRecord` (trades, realized %, win rate, avg hold, current weight).
  - **Revision history:** collapsible; GET `/api/stocks/{ticker}/profile/revisions?bucket=`.
  Follow the `NotesPanel.tsx` structure for fetch/save/error/skeleton idioms (verbatim patterns: `useState` for form fields, `fetch(...).then`, `Skeleton`, `EmptyState`).
- [ ] **Step 2:** `npm run build` → green (fix any type errors against the Task 10 types). **Commit:** `feat(profile-panel): build flow (autofill -> interview -> review -> save) + track record + revisions`.

## Task 14: Add the Profile tab to `StockHubContent.tsx`

- [ ] **Step 1:** Edit `src/components/stock/StockHubContent.tsx`:
  - Add `'profile'` to `type TabKey` (currently `'chat' | 'ideas' | 'analysis' | 'raw' | 'insights' | 'notes'`).
  - Add `{ key: 'profile', label: 'Profile' }` to the `TABS` array (put it first or right after Chat).
  - Add to BOTH conditional-render blocks (desktop ~362–367 and mobile ~262–267):
    `{activeTab === 'profile' && <ProfilePanel ticker={ticker} key={`profile-${refreshKey}`} />}`
  - Import `ProfilePanel`.
- [ ] **Step 2:** `npm run build` → green. **Commit:** `feat(stock): add Profile tab`.

## Task 15: Profiles workspace page (`src/app/profiles/page.tsx`)

- [ ] **Step 1:** Create `src/app/profiles/page.tsx` mirroring `positions/page.tsx` layout (`<div className="flex h-screen"><Sidebar/><div…><TopBar/><main…><div className="max-w-7xl…"><Suspense><BucketSwitcher/></Suspense>…`). Fetch `/api/profiles?queue=1` (+ bucket via `withBucket`), render the prioritized queue with progress ("N to review"), and a "Save & Next" flow that mounts `ProfilePanel` for the current `(symbol, bucket)` and advances on save/skip. Reuse `ProfilePanel` for the editor.
- [ ] **Step 2:** Add a "Profiles" nav entry in `src/components/layout/Sidebar.tsx` (`researchNav` array): `{ name: 'Profiles', href: '/profiles', icon: ClipboardDocumentListIcon, activeIcon: ClipboardDocumentListIconSolid }` (icons already imported).
- [ ] **Step 3:** `npm run build` → green. **Commit:** `feat(profiles): review-queue workspace page + nav`.

---

# Phase 5 — Verification

## Task 16: Full verification sweep

- [ ] Backend: `pytest tests/ -v -m "not openai and not integration"` → all pass; `ruff check src/ app/ tests/` → clean; `python scripts/verify_database.py --verbose` → both tables present.
- [ ] Frontend: `npm run lint` + `npm run build` → green.
- [ ] Manual smoke (when app is running): stock page Profile tab → "Build profile" runs autofill → interview → review → save; saved view shows track record + revision history; `/profiles` queue lists holdings and walks Save & Next; reassigning an account's bucket surfaces affected profiles in the queue (reconciliation).
- [ ] No commit (verification only).

---

## Notes for the executor

- **Cold-start cost:** the first autofill for an unprofiled holding runs the full 5-agent + consensus LLM pipeline via `get_stock_analysis` (multi-second, ~$). The frontend MUST run autofill async with a loading state (Task 13). A whole build is ~5–7 LLM calls (autofill consensus + interview + 0–2 follow-ups + 1–2 synthesize).
- **Within-account limitation (documented):** `bucket` is per-account, so a swing-vs-long-term thesis for the same ticker only gets separate track records when the shares sit in differently-bucketed accounts. The thesis text is always independent.
- **Reconciliation:** profiles are NOT auto-orphaned on bucket reassignment — the queue surfaces them (a profiled `(symbol, bucket)` whose holding moved shows up as no-profile under the new bucket; the old profile stays visible in the non-queue `/profiles` list and the "all" view).
- **Model env:** set `OPENAI_MODEL_PROFILE_LIGHT` / `OPENAI_MODEL_PROFILE_SYNTH` (default `gpt-5-mini`); they fall back cleanly if the model name isn't available in your OpenAI account — adjust to `gpt-4o-mini` if needed.
- **Advisory lock:** deterministic `hashlib.sha256` key (NOT Python `hash()`), so it serializes across processes/restarts.
