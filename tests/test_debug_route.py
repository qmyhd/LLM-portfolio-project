"""Tests for GET /debug/symbol-trace endpoint."""

import importlib
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


def _mock_row(data: dict):
    row = MagicMock()
    row._mapping = data
    return row


@pytest.fixture
def client_with_debug():
    """Test client with debug endpoints enabled."""
    with patch.dict("os.environ", {"DISABLE_AUTH": "true", "DEBUG_ENDPOINTS": "1"}):
        import app.main

        importlib.reload(app.main)
        with TestClient(app.main.app) as c:
            yield c
        # Reload again to restore default state
        with patch.dict("os.environ", {"DISABLE_AUTH": "true", "DEBUG_ENDPOINTS": ""}):
            importlib.reload(app.main)


class TestSymbolTrace:
    @patch("app.routes.debug.get_realtime_quotes_batch")
    @patch("app.routes.debug.get_latest_closes_batch")
    @patch("app.routes.debug.execute_sql")
    def test_crypto_trace(self, mock_sql, mock_databento, mock_yf, client_with_debug):
        """XRP crypto trace should show correct identity and price resolution."""
        mock_sql.side_effect = [
            [_mock_row({"symbol": "XRP", "asset_type": "Cryptocurrency", "price": 1.35,
                        "quantity": 50, "equity": 67.5, "account_id": "acc1",
                        "sync_timestamp": "2026-03-01T18:00:00"})],
            [_mock_row({"ticker": "XRP", "asset_type": "Cryptocurrency",
                        "type_code": "crypto", "exchange_code": None})],
            [],  # activities
            [],  # orders
        ]
        mock_databento.return_value = {}
        mock_yf.return_value = {
            "XRP": {"price": 1.353, "previousClose": 1.30, "dayChange": 0.053, "dayChangePct": 4.08},
        }

        response = client_with_debug.get("/debug/symbol-trace?symbol=XRP")
        assert response.status_code == 200
        data = response.json()
        assert data["is_crypto"] is True
        assert data["tv_symbol"] == "COINBASE:XRPUSD"
        assert data["canonical_quote_symbol"] == "XRP-USD"
        assert data["price_resolution"]["selected_source"] in ("yfinance", "snaptrade")
        assert data["price_resolution"]["yfinance_price"] == 1.353

    @patch("app.routes.debug.get_realtime_quotes_batch")
    @patch("app.routes.debug.get_latest_closes_batch")
    @patch("app.routes.debug.execute_sql")
    def test_equity_trace(self, mock_sql, mock_databento, mock_yf, client_with_debug):
        """NVDA equity trace should use Databento and have no crypto identity."""
        mock_sql.side_effect = [
            [_mock_row({"symbol": "NVDA", "asset_type": "Common Stock", "price": 177.80,
                        "quantity": 8, "equity": 1422.40, "account_id": "acc1",
                        "sync_timestamp": "2026-03-01T18:00:00"})],
            [_mock_row({"ticker": "NVDA", "asset_type": "Common Stock",
                        "type_code": "cs", "exchange_code": "XNAS"})],
            [],  # activities
            [],  # orders
        ]
        mock_databento.return_value = {"NVDA": 177.80}
        mock_yf.return_value = {}

        response = client_with_debug.get("/debug/symbol-trace?symbol=NVDA")
        assert response.status_code == 200
        data = response.json()
        assert data["is_crypto"] is False
        assert data["tv_symbol"] is None  # equities don't have crypto identity
        assert data["price_resolution"]["databento_hit"] is True
        assert data["price_resolution"]["selected_source"] == "databento"
