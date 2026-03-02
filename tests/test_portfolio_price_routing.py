"""
Tests for crypto vs equity price routing in portfolio endpoint.

Verifies that crypto symbols are NEVER sent to Databento (ohlcv_daily)
and always routed through yfinance with -USD suffix.
"""

from unittest.mock import MagicMock, patch
import pytest


@pytest.fixture
def client():
    """Create test client with auth disabled."""
    with patch.dict("os.environ", {"DISABLE_AUTH": "true"}):
        from app.main import app
        from fastapi.testclient import TestClient
        with TestClient(app) as c:
            yield c


def _mock_row(data: dict):
    row = MagicMock()
    row._mapping = data
    return row


class TestDayChangeGuardrails:
    """Day change % must use provider 24h for crypto, cap at 300% for equity."""

    @patch("app.routes.portfolio.get_realtime_quotes_batch")
    @patch("app.routes.portfolio.get_previous_closes_batch")
    @patch("app.routes.portfolio.get_latest_closes_batch")
    @patch("app.routes.portfolio.execute_sql")
    def test_crypto_uses_provider_24h_change(
        self, mock_sql, mock_latest, mock_prev, mock_yf, client
    ):
        """Crypto day change should come from yfinance provider, not computed."""
        mock_sql.side_effect = [
            [_mock_row({
                "symbol": "TRUMP", "quantity": 15, "average_cost": 5.0,
                "snaptrade_price": 3.43, "raw_symbol": "TRUMP",
                "account_id": "acc1", "asset_type": "Cryptocurrency",
                "company_name": "TRUMP",
            })],
            [_mock_row({"total_cash": 0, "total_buying_power": 0})],
            [_mock_row({"last_update": "2026-03-01T18:00:00+00:00"})],
            [_mock_row({"status": "connected"})],
        ]
        mock_latest.return_value = {}
        mock_prev.return_value = {}
        mock_yf.return_value = {
            "TRUMP": {"price": 3.43, "previousClose": 3.50, "dayChange": -0.07, "dayChangePct": -2.0},
        }

        response = client.get("/portfolio")
        data = response.json()
        trump = next(p for p in data["positions"] if p["symbol"] == "TRUMP")
        # Should use provider's -2.0%, not compute from some random prev_close
        assert trump["dayChangePercent"] == -2.0

    @patch("app.routes.portfolio.get_realtime_quotes_batch")
    @patch("app.routes.portfolio.get_previous_closes_batch")
    @patch("app.routes.portfolio.get_latest_closes_batch")
    @patch("app.routes.portfolio.execute_sql")
    def test_equity_absurd_pct_nulled(
        self, mock_sql, mock_latest, mock_prev, mock_yf, client
    ):
        """Equity day change > 300% should be set to null."""
        mock_sql.side_effect = [
            [_mock_row({
                "symbol": "AAPL", "quantity": 10, "average_cost": 150,
                "snaptrade_price": 178, "raw_symbol": "AAPL",
                "account_id": "acc1", "asset_type": "Common Stock",
                "company_name": "Apple Inc.",
            })],
            [_mock_row({"total_cash": 0, "total_buying_power": 0})],
            [_mock_row({"last_update": "2026-03-01T18:00:00+00:00"})],
            [_mock_row({"status": "connected"})],
        ]
        mock_latest.return_value = {"AAPL": 178.0}
        mock_prev.return_value = {"AAPL": 0.50}  # Absurd → 35500% change
        mock_yf.return_value = {}

        response = client.get("/portfolio")
        data = response.json()
        aapl = next(p for p in data["positions"] if p["symbol"] == "AAPL")
        assert aapl["dayChangePercent"] is None
        assert aapl["dayChange"] is None

    @patch("app.routes.portfolio.get_realtime_quotes_batch")
    @patch("app.routes.portfolio.get_previous_closes_batch")
    @patch("app.routes.portfolio.get_latest_closes_batch")
    @patch("app.routes.portfolio.execute_sql")
    def test_equity_missing_prev_close_nulled(
        self, mock_sql, mock_latest, mock_prev, mock_yf, client
    ):
        """Equity with no prev_close should have null day change."""
        mock_sql.side_effect = [
            [_mock_row({
                "symbol": "AAPL", "quantity": 10, "average_cost": 150,
                "snaptrade_price": 178, "raw_symbol": "AAPL",
                "account_id": "acc1", "asset_type": "Common Stock",
                "company_name": "Apple Inc.",
            })],
            [_mock_row({"total_cash": 0, "total_buying_power": 0})],
            [_mock_row({"last_update": "2026-03-01T18:00:00+00:00"})],
            [_mock_row({"status": "connected"})],
        ]
        mock_latest.return_value = {"AAPL": 178.0}
        mock_prev.return_value = {}
        mock_yf.return_value = {}

        response = client.get("/portfolio")
        data = response.json()
        aapl = next(p for p in data["positions"] if p["symbol"] == "AAPL")
        assert aapl["dayChangePercent"] is None


class TestCryptoPriceRouting:
    """Crypto symbols must never hit Databento; always use yfinance."""

    @patch("app.routes.portfolio.get_realtime_quotes_batch")
    @patch("app.routes.portfolio.get_previous_closes_batch")
    @patch("app.routes.portfolio.get_latest_closes_batch")
    @patch("app.routes.portfolio.execute_sql")
    def test_crypto_excluded_from_databento(
        self, mock_sql, mock_latest, mock_prev, mock_yf, client
    ):
        """BTC position should not be passed to Databento batch queries."""
        mock_sql.side_effect = [
            # 1) positions query
            [
                _mock_row({
                    "symbol": "BTC", "quantity": 0.001, "average_cost": 50000,
                    "snaptrade_price": 65000, "raw_symbol": "BTC",
                    "account_id": "acc1", "asset_type": "Cryptocurrency",
                    "company_name": "Bitcoin",
                }),
                _mock_row({
                    "symbol": "AAPL", "quantity": 10, "average_cost": 150,
                    "snaptrade_price": 175, "raw_symbol": "AAPL",
                    "account_id": "acc1", "asset_type": "Common Stock",
                    "company_name": "Apple Inc.",
                }),
            ],
            # 2) account_balances query (uses SQL aliases total_cash, total_buying_power)
            [_mock_row({"total_cash": 100, "total_buying_power": 200})],
            # 3) last_updated query (MAX(sync_timestamp) as last_update)
            [_mock_row({"last_update": "2026-03-01T18:00:00+00:00"})],
            # 4) connection status query (COALESCE(connection_status, 'connected') as status)
            [_mock_row({"status": "connected"})],
        ]
        mock_latest.return_value = {"AAPL": 178.0}
        mock_prev.return_value = {"AAPL": 176.0}
        mock_yf.return_value = {
            "BTC": {"price": 65842.71, "previousClose": 65000.0, "dayChange": 842.71, "dayChangePct": 1.30},
        }

        response = client.get("/portfolio")
        assert response.status_code == 200

        # Verify Databento was called with ONLY equity symbols
        latest_call_args = mock_latest.call_args[0][0]
        assert "BTC" not in latest_call_args, "BTC should NOT be sent to Databento"
        assert "AAPL" in latest_call_args, "AAPL should be sent to Databento"

        prev_call_args = mock_prev.call_args[0][0]
        assert "BTC" not in prev_call_args, "BTC should NOT be in prev_closes query"

        # Verify yfinance was called with BTC
        yf_call_args = mock_yf.call_args[0][0]
        assert "BTC" in yf_call_args, "BTC must be routed to yfinance"

    @patch("app.routes.portfolio.get_realtime_quotes_batch")
    @patch("app.routes.portfolio.get_previous_closes_batch")
    @patch("app.routes.portfolio.get_latest_closes_batch")
    @patch("app.routes.portfolio.execute_sql")
    def test_crypto_gets_yfinance_price(
        self, mock_sql, mock_latest, mock_prev, mock_yf, client
    ):
        """Crypto position price should come from yfinance, not Databento."""
        mock_sql.side_effect = [
            # 1) positions query
            [_mock_row({
                "symbol": "XRP", "quantity": 50, "average_cost": 1.0,
                "snaptrade_price": 1.35, "raw_symbol": "XRP",
                "account_id": "acc1", "asset_type": "Cryptocurrency",
                "company_name": "XRP",
            })],
            # 2) account_balances query
            [_mock_row({"total_cash": 0, "total_buying_power": 0})],
            # 3) last_updated query
            [_mock_row({"last_update": "2026-03-01T18:00:00+00:00"})],
            # 4) connection status query
            [_mock_row({"status": "connected"})],
        ]
        mock_latest.return_value = {}  # Databento should return nothing for crypto
        mock_prev.return_value = {}
        mock_yf.return_value = {
            "XRP": {"price": 1.353, "previousClose": 1.30, "dayChange": 0.053, "dayChangePct": 4.08},
        }

        response = client.get("/portfolio")
        data = response.json()
        assert response.status_code == 200

        xrp = next(p for p in data["positions"] if p["symbol"] == "XRP")
        assert xrp["currentPrice"] == 1.35  # yfinance price rounded to 2dp
        assert xrp["assetType"] == "crypto"


class TestMoversEndpoint:
    """Movers must also use crypto-safe price routing."""

    @patch("app.routes.portfolio.get_realtime_quotes_batch")
    @patch("app.routes.portfolio.get_previous_closes_batch")
    @patch("app.routes.portfolio.get_latest_closes_batch")
    @patch("app.routes.portfolio.execute_sql")
    def test_movers_crypto_not_sent_to_databento(
        self, mock_sql, mock_latest, mock_prev, mock_yf, client
    ):
        """Crypto symbols should be routed to yfinance in movers endpoint too."""
        mock_sql.return_value = [
            _mock_row({"symbol": "BTC", "quantity": 0.001, "average_cost": 50000, "snaptrade_price": 65000}),
            _mock_row({"symbol": "AAPL", "quantity": 10, "average_cost": 150, "snaptrade_price": 178}),
        ]
        mock_latest.return_value = {"AAPL": 178.0}
        mock_prev.return_value = {"AAPL": 176.0}
        mock_yf.return_value = {
            "BTC": {"price": 65842.71, "previousClose": 65000.0, "dayChange": 842.71, "dayChangePct": 1.30},
        }

        response = client.get("/portfolio/movers?limit=3")
        assert response.status_code == 200

        # Databento should only get equity symbols
        latest_args = mock_latest.call_args[0][0]
        assert "BTC" not in latest_args

    @patch("app.routes.portfolio.get_realtime_quotes_batch")
    @patch("app.routes.portfolio.get_previous_closes_batch")
    @patch("app.routes.portfolio.get_latest_closes_batch")
    @patch("app.routes.portfolio.execute_sql")
    def test_movers_absurd_equity_pct_excluded(
        self, mock_sql, mock_latest, mock_prev, mock_yf, client
    ):
        """Equity with absurd day change should have null dayChangePct in movers."""
        mock_sql.return_value = [
            _mock_row({"symbol": "BAD", "quantity": 5, "average_cost": 100, "snaptrade_price": 50}),
        ]
        mock_latest.return_value = {"BAD": 50.0}
        mock_prev.return_value = {"BAD": 0.10}  # produces 49900% change
        mock_yf.return_value = {}

        response = client.get("/portfolio/movers?limit=3")
        data = response.json()
        # BAD should not appear as a gainer/loser with absurd % since dayChangePct is null
        all_symbols = [g["symbol"] for g in data["topGainers"]] + [l["symbol"] for l in data["topLosers"]]
        # If BAD appears, its dayChangePct should be null (using openPnlPct fallback)
        if data["topGainers"] or data["topLosers"]:
            items = data["topGainers"] + data["topLosers"]
            for item in items:
                if item["symbol"] == "BAD":
                    assert item["dayChangePct"] is None
