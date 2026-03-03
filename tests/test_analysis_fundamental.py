"""Tests for the fundamental scoring agent (4-pillar deterministic scoring)."""

from __future__ import annotations

import pytest

from src.analysis.models import AnalysisInput, AnalystSignal
from src.analysis.fundamental import run


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def strong_fundamentals_input() -> AnalysisInput:
    """Input with strong fundamental metrics."""
    return AnalysisInput(
        ticker="AAPL",
        ohlcv=[],
        fundamentals={
            "returnOnEquity": 0.25,
            "peRatio": 18.0,
            "priceToBook": 2.0,
            "priceToSales": 3.5,
            "debtToEquity": 0.3,
            "currentRatio": 2.0,
            "revenuePerShare": 25.0,
            "epsActual": 6.5,
            "freeCashFlowPerShare": 6.0,
            "marketCap": 3e12,
            "pegRatio": 1.2,
            "bookValuePerShare": 20.0,
            "returnOnAssets": 0.18,
            "dividendYield": 0.005,
        },
        portfolio_value=100000.0,
    )


@pytest.fixture
def weak_fundamentals_input() -> AnalysisInput:
    """Weak fundamentals."""
    return AnalysisInput(
        ticker="WEAK",
        ohlcv=[],
        fundamentals={
            "returnOnEquity": 0.05,
            "peRatio": 45.0,
            "priceToBook": 8.0,
            "priceToSales": 12.0,
            "debtToEquity": 2.5,
            "currentRatio": 0.8,
            "epsActual": 0.50,
            "freeCashFlowPerShare": 0.10,
            "marketCap": 5e8,
        },
        portfolio_value=100000.0,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fundamental_strong(strong_fundamentals_input: AnalysisInput) -> None:
    """Strong fundamentals should produce a bullish signal with decent confidence."""
    result = await run(strong_fundamentals_input)

    assert isinstance(result, AnalystSignal)
    assert result.agent_id == "fundamental"
    assert result.signal == "bullish"
    assert result.confidence > 0.5


@pytest.mark.asyncio
async def test_fundamental_weak(weak_fundamentals_input: AnalysisInput) -> None:
    """Weak fundamentals should produce a bearish signal."""
    result = await run(weak_fundamentals_input)

    assert isinstance(result, AnalystSignal)
    assert result.agent_id == "fundamental"
    assert result.signal == "bearish"
    assert result.confidence > 0.3


@pytest.mark.asyncio
async def test_fundamental_no_data() -> None:
    """No fundamental data should return neutral with zero confidence."""
    inp = AnalysisInput(ticker="NONE", ohlcv=[], fundamentals=None, portfolio_value=50000.0)
    result = await run(inp)

    assert isinstance(result, AnalystSignal)
    assert result.agent_id == "fundamental"
    assert result.signal == "neutral"
    assert result.confidence == 0.0
    assert "No fundamental data" in result.reasoning


@pytest.mark.asyncio
async def test_fundamental_metrics_include_pillars(strong_fundamentals_input: AnalysisInput) -> None:
    """Metrics dict should contain all four pillar keys."""
    result = await run(strong_fundamentals_input)

    expected_pillars = {"profitability", "growth", "financial_health", "valuation"}
    assert expected_pillars.issubset(result.metrics.keys()), (
        f"Missing pillar keys: {expected_pillars - result.metrics.keys()}"
    )

    # Each pillar sub-dict should have signal and confidence
    for pillar_name in expected_pillars:
        pillar = result.metrics[pillar_name]
        assert "signal" in pillar, f"pillar {pillar_name} missing 'signal'"
        assert "confidence" in pillar, f"pillar {pillar_name} missing 'confidence'"
