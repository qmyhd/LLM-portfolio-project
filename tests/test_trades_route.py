"""
Tests for app/routes/trades.py — unified trades endpoints.

Tests cover:
- GET /stocks/{ticker}/trades — per-stock trade history with enrichment
- GET /trades/recent — dashboard recent trades across all stocks
- Deduplication logic (activities preferred over orders)
- P/L enrichment calculations
"""

import os
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_row(data: dict):
    """Create a mock SQLAlchemy Row with _mapping."""
    row = MagicMock()
    row._mapping = data
    return row


def _make_activity_row(
    symbol="AAPL",
    side="BUY",
    activity_id="act-001",
    price=150.0,
    units=10.0,
    amount=1500.0,
    fee=1.50,
    executed_at="2026-02-28 10:30:00",
    description="Buy 10 AAPL",
):
    """Helper to build a mock activity row."""
    return _mock_row({
        "id": activity_id,
        "symbol": symbol,
        "side": side,
        "price": price,
        "units": units,
        "amount": amount,
        "fee": fee,
        "executed_at": executed_at,
        "description": description,
    })


def _make_order_row(
    symbol="AAPL",
    side="BUY",
    order_id="ord-001",
    price=150.0,
    units=10.0,
    amount=1500.0,
    executed_at="2026-02-28 10:30:00",
):
    """Helper to build a mock order row."""
    return _mock_row({
        "id": order_id,
        "symbol": symbol,
        "side": side,
        "price": price,
        "units": units,
        "amount": amount,
        "fee": 0,
        "executed_at": executed_at,
        "description": None,
    })


def _make_position_row(
    symbol="AAPL",
    quantity=100.0,
    average_buy_price=145.0,
    current_price=155.0,
):
    """Helper to build a mock position row."""
    return _mock_row({
        "symbol": symbol,
        "quantity": quantity,
        "average_buy_price": average_buy_price,
        "current_price": current_price,
    })


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def client():
    """Create test client with auth disabled."""
    with patch.dict("os.environ", {"DISABLE_AUTH": "true"}):
        from app.main import app
        with TestClient(app) as c:
            yield c


# =========================================================================
# GET /stocks/{ticker}/trades — per-stock trades
# =========================================================================

class TestGetStockTrades:
    """Tests for the per-stock trade history endpoint."""

    @patch("app.routes.trades.execute_sql")
    def test_returns_activities_as_enriched_trades(self, mock_sql, client):
        """Activities are returned as enriched trades with position data."""
        mock_sql.side_effect = [
            # 1. activities query
            [_make_activity_row(symbol="AAPL", price=150.0, units=10.0, amount=1500.0)],
            # 2. orders query
            [],
            # 3. position for this symbol
            [_make_position_row(symbol="AAPL", quantity=100, average_buy_price=145.0, current_price=155.0)],
            # 4. all positions (total portfolio value)
            [_make_position_row(symbol="AAPL", quantity=100, average_buy_price=145.0, current_price=155.0)],
        ]

        resp = client.get("/stocks/AAPL/trades")
        assert resp.status_code == 200
        data = resp.json()

        assert data["ticker"] == "AAPL"
        assert data["total"] == 1
        assert len(data["trades"]) == 1

        trade = data["trades"][0]
        assert trade["symbol"] == "AAPL"
        assert trade["type"] == "BUY"
        assert trade["source"] == "activity"
        assert trade["price"] == 150.0
        assert trade["units"] == 10.0
        assert trade["fee"] == 1.5

        # Position enrichment
        assert trade["currentPrice"] == 155.0
        assert trade["avgCost"] == 145.0
        assert trade["totalShares"] == 100.0

        # P/L: BUY trade => unrealizedPnl = (currentPrice - avgCost) * units
        assert trade["unrealizedPnl"] == (155.0 - 145.0) * 10.0

    @patch("app.routes.trades.execute_sql")
    def test_returns_orders_when_no_activities(self, mock_sql, client):
        """Orders are returned when no activities exist for the symbol."""
        mock_sql.side_effect = [
            # 1. activities query — empty
            [],
            # 2. orders query
            [_make_order_row(symbol="TSLA", side="BUY", price=200.0, units=5.0, amount=1000.0)],
            # 3. position for this symbol
            [],
            # 4. all positions
            [],
        ]

        resp = client.get("/stocks/TSLA/trades")
        assert resp.status_code == 200
        data = resp.json()

        assert data["ticker"] == "TSLA"
        assert data["total"] == 1
        assert len(data["trades"]) == 1

        trade = data["trades"][0]
        assert trade["source"] == "order"
        assert trade["symbol"] == "TSLA"
        assert trade["type"] == "BUY"
        assert trade["price"] == 200.0
        assert trade["fee"] == 0  # orders don't have fee data

    @patch("app.routes.trades.execute_sql")
    def test_deduplication_prefers_activity(self, mock_sql, client):
        """When both sources have same trade, activity is kept (has fee data)."""
        # Same symbol, same minute, same amount => dedup
        mock_sql.side_effect = [
            # 1. activities query — one trade
            [_make_activity_row(
                symbol="AAPL", side="BUY", price=150.0, units=10.0,
                amount=1500.0, fee=1.50, executed_at="2026-02-28 10:30:00",
            )],
            # 2. orders query — same trade from orders perspective
            [_make_order_row(
                symbol="AAPL", side="BUY", price=150.0, units=10.0,
                amount=1500.0, executed_at="2026-02-28 10:30:00",
            )],
            # 3. position
            [],
            # 4. all positions
            [],
        ]

        resp = client.get("/stocks/AAPL/trades")
        assert resp.status_code == 200
        data = resp.json()

        # Should be deduplicated to 1 trade
        assert data["total"] == 1
        assert len(data["trades"]) == 1

        trade = data["trades"][0]
        # Activity is preferred (has fee data)
        assert trade["source"] == "activity"
        assert trade["fee"] == 1.5

    @patch("app.routes.trades.execute_sql")
    def test_different_times_not_deduplicated(self, mock_sql, client):
        """Trades at different times are not deduplicated."""
        mock_sql.side_effect = [
            # 1. activities
            [_make_activity_row(
                symbol="AAPL", activity_id="act-001",
                executed_at="2026-02-28 10:30:00", amount=1500.0,
            )],
            # 2. orders — different time
            [_make_order_row(
                symbol="AAPL", order_id="ord-001",
                executed_at="2026-02-28 14:00:00", amount=1500.0,
            )],
            # 3. position
            [],
            # 4. all positions
            [],
        ]

        resp = client.get("/stocks/AAPL/trades")
        assert resp.status_code == 200
        data = resp.json()

        # Both trades should be returned (different times)
        assert data["total"] == 2
        assert len(data["trades"]) == 2

    @patch("app.routes.trades.execute_sql")
    def test_sell_trade_has_realized_pnl(self, mock_sql, client):
        """SELL trades get realizedPnl calculation."""
        mock_sql.side_effect = [
            # 1. activities — a SELL trade
            [_make_activity_row(
                symbol="AAPL", side="SELL", price=160.0, units=10.0,
                amount=1600.0, fee=1.0,
            )],
            # 2. orders
            [],
            # 3. position (still has shares, avg cost $145)
            [_make_position_row(symbol="AAPL", quantity=90, average_buy_price=145.0, current_price=155.0)],
            # 4. all positions
            [_make_position_row(symbol="AAPL", quantity=90, average_buy_price=145.0, current_price=155.0)],
        ]

        resp = client.get("/stocks/AAPL/trades")
        assert resp.status_code == 200
        data = resp.json()

        trade = data["trades"][0]
        assert trade["type"] == "SELL"
        # realizedPnl = (salePrice - avgCost) * units = (160 - 145) * 10 = 150
        assert trade["realizedPnl"] == 150.0
        # realizedPnlPct = (160 - 145) / 145 * 100 ≈ 10.34%
        assert trade["realizedPnlPct"] == pytest.approx(10.34, abs=0.01)
        assert trade["unrealizedPnl"] is None

    @patch("app.routes.trades.execute_sql")
    def test_empty_result(self, mock_sql, client):
        """No trades returns empty list."""
        mock_sql.side_effect = [
            [],  # activities
            [],  # orders
            [],  # position
            [],  # all positions
        ]

        resp = client.get("/stocks/AAPL/trades")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ticker"] == "AAPL"
        assert data["trades"] == []
        assert data["total"] == 0

    @patch("app.routes.trades.execute_sql")
    def test_error_returns_empty_gracefully(self, mock_sql, client):
        """Database errors return empty response, not 500."""
        mock_sql.side_effect = Exception("DB connection failed")

        resp = client.get("/stocks/AAPL/trades")
        assert resp.status_code == 200
        data = resp.json()
        assert data["trades"] == []
        assert data["total"] == 0


# =========================================================================
# GET /trades/recent — dashboard recent trades
# =========================================================================

class TestGetRecentTrades:
    """Tests for the dashboard recent trades endpoint."""

    @patch("app.routes.trades.execute_sql")
    def test_recent_trades_returns_results(self, mock_sql, client):
        """Recent trades endpoint returns enriched trades."""
        mock_sql.side_effect = [
            # 1. activities
            [
                _make_activity_row(symbol="AAPL", side="BUY", amount=1500.0, executed_at="2026-02-28 10:30:00"),
                _make_activity_row(symbol="TSLA", side="SELL", amount=2000.0,
                                   activity_id="act-002", executed_at="2026-02-27 14:00:00", price=400.0, units=5.0),
            ],
            # 2. orders
            [],
            # 3. all positions
            [
                _make_position_row(symbol="AAPL", quantity=100, average_buy_price=145.0, current_price=155.0),
                _make_position_row(symbol="TSLA", quantity=10, average_buy_price=350.0, current_price=390.0),
            ],
        ]

        resp = client.get("/trades/recent")
        assert resp.status_code == 200
        data = resp.json()

        assert data["total"] == 2
        assert len(data["trades"]) == 2
        # Most recent first
        assert data["trades"][0]["symbol"] == "AAPL"
        assert data["trades"][1]["symbol"] == "TSLA"

    @patch("app.routes.trades.execute_sql")
    def test_recent_trades_deduplicates(self, mock_sql, client):
        """Recent trades also deduplicates across sources."""
        mock_sql.side_effect = [
            # 1. activities — one BUY
            [_make_activity_row(
                symbol="AAPL", side="BUY", amount=1500.0,
                executed_at="2026-02-28 10:30:00", fee=1.5,
            )],
            # 2. orders — same trade
            [_make_order_row(
                symbol="AAPL", side="BUY", amount=1500.0,
                executed_at="2026-02-28 10:30:00",
            )],
            # 3. all positions
            [],
        ]

        resp = client.get("/trades/recent")
        assert resp.status_code == 200
        data = resp.json()

        assert data["total"] == 1
        assert data["trades"][0]["source"] == "activity"

    @patch("app.routes.trades.execute_sql")
    def test_recent_trades_empty(self, mock_sql, client):
        """No recent trades returns empty list."""
        mock_sql.side_effect = [
            [],  # activities
            [],  # orders
            [],  # all positions
        ]

        resp = client.get("/trades/recent")
        assert resp.status_code == 200
        data = resp.json()
        assert data["trades"] == []
        assert data["total"] == 0

    @patch("app.routes.trades.execute_sql")
    def test_recent_trades_limit_param(self, mock_sql, client):
        """Limit parameter controls number of returned trades."""
        # Create 5 activities with different times
        activities = [
            _make_activity_row(
                symbol="AAPL", activity_id=f"act-{i:03d}",
                amount=100.0 * (i + 1),
                executed_at=f"2026-02-{28 - i} 10:00:00",
            )
            for i in range(5)
        ]

        mock_sql.side_effect = [
            activities,  # activities
            [],  # orders
            [],  # all positions
        ]

        resp = client.get("/trades/recent?limit=3")
        assert resp.status_code == 200
        data = resp.json()

        assert len(data["trades"]) == 3
        assert data["total"] == 5  # total before limiting

    @patch("app.routes.trades.execute_sql")
    def test_recent_trades_error_returns_empty(self, mock_sql, client):
        """Database errors return empty response, not 500."""
        mock_sql.side_effect = Exception("DB connection failed")

        resp = client.get("/trades/recent")
        assert resp.status_code == 200
        data = resp.json()
        assert data["trades"] == []
        assert data["total"] == 0


# =========================================================================
# Unit tests for helper functions
# =========================================================================

class TestHelperFunctions:
    """Tests for the internal helper functions."""

    def test_round_minute(self):
        """_round_minute truncates to minute precision."""
        from app.routes.trades import _round_minute

        assert _round_minute("2026-02-28 10:30:45") == "2026-02-28 10:30"
        assert _round_minute("2026-02-28T10:30:45.123456") == "2026-02-28 10:30"
        assert _round_minute("2026-02-28T10:30:45+00:00") == "2026-02-28 10:30"
        assert _round_minute(None) is None
        assert _round_minute("") is None

    def test_dedup_key(self):
        """_dedup_key generates consistent keys."""
        from app.routes.trades import _dedup_key

        key1 = _dedup_key("AAPL", "2026-02-28 10:30:45", 1500.0)
        key2 = _dedup_key("aapl", "2026-02-28 10:30:59", 1500.0)
        # Same symbol (case-insensitive), same minute, same amount => same key
        assert key1 == key2

        key3 = _dedup_key("AAPL", "2026-02-28 10:31:00", 1500.0)
        # Different minute => different key
        assert key1 != key3

    def test_merge_and_dedup_prefers_activities(self):
        """_merge_and_dedup keeps activity when both match."""
        from app.routes.trades import _merge_and_dedup

        activity = {
            "id": "act-001",
            "symbol": "AAPL",
            "side": "BUY",
            "price": 150.0,
            "units": 10.0,
            "amount": 1500.0,
            "fee": 1.5,
            "executed_at": "2026-02-28 10:30:00",
            "source": "activity",
        }
        order = {
            "id": "ord-001",
            "symbol": "AAPL",
            "side": "BUY",
            "price": 150.0,
            "units": 10.0,
            "amount": 1500.0,
            "fee": 0,
            "executed_at": "2026-02-28 10:30:00",
            "source": "order",
        }

        result = _merge_and_dedup([activity], [order])
        assert len(result) == 1
        assert result[0]["source"] == "activity"
        assert result[0]["fee"] == 1.5

    def test_merge_and_dedup_keeps_unique_orders(self):
        """_merge_and_dedup keeps orders that have no matching activity."""
        from app.routes.trades import _merge_and_dedup

        activity = {
            "id": "act-001",
            "symbol": "AAPL",
            "amount": 1500.0,
            "executed_at": "2026-02-28 10:30:00",
            "source": "activity",
        }
        order = {
            "id": "ord-001",
            "symbol": "TSLA",
            "amount": 2000.0,
            "executed_at": "2026-02-28 14:00:00",
            "source": "order",
        }

        result = _merge_and_dedup([activity], [order])
        assert len(result) == 2
        sources = {r["source"] for r in result}
        assert sources == {"activity", "order"}
