"""Risk analysis agent — volatility, VaR, and portfolio risk metrics.

Entirely deterministic (no LLM calls). Uses OHLCV data from Databento,
positions table, and account_balances.

Data source: Databento OHLCV via price_service, positions, account_balances
"""

from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pandas as pd

from src.analysis.models import AnalysisInput, AnalystSignal, PortfolioRiskReport

MIN_BARS = 30  # Minimum bars for risk calculations


async def run(input: AnalysisInput) -> AnalystSignal:
    """Run per-stock risk analysis on OHLCV data.

    Computes: annualized volatility, volatility percentile, max drawdown,
    and position size recommendation.

    Signal logic:
    - Low vol (<15% annualized): bullish (favorable risk profile)
    - High vol (>40%): bearish (elevated risk)
    - Moderate: neutral
    """
    if not input.ohlcv or len(input.ohlcv) < MIN_BARS:
        return AnalystSignal(
            agent_id="risk",
            signal="neutral",
            confidence=0.0,
            reasoning="Insufficient OHLCV data for risk analysis",
            metrics={"bars_available": len(input.ohlcv) if input.ohlcv else 0},
        )

    # Convert to DataFrame
    df = pd.DataFrame([bar.model_dump() for bar in input.ohlcv])
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)
    close = df["close"]

    # Daily returns
    daily_returns = close.pct_change().dropna()

    # Annualized volatility: 60d rolling std * sqrt(252)
    window = min(60, len(daily_returns))
    rolling_vol = daily_returns.rolling(window=window).std() * np.sqrt(252)
    ann_vol = float(rolling_vol.iloc[-1]) if not pd.isna(rolling_vol.iloc[-1]) else 0.0

    # Volatility percentile: current vol rank vs available history
    vol_values = rolling_vol.dropna()
    if len(vol_values) > 1:
        vol_percentile = float((vol_values < ann_vol).sum() / len(vol_values))
    else:
        vol_percentile = 0.5

    # Max drawdown
    cumulative = (1 + daily_returns).cumprod()
    running_max = cumulative.cummax()
    drawdown = (cumulative - running_max) / running_max
    max_drawdown = float(drawdown.min()) if len(drawdown) > 0 else 0.0

    # Position size recommendation (volatility-adjusted)
    if ann_vol < 0.15:
        pos_size_pct = 25.0  # Low vol: up to 25%
    elif ann_vol < 0.30:
        pos_size_pct = 20.0 - (ann_vol - 0.15) * 50.0  # Linear scale 20% -> 12.5%
    elif ann_vol < 0.50:
        pos_size_pct = 12.5 - (ann_vol - 0.30) * 37.5  # Linear scale 12.5% -> 5%
    else:
        pos_size_pct = max(2.0, 10.0 - ann_vol * 10.0)  # Cap at 10%, floor at 2%

    # Signal logic
    if ann_vol < 0.15:
        signal = "bullish"
    elif ann_vol > 0.40:
        signal = "bearish"
    else:
        signal = "neutral"

    # Confidence based on how extreme the volatility is
    if signal == "bullish":
        confidence = min((0.15 - ann_vol) / 0.15, 1.0)
    elif signal == "bearish":
        confidence = min((ann_vol - 0.40) / 0.30, 1.0)
    else:
        confidence = 0.3 + abs(ann_vol - 0.275) / 0.275 * 0.4  # 0.3-0.7 range

    confidence = max(0.0, min(confidence, 1.0))

    metrics = {
        "annualized_volatility": round(ann_vol, 4),
        "volatility_percentile": round(vol_percentile, 4),
        "max_drawdown": round(max_drawdown, 4),
        "position_size_recommendation_pct": round(pos_size_pct, 2),
        "bars_available": len(df),
    }

    reasoning = (
        f"{signal} ({confidence:.0%}): vol={ann_vol:.1%}, "
        f"percentile={vol_percentile:.0%}, drawdown={max_drawdown:.1%}, "
        f"size_rec={pos_size_pct:.1f}%"
    )

    return AnalystSignal(
        agent_id="risk",
        signal=signal,
        confidence=confidence,
        reasoning=reasoning[:200],
        metrics=metrics,
    )


def compute_portfolio_risk(
    returns_data: dict[str, np.ndarray],
    weights: dict[str, float],
    sector_map: dict[str, str],
    total_value: float,
) -> PortfolioRiskReport:
    """Compute portfolio-wide risk metrics.

    Args:
        returns_data: {ticker: array of daily returns}
        weights: {ticker: portfolio weight (0-1)}
        sector_map: {ticker: sector_name}
        total_value: Total portfolio value in dollars

    Returns:
        PortfolioRiskReport with VaR, HHI, correlation matrix, etc.
    """
    tickers = list(returns_data.keys())

    if not tickers:
        now = datetime.now(tz=timezone.utc)
        return PortfolioRiskReport(
            var_95_1d=0.0,
            var_95_5d=0.0,
            concentration_hhi=0.0,
            diversification_ratio=0.0,
            correlation_matrix={},
            top_risk_contributors=[],
            sector_exposure={},
            computed_at=now,
            data_sources=[],
        )

    # Align returns to same length (use shortest)
    min_len = min(len(r) for r in returns_data.values())
    aligned = {t: r[-min_len:] for t, r in returns_data.items()}

    # Build returns DataFrame
    returns_df = pd.DataFrame(aligned)

    # Portfolio returns (weighted)
    weight_array = np.array([weights.get(t, 0.0) for t in tickers])
    weight_array = weight_array / weight_array.sum() if weight_array.sum() > 0 else weight_array
    portfolio_returns = returns_df.values @ weight_array

    # VaR 95% (historical simulation)
    var_95_1d_pct = float(np.percentile(portfolio_returns, 5))
    var_95_1d = abs(var_95_1d_pct) * total_value

    # 5-day VaR: scale by sqrt(5)
    var_95_5d = var_95_1d * np.sqrt(5)

    # Concentration HHI (Herfindahl-Hirschman Index)
    hhi = float(np.sum(weight_array**2))

    # Correlation matrix
    corr_matrix = returns_df.corr()
    correlation_dict: dict[str, dict[str, float]] = {}
    for t1 in tickers:
        correlation_dict[t1] = {}
        for t2 in tickers:
            val = corr_matrix.loc[t1, t2] if t1 in corr_matrix.index and t2 in corr_matrix.columns else 0.0
            correlation_dict[t1][t2] = round(float(val), 4) if not pd.isna(val) else 0.0

    # Diversification ratio: weighted avg individual vol / portfolio vol
    individual_vols = returns_df.std() * np.sqrt(252)
    weighted_avg_vol = float(np.sum(weight_array * individual_vols.values))
    portfolio_vol = float(np.std(portfolio_returns) * np.sqrt(252))
    diversification_ratio = weighted_avg_vol / portfolio_vol if portfolio_vol > 0 else 1.0

    # Top risk contributors (marginal VaR contribution)
    top_risk = []
    for i, t in enumerate(tickers):
        contribution = float(weight_array[i] * individual_vols.iloc[i])
        top_risk.append({
            "ticker": t,
            "weight_pct": round(float(weight_array[i]) * 100, 2),
            "annualized_vol": round(float(individual_vols.iloc[i]), 4),
            "contribution_pct": round(contribution / weighted_avg_vol * 100, 2) if weighted_avg_vol > 0 else 0.0,
        })
    top_risk.sort(key=lambda x: x["contribution_pct"], reverse=True)

    # Sector exposure
    sector_exposure: dict[str, float] = {}
    for i, t in enumerate(tickers):
        sector = sector_map.get(t, "Unknown")
        sector_exposure[sector] = sector_exposure.get(sector, 0.0) + float(weight_array[i])
    sector_exposure = {k: round(v, 4) for k, v in sector_exposure.items()}

    now = datetime.now(tz=timezone.utc)

    return PortfolioRiskReport(
        var_95_1d=round(var_95_1d, 2),
        var_95_5d=round(var_95_5d, 2),
        concentration_hhi=round(hhi, 4),
        diversification_ratio=round(diversification_ratio, 4),
        correlation_matrix=correlation_dict,
        top_risk_contributors=top_risk,
        sector_exposure=sector_exposure,
        computed_at=now,
        data_sources=["ohlcv", "positions"],
    )
