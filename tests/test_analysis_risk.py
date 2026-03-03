"""Tests for the risk analysis agent."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.analysis.models import AnalysisInput, OHLCVBar, PositionData, PortfolioRiskReport
from src.analysis.risk import compute_portfolio_risk, run


@pytest.fixture
def risk_input() -> AnalysisInput:
    """200 days of OHLCV with a position."""
    np.random.seed(42)
    n = 200
    close = 100.0 + np.cumsum(np.random.randn(n) * 1.5)
    close = np.maximum(close, 10.0)
    bars = []
    for i in range(n):
        d = (pd.Timestamp("2025-01-01") + pd.Timedelta(days=i)).strftime("%Y-%m-%d")
        c = float(close[i])
        bars.append(OHLCVBar(
            date=d, open=c - 0.3, high=c + 1.0, low=c - 1.0,
            close=c, volume=5_000_000.0,
        ))
    position = PositionData(
        quantity=100, avg_cost=95.0, current_price=float(close[-1]),
        market_value=float(close[-1]) * 100,
        unrealized_pnl=(float(close[-1]) - 95.0) * 100,
        unrealized_pnl_pct=((float(close[-1]) - 95.0) / 95.0) * 100,
    )
    return AnalysisInput(
        ticker="TEST", ohlcv=bars, position=position, portfolio_value=100000.0,
    )


@pytest.mark.anyio
async def test_risk_produces_signal(risk_input: AnalysisInput) -> None:
    """Risk agent returns valid signal with risk metrics."""
    signal = await run(risk_input)
    assert signal.agent_id == "risk"
    assert signal.signal in ("bullish", "bearish", "neutral")
    assert 0.0 <= signal.confidence <= 1.0


@pytest.mark.anyio
async def test_risk_metrics_structure(risk_input: AnalysisInput) -> None:
    """Risk metrics include volatility, drawdown, and sizing."""
    signal = await run(risk_input)
    assert "annualized_volatility" in signal.metrics
    assert "max_drawdown" in signal.metrics
    assert "volatility_percentile" in signal.metrics
    assert "position_size_recommendation_pct" in signal.metrics


@pytest.mark.anyio
async def test_risk_no_data() -> None:
    """Empty OHLCV returns neutral."""
    inp = AnalysisInput(ticker="EMPTY", ohlcv=[], portfolio_value=50000.0)
    signal = await run(inp)
    assert signal.signal == "neutral"
    assert signal.confidence == 0.0


def test_portfolio_risk_report() -> None:
    """Portfolio risk computation returns valid report."""
    np.random.seed(42)
    n = 100
    returns_data = {"AAPL": np.random.randn(n) * 0.02}
    weights = {"AAPL": 1.0}
    sector_map = {"AAPL": "Technology"}

    report = compute_portfolio_risk(
        returns_data=returns_data,
        weights=weights,
        sector_map=sector_map,
        total_value=100000.0,
    )
    assert isinstance(report, PortfolioRiskReport)
    assert report.var_95_1d > 0
    assert "Technology" in report.sector_exposure
