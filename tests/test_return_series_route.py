from unittest.mock import MagicMock, patch

import pandas as pd
import pytest


@pytest.fixture
def client():
    with patch.dict("os.environ", {"DISABLE_AUTH": "true"}):
        from fastapi.testclient import TestClient

        from app.main import app
        with TestClient(app) as c:
            yield c


def _mock_row(data: dict):
    row = MagicMock()
    row._mapping = data
    return row


@patch("app.routes.portfolio.get_crypto_price_series")
@patch("app.routes.portfolio.get_ohlcv")
@patch("app.routes.portfolio.execute_sql")
def test_return_series_equity_only(mock_sql, mock_ohlcv, mock_crypto, client):
    mock_sql.return_value = [_mock_row({"symbol": "AAPL", "quantity": 10})]
    df = pd.DataFrame(
        {
            "Open": [100.0, 110.0], "High": [100.0, 110.0], "Low": [100.0, 110.0],
            "Close": [100.0, 110.0], "Volume": [1, 1],
        },
        index=pd.to_datetime(["2026-05-01", "2026-05-02"]),
    )
    mock_ohlcv.return_value = df
    mock_crypto.return_value = {}

    resp = client.get("/portfolio/return-series?period=1M")
    assert resp.status_code == 200
    data = resp.json()
    assert data["period"] == "1M"
    assert data["points"][0]["returnPct"] == 0.0
    assert data["periodReturnPct"] == 10.0
    mock_crypto.assert_not_called()  # equity symbol must not hit crypto fetch


@patch("app.routes.portfolio.get_crypto_price_series")
@patch("app.routes.portfolio.get_ohlcv")
@patch("app.routes.portfolio.execute_sql")
def test_return_series_routes_crypto(mock_sql, mock_ohlcv, mock_crypto, client):
    mock_sql.return_value = [_mock_row({"symbol": "BTC", "quantity": 2})]
    mock_ohlcv.return_value = pd.DataFrame()
    mock_crypto.return_value = {"2026-05-01": 100.0, "2026-05-02": 120.0}

    resp = client.get("/portfolio/return-series?period=1W")
    assert resp.status_code == 200
    data = resp.json()
    assert data["periodReturnPct"] == 20.0
    mock_crypto.assert_called_once()
    mock_ohlcv.assert_not_called()  # crypto symbol must not hit Databento OHLCV


@patch("app.routes.portfolio.get_crypto_price_series")
@patch("app.routes.portfolio.get_ohlcv")
@patch("app.routes.portfolio.execute_sql")
def test_return_series_empty_portfolio(mock_sql, mock_ohlcv, mock_crypto, client):
    mock_sql.return_value = []
    resp = client.get("/portfolio/return-series?period=3M")
    assert resp.status_code == 200
    data = resp.json()
    assert data["points"] == []
    assert data["periodReturnPct"] == 0.0
