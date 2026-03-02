"""Tests for GET /orders API route — action filter and UUID symbol guard."""

import os
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


def _mock_row(data: dict):
    """Create a mock SQLAlchemy Row with _mapping."""
    row = MagicMock()
    row._mapping = data
    return row


def _make_order_row(
    symbol="AAPL",
    action="BUY",
    order_id="ord-001",
    quantity=10,
    execution_price=150.0,
    status="filled",
):
    """Helper to build a mock order row with sensible defaults."""
    return _mock_row(
        {
            "id": order_id,
            "symbol": symbol,
            "side": action,
            "type": "market",
            "quantity": quantity,
            "filled_quantity": quantity,
            "limit_price": None,
            "stop_price": None,
            "execution_price": execution_price,
            "status": status,
            "time_placed": "2026-02-28T10:00:00",
            "time_executed": "2026-02-28T10:00:01",
            "notified": False,
        }
    )


def _count_row(total: int):
    """Helper to build a mock count row."""
    return _mock_row({"total": total})


@pytest.fixture
def client():
    """Create test client with auth disabled."""
    os.environ["DISABLE_AUTH"] = "true"
    from app.main import app

    return TestClient(app)


class TestDefaultActionFilter:
    """Default query should include only trade-relevant actions (BUY/SELL/etc.)."""

    @patch("app.routes.orders.execute_sql")
    def test_default_includes_action_filter(self, mock_sql, client):
        """Without include_drip, the SQL should filter to TRADE_ACTIONS only."""
        mock_sql.side_effect = [
            [_make_order_row(action="BUY")],  # main query
            [_count_row(1)],  # count query
        ]

        response = client.get("/orders")
        assert response.status_code == 200

        # Inspect the SQL query that was called
        main_call = mock_sql.call_args_list[0]
        query_str = main_call[0][0] if main_call[0] else main_call[1].get("query", "")
        params = main_call[1].get("params", main_call[0][1] if len(main_call[0]) > 1 else {})

        # The query should contain the IN clause for action filtering
        assert "UPPER(o.action) IN" in query_str
        # The params should include the trade actions
        assert params["act_0"] == "BUY"
        assert params["act_1"] == "SELL"
        assert params["act_2"] == "BUY_OPEN"
        assert params["act_3"] == "SELL_CLOSE"
        assert params["act_4"] == "BUY_TO_COVER"
        assert params["act_5"] == "SELL_SHORT"

    @patch("app.routes.orders.execute_sql")
    def test_include_drip_true_no_action_filter(self, mock_sql, client):
        """With include_drip=true, the SQL should NOT filter by action."""
        mock_sql.side_effect = [
            [_make_order_row(action="DRIP")],  # main query
            [_count_row(1)],  # count query
        ]

        response = client.get("/orders?include_drip=true")
        assert response.status_code == 200

        # Inspect the SQL query — should NOT have action filter
        main_call = mock_sql.call_args_list[0]
        query_str = main_call[0][0] if main_call[0] else main_call[1].get("query", "")

        assert "UPPER(o.action) IN" not in query_str

        # Verify the DRIP order is returned
        data = response.json()
        assert len(data["orders"]) == 1
        assert data["orders"][0]["action"] == "DRIP"

    @patch("app.routes.orders.execute_sql")
    def test_action_filter_applied_to_count_query(self, mock_sql, client):
        """The action filter should also be applied to the COUNT query."""
        mock_sql.side_effect = [
            [],  # main query — no results
            [_count_row(0)],  # count query
        ]

        response = client.get("/orders")
        assert response.status_code == 200

        # Both the main query and count query should have the action filter
        assert mock_sql.call_count == 2
        count_call = mock_sql.call_args_list[1]
        count_query_str = count_call[0][0] if count_call[0] else count_call[1].get("query", "")
        count_params = count_call[1].get("params", count_call[0][1] if len(count_call[0]) > 1 else {})

        assert "UPPER(o.action) IN" in count_query_str
        assert "act_0" in count_params
        # limit and offset should NOT be in count params
        assert "limit" not in count_params
        assert "offset" not in count_params


class TestUUIDSymbolGuard:
    """UUID-like symbols should be replaced with 'Unknown'."""

    @patch("app.routes.orders.execute_sql")
    def test_uuid_symbol_replaced(self, mock_sql, client):
        """An order with a UUID symbol should have it replaced with 'Unknown'."""
        mock_sql.side_effect = [
            [_make_order_row(symbol="c4caf1cc-1234-5678-abcd-ef0123456789")],
            [_count_row(1)],
        ]

        response = client.get("/orders")
        assert response.status_code == 200
        data = response.json()
        assert data["orders"][0]["symbol"] == "Unknown"

    @patch("app.routes.orders.execute_sql")
    def test_uppercase_uuid_replaced(self, mock_sql, client):
        """UUID detection should be case-insensitive."""
        mock_sql.side_effect = [
            [_make_order_row(symbol="C4CAF1CC-1234-5678-ABCD-EF0123456789")],
            [_count_row(1)],
        ]

        response = client.get("/orders")
        assert response.status_code == 200
        data = response.json()
        assert data["orders"][0]["symbol"] == "Unknown"

    @patch("app.routes.orders.execute_sql")
    def test_normal_symbol_passes_through(self, mock_sql, client):
        """A normal ticker symbol should pass through unchanged."""
        mock_sql.side_effect = [
            [_make_order_row(symbol="NVDA")],
            [_count_row(1)],
        ]

        response = client.get("/orders")
        assert response.status_code == 200
        data = response.json()
        assert data["orders"][0]["symbol"] == "NVDA"

    @patch("app.routes.orders.execute_sql")
    def test_dotted_symbol_passes_through(self, mock_sql, client):
        """A dotted ticker like BRK.B should pass through unchanged."""
        mock_sql.side_effect = [
            [_make_order_row(symbol="BRK.B")],
            [_count_row(1)],
        ]

        response = client.get("/orders")
        assert response.status_code == 200
        data = response.json()
        assert data["orders"][0]["symbol"] == "BRK.B"

    @patch("app.routes.orders.execute_sql")
    def test_null_symbol_becomes_unknown(self, mock_sql, client):
        """A None symbol should become UNKNOWN (existing behavior)."""
        mock_sql.side_effect = [
            [_make_order_row(symbol=None)],
            [_count_row(1)],
        ]

        response = client.get("/orders")
        assert response.status_code == 200
        data = response.json()
        # None falls through to "UNKNOWN" before UUID check
        assert data["orders"][0]["symbol"] == "UNKNOWN"

    @patch("app.routes.orders.execute_sql")
    def test_mixed_orders_uuid_and_normal(self, mock_sql, client):
        """Mixed batch: UUID symbol cleaned, normal symbol preserved."""
        mock_sql.side_effect = [
            [
                _make_order_row(symbol="AAPL", order_id="ord-001"),
                _make_order_row(symbol="49594270-abcd-4321-9876-fedcba987654", order_id="ord-002"),
                _make_order_row(symbol="TSLA", order_id="ord-003"),
            ],
            [_count_row(3)],
        ]

        response = client.get("/orders")
        assert response.status_code == 200
        data = response.json()
        symbols = [o["symbol"] for o in data["orders"]]
        assert symbols == ["AAPL", "Unknown", "TSLA"]
