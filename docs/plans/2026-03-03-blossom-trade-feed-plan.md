# Blossom-Style Activity Feed Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Merge orders + activities into a unified enriched trade feed with Blossom-style cards, add position snapshots for historical P/L, and filter bot noise from raw message context.

**Architecture:** New `app/routes/trades.py` backend route merges data from `orders` and `activities` tables, enriches with position data from `positions` table, and optionally uses `position_snapshots` for historical lookups. Frontend replaces existing `TradeCard`/`ActivityRow` components with new `BlossomTradeCard`. Context filtering is a surgical SQL change in `app/routes/stocks.py`.

**Tech Stack:** Python/FastAPI, PostgreSQL/Supabase, Next.js 14, TypeScript, SWR, Tailwind CSS

---

### Task 1: Position Snapshots Migration

**Files:**
- Create: `schema/068_position_snapshots.sql`

**Step 1: Write the migration**

```sql
-- =======================================================================
-- Migration 068: Position snapshots for historical P/L tracking
-- =======================================================================
-- Captures daily position state for accurate gain/loss calculations
-- on historical trades. Populated by nightly pipeline after SnapTrade sync.

CREATE TABLE IF NOT EXISTS public.position_snapshots (
    account_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    snapshot_date DATE NOT NULL,
    quantity NUMERIC(15,4),
    average_buy_price NUMERIC(12,4),
    current_price NUMERIC(12,4),
    equity NUMERIC(15,4),
    total_portfolio_value NUMERIC(15,4),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (account_id, symbol, snapshot_date)
);

CREATE INDEX IF NOT EXISTS idx_position_snapshots_symbol_date
    ON position_snapshots(symbol, snapshot_date DESC);

ALTER TABLE position_snapshots ENABLE ROW LEVEL SECURITY;

-- Track migration
INSERT INTO schema_migrations (version, description)
VALUES ('068_position_snapshots', 'Position snapshots for historical P/L tracking')
ON CONFLICT (version) DO NOTHING;
```

**Step 2: Deploy migration to Supabase**

Run: `python scripts/deploy_database.py`
Expected: Migration 068 applied successfully.

**Step 3: Commit**

```bash
git add schema/068_position_snapshots.sql
git commit -m "schema: add position_snapshots table for historical P/L (068)"
```

---

### Task 2: Nightly Pipeline — Snapshot Positions

**Files:**
- Modify: `scripts/nightly_pipeline.py:157-228` (add step after SnapTrade sync)

**Step 1: Add snapshot function**

After `run_snaptrade_sync()` (line 59-105), add this function before `run_script()`:

```python
def snapshot_positions() -> bool:
    """Snapshot current positions for historical P/L tracking.

    Inserts one row per (account_id, symbol) into position_snapshots.
    Uses ON CONFLICT to update if already snapshotted today.
    Only includes positions from non-deleted accounts.
    """
    try:
        from src.db import execute_sql

        logger.info("Snapshotting positions for historical P/L...")
        execute_sql(
            """
            INSERT INTO position_snapshots
                (account_id, symbol, snapshot_date, quantity, average_buy_price,
                 current_price, equity, total_portfolio_value)
            SELECT
                p.account_id,
                p.symbol,
                CURRENT_DATE,
                p.quantity,
                p.average_buy_price,
                COALESCE(p.current_price, p.price),
                p.equity,
                (SELECT COALESCE(SUM(equity), 0)
                 FROM positions
                 WHERE account_id IN (
                     SELECT id FROM accounts WHERE COALESCE(connection_status, 'connected') != 'deleted'
                 ))
            FROM positions p
            JOIN accounts a ON a.id = p.account_id
                AND COALESCE(a.connection_status, 'connected') != 'deleted'
            WHERE p.quantity > 0
            ON CONFLICT (account_id, symbol, snapshot_date) DO UPDATE SET
                quantity = EXCLUDED.quantity,
                average_buy_price = EXCLUDED.average_buy_price,
                current_price = EXCLUDED.current_price,
                equity = EXCLUDED.equity,
                total_portfolio_value = EXCLUDED.total_portfolio_value
            """,
            fetch_results=False,
        )
        logger.info("✅ Position snapshot complete")
        return True
    except Exception as e:
        logger.error(f"Position snapshot failed: {e}")
        return False
```

**Step 2: Add snapshot step to main() pipeline**

In `main()`, after the SnapTrade sync block (after line 168), add:

```python
    # Step 0b: Snapshot positions for historical P/L
    logger.info("\n📸 Step 0b: Position Snapshots")
    results["position_snapshots"] = snapshot_positions()
```

And in the summary section (after line 278), add:

```python
    # Position snapshot failure is non-critical
    if results.get("position_snapshots") is False:
        logger.warning("⚠️ Position snapshots failed (non-critical)")
```

**Step 3: Run test to verify it doesn't break existing pipeline**

Run: `pytest tests/ -v -m "not openai and not integration" -x`
Expected: All existing tests pass.

**Step 4: Commit**

```bash
git add scripts/nightly_pipeline.py
git commit -m "feat: add position snapshot step to nightly pipeline"
```

---

### Task 3: Unified Trades Backend Route

**Files:**
- Create: `app/routes/trades.py`
- Modify: `app/main.py:33-47` (add import), `app/main.py:134-206` (register router)

**Step 1: Write test for unified trades endpoint**

Create `tests/test_trades_route.py`:

```python
"""Tests for unified trades endpoint merging orders + activities."""

import os
from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient


def _mock_row(data: dict):
    """Create a mock SQLAlchemy Row with _mapping."""
    row = MagicMock()
    row._mapping = data
    return row


@pytest.fixture
def client():
    """Create test client with auth disabled."""
    os.environ["DISABLE_AUTH"] = "true"
    from app.main import app
    return TestClient(app)


class TestStockTrades:
    """GET /stocks/{ticker}/trades merges orders + activities."""

    @patch("app.routes.trades.execute_sql")
    def test_returns_activities(self, mock_sql, client):
        """Activities are returned as enriched trades."""
        mock_sql.side_effect = [
            # 1. activities query
            [_mock_row({
                "id": "act-1", "activity_type": "BUY", "trade_date": "2026-02-26T10:28:00",
                "price": 186.30, "units": 0.076, "amount": 14.26, "fee": 0.0,
                "symbol": "NVDA", "description": "Buy NVDA",
            })],
            # 2. orders query
            [],
            # 3. position lookup
            [_mock_row({
                "quantity": 9.2149, "average_buy_price": 188.46,
                "current_price": 180.12, "equity": 1681.54,
            })],
            # 4. total portfolio value
            [_mock_row({"total_value": 21000.0})],
        ]
        resp = client.get("/stocks/NVDA/trades?limit=10")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["trades"]) == 1
        trade = data["trades"][0]
        assert trade["symbol"] == "NVDA"
        assert trade["type"] == "BUY"
        assert trade["source"] == "activity"
        assert trade["avgCost"] == 188.46
        assert trade["currentPrice"] == 180.12

    @patch("app.routes.trades.execute_sql")
    def test_returns_orders_when_no_activities(self, mock_sql, client):
        """Orders fill in when activities are missing."""
        mock_sql.side_effect = [
            [],  # no activities
            [_mock_row({
                "brokerage_order_id": "ord-1", "action": "BUY",
                "time_executed": "2026-02-26T10:28:00", "execution_price": 186.30,
                "filled_quantity": 0.076, "symbol": "NVDA",
            })],
            [_mock_row({
                "quantity": 9.2149, "average_buy_price": 188.46,
                "current_price": 180.12, "equity": 1681.54,
            })],
            [_mock_row({"total_value": 21000.0})],
        ]
        resp = client.get("/stocks/NVDA/trades?limit=10")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["trades"]) == 1
        assert data["trades"][0]["source"] == "order"

    @patch("app.routes.trades.execute_sql")
    def test_deduplication(self, mock_sql, client):
        """When both sources have same trade, prefer activity (has fee data)."""
        mock_sql.side_effect = [
            [_mock_row({
                "id": "act-1", "activity_type": "BUY", "trade_date": "2026-02-26T10:28:00",
                "price": 186.30, "units": 0.076, "amount": 14.26, "fee": 0.01,
                "symbol": "NVDA", "description": "Buy NVDA",
            })],
            [_mock_row({
                "brokerage_order_id": "ord-1", "action": "BUY",
                "time_executed": "2026-02-26T10:28:00", "execution_price": 186.30,
                "filled_quantity": 0.076, "symbol": "NVDA",
            })],
            [_mock_row({
                "quantity": 9.2149, "average_buy_price": 188.46,
                "current_price": 180.12, "equity": 1681.54,
            })],
            [_mock_row({"total_value": 21000.0})],
        ]
        resp = client.get("/stocks/NVDA/trades?limit=10")
        data = resp.json()
        # Should deduplicate to 1 trade, preferring activity
        assert len(data["trades"]) == 1
        assert data["trades"][0]["source"] == "activity"
        assert data["trades"][0]["fee"] == 0.01


class TestRecentTrades:
    """GET /trades/recent returns latest trades across all stocks."""

    @patch("app.routes.trades.execute_sql")
    def test_recent_trades_returns_data(self, mock_sql, client):
        """Recent trades endpoint returns enriched trades."""
        mock_sql.side_effect = [
            [_mock_row({
                "id": "act-1", "activity_type": "SELL", "trade_date": "2026-02-25T15:54:00",
                "price": 387.21, "units": -0.1776, "amount": -68.77, "fee": 0.0,
                "symbol": "TSM", "description": "Sell TSM",
            })],
            [],  # no orders that aren't already activities
            # position lookups per symbol
            [_mock_row({
                "quantity": 1.8688, "average_buy_price": 163.31,
                "current_price": 354.95, "equity": 689.79,
            })],
            [_mock_row({"total_value": 21000.0})],
        ]
        resp = client.get("/trades/recent?limit=5")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["trades"]) >= 1
        trade = data["trades"][0]
        assert trade["type"] == "SELL"
        assert trade["realizedPnl"] is not None
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_trades_route.py -v -x`
Expected: ImportError — `app.routes.trades` does not exist yet.

**Step 3: Create the trades route**

Create `app/routes/trades.py`:

```python
"""
Unified trade feed — merges orders + activities with position enrichment.

Provides:
    GET /stocks/{ticker}/trades  — per-stock trade history with P/L
    GET /trades/recent           — dashboard recent trades across all stocks
"""

import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Path, Query
from pydantic import BaseModel

from src.db import execute_sql

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

class EnrichedTrade(BaseModel):
    id: str
    source: str  # "activity" | "order"
    type: str  # "BUY" | "SELL" | "DIVIDEND" | "FEE"
    symbol: str
    tradeDate: Optional[str] = None
    price: Optional[float] = None
    units: Optional[float] = None
    amount: float = 0.0
    fee: float = 0.0
    description: Optional[str] = None

    # Enrichment from positions
    currentPrice: Optional[float] = None
    avgCost: Optional[float] = None
    totalShares: Optional[float] = None
    marketValue: Optional[float] = None
    portfolioPct: Optional[float] = None
    unrealizedPnl: Optional[float] = None
    unrealizedPnlPct: Optional[float] = None
    realizedPnl: Optional[float] = None
    realizedPnlPct: Optional[float] = None


class TradesResponse(BaseModel):
    trades: list[EnrichedTrade]
    ticker: Optional[str] = None
    total: int = 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_float(val) -> float:
    """Convert to float, defaulting to 0.0."""
    if val is None:
        return 0.0
    try:
        return float(val)
    except (TypeError, ValueError):
        return 0.0


def _safe_float_opt(val) -> Optional[float]:
    """Convert to float or None."""
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _normalize_type(raw: Optional[str]) -> str:
    """Normalize activity/order type to BUY|SELL|DIVIDEND|FEE."""
    if not raw:
        return "OTHER"
    t = raw.upper().strip()
    if t in ("BUY", "BUY_OPEN", "BUY_TO_COVER"):
        return "BUY"
    if t in ("SELL", "SELL_CLOSE", "SELL_SHORT"):
        return "SELL"
    if t.startswith("DIV"):
        return "DIVIDEND"
    if t == "FEE":
        return "FEE"
    return t


def _dedup_key(trade_date_str: Optional[str], symbol: str, amount: float) -> str:
    """Build a dedup key: symbol + minute-rounded timestamp + rounded amount."""
    sym = symbol.upper()
    amt = round(abs(amount), 1)
    if trade_date_str:
        try:
            dt = datetime.fromisoformat(str(trade_date_str).replace("Z", "+00:00"))
            # Round to nearest minute for fuzzy matching
            minute_key = dt.strftime("%Y%m%d%H%M")
            return f"{sym}|{minute_key}|{amt}"
        except (ValueError, TypeError):
            pass
    return f"{sym}|none|{amt}"


def _fetch_activities(symbol: Optional[str], limit: int) -> list[dict]:
    """Fetch from activities table, optionally filtered by symbol."""
    where = "WHERE a.account_id IN (SELECT id FROM accounts WHERE COALESCE(connection_status, 'connected') != 'deleted')"
    params: dict = {"limit": limit}
    if symbol:
        where += " AND UPPER(a.symbol) = UPPER(:symbol)"
        params["symbol"] = symbol

    rows = execute_sql(
        f"""
        SELECT a.id, a.activity_type, a.trade_date, a.price, a.units,
               a.amount, a.fee, a.symbol, a.description
        FROM activities a
        {where}
          AND a.activity_type IN ('BUY', 'SELL', 'DIVIDEND', 'FEE')
        ORDER BY a.trade_date DESC NULLS LAST
        LIMIT :limit
        """,
        params=params,
        fetch_results=True,
    ) or []

    result = []
    for r in rows:
        d = dict(r._mapping) if hasattr(r, "_mapping") else dict(r)
        result.append(d)
    return result


def _fetch_orders(symbol: Optional[str], limit: int) -> list[dict]:
    """Fetch executed orders, optionally filtered by symbol."""
    where = "WHERE o.account_id IN (SELECT id FROM accounts WHERE COALESCE(connection_status, 'connected') != 'deleted')"
    params: dict = {"limit": limit}
    if symbol:
        where += " AND UPPER(o.symbol) = UPPER(:symbol)"
        params["symbol"] = symbol

    rows = execute_sql(
        f"""
        SELECT o.brokerage_order_id, o.action, o.time_executed,
               o.execution_price, o.filled_quantity, o.symbol
        FROM orders o
        {where}
          AND UPPER(o.status) IN ('EXECUTED', 'FILLED')
          AND UPPER(o.action) IN ('BUY', 'SELL', 'BUY_OPEN', 'SELL_CLOSE', 'BUY_TO_COVER', 'SELL_SHORT')
        ORDER BY o.time_executed DESC NULLS LAST
        LIMIT :limit
        """,
        params=params,
        fetch_results=True,
    ) or []

    result = []
    for r in rows:
        d = dict(r._mapping) if hasattr(r, "_mapping") else dict(r)
        result.append(d)
    return result


def _fetch_position(symbol: str) -> Optional[dict]:
    """Fetch current position for a symbol (aggregated across non-deleted accounts)."""
    rows = execute_sql(
        """
        SELECT
            SUM(p.quantity) as quantity,
            -- Weighted average buy price
            CASE WHEN SUM(p.quantity) > 0
                 THEN SUM(p.average_buy_price * p.quantity) / SUM(p.quantity)
                 ELSE NULL END as average_buy_price,
            MAX(COALESCE(p.current_price, p.price)) as current_price,
            SUM(p.equity) as equity
        FROM positions p
        JOIN accounts a ON a.id = p.account_id
            AND COALESCE(a.connection_status, 'connected') != 'deleted'
        WHERE UPPER(p.symbol) = UPPER(:symbol)
          AND p.quantity > 0
        """,
        params={"symbol": symbol},
        fetch_results=True,
    ) or []

    if rows and rows[0]:
        d = dict(rows[0]._mapping) if hasattr(rows[0], "_mapping") else dict(rows[0])
        if d.get("quantity") and float(d["quantity"]) > 0:
            return d
    return None


def _fetch_total_portfolio_value() -> float:
    """Sum equity across all positions in non-deleted accounts."""
    rows = execute_sql(
        """
        SELECT COALESCE(SUM(p.equity), 0) as total_value
        FROM positions p
        JOIN accounts a ON a.id = p.account_id
            AND COALESCE(a.connection_status, 'connected') != 'deleted'
        WHERE p.quantity > 0
        """,
        fetch_results=True,
    ) or []

    if rows:
        d = dict(rows[0]._mapping) if hasattr(rows[0], "_mapping") else dict(rows[0])
        return _safe_float(d.get("total_value"))
    return 0.0


def _enrich_trade(
    trade: EnrichedTrade,
    position: Optional[dict],
    total_portfolio: float,
) -> EnrichedTrade:
    """Add position-derived fields to a trade."""
    if not position:
        return trade

    qty = _safe_float(position.get("quantity"))
    avg_cost = _safe_float_opt(position.get("average_buy_price"))
    cur_price = _safe_float_opt(position.get("current_price"))
    equity = _safe_float(position.get("equity"))

    trade.totalShares = qty if qty > 0 else None
    trade.avgCost = avg_cost
    trade.currentPrice = cur_price
    trade.marketValue = equity if equity > 0 else None

    if total_portfolio > 0 and equity > 0:
        trade.portfolioPct = round(equity / total_portfolio * 100, 2)

    # P/L calculations
    if avg_cost and avg_cost > 0:
        if trade.type == "SELL" and trade.price:
            # Realized P/L: (sale price - avg cost) * units sold
            units_sold = abs(_safe_float(trade.units))
            trade.realizedPnl = round((trade.price - avg_cost) * units_sold, 2)
            trade.realizedPnlPct = round((trade.price - avg_cost) / avg_cost * 100, 2)
        elif trade.type == "BUY" and cur_price:
            # Unrealized P/L for position
            trade.unrealizedPnl = round((cur_price - avg_cost) * qty, 2)
            trade.unrealizedPnlPct = round((cur_price - avg_cost) / avg_cost * 100, 2)

    return trade


def _build_trades(
    symbol: Optional[str],
    limit: int,
) -> list[EnrichedTrade]:
    """Merge activities + orders, deduplicate, enrich with positions."""
    # 1. Fetch from both sources
    activities = _fetch_activities(symbol, limit)
    orders = _fetch_orders(symbol, limit)

    # 2. Build trades from activities (preferred source)
    seen_keys: set[str] = set()
    trades: list[EnrichedTrade] = []

    for a in activities:
        sym = a.get("symbol") or ""
        if not sym:
            continue
        t = EnrichedTrade(
            id=str(a.get("id", "")),
            source="activity",
            type=_normalize_type(a.get("activity_type")),
            symbol=sym.upper(),
            tradeDate=str(a["trade_date"]) if a.get("trade_date") else None,
            price=_safe_float_opt(a.get("price")),
            units=_safe_float_opt(a.get("units")),
            amount=_safe_float(a.get("amount")),
            fee=_safe_float(a.get("fee")),
            description=a.get("description"),
        )
        trades.append(t)
        key = _dedup_key(t.tradeDate, t.symbol, t.amount)
        seen_keys.add(key)

    # 3. Add orders not already covered by activities
    for o in orders:
        sym = o.get("symbol") or ""
        if not sym:
            continue
        exec_price = _safe_float_opt(o.get("execution_price"))
        filled_qty = _safe_float_opt(o.get("filled_quantity"))
        amount = (exec_price or 0) * (filled_qty or 0)
        trade_date = str(o["time_executed"]) if o.get("time_executed") else None

        key = _dedup_key(trade_date, sym, amount)
        if key in seen_keys:
            continue  # Already have this from activities

        t = EnrichedTrade(
            id=str(o.get("brokerage_order_id", "")),
            source="order",
            type=_normalize_type(o.get("action")),
            symbol=sym.upper(),
            tradeDate=trade_date,
            price=exec_price,
            units=filled_qty,
            amount=amount,
            fee=0.0,
        )
        trades.append(t)

    # 4. Sort by trade date descending
    trades.sort(
        key=lambda t: t.tradeDate or "1970-01-01",
        reverse=True,
    )
    trades = trades[:limit]

    # 5. Enrich with position data
    total_portfolio = _fetch_total_portfolio_value()
    # Cache position lookups per symbol
    pos_cache: dict[str, Optional[dict]] = {}
    for t in trades:
        if t.symbol not in pos_cache:
            pos_cache[t.symbol] = _fetch_position(t.symbol)
        _enrich_trade(t, pos_cache[t.symbol], total_portfolio)

    return trades


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/stocks/{ticker}/trades", response_model=TradesResponse)
async def get_stock_trades(
    ticker: str = Path(..., description="Stock ticker symbol"),
    limit: int = Query(20, ge=1, le=100, description="Max trades to return"),
):
    """Get enriched trade history for a specific stock.

    Merges data from both `activities` and `orders` tables, deduplicates,
    and enriches with current position data (avg cost, P/L, portfolio %).
    """
    clean = ticker.strip().upper()
    if not clean or len(clean) > 10:
        raise HTTPException(status_code=400, detail="Invalid ticker")

    try:
        trades = _build_trades(symbol=clean, limit=limit)
        return TradesResponse(trades=trades, ticker=clean, total=len(trades))
    except Exception as e:
        logger.error(f"Error fetching trades for {clean}: {e}", exc_info=True)
        return TradesResponse(trades=[], ticker=clean, total=0)


@router.get("/trades/recent", response_model=TradesResponse)
async def get_recent_trades(
    limit: int = Query(10, ge=1, le=50, description="Max trades to return"),
):
    """Get recent trades across all stocks for the dashboard feed.

    Same merge + enrichment logic as per-stock, but no ticker filter.
    """
    try:
        trades = _build_trades(symbol=None, limit=limit)
        return TradesResponse(trades=trades, total=len(trades))
    except Exception as e:
        logger.error(f"Error fetching recent trades: {e}", exc_info=True)
        return TradesResponse(trades=[], total=0)
```

**Step 4: Register the router in app/main.py**

Add to imports (after line 47 `webhook,` add):

```python
from app.routes import (
    ...
    webhook,
    trades,   # <-- add this
)
```

Add router registration (after the connections router block, before the webhook line ~208):

```python
app.include_router(
    trades.router,
    tags=["Trades"],
    dependencies=[Depends(require_api_key)],
)
```

Note: the trades router has `/stocks/{ticker}/trades` and `/trades/recent` paths defined directly on the endpoints, so no prefix is needed.

**Step 5: Run tests**

Run: `pytest tests/test_trades_route.py -v -x`
Expected: All 4 tests pass.

Run: `pytest tests/ -v -m "not openai and not integration" -x`
Expected: Full suite passes with no regressions.

**Step 6: Commit**

```bash
git add app/routes/trades.py app/main.py tests/test_trades_route.py
git commit -m "feat: unified trades endpoint merging orders + activities with P/L enrichment"
```

---

### Task 4: Context Filtering for Raw Messages

**Files:**
- Modify: `app/routes/stocks.py:628-666` (context query)

**Step 1: Write test for context filtering**

Add to `tests/test_trades_route.py` or create `tests/test_context_filter.py`:

```python
"""Tests for context message filtering in stock idea context endpoint."""

import os
from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient


def _mock_row(data: dict):
    row = MagicMock()
    row._mapping = data
    return row


@pytest.fixture
def client():
    os.environ["DISABLE_AUTH"] = "true"
    from app.main import app
    return TestClient(app)


class TestContextFiltering:
    """GET /stocks/{ticker}/ideas/{message_id}/context filters bot noise."""

    @patch("app.routes.stocks.execute_sql")
    def test_bot_messages_excluded(self, mock_sql, client):
        """Bot messages and commands should be filtered from context."""
        # First call: parent message lookup
        mock_sql.side_effect = [
            [_mock_row({
                "message_id": "123", "content": "NVDA guidance is insane",
                "author": "qmy.y", "timestamp": "2026-02-26T10:00:00", "channel": "trading-picks",
            })],
            # Second call: context query (should NOT return bot/command msgs)
            [
                _mock_row({
                    "message_id": "121", "content": "Nvidia guiding for 79% Revenue growth",
                    "author": "qmy.y", "timestamp": "2026-02-25T14:00:00", "channel": "trading-picks",
                }),
                _mock_row({
                    "message_id": "123", "content": "NVDA guidance is insane",
                    "author": "qmy.y", "timestamp": "2026-02-26T10:00:00", "channel": "trading-picks",
                }),
            ],
        ]

        resp = client.get("/stocks/NVDA/ideas/123/context")
        assert resp.status_code == 200
        data = resp.json()

        # Verify the SQL was called with bot filtering
        context_call = mock_sql.call_args_list[1]
        query_str = context_call[0][0] if context_call[0] else ""
        # Should contain bot author exclusion
        assert "QBOT" in query_str.upper() or "qbot" in query_str.lower()
```

**Step 2: Run test to see it fail**

Run: `pytest tests/test_context_filter.py -v -x`
Expected: FAIL — current SQL doesn't filter bots.

**Step 3: Modify context query in stocks.py**

Replace lines 630-652 in `app/routes/stocks.py` with:

```python
    # 2. Fetch surrounding messages from same channel
    # Filter out bot responses and commands for cleaner context
    bot_filter = """
        AND author NOT IN ('QBOT', 'QBot', 'qbot')
        AND content NOT LIKE '!%'
        AND content NOT LIKE '/%'
        AND LENGTH(COALESCE(content, '')) >= 5
    """
    ctx_rows = execute_sql(
        f"""
        (SELECT message_id, content, author, timestamp, channel
         FROM discord_messages
         WHERE channel = :channel AND timestamp <= :ts
           {bot_filter}
         ORDER BY timestamp DESC
         LIMIT :before)
        UNION ALL
        (SELECT message_id, content, author, timestamp, channel
         FROM discord_messages
         WHERE channel = :channel AND timestamp > :ts
           {bot_filter}
         ORDER BY timestamp ASC
         LIMIT :after)
        ORDER BY timestamp ASC
        """,
        params={
            "channel": mr["channel"],
            "ts": mr["timestamp"],
            "before": context_window + 1,
            "after": context_window,
        },
        fetch_results=True,
    )
```

**Step 4: Ensure parent message always appears**

After building context_msgs, ensure the parent (even if from a bot) is included:

```python
    # Ensure the parent message is always included even if it was filtered
    parent_ids = {cm.messageId for cm in context_msgs}
    if message_id not in parent_ids:
        context_msgs.append(IdeaContextMessage(
            messageId=mr["message_id"],
            content=mr["content"],
            author=mr["author"],
            sentAt=str(mr["timestamp"]),
            channel=mr["channel"],
            isParent=True,
        ))
        context_msgs.sort(key=lambda cm: cm.sentAt)
```

**Step 5: Run tests**

Run: `pytest tests/test_context_filter.py tests/ -v -m "not openai and not integration" -x`
Expected: All pass.

**Step 6: Commit**

```bash
git add app/routes/stocks.py tests/test_context_filter.py
git commit -m "fix: filter bot commands and responses from idea context messages"
```

---

### Task 5: Frontend Types + Hook + BFF Routes

**Files:**
- Modify: `frontend/src/types/api.ts:444` (add EnrichedTrade type after StockActivitiesResponse)
- Create: `frontend/src/hooks/useEnrichedTrades.ts`
- Create: `frontend/src/app/api/stocks/[ticker]/trades/route.ts`
- Create: `frontend/src/app/api/trades/route.ts`

**Step 1: Add EnrichedTrade type to api.ts**

After the `StockActivitiesResponse` block (line ~445), add:

```typescript
// =============================================================================
// Enriched Trades (unified orders + activities with P/L)
// =============================================================================

export interface EnrichedTrade {
  id: string;
  source: 'activity' | 'order';
  type: 'BUY' | 'SELL' | 'DIVIDEND' | 'FEE' | string;
  symbol: string;
  tradeDate: string | null;
  price: number | null;
  units: number | null;
  amount: number;
  fee: number;
  description: string | null;
  // Enrichment from positions
  currentPrice: number | null;
  avgCost: number | null;
  totalShares: number | null;
  marketValue: number | null;
  portfolioPct: number | null;
  unrealizedPnl: number | null;
  unrealizedPnlPct: number | null;
  realizedPnl: number | null;
  realizedPnlPct: number | null;
}

export interface EnrichedTradesResponse {
  trades: EnrichedTrade[];
  ticker?: string;
  total: number;
}
```

**Step 2: Create SWR hook**

Create `frontend/src/hooks/useEnrichedTrades.ts`:

```typescript
import useSWR from 'swr';
import type { EnrichedTradesResponse } from '@/types/api';

const fetcher = async (url: string): Promise<EnrichedTradesResponse> => {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`Failed to fetch trades (${res.status})`);
  return res.json();
};

/** Fetch enriched trades for a specific stock. */
export function useStockTrades(ticker: string, limit = 20) {
  const { data, error, isLoading } = useSWR<EnrichedTradesResponse>(
    `/api/stocks/${ticker}/trades?limit=${limit}`,
    fetcher,
    { revalidateOnFocus: false, dedupingInterval: 30000 },
  );
  return { data, error, isLoading };
}

/** Fetch recent enriched trades across all stocks (dashboard). */
export function useRecentTrades(limit = 10) {
  const { data, error, isLoading } = useSWR<EnrichedTradesResponse>(
    `/api/trades?limit=${limit}`,
    fetcher,
    { revalidateOnFocus: false, dedupingInterval: 30000 },
  );
  return { data, error, isLoading };
}
```

**Step 3: Create BFF proxy for stock trades**

Create `frontend/src/app/api/stocks/[ticker]/trades/route.ts`:

```typescript
export const dynamic = 'force-dynamic';
import { NextRequest, NextResponse } from 'next/server';
import type { EnrichedTradesResponse, ApiError } from '@/types/api';
import { backendFetch, authGuard } from '@/lib/api-client';

interface RouteParams {
  params: Promise<{ ticker: string }>;
}

export async function GET(request: NextRequest, { params }: RouteParams) {
  try {
    await authGuard();
    const { ticker } = await params;
    const normalizedTicker = ticker.toUpperCase();
    const { searchParams } = new URL(request.url);
    const limit = searchParams.get('limit') || '20';

    const response = await backendFetch(
      `/stocks/${normalizedTicker}/trades?limit=${limit}`,
      { next: { revalidate: 30 } },
    );

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      return NextResponse.json(
        { error: errorData.detail || 'Failed to fetch trades' } as ApiError,
        { status: response.status },
      );
    }

    const data: EnrichedTradesResponse = await response.json();
    return NextResponse.json(data);
  } catch (error) {
    if (error instanceof Response) return error;
    console.error('Stock trades fetch error:', error);
    return NextResponse.json(
      { error: 'Failed to connect to backend API' } as ApiError,
      { status: 502 },
    );
  }
}
```

**Step 4: Create BFF proxy for recent trades**

Create `frontend/src/app/api/trades/route.ts`:

```typescript
export const dynamic = 'force-dynamic';
import { NextRequest, NextResponse } from 'next/server';
import type { EnrichedTradesResponse, ApiError } from '@/types/api';
import { backendFetch, authGuard } from '@/lib/api-client';

export async function GET(request: NextRequest) {
  try {
    await authGuard();
    const { searchParams } = new URL(request.url);
    const limit = searchParams.get('limit') || '10';

    const response = await backendFetch(
      `/trades/recent?limit=${limit}`,
      { next: { revalidate: 30 } },
    );

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      return NextResponse.json(
        { error: errorData.detail || 'Failed to fetch recent trades' } as ApiError,
        { status: response.status },
      );
    }

    const data: EnrichedTradesResponse = await response.json();
    return NextResponse.json(data);
  } catch (error) {
    if (error instanceof Response) return error;
    console.error('Recent trades fetch error:', error);
    return NextResponse.json(
      { error: 'Failed to connect to backend API' } as ApiError,
      { status: 502 },
    );
  }
}
```

**Step 5: Commit**

```bash
cd frontend
git add src/types/api.ts src/hooks/useEnrichedTrades.ts \
  src/app/api/stocks/\[ticker\]/trades/route.ts \
  src/app/api/trades/route.ts
git commit -m "feat: add EnrichedTrade types, SWR hooks, and BFF proxy routes"
```

---

### Task 6: BlossomTradeCard Component

**Files:**
- Create: `frontend/src/components/trade/BlossomTradeCard.tsx`

**Step 1: Create the component**

```tsx
'use client';

import { clsx } from 'clsx';
import Link from 'next/link';
import type { EnrichedTrade } from '@/types/api';
import { formatMoney, formatNumber, formatDate, formatPercent } from '@/lib/format';
import { pnlTextColor } from '@/lib/colors';

// ---------------------------------------------------------------------------
// Badge config per trade type
// ---------------------------------------------------------------------------

interface BadgeStyle {
  label: string;
  badge: string;
  border: string;
}

function tradeStyle(trade: EnrichedTrade): BadgeStyle {
  const t = trade.type;

  if (t === 'BUY') {
    return {
      label: 'BUY',
      badge: 'bg-indigo-500/20 text-indigo-400',
      border: 'border-l-indigo-500',
    };
  }

  if (t === 'SELL') {
    const gain = (trade.realizedPnl ?? 0) >= 0;
    return {
      label: 'SELL',
      badge: gain ? 'bg-profit/20 text-profit' : 'bg-loss/20 text-loss',
      border: gain ? 'border-l-profit' : 'border-l-loss',
    };
  }

  if (t === 'DIVIDEND') {
    return {
      label: 'DIV',
      badge: 'bg-blue-500/20 text-blue-400',
      border: 'border-l-blue-500',
    };
  }

  return {
    label: t || 'OTHER',
    badge: 'bg-background-tertiary text-foreground-muted',
    border: 'border-l-foreground-muted',
  };
}

// ---------------------------------------------------------------------------
// Metric pill sub-component
// ---------------------------------------------------------------------------

function MetricBox({
  label,
  value,
  sub,
  valueColor,
}: {
  label: string;
  value: string;
  sub?: string;
  valueColor?: string;
}) {
  return (
    <div className="flex-1 rounded-lg bg-background-tertiary/50 px-3 py-2">
      <span className="text-2xs text-foreground-subtle uppercase tracking-wide">{label}</span>
      <div className={clsx('text-sm font-mono font-semibold mt-0.5', valueColor || 'text-foreground')}>
        {value}
      </div>
      {sub && <span className="text-2xs text-foreground-muted">{sub}</span>}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main card
// ---------------------------------------------------------------------------

interface BlossomTradeCardProps {
  trade: EnrichedTrade;
  /** Show ticker as clickable link (true on dashboard, false on stock page) */
  showSymbol?: boolean;
  /** Compact mode for dashboard preview */
  compact?: boolean;
}

export function BlossomTradeCard({ trade, showSymbol = true, compact = false }: BlossomTradeCardProps) {
  const style = tradeStyle(trade);
  const units = Math.abs(trade.units ?? 0);
  const isSell = trade.type === 'SELL';
  const isDividend = trade.type === 'DIVIDEND';

  // Action description line
  let actionText: string;
  if (isDividend) {
    actionText = `${formatMoney(Math.abs(trade.amount))} dividend received`;
  } else if (isSell) {
    actionText = `Sold ${formatNumber(units, units % 1 === 0 ? 0 : 4)} shares`;
    if (trade.price) actionText += ` @ ${formatMoney(trade.price)}`;
  } else {
    actionText = `Bought ${formatNumber(units, units % 1 === 0 ? 0 : 4)} shares`;
    if (trade.price) actionText += ` @ ${formatMoney(trade.price)}`;
  }

  return (
    <div
      className={clsx(
        'card border-l-[3px] transition-colors hover:bg-background-hover',
        style.border,
        compact ? 'p-3' : 'p-4',
      )}
    >
      {/* Header: badge + symbol + date */}
      <div className="flex items-center justify-between mb-1.5">
        <div className="flex items-center gap-2">
          <span className={clsx('px-2 py-0.5 text-2xs font-semibold rounded', style.badge)}>
            {style.label}
          </span>
          {showSymbol && trade.symbol && (
            <Link
              href={`/stock/${trade.symbol}`}
              className="font-mono font-semibold text-sm hover:text-primary transition-colors"
            >
              {trade.symbol}
            </Link>
          )}
        </div>
        <span className="text-xs text-foreground-subtle">
          {formatDate(trade.tradeDate, 'short')}
        </span>
      </div>

      {/* Action description */}
      <p className="text-sm text-foreground/90 mb-1">{actionText}</p>

      {/* Realized P/L for sells */}
      {isSell && trade.realizedPnl != null && (
        <p className={clsx('text-sm font-mono font-semibold mb-2', pnlTextColor(trade.realizedPnl))}>
          Realized: {trade.realizedPnl >= 0 ? '+' : ''}{formatMoney(trade.realizedPnl)}
          {trade.realizedPnlPct != null && ` (${trade.realizedPnlPct >= 0 ? '+' : ''}${formatPercent(trade.realizedPnlPct)})`}
        </p>
      )}

      {/* Total amount for non-sell */}
      {!isSell && !isDividend && trade.amount !== 0 && (
        <p className="text-xs text-foreground-muted mb-2">
          Total: {formatMoney(Math.abs(trade.amount))}
        </p>
      )}

      {/* Metric boxes — only show when we have enrichment data */}
      {!compact && (trade.portfolioPct != null || trade.avgCost != null) && (
        <div className="flex gap-2 mt-2">
          {trade.portfolioPct != null && (
            <MetricBox
              label="Portfolio"
              value={`${formatPercent(trade.portfolioPct)}`}
              sub="of total"
            />
          )}

          {isSell && trade.avgCost != null ? (
            <MetricBox
              label="Avg Cost"
              value={formatMoney(trade.avgCost)}
              sub={trade.price ? `→ ${formatMoney(trade.price)}` : undefined}
            />
          ) : trade.unrealizedPnl != null ? (
            <MetricBox
              label="Position P/L"
              value={`${trade.unrealizedPnl >= 0 ? '+' : ''}${formatMoney(trade.unrealizedPnl)}`}
              sub={trade.unrealizedPnlPct != null ? `${trade.unrealizedPnlPct >= 0 ? '+' : ''}${formatPercent(trade.unrealizedPnlPct)}` : undefined}
              valueColor={pnlTextColor(trade.unrealizedPnl)}
            />
          ) : trade.avgCost != null ? (
            <MetricBox
              label="Avg Cost"
              value={formatMoney(trade.avgCost)}
            />
          ) : null}
        </div>
      )}

      {/* Fee */}
      {trade.fee > 0 && (
        <p className="text-2xs text-foreground-subtle mt-1.5">Fee: {formatMoney(trade.fee)}</p>
      )}
    </div>
  );
}
```

**Step 2: Verify `formatPercent` exists in format.ts**

Check `frontend/src/lib/format.ts` for `formatPercent`. If it doesn't exist, add:

```typescript
export function formatPercent(value: number, decimals = 1): string {
  return `${value.toFixed(decimals)}%`;
}
```

**Step 3: Commit**

```bash
cd frontend
git add src/components/trade/BlossomTradeCard.tsx
git commit -m "feat: add BlossomTradeCard component with P/L enrichment display"
```

---

### Task 7: Wire Up TradesPanel (Stock Page)

**Files:**
- Modify: `frontend/src/components/stock/TradesPanel.tsx` (replace entirely)

**Step 1: Replace TradesPanel to use enriched trades**

Replace the entire file content:

```tsx
'use client';

import { Skeleton } from '@/components/ui/Skeleton';
import { EmptyState } from '@/components/ui/EmptyState';
import { ArrowsRightLeftIcon } from '@heroicons/react/24/outline';
import { useStockTrades } from '@/hooks/useEnrichedTrades';
import { BlossomTradeCard } from '@/components/trade/BlossomTradeCard';

interface TradesPanelProps {
  ticker: string;
}

export function TradesPanel({ ticker }: TradesPanelProps) {
  const { data, error, isLoading } = useStockTrades(ticker, 20);

  if (isLoading) {
    return (
      <div className="p-4 space-y-3">
        {[...Array(5)].map((_, i) => (
          <Skeleton.Card key={i} />
        ))}
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-4">
        <p className="text-sm text-loss">Failed to load trades</p>
        <p className="text-xs text-foreground-subtle mt-1">{error.message}</p>
      </div>
    );
  }

  const trades = data?.trades ?? [];

  return (
    <div className="h-full flex flex-col">
      <div className="flex-1 overflow-y-auto p-4 space-y-3">
        {trades.length === 0 ? (
          <EmptyState
            icon={ArrowsRightLeftIcon}
            title="No trades found"
            description={`No trade or dividend activity for ${ticker}`}
          />
        ) : (
          trades.map((t) => (
            <BlossomTradeCard key={t.id} trade={t} showSymbol={false} />
          ))
        )}
      </div>
    </div>
  );
}
```

**Step 2: Verify it compiles**

Run: `cd frontend && npx tsc --noEmit`
Expected: No type errors.

**Step 3: Commit**

```bash
cd frontend
git add src/components/stock/TradesPanel.tsx
git commit -m "feat: wire TradesPanel to unified trades endpoint with BlossomTradeCard"
```

---

### Task 8: Wire Up TradeRecap (Dashboard)

**Files:**
- Modify: `frontend/src/components/dashboard/TradeRecap.tsx` (update to use enriched trades)

**Step 1: Update TradeRecap to use enriched data**

Replace the entire file with the updated version that uses `useRecentTrades` and `BlossomTradeCard`:

```tsx
'use client';

import Link from 'next/link';
import { CardSpotlight } from '@/components/ui/CardSpotlight';
import { useRecentTrades } from '@/hooks/useEnrichedTrades';
import { BlossomTradeCard } from '@/components/trade/BlossomTradeCard';

// ---------------------------------------------------------------------------
// Skeleton loader
// ---------------------------------------------------------------------------

function TradeRecapSkeleton() {
  return (
    <CardSpotlight className="card overflow-hidden animate-pulse">
      <div className="px-5 py-4 border-b border-border flex justify-between">
        <div className="h-5 w-28 bg-background-hover rounded" />
        <div className="h-5 w-16 bg-background-hover rounded" />
      </div>
      <div className="p-4 space-y-3">
        {Array.from({ length: 5 }).map((_, i) => (
          <div key={i} className="flex gap-3">
            <div className="w-1 rounded-full bg-background-hover" />
            <div className="flex-1 space-y-2">
              <div className="h-4 w-32 bg-background-hover rounded" />
              <div className="h-3 w-48 bg-background-hover rounded" />
            </div>
            <div className="h-3 w-14 bg-background-hover rounded self-start" />
          </div>
        ))}
      </div>
    </CardSpotlight>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function TradeRecap() {
  const { data, error, isLoading } = useRecentTrades(10);

  if (isLoading) {
    return <TradeRecapSkeleton />;
  }

  if (error) {
    return (
      <CardSpotlight className="card p-6 text-center">
        <p className="text-loss font-medium">Failed to load trades</p>
        <p className="text-sm text-foreground-muted mt-1">{error.message}</p>
      </CardSpotlight>
    );
  }

  const trades = data?.trades ?? [];

  if (trades.length === 0) {
    return (
      <CardSpotlight className="card p-6 text-center">
        <p className="text-foreground-muted">No recent trades</p>
      </CardSpotlight>
    );
  }

  return (
    <CardSpotlight className="card overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-5 py-4 border-b border-border">
        <h2 className="text-lg font-semibold">Recent Trades</h2>
        <Link
          href="/activity"
          className="text-sm text-primary hover:text-primary-hover transition-colors focus-visible:ring-2 focus-visible:ring-primary rounded"
        >
          View All &rarr;
        </Link>
      </div>

      {/* Trade list */}
      <div className="p-4 space-y-2 stagger-fade-in">
        {trades.map((trade) => (
          <BlossomTradeCard
            key={trade.id}
            trade={trade}
            showSymbol={true}
            compact={true}
          />
        ))}
      </div>
    </CardSpotlight>
  );
}
```

**Step 2: Verify it compiles**

Run: `cd frontend && npx tsc --noEmit`
Expected: No type errors.

**Step 3: Commit**

```bash
cd frontend
git add src/components/dashboard/TradeRecap.tsx
git commit -m "feat: wire TradeRecap dashboard to unified trades with BlossomTradeCard"
```

---

### Task 9: Full Integration Test

**Step 1: Run backend tests**

Run: `pytest tests/ -v -m "not openai and not integration" -x`
Expected: All pass, no regressions.

**Step 2: Run frontend type check**

Run: `cd frontend && npx tsc --noEmit`
Expected: No type errors.

**Step 3: Run frontend build**

Run: `cd frontend && npm run build`
Expected: Build succeeds.

**Step 4: Deploy migration to Supabase**

Run: `python scripts/deploy_database.py`
Expected: Migration 068 applied.

**Step 5: Commit any remaining changes**

If any fixes were needed during integration testing, commit them:

```bash
git add -A
git commit -m "fix: integration fixes for unified trade feed"
```
