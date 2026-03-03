"""Tests for the technical indicator math library."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.analysis.indicators import (
    calculate_adx,
    calculate_atr,
    calculate_bollinger_bands,
    calculate_ema,
    calculate_hurst_exponent,
    calculate_macd,
    calculate_rsi,
    calculate_sma,
)


@pytest.fixture
def sample_ohlcv() -> pd.DataFrame:
    """Generate 200 days of synthetic OHLCV data."""
    np.random.seed(42)
    n = 200
    # Start at 100 and do a random walk for close prices
    close = 100 + np.cumsum(np.random.randn(n) * 1.5)
    # High is close + random positive offset
    high = close + np.abs(np.random.randn(n) * 0.8)
    # Low is close - random positive offset
    low = close - np.abs(np.random.randn(n) * 0.8)
    # Open is between low and high
    open_ = low + np.random.rand(n) * (high - low)
    # Volume is random positive integers
    volume = np.random.randint(1_000_000, 10_000_000, size=n)

    return pd.DataFrame({
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    })


class TestEMA:
    def test_ema_basic(self, sample_ohlcv: pd.DataFrame) -> None:
        """EMA returns correct length, not all NaN, fewer than period NaNs."""
        period = 20
        result = calculate_ema(sample_ohlcv["close"], period)

        assert len(result) == len(sample_ohlcv)
        assert not result.isna().all()
        # EWM with adjust=False produces values from the first element,
        # so there should be no NaN values at all
        assert result.isna().sum() < period

    def test_ema_short_series(self) -> None:
        """Series shorter than period doesn't crash."""
        short_series = pd.Series([1.0, 2.0, 3.0])
        result = calculate_ema(short_series, period=20)
        assert len(result) == 3
        assert not result.isna().all()


class TestSMA:
    def test_sma_basic(self, sample_ohlcv: pd.DataFrame) -> None:
        """SMA returns correct length with expected NaN count."""
        period = 20
        result = calculate_sma(sample_ohlcv["close"], period)

        assert len(result) == len(sample_ohlcv)
        # First (period - 1) values should be NaN
        assert result.isna().sum() == period - 1


class TestRSI:
    def test_rsi_range(self, sample_ohlcv: pd.DataFrame) -> None:
        """All valid RSI values are between 0 and 100."""
        result = calculate_rsi(sample_ohlcv["close"])
        valid = result.dropna()

        assert len(valid) > 0
        assert (valid >= 0).all()
        assert (valid <= 100).all()


class TestBollingerBands:
    def test_bollinger_bands_contain_price(self, sample_ohlcv: pd.DataFrame) -> None:
        """Upper >= middle >= lower for all valid points."""
        upper, middle, lower = calculate_bollinger_bands(sample_ohlcv["close"])

        # Find indices where all three are valid
        valid_mask = upper.notna() & middle.notna() & lower.notna()
        assert valid_mask.sum() > 0

        assert (upper[valid_mask] >= middle[valid_mask]).all()
        assert (middle[valid_mask] >= lower[valid_mask]).all()


class TestMACD:
    def test_macd_structure(self, sample_ohlcv: pd.DataFrame) -> None:
        """MACD returns 3 series of same length; histogram = macd - signal."""
        macd_line, signal_line, histogram = calculate_macd(sample_ohlcv["close"])

        assert len(macd_line) == len(sample_ohlcv)
        assert len(signal_line) == len(sample_ohlcv)
        assert len(histogram) == len(sample_ohlcv)

        # Where all three are valid, histogram should equal macd - signal
        valid_mask = macd_line.notna() & signal_line.notna() & histogram.notna()
        assert valid_mask.sum() > 0
        expected = macd_line[valid_mask] - signal_line[valid_mask]
        pd.testing.assert_series_equal(histogram[valid_mask], expected, check_names=False)


class TestADX:
    def test_adx_range(self, sample_ohlcv: pd.DataFrame) -> None:
        """All valid ADX values are between 0 and 100."""
        result = calculate_adx(
            sample_ohlcv["high"],
            sample_ohlcv["low"],
            sample_ohlcv["close"],
        )
        valid = result.dropna()

        assert len(valid) > 0
        assert (valid >= 0).all()
        assert (valid <= 100).all()


class TestATR:
    def test_atr_positive(self, sample_ohlcv: pd.DataFrame) -> None:
        """All valid ATR values are positive."""
        result = calculate_atr(
            sample_ohlcv["high"],
            sample_ohlcv["low"],
            sample_ohlcv["close"],
        )
        valid = result.dropna()

        assert len(valid) > 0
        assert (valid > 0).all()


class TestHurstExponent:
    def test_hurst_exponent_range(self, sample_ohlcv: pd.DataFrame) -> None:
        """Hurst exponent is between 0 and 1."""
        result = calculate_hurst_exponent(sample_ohlcv["close"])

        assert isinstance(result, float)
        assert 0.0 <= result <= 1.0

    def test_hurst_insufficient_data(self) -> None:
        """Short series returns 0.5 (random walk default)."""
        short_series = pd.Series([1.0, 2.0, 3.0])
        result = calculate_hurst_exponent(short_series, max_lag=20)
        assert result == 0.5
