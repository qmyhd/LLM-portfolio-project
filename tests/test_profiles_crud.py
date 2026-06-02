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
    r = MagicMock()
    r._mapping = d
    return r


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
