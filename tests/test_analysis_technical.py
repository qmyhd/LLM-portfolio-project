"""Tests for the technical analysis agent (5-strategy weighted signal system)."""

from __future__ import annotations

import numpy as np
import pytest

from src.analysis.models import AnalysisInput, OHLCVBar
from src.analysis.technical import run


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_bars(n: int, seed: int = 42, drift: float = 0.0) -> list[OHLCVBar]:
    """Generate *n* synthetic OHLCVBar objects.

    Parameters
    ----------
    n : int
        Number of bars to generate.
    seed : int
        Random seed for reproducibility.
    drift : float
        Per-bar upward drift added to close prices.  Use a positive value
        (e.g. 0.5) to simulate an uptrend.
    """
    rng = np.random.RandomState(seed)
    base = 100 + np.arange(n) * drift + np.cumsum(rng.randn(n) * 0.3)
    bars: list[OHLCVBar] = []
    for i in range(n):
        c = float(base[i])
        h = c + abs(float(rng.randn() * 0.5))
        l_ = c - abs(float(rng.randn() * 0.5))
        o = l_ + float(rng.rand()) * (h - l_)
        v = float(rng.randint(500_000, 5_000_000))
        bars.append(OHLCVBar(
            date=f"2024-{1 + i // 30:02d}-{1 + i % 28:02d}",
            open=round(o, 2),
            high=round(h, 2),
            low=round(l_, 2),
            close=round(c, 2),
            volume=v,
        ))
    return bars


@pytest.fixture
def bullish_ohlcv_input() -> AnalysisInput:
    """200 bars with strong upward drift."""
    return AnalysisInput(
        ticker="TEST",
        ohlcv=_make_bars(200, seed=42, drift=0.5),
    )


@pytest.fixture
def short_ohlcv_input() -> AnalysisInput:
    """Only 10 bars — too few for most strategies."""
    return AnalysisInput(
        ticker="TEST",
        ohlcv=_make_bars(10, seed=42, drift=0.0),
    )


@pytest.fixture
def empty_ohlcv_input() -> AnalysisInput:
    """Zero bars."""
    return AnalysisInput(ticker="TEST", ohlcv=[])


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_technical_bullish_trend(bullish_ohlcv_input: AnalysisInput) -> None:
    """200 bars with a strong uptrend should produce a bullish or neutral signal
    with positive confidence and expected metric keys."""
    result = await run(bullish_ohlcv_input)

    assert result.agent_id == "technical"
    assert result.signal in ("bullish", "neutral")
    assert result.confidence > 0
    assert "rsi_14" in result.metrics
    assert "macd_histogram" in result.metrics


@pytest.mark.asyncio
async def test_technical_short_data_degrades(short_ohlcv_input: AnalysisInput) -> None:
    """With only 10 bars, signal should degrade to neutral with low confidence."""
    result = await run(short_ohlcv_input)

    assert result.agent_id == "technical"
    assert result.signal == "neutral"
    assert result.confidence <= 0.3


@pytest.mark.asyncio
async def test_technical_empty_data(empty_ohlcv_input: AnalysisInput) -> None:
    """Zero bars should return neutral with zero confidence."""
    result = await run(empty_ohlcv_input)

    assert result.agent_id == "technical"
    assert result.signal == "neutral"
    assert result.confidence == 0.0
    assert result.metrics["bars_available"] == 0


@pytest.mark.asyncio
async def test_technical_metrics_structure(bullish_ohlcv_input: AnalysisInput) -> None:
    """200 bars should produce metrics with all expected top-level keys."""
    result = await run(bullish_ohlcv_input)

    expected_keys = {
        "rsi_14",
        "macd_histogram",
        "macd_signal",
        "bb_position",
        "adx",
        "ema_8",
        "ema_21",
        "ema_55",
        "momentum_1m",
        "hurst_exponent",
        "strategies",
    }
    assert expected_keys.issubset(result.metrics.keys()), (
        f"Missing keys: {expected_keys - result.metrics.keys()}"
    )

    # strategies sub-dict should have signal/confidence per strategy
    strategies = result.metrics["strategies"]
    assert isinstance(strategies, dict)
    for name, info in strategies.items():
        assert "signal" in info, f"strategy {name} missing 'signal'"
        assert "confidence" in info, f"strategy {name} missing 'confidence'"
