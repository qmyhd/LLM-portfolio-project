"""Tests for the valuation agent (4-model weighted DCF analysis)."""

from __future__ import annotations

import pytest

from src.analysis.models import AnalysisInput, AnalystSignal, OHLCVBar
from src.analysis.valuation import run


@pytest.fixture
def undervalued_input() -> AnalysisInput:
    """Input with fundamentals suggesting undervaluation."""
    return AnalysisInput(
        ticker="VALUE",
        ohlcv=[OHLCVBar(date="2026-03-01", open=50.0, high=52.0, low=49.0, close=50.0, volume=1000000)],
        fundamentals={
            "netIncome": 5_000_000_000,
            "depreciationAndAmortization": 1_000_000_000,
            "capitalExpenditure": 800_000_000,
            "changeInWorkingCapital": 200_000_000,
            "sharesOutstanding": 1_000_000_000,
            "freeCashFlow": 4_000_000_000,
            "ebitda": 8_000_000_000,
            "totalDebt": 5_000_000_000,
            "cashAndEquivalents": 10_000_000_000,
            "bookValuePerShare": 35.0,
            "returnOnEquity": 0.20,
            "debtToEquity": 0.3,
            "beta": 1.0,
        },
        portfolio_value=100000.0,
    )


@pytest.fixture
def overvalued_input() -> AnalysisInput:
    """Input with fundamentals suggesting overvaluation at high price."""
    return AnalysisInput(
        ticker="OVER",
        ohlcv=[OHLCVBar(date="2026-03-01", open=500.0, high=510.0, low=495.0, close=500.0, volume=500000)],
        fundamentals={
            "netIncome": 500_000_000,
            "depreciationAndAmortization": 100_000_000,
            "capitalExpenditure": 200_000_000,
            "sharesOutstanding": 1_000_000_000,
            "freeCashFlow": 300_000_000,
            "ebitda": 800_000_000,
            "totalDebt": 20_000_000_000,
            "cashAndEquivalents": 2_000_000_000,
            "bookValuePerShare": 10.0,
            "returnOnEquity": 0.05,
            "debtToEquity": 2.5,
            "beta": 1.5,
        },
        portfolio_value=100000.0,
    )


@pytest.mark.anyio
async def test_valuation_undervalued(undervalued_input: AnalysisInput) -> None:
    """Stock trading well below intrinsic value should produce bullish signal."""
    result = await run(undervalued_input)
    assert isinstance(result, AnalystSignal)
    assert result.agent_id == "valuation"
    assert result.signal == "bullish"
    assert result.confidence > 0.3


@pytest.mark.anyio
async def test_valuation_overvalued(overvalued_input: AnalysisInput) -> None:
    """Stock trading well above intrinsic value should produce bearish signal."""
    result = await run(overvalued_input)
    assert isinstance(result, AnalystSignal)
    assert result.agent_id == "valuation"
    assert result.signal == "bearish"
    assert result.confidence > 0.3


@pytest.mark.anyio
async def test_valuation_no_data() -> None:
    """No fundamentals should return neutral with zero confidence."""
    inp = AnalysisInput(ticker="NONE", ohlcv=[], fundamentals=None, portfolio_value=50000.0)
    result = await run(inp)
    assert result.agent_id == "valuation"
    assert result.signal == "neutral"
    assert result.confidence == 0.0


@pytest.mark.anyio
async def test_valuation_no_price() -> None:
    """No OHLCV price should return neutral."""
    inp = AnalysisInput(
        ticker="NOPRICE",
        ohlcv=[],
        fundamentals={"netIncome": 1000000, "sharesOutstanding": 100000},
        portfolio_value=50000.0,
    )
    result = await run(inp)
    assert result.agent_id == "valuation"
    assert result.signal == "neutral"
    assert result.confidence == 0.0


@pytest.mark.anyio
async def test_valuation_metrics_structure(undervalued_input: AnalysisInput) -> None:
    """Metrics should contain model results and weighted gap."""
    result = await run(undervalued_input)
    assert "weighted_gap_pct" in result.metrics
    assert "models_used" in result.metrics
    assert "current_price" in result.metrics
    assert isinstance(result.metrics["models_used"], list)
    assert len(result.metrics["models_used"]) > 0
