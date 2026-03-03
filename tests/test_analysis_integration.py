"""Integration test: full pipeline from OHLCV to consensus report."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from unittest.mock import patch, MagicMock

from src.analysis.models import AnalysisInput, OHLCVBar, IdeaData, NewsItem


@pytest.fixture
def full_input():
    """Realistic AnalysisInput with all data populated."""
    np.random.seed(42)
    n = 200
    close = 150.0 + np.cumsum(np.random.randn(n) * 2.0)
    close = np.maximum(close, 50.0)
    bars = []
    for i in range(n):
        d = (pd.Timestamp("2025-01-01") + pd.Timedelta(days=i)).strftime("%Y-%m-%d")
        c = float(close[i])
        bars.append(OHLCVBar(
            date=d, open=c - 0.5, high=c + 1.5, low=c - 1.5,
            close=c, volume=8_000_000.0,
        ))

    return AnalysisInput(
        ticker="AAPL",
        ohlcv=bars,
        fundamentals={
            "returnOnEquity": 0.25, "peRatio": 20.0, "priceToBook": 2.5,
            "priceToSales": 4.0, "debtToEquity": 0.3, "currentRatio": 1.8,
            "epsActual": 7.5, "freeCashFlowPerShare": 6.0,
            "marketCap": 3_000_000_000_000, "bookValuePerShare": 60.0,
            "revenuePerShare": 37.5, "pegRatio": 1.1,
        },
        ideas=[
            IdeaData(
                direction="bullish", confidence=0.8, labels=["trade_plan"],
                idea_text="Long AAPL", created_at="2026-03-01", author="test",
            ),
        ],
        news=[
            NewsItem(title="Apple beats earnings expectations", date="2026-03-01"),
        ],
        portfolio_value=200000.0,
    )


@pytest.mark.anyio
async def test_all_agents_run_without_error(full_input):
    """Every agent produces a valid AnalystSignal from realistic data."""
    from src.analysis import technical, fundamental, valuation, sentiment, risk

    results = []
    for agent in [technical, fundamental, valuation, sentiment, risk]:
        sig = await agent.run(full_input)
        assert sig.signal in ("bullish", "bearish", "neutral")
        assert 0.0 <= sig.confidence <= 1.0
        assert len(sig.reasoning) > 0
        results.append(sig)

    # All 5 agents returned
    assert len(results) == 5
    agent_ids = {s.agent_id for s in results}
    assert agent_ids == {"technical", "fundamental", "valuation", "sentiment", "risk"}


@pytest.mark.anyio
async def test_full_pipeline_with_mocked_llm(full_input):
    """Full pipeline: 5 agents -> consensus with mocked LLM."""
    from src.analysis import technical, fundamental, valuation, sentiment, risk
    from src.analysis.consensus import run as consensus_run

    # Run all agents
    signals = []
    for agent in [technical, fundamental, valuation, sentiment, risk]:
        signals.append(await agent.run(full_input))

    # Mock the OpenAI client and settings for consensus narrative generation
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(
            content="AAPL shows strong fundamentals with solid technical momentum."
        ))]
    )

    mock_settings = MagicMock()
    mock_settings.OPENAI_API_KEY = "test-key"

    with patch("src.analysis.consensus.OpenAI", return_value=mock_client), \
         patch("src.analysis.consensus.settings", return_value=mock_settings):
        report = await consensus_run(
            ticker="AAPL",
            signals=signals,
            data_sources=["Databento OHLCV (200 days)", "OpenBB/FMP fundamentals"],
        )

    assert report.ticker == "AAPL"
    assert report.overall_signal in ("strong_buy", "buy", "hold", "sell", "strong_sell")
    assert -1.0 <= report.bull_bear_score <= 1.0
    assert len(report.agent_signals) == 5
    assert report.model_used.startswith("gpt-")
