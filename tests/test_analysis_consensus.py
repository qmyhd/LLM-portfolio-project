"""Tests for the consensus aggregator agent."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.analysis.consensus import _should_escalate, compute_deterministic_score, run
from src.analysis.models import AnalystSignal, ConsensusReport


@pytest.fixture
def bullish_signals() -> list[AnalystSignal]:
    """5 agent signals, mostly bullish."""
    return [
        AnalystSignal(agent_id="technical", signal="bullish", confidence=0.8, reasoning="Strong uptrend", metrics={}),
        AnalystSignal(
            agent_id="fundamental", signal="bullish", confidence=0.7, reasoning="Good profitability", metrics={}
        ),
        AnalystSignal(
            agent_id="valuation", signal="bullish", confidence=0.6, reasoning="Undervalued by 20%", metrics={}
        ),
        AnalystSignal(agent_id="sentiment", signal="neutral", confidence=0.4, reasoning="Mixed sentiment", metrics={}),
        AnalystSignal(agent_id="risk", signal="neutral", confidence=0.5, reasoning="Moderate volatility", metrics={}),
    ]


@pytest.fixture
def bearish_signals() -> list[AnalystSignal]:
    """5 agent signals, mostly bearish."""
    return [
        AnalystSignal(agent_id="technical", signal="bearish", confidence=0.9, reasoning="Downtrend", metrics={}),
        AnalystSignal(
            agent_id="fundamental", signal="bearish", confidence=0.8, reasoning="Weak financials", metrics={}
        ),
        AnalystSignal(
            agent_id="valuation", signal="bearish", confidence=0.7, reasoning="Overvalued by 30%", metrics={}
        ),
        AnalystSignal(
            agent_id="sentiment", signal="bearish", confidence=0.6, reasoning="Negative sentiment", metrics={}
        ),
        AnalystSignal(agent_id="risk", signal="bearish", confidence=0.8, reasoning="High volatility", metrics={}),
    ]


def test_deterministic_scoring_bullish(bullish_signals: list[AnalystSignal]) -> None:
    """Mostly bullish signals produce positive bull_bear_score."""
    score, verdict = compute_deterministic_score(bullish_signals)
    assert score > 0.0
    assert verdict in ("strong_buy", "buy")


def test_deterministic_scoring_bearish(bearish_signals: list[AnalystSignal]) -> None:
    """Mostly bearish signals produce negative bull_bear_score."""
    score, verdict = compute_deterministic_score(bearish_signals)
    assert score < 0.0
    assert verdict in ("strong_sell", "sell")


def test_deterministic_scoring_empty() -> None:
    """Empty signals produce hold verdict."""
    score, verdict = compute_deterministic_score([])
    assert score == 0.0
    assert verdict == "hold"


def test_should_escalate_conflicting() -> None:
    """High confidence spread + 3 different signals = escalation."""
    signals = [
        AnalystSignal(agent_id="technical", signal="bullish", confidence=0.95, reasoning="x", metrics={}),
        AnalystSignal(agent_id="fundamental", signal="bearish", confidence=0.2, reasoning="x", metrics={}),
        AnalystSignal(agent_id="valuation", signal="neutral", confidence=0.5, reasoning="x", metrics={}),
    ]
    assert _should_escalate(signals) is True


def test_should_not_escalate_aligned() -> None:
    """Aligned signals should not escalate."""
    signals = [
        AnalystSignal(agent_id="technical", signal="bullish", confidence=0.8, reasoning="x", metrics={}),
        AnalystSignal(agent_id="fundamental", signal="bullish", confidence=0.7, reasoning="x", metrics={}),
        AnalystSignal(agent_id="valuation", signal="bullish", confidence=0.6, reasoning="x", metrics={}),
    ]
    assert _should_escalate(signals) is False


@pytest.mark.asyncio
@pytest.mark.openai
async def test_consensus_full_run(bullish_signals: list[AnalystSignal]) -> None:
    """Full consensus run with mocked OpenAI call."""
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_choice = MagicMock()
    mock_choice.message.content = "AAPL shows strong technical momentum backed by solid fundamentals."
    mock_response.choices = [mock_choice]
    mock_client.chat.completions.create.return_value = mock_response

    with (
        patch("src.analysis.consensus.OpenAI", return_value=mock_client),
        patch("src.analysis.consensus.settings") as mock_settings,
    ):
        mock_settings.return_value.OPENAI_API_KEY = "test-key"
        report = await run(
            ticker="AAPL",
            signals=bullish_signals,
            data_sources=["Databento OHLCV", "OpenBB/FMP"],
        )

    assert isinstance(report, ConsensusReport)
    assert report.ticker == "AAPL"
    assert report.overall_signal in ("strong_buy", "buy", "hold", "sell", "strong_sell")
    assert report.bull_bear_score > 0
    assert len(report.agent_signals) == 5
    assert len(report.data_sources) == 2
    assert report.model_used.startswith("gpt-")
