from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from src.analysis.models import AnalystSignal, ConsensusReport


@pytest.fixture
def client():
    with patch.dict("os.environ", {"DISABLE_AUTH": "true"}):
        from fastapi.testclient import TestClient

        from app.main import app
        with TestClient(app) as c:
            yield c


# --------------------------------------------------------------------------- #
# E4 — credibility breakdown surfaces verbatim in the analysis payload
# --------------------------------------------------------------------------- #


@patch("app.routes.analysis.get_stock_analysis", new_callable=AsyncMock)
def test_credibility_breakdown_surfaces_in_analysis_payload(mock_analysis, client):
    signal = AnalystSignal(
        agent_id="sentiment",
        signal="bullish",
        confidence=0.5,
        reasoning="x",
        metrics={
            "credibility": {
                "baseline_score": 0.4,
                "adjusted_score": 0.5,
                "delta": 0.1,
                "contributors": [],
            }
        },
    )
    report = ConsensusReport(
        ticker="AAPL",
        overall_signal="buy",
        overall_confidence=0.5,
        bull_bear_score=0.5,
        agent_signals=[signal],
        summary="s",
        data_sources=[],
        computed_at=datetime(2026, 6, 3, tzinfo=timezone.utc),
        model_used="m",
    )
    mock_analysis.return_value = report

    r = client.get("/stocks/AAPL/analysis")
    assert r.status_code == 200
    body = r.json()
    sentiment = next(s for s in body["agent_signals"] if s["agent_id"] == "sentiment")
    assert sentiment["metrics"]["credibility"]["delta"] == 0.1
