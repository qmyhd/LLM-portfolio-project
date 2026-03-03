"""Tests for analysis API routes."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest


@pytest.fixture
def client():
    """Create test client with auth disabled."""
    with patch.dict("os.environ", {"DISABLE_AUTH": "true"}):
        from app.main import app
        from fastapi.testclient import TestClient

        with TestClient(app) as c:
            yield c


def test_get_stock_analysis(client):
    """GET /stocks/{ticker}/analysis returns consensus report."""
    mock_report = {
        "ticker": "AAPL",
        "overall_signal": "buy",
        "overall_confidence": 0.75,
        "bull_bear_score": 0.3,
        "agent_signals": [],
        "summary": "Strong buy signal",
        "data_sources": ["Databento OHLCV"],
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "model_used": "gpt-5-mini",
    }

    with patch("app.routes.analysis.get_stock_analysis", new_callable=AsyncMock, return_value=mock_report):
        resp = client.get("/stocks/AAPL/analysis")

    assert resp.status_code == 200
    data = resp.json()
    assert data["ticker"] == "AAPL"
    assert data["overall_signal"] == "buy"


def test_get_stock_analysis_refresh(client):
    """?refresh=true bypasses cache."""
    mock_report = {
        "ticker": "AAPL",
        "overall_signal": "hold",
        "overall_confidence": 0.5,
        "bull_bear_score": 0.0,
        "agent_signals": [],
        "summary": "Fresh analysis",
        "data_sources": [],
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "model_used": "gpt-5-mini",
    }

    with patch(
        "app.routes.analysis.get_stock_analysis", new_callable=AsyncMock, return_value=mock_report
    ) as mock_fn:
        resp = client.get("/stocks/AAPL/analysis?refresh=true")

    assert resp.status_code == 200
    mock_fn.assert_called_once_with("AAPL", refresh=True, agents=None)


def test_get_stock_analysis_technical(client):
    """GET /stocks/{ticker}/analysis/technical routes to technical agent only."""
    mock_report = {
        "ticker": "TSLA",
        "overall_signal": "buy",
        "overall_confidence": 0.8,
        "bull_bear_score": 0.5,
        "agent_signals": [],
        "summary": "Technical only",
        "data_sources": [],
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "model_used": "gpt-5-mini",
    }

    with patch(
        "app.routes.analysis.get_stock_analysis", new_callable=AsyncMock, return_value=mock_report
    ) as mock_fn:
        resp = client.get("/stocks/TSLA/analysis/technical")

    assert resp.status_code == 200
    mock_fn.assert_called_once_with("TSLA", refresh=False, agents=["technical"])


def test_get_portfolio_risk(client):
    """GET /portfolio/risk returns portfolio risk report."""
    mock_report = {
        "var_95_1d": 1200.50,
        "var_95_5d": 2800.00,
        "concentration_hhi": 0.12,
        "diversification_ratio": 1.35,
        "correlation_matrix": {},
        "top_risk_contributors": [],
        "sector_exposure": {"Technology": 0.45},
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "data_sources": ["Databento OHLCV"],
    }

    with patch("app.routes.analysis.get_portfolio_risk", new_callable=AsyncMock, return_value=mock_report):
        resp = client.get("/portfolio/risk")

    assert resp.status_code == 200
    data = resp.json()
    assert "var_95_1d" in data
    assert data["sector_exposure"]["Technology"] == 0.45
