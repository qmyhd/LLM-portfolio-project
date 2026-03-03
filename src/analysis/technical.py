"""
Technical analysis agent -- 5-strategy weighted signal system.

Entirely deterministic (no LLM calls). Uses OHLCV data from Databento
via price_service. Adapted from ai-hedge-fund technicals.py.

Data source: Databento OHLCV via price_service.get_ohlcv()
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

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
from src.analysis.models import AnalysisInput, AnalystSignal

logger = logging.getLogger(__name__)

# Strategy weights for signal aggregation
STRATEGY_WEIGHTS: dict[str, float] = {
    "trend": 0.25,
    "mean_reversion": 0.20,
    "momentum": 0.25,
    "volatility": 0.15,
    "stat_arb": 0.15,
}

MIN_BARS = 20  # Minimum bars needed for any analysis


# ---------------------------------------------------------------------------
# Individual strategy implementations
# ---------------------------------------------------------------------------


def _trend_following(df: pd.DataFrame) -> tuple[str, float, dict]:
    """EMA alignment + ADX trend strength.

    Requires >= 55 bars. Returns (signal, confidence, metrics).
    """
    close = df["close"]
    ema_8 = calculate_ema(close, 8)
    ema_21 = calculate_ema(close, 21)
    ema_55 = calculate_ema(close, 55)
    adx = calculate_adx(df["high"], df["low"], close, 14)

    e8 = float(ema_8.iloc[-1])
    e21 = float(ema_21.iloc[-1])
    e55 = float(ema_55.iloc[-1])

    # Last valid ADX
    adx_valid = adx.dropna()
    adx_val = float(adx_valid.iloc[-1]) if len(adx_valid) > 0 else 0.0

    # EMA alignment
    if e8 > e21 > e55:
        signal = "bullish"
    elif e8 < e21 < e55:
        signal = "bearish"
    else:
        signal = "neutral"

    confidence = min(adx_val / 100.0, 1.0)

    metrics = {
        "ema_8": round(e8, 4),
        "ema_21": round(e21, 4),
        "ema_55": round(e55, 4),
        "adx": round(adx_val, 4),
    }
    return signal, confidence, metrics


def _mean_reversion(df: pd.DataFrame) -> tuple[str, float, dict]:
    """Z-score + Bollinger Band position + RSI.

    Requires >= 50 bars. Returns (signal, confidence, metrics).
    """
    close = df["close"]

    # Z-score: (price - SMA50) / rolling_std(50)
    sma_50 = calculate_sma(close, 50)
    rolling_std_50 = close.rolling(window=50).std()
    z_score_series = (close - sma_50) / rolling_std_50
    z_score = float(z_score_series.iloc[-1]) if not pd.isna(z_score_series.iloc[-1]) else 0.0

    # Bollinger Bands (20, 2.0)
    upper, _middle, lower = calculate_bollinger_bands(close, 20, 2.0)
    band_width = upper.iloc[-1] - lower.iloc[-1]
    if band_width > 0 and not pd.isna(band_width):
        bb_position = float((close.iloc[-1] - lower.iloc[-1]) / band_width)
    else:
        bb_position = 0.5

    # RSI
    rsi_14 = calculate_rsi(close, 14)
    rsi_28 = calculate_rsi(close, 28)
    rsi_14_val = float(rsi_14.iloc[-1]) if not pd.isna(rsi_14.iloc[-1]) else 50.0
    rsi_28_val = float(rsi_28.iloc[-1]) if not pd.isna(rsi_28.iloc[-1]) else 50.0

    # Signal logic
    if z_score < -2 and bb_position < 0.2:
        signal = "bullish"
    elif z_score > 2 and bb_position > 0.8:
        signal = "bearish"
    else:
        signal = "neutral"

    confidence = min(abs(z_score) / 4.0, 1.0)

    metrics = {
        "z_score": round(z_score, 4),
        "rsi_14": round(rsi_14_val, 4),
        "rsi_28": round(rsi_28_val, 4),
        "bb_position": round(bb_position, 4),
    }
    return signal, confidence, metrics


def _momentum(df: pd.DataFrame) -> tuple[str, float, dict]:
    """Multi-timeframe momentum with volume confirmation.

    Requires >= 21 bars. Returns (signal, confidence, metrics).
    """
    close = df["close"]
    volume = df["volume"]
    n = len(df)

    # 1-month return (~21 trading days)
    mom_1m = float(close.iloc[-1] / close.iloc[-21] - 1)

    # 3-month return (~63 trading days)
    mom_3m: float | None = None
    if n >= 63:
        mom_3m = float(close.iloc[-1] / close.iloc[-63] - 1)

    # 6-month return (~126 trading days)
    mom_6m: float | None = None
    if n >= 126:
        mom_6m = float(close.iloc[-1] / close.iloc[-126] - 1)

    # Momentum score (weighted combination)
    if mom_6m is not None and mom_3m is not None:
        momentum_score = 0.4 * mom_1m + 0.3 * mom_3m + 0.3 * mom_6m
    elif mom_3m is not None:
        # Redistribute 6m weight to 1m and 3m
        momentum_score = 0.55 * mom_1m + 0.45 * mom_3m
    else:
        momentum_score = mom_1m

    # Volume ratio: current volume vs 21-day average
    vol_avg_21 = volume.rolling(window=21).mean()
    vol_avg_val = float(vol_avg_21.iloc[-1]) if not pd.isna(vol_avg_21.iloc[-1]) else 1.0
    volume_ratio = float(volume.iloc[-1] / vol_avg_val) if vol_avg_val > 0 else 1.0

    # Signal logic
    if momentum_score > 0.05 and volume_ratio > 0.8:
        signal = "bullish"
    elif momentum_score < -0.05 and volume_ratio > 0.8:
        signal = "bearish"
    else:
        signal = "neutral"

    confidence = min(abs(momentum_score) * 5, 1.0)

    metrics = {
        "momentum_1m": round(mom_1m, 4),
        "momentum_3m": round(mom_3m, 4) if mom_3m is not None else None,
        "momentum_6m": round(mom_6m, 4) if mom_6m is not None else None,
        "volume_ratio": round(volume_ratio, 4),
        "momentum_score": round(momentum_score, 4),
    }
    return signal, confidence, metrics


def _volatility_analysis(df: pd.DataFrame) -> tuple[str, float, dict]:
    """Historical volatility regime analysis with ATR.

    Requires >= 21 bars. Returns (signal, confidence, metrics).
    """
    close = df["close"]
    n = len(df)

    # Daily returns
    daily_returns = close.pct_change().dropna()

    # Historical volatility: 21-day rolling std of returns, annualised
    hv_21 = daily_returns.rolling(window=21).std() * np.sqrt(252)
    hv_current = float(hv_21.iloc[-1]) if not pd.isna(hv_21.iloc[-1]) else 0.0

    # Volatility regime = current HV / 63-day MA of HV
    if n >= 63:
        hv_ma_63 = hv_21.rolling(window=63).mean()
        hv_ma_val = float(hv_ma_63.iloc[-1]) if not pd.isna(hv_ma_63.iloc[-1]) else hv_current
        hv_std_63 = hv_21.rolling(window=63).std()
        hv_std_val = float(hv_std_63.iloc[-1]) if not pd.isna(hv_std_63.iloc[-1]) else 1.0
    else:
        # Fallback: use 21-day stats
        hv_ma_val = float(hv_21.mean()) if not hv_21.isna().all() else hv_current
        hv_std_val = float(hv_21.std()) if not hv_21.isna().all() else 1.0

    vol_regime = (hv_current / hv_ma_val) if hv_ma_val > 0 else 1.0

    # Vol z-score = (HV - MA) / std
    vol_z_score = ((hv_current - hv_ma_val) / hv_std_val) if hv_std_val > 0 else 0.0

    # ATR ratio = ATR(14) / close price
    atr = calculate_atr(df["high"], df["low"], close, 14)
    atr_valid = atr.dropna()
    atr_val = float(atr_valid.iloc[-1]) if len(atr_valid) > 0 else 0.0
    atr_ratio = atr_val / float(close.iloc[-1]) if float(close.iloc[-1]) > 0 else 0.0

    # Signal logic
    if vol_regime < 0.8 and vol_z_score < -1:
        signal = "bullish"  # Low vol, expansion expected
    elif vol_regime > 1.2 and vol_z_score > 1:
        signal = "bearish"  # High vol, risk-off
    else:
        signal = "neutral"

    confidence = min(abs(vol_z_score) / 3.0, 1.0)

    metrics = {
        "annualized_vol": round(hv_current, 4),
        "vol_regime": round(vol_regime, 4),
        "vol_z_score": round(vol_z_score, 4),
        "atr_ratio": round(atr_ratio, 4),
    }
    return signal, confidence, metrics


def _statistical_arbitrage(df: pd.DataFrame) -> tuple[str, float, dict]:
    """Hurst exponent + return distribution analysis.

    Requires >= 63 bars. Returns (signal, confidence, metrics).
    """
    close = df["close"]

    # Daily returns
    daily_returns = close.pct_change().dropna()

    # 63-day rolling skewness and kurtosis
    skew_series = daily_returns.rolling(window=63).skew()
    kurt_series = daily_returns.rolling(window=63).kurt()

    skewness = float(skew_series.iloc[-1]) if not pd.isna(skew_series.iloc[-1]) else 0.0
    kurtosis = float(kurt_series.iloc[-1]) if not pd.isna(kurt_series.iloc[-1]) else 0.0

    # Hurst exponent
    hurst = calculate_hurst_exponent(close, max_lag=20)

    # Signal logic
    if hurst < 0.4 and skewness > 0:
        signal = "bullish"
    elif hurst < 0.4 and skewness < 0:
        signal = "bearish"
    elif hurst > 0.6:
        signal = "neutral"  # Trending, not mean-reverting
    else:
        signal = "neutral"

    confidence = min(abs(0.5 - hurst) * 4, 1.0)

    metrics = {
        "hurst_exponent": round(hurst, 4),
        "skewness": round(skewness, 4),
        "kurtosis": round(kurtosis, 4),
    }
    return signal, confidence, metrics


# ---------------------------------------------------------------------------
# Signal aggregation
# ---------------------------------------------------------------------------


_SIGNAL_MAP: dict[str, float] = {"bullish": 1.0, "neutral": 0.0, "bearish": -1.0}


def _weighted_signal_combination(strategies: dict[str, tuple[str, float, dict]]) -> tuple[str, float]:
    """Combine strategy signals using weights. Returns (signal, confidence)."""
    total_weighted_signal = 0.0
    total_weight = 0.0

    for name, (signal, confidence, _) in strategies.items():
        weight = STRATEGY_WEIGHTS.get(name, 0.0)
        total_weighted_signal += _SIGNAL_MAP[signal] * weight * confidence
        total_weight += weight * confidence

    if total_weight == 0:
        return "neutral", 0.0

    normalized = total_weighted_signal / total_weight
    if normalized > 0.2:
        return "bullish", min(abs(normalized), 1.0)
    elif normalized < -0.2:
        return "bearish", min(abs(normalized), 1.0)
    return "neutral", min(1.0 - abs(normalized), 1.0)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


async def run(input: AnalysisInput) -> AnalystSignal:
    """Run technical analysis on OHLCV data.

    Executes up to 5 strategy categories (trend, mean_reversion, momentum,
    volatility, stat_arb) depending on available data length, then combines
    them via weighted signal aggregation.
    """
    if not input.ohlcv or len(input.ohlcv) < MIN_BARS:
        return AnalystSignal(
            agent_id="technical",
            signal="neutral",
            confidence=0.0,
            reasoning="Insufficient OHLCV data for technical analysis",
            metrics={"bars_available": len(input.ohlcv) if input.ohlcv else 0},
        )

    # Convert to DataFrame
    df = pd.DataFrame([bar.model_dump() for bar in input.ohlcv])
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)

    # Run strategies (skip those without enough data)
    strategies: dict[str, tuple[str, float, dict]] = {}
    n = len(df)

    if n >= 55:
        strategies["trend"] = _trend_following(df)
    if n >= 50:
        strategies["mean_reversion"] = _mean_reversion(df)
    if n >= 21:
        strategies["momentum"] = _momentum(df)
    if n >= 21:
        strategies["volatility"] = _volatility_analysis(df)
    if n >= 63:
        strategies["stat_arb"] = _statistical_arbitrage(df)

    if not strategies:
        return AnalystSignal(
            agent_id="technical",
            signal="neutral",
            confidence=0.0,
            reasoning=f"Only {n} bars available, need at least 21 for basic analysis",
            metrics={"bars_available": n},
        )

    signal, confidence = _weighted_signal_combination(strategies)

    # Collect all metrics
    all_metrics: dict = {"bars_available": n, "strategies": {}}
    for name, (sig, conf, metrics) in strategies.items():
        all_metrics["strategies"][name] = {"signal": sig, "confidence": conf, **metrics}

    # Add top-level convenience metrics from strategies (for frontend quick access)
    if "mean_reversion" in strategies:
        _, _, mr_metrics = strategies["mean_reversion"]
        all_metrics["rsi_14"] = mr_metrics.get("rsi_14")
        all_metrics["bb_position"] = mr_metrics.get("bb_position")
    if "trend" in strategies:
        _, _, tr_metrics = strategies["trend"]
        all_metrics["ema_8"] = tr_metrics.get("ema_8")
        all_metrics["ema_21"] = tr_metrics.get("ema_21")
        all_metrics["ema_55"] = tr_metrics.get("ema_55")
        all_metrics["adx"] = tr_metrics.get("adx")
    if "momentum" in strategies:
        _, _, mom_metrics = strategies["momentum"]
        all_metrics["momentum_1m"] = mom_metrics.get("momentum_1m")
    if "stat_arb" in strategies:
        _, _, sa_metrics = strategies["stat_arb"]
        all_metrics["hurst_exponent"] = sa_metrics.get("hurst_exponent")

    # Add MACD for convenience
    macd_line, signal_line, histogram = calculate_macd(df["close"])
    all_metrics["macd_histogram"] = float(histogram.iloc[-1]) if not pd.isna(histogram.iloc[-1]) else 0.0
    all_metrics["macd_signal"] = float(signal_line.iloc[-1]) if not pd.isna(signal_line.iloc[-1]) else 0.0

    reasoning_parts = []
    for name, (sig, conf, _) in strategies.items():
        reasoning_parts.append(f"{name}={sig}({conf:.0%})")
    reasoning = f"{signal} ({confidence:.0%}): " + ", ".join(reasoning_parts)

    return AnalystSignal(
        agent_id="technical",
        signal=signal,
        confidence=confidence,
        reasoning=reasoning[:200],
        metrics=all_metrics,
    )
