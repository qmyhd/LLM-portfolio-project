from unittest.mock import AsyncMock, patch

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
    mock_news.return_value = [
        {"date": "2026-05-01", "title": "Apple WWDC", "url": "u", "source": "s", "text": ""}
    ]
    mock_analysis.return_value = {"overall_signal": "buy", "overall_confidence": 0.62, "summary": "..."}
    mock_sql.return_value = []  # ideas digest empty
    r = client.post("/stocks/AAPL/profile/autofill?bucket=long_term")
    assert r.status_code == 200
    data = r.json()
    assert data["trackRecord"]["tradeCount"] == 5
    assert data["catalysts"][0]["title"] == "Apple WWDC"
    assert data["consensus"]["overall_signal"] == "buy"
    mock_analysis.assert_awaited_once()
