"""Technical indicator calculations — pure math, no API calls, no DB access.

Adapted from ai-hedge-fund technicals.py. All functions accept pandas Series
(or Series + high/low/close for volume-aware indicators) and return pandas
Series or scalar values. No side effects.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Moving Averages
# ---------------------------------------------------------------------------


def calculate_ema(series: pd.Series, period: int) -> pd.Series:
    """Exponential Moving Average.

    Uses pandas ewm with ``adjust=False`` for a recursive EMA that produces
    values starting from the first element (no leading NaN window).
    """
    return series.ewm(span=period, adjust=False).mean()


def calculate_sma(series: pd.Series, period: int) -> pd.Series:
    """Simple Moving Average.

    The first ``period - 1`` values will be NaN.
    """
    return series.rolling(window=period).mean()


# ---------------------------------------------------------------------------
# Oscillators
# ---------------------------------------------------------------------------


def calculate_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """Relative Strength Index using Wilder's smoothing.

    Returns values clipped to [0, 100].
    """
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)

    # Wilder's smoothing is equivalent to EWM with alpha = 1/period
    avg_gain = gain.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()

    rs = avg_gain / avg_loss
    rsi = 100.0 - (100.0 / (1.0 + rs))
    return rsi.clip(lower=0.0, upper=100.0)


# ---------------------------------------------------------------------------
# Bands
# ---------------------------------------------------------------------------


def calculate_bollinger_bands(
    series: pd.Series,
    period: int = 20,
    std_dev: float = 2.0,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Bollinger Bands.

    Returns ``(upper, middle, lower)`` where *middle* is the SMA and upper/lower
    are offset by ``std_dev`` rolling standard deviations.
    """
    middle = calculate_sma(series, period)
    rolling_std = series.rolling(window=period).std()
    upper = middle + std_dev * rolling_std
    lower = middle - std_dev * rolling_std
    return upper, middle, lower


# ---------------------------------------------------------------------------
# MACD
# ---------------------------------------------------------------------------


def calculate_macd(
    series: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal_period: int = 9,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Moving Average Convergence Divergence.

    Returns ``(macd_line, signal_line, histogram)``.

    * ``macd_line``   = EMA(fast) - EMA(slow)
    * ``signal_line`` = EMA(macd_line, signal_period)
    * ``histogram``   = macd_line - signal_line
    """
    ema_fast = calculate_ema(series, fast)
    ema_slow = calculate_ema(series, slow)
    macd_line = ema_fast - ema_slow
    signal_line = calculate_ema(macd_line, signal_period)
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


# ---------------------------------------------------------------------------
# Volatility
# ---------------------------------------------------------------------------


def calculate_atr(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    period: int = 14,
) -> pd.Series:
    """Average True Range.

    True Range is the greatest of:
    * ``high - low``
    * ``|high - previous_close|``
    * ``|low  - previous_close|``

    ATR is the EWM smoothing of the True Range using Wilder's method.
    """
    prev_close = close.shift(1)
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return true_range.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()


# ---------------------------------------------------------------------------
# Trend Strength
# ---------------------------------------------------------------------------


def calculate_adx(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    period: int = 14,
) -> pd.Series:
    """Average Directional Index.

    Computes +DM / -DM, smooths them with Wilder's EWM, derives DI+ / DI-,
    then DX = |DI+ - DI-| / (DI+ + DI-) * 100. ADX is the smoothed DX.

    Returns values clipped to [0, 100].
    """
    # Directional movement
    up_move = high.diff()
    down_move = -low.diff()

    plus_dm = pd.Series(np.where((up_move > down_move) & (up_move > 0), up_move, 0.0), index=high.index)
    minus_dm = pd.Series(np.where((down_move > up_move) & (down_move > 0), down_move, 0.0), index=high.index)

    # Wilder smoothing
    alpha = 1.0 / period
    atr = calculate_atr(high, low, close, period)
    smooth_plus_dm = plus_dm.ewm(alpha=alpha, min_periods=period, adjust=False).mean()
    smooth_minus_dm = minus_dm.ewm(alpha=alpha, min_periods=period, adjust=False).mean()

    # Directional indicators
    di_plus = 100.0 * smooth_plus_dm / atr
    di_minus = 100.0 * smooth_minus_dm / atr

    # Directional index
    di_sum = di_plus + di_minus
    dx = (di_plus - di_minus).abs() / di_sum.replace(0, np.nan) * 100.0

    # Average DX
    adx = dx.ewm(alpha=alpha, min_periods=period, adjust=False).mean()
    return adx.clip(lower=0.0, upper=100.0)


# ---------------------------------------------------------------------------
# Fractal / Regime
# ---------------------------------------------------------------------------


def calculate_hurst_exponent(series: pd.Series, max_lag: int = 20) -> float:
    """Hurst exponent via the Rescaled Range (R/S) method.

    * ``H < 0.5`` -- mean-reverting
    * ``H = 0.5`` -- random walk
    * ``H > 0.5`` -- trending

    Returns 0.5 if the series has insufficient data for a meaningful estimate.
    """
    vals = series.dropna().values
    n = len(vals)

    if n < max_lag + 2:
        return 0.5

    lags = range(2, max_lag + 1)
    rs_values = []

    for lag in lags:
        # Partition into non-overlapping chunks of length `lag`
        chunks = [vals[i : i + lag] for i in range(0, n - lag + 1, lag)]
        rs_chunk = []
        for chunk in chunks:
            if len(chunk) < 2:
                continue
            mean_c = np.mean(chunk)
            deviations = chunk - mean_c
            cumulative = np.cumsum(deviations)
            r = np.max(cumulative) - np.min(cumulative)
            s = np.std(chunk, ddof=1)
            if s > 0:
                rs_chunk.append(r / s)
        if rs_chunk:
            rs_values.append(np.mean(rs_chunk))
        else:
            rs_values.append(np.nan)

    # Log-log regression: log(R/S) vs log(lag)
    log_lags = np.log(np.array(list(lags), dtype=float))
    log_rs = np.log(np.array(rs_values, dtype=float))

    # Filter out NaN / inf
    valid = np.isfinite(log_lags) & np.isfinite(log_rs)
    if valid.sum() < 2:
        return 0.5

    log_lags = log_lags[valid]
    log_rs = log_rs[valid]

    # OLS slope
    slope, _ = np.polyfit(log_lags, log_rs, 1)

    # Clamp to [0, 1]
    return float(np.clip(slope, 0.0, 1.0))
