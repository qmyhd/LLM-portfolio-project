"""Fundamental scoring agent — deterministic, no LLM calls.

Scores a ticker's fundamentals across 4 equal-weight pillars:
  1. Profitability  (ROE, net margin, ROA)
  2. Growth         (PEG ratio, dividend yield)
  3. Financial Health (current ratio, debt/equity, FCF quality)
  4. Valuation      (P/E, P/B, P/S)

Data source: OpenBB/FMP via ``openbb_service.get_fundamentals()`` which returns
a flat dict with keys like ``returnOnEquity``, ``peRatio``, etc.
"""

from __future__ import annotations

from src.analysis.models import AnalysisInput, AnalystSignal


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _safe_get(d: dict, key: str) -> float | None:
    """Return *d[key]* as a float, or ``None`` if missing / unconvertible."""
    v = d.get(key)
    if v is None:
        return None
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


def _direction(bullish: int, bearish: int) -> str:
    """Derive an overall direction from bullish/bearish vote counts."""
    if bullish > bearish:
        return "bullish"
    if bearish > bullish:
        return "bearish"
    return "neutral"


# ---------------------------------------------------------------------------
# Pillar 1 — Profitability
# ---------------------------------------------------------------------------


def _score_profitability(f: dict) -> tuple[str, float, dict]:
    """Score profitability using ROE, net margin, and ROA.

    Returns (signal, confidence, metrics_dict).
    """
    bullish = 0
    bearish = 0
    evaluated = 0
    scores: dict[str, str] = {}

    roe = _safe_get(f, "returnOnEquity")
    if roe is not None:
        evaluated += 1
        if roe > 0.15:
            bullish += 1
            scores["roe"] = "bullish"
        else:
            bearish += 1
            scores["roe"] = "bearish"

    # Net margin derived from epsActual / revenuePerShare
    eps = _safe_get(f, "epsActual")
    rps = _safe_get(f, "revenuePerShare")
    net_margin: float | None = None
    if eps is not None and rps is not None and rps != 0:
        net_margin = eps / rps
        evaluated += 1
        if net_margin > 0.20:
            bullish += 1
            scores["net_margin"] = "bullish"
        else:
            bearish += 1
            scores["net_margin"] = "bearish"

    roa = _safe_get(f, "returnOnAssets")
    if roa is not None:
        evaluated += 1
        if roa > 0.10:
            bullish += 1
            scores["roa"] = "bullish"
        else:
            bearish += 1
            scores["roa"] = "bearish"

    if evaluated == 0:
        return ("neutral", 0.0, {"roe": roe, "net_margin": net_margin, "roa": roa, "scores": scores})

    signal = _direction(bullish, bearish)
    confidence = max(bullish, bearish) / evaluated

    return (signal, confidence, {"roe": roe, "net_margin": net_margin, "roa": roa, "scores": scores})


# ---------------------------------------------------------------------------
# Pillar 2 — Growth
# ---------------------------------------------------------------------------


def _score_growth(f: dict) -> tuple[str, float, dict]:
    """Score growth using PEG ratio and dividend yield.

    Returns (signal, confidence, metrics_dict).
    """
    peg = _safe_get(f, "pegRatio")
    div_yield = _safe_get(f, "dividendYield")

    if peg is None:
        return ("neutral", 0.0, {"peg_ratio": peg, "dividend_yield": div_yield})

    bullish_points = 0
    bearish_points = 0

    # PEG scoring
    if peg < 1.0:
        bullish_points += 2  # strong bullish
    elif peg <= 1.5:
        bullish_points += 1  # weak bullish
    elif peg > 2.0:
        bearish_points += 1

    # Dividend yield bonus
    if div_yield is not None and div_yield > 0:
        bullish_points += 1

    if bullish_points >= 2:
        signal = "bullish"
    elif bearish_points >= 2:
        signal = "bearish"
    else:
        signal = "neutral"

    total = bullish_points + bearish_points
    confidence = max(bullish_points, bearish_points) / max(total, 1)

    return (signal, confidence, {"peg_ratio": peg, "dividend_yield": div_yield})


# ---------------------------------------------------------------------------
# Pillar 3 — Financial Health
# ---------------------------------------------------------------------------


def _score_financial_health(f: dict) -> tuple[str, float, dict]:
    """Score financial health using current ratio, debt/equity, and FCF quality.

    Returns (signal, confidence, metrics_dict).
    """
    bullish = 0
    bearish = 0
    evaluated = 0

    current_ratio = _safe_get(f, "currentRatio")
    if current_ratio is not None:
        evaluated += 1
        if current_ratio > 1.5:
            bullish += 1
        elif current_ratio < 1.0:
            bearish += 1

    debt_to_equity = _safe_get(f, "debtToEquity")
    if debt_to_equity is not None:
        evaluated += 1
        if debt_to_equity < 0.5:
            bullish += 1
        elif debt_to_equity > 2.0:
            bearish += 1

    # FCF quality: freeCashFlowPerShare / epsActual
    fcf_ps = _safe_get(f, "freeCashFlowPerShare")
    eps = _safe_get(f, "epsActual")
    fcf_to_eps: float | None = None
    if fcf_ps is not None and eps is not None and eps != 0:
        fcf_to_eps = fcf_ps / eps
        evaluated += 1
        if fcf_to_eps > 0.8:
            bullish += 1
        else:
            bearish += 1

    if evaluated == 0:
        return (
            "neutral",
            0.0,
            {"current_ratio": current_ratio, "debt_to_equity": debt_to_equity, "fcf_to_eps": fcf_to_eps},
        )

    signal = _direction(bullish, bearish)
    confidence = max(bullish, bearish) / evaluated

    return (
        signal,
        confidence,
        {"current_ratio": current_ratio, "debt_to_equity": debt_to_equity, "fcf_to_eps": fcf_to_eps},
    )


# ---------------------------------------------------------------------------
# Pillar 4 — Valuation
# ---------------------------------------------------------------------------


def _score_valuation(f: dict) -> tuple[str, float, dict]:
    """Score valuation using P/E, P/B, and P/S multiples.

    Returns (signal, confidence, metrics_dict).
    """
    bullish = 0
    bearish = 0
    evaluated = 0

    pe = _safe_get(f, "peRatio")
    if pe is not None:
        evaluated += 1
        if pe > 25:
            bearish += 1
        elif pe < 15:
            bullish += 1

    ptb = _safe_get(f, "priceToBook")
    if ptb is not None:
        evaluated += 1
        if ptb > 3:
            bearish += 1
        elif ptb < 1.5:
            bullish += 1

    pts = _safe_get(f, "priceToSales")
    if pts is not None:
        evaluated += 1
        if pts > 5:
            bearish += 1
        elif pts < 2:
            bullish += 1

    if evaluated == 0:
        return ("neutral", 0.0, {"pe_ratio": pe, "price_to_book": ptb, "price_to_sales": pts})

    signal = _direction(bullish, bearish)
    confidence = max(bullish, bearish) / evaluated

    return (signal, confidence, {"pe_ratio": pe, "price_to_book": ptb, "price_to_sales": pts})


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


async def run(input: AnalysisInput) -> AnalystSignal:
    """Run fundamental scoring on financial metrics.

    Deterministic — no LLM or network calls. Scores fundamentals from
    OpenBB/FMP data using threshold-based rules across 4 pillars.
    """
    if not input.fundamentals:
        return AnalystSignal(
            agent_id="fundamental",
            signal="neutral",
            confidence=0.0,
            reasoning="No fundamental data available",
            metrics={},
        )

    f = input.fundamentals
    pillars: dict[str, tuple[str, float, dict]] = {}

    pillars["profitability"] = _score_profitability(f)
    pillars["growth"] = _score_growth(f)
    pillars["financial_health"] = _score_financial_health(f)
    pillars["valuation"] = _score_valuation(f)

    # Aggregate: count pillar signals
    bullish = sum(1 for _, (sig, _, _) in pillars.items() if sig == "bullish")
    bearish = sum(1 for _, (sig, _, _) in pillars.items() if sig == "bearish")
    evaluated = sum(1 for _, (_, conf, _) in pillars.items() if conf > 0)

    if evaluated == 0:
        overall_signal = "neutral"
        overall_confidence = 0.0
    elif bullish > bearish:
        overall_signal = "bullish"
        overall_confidence = bullish / max(evaluated, 1)
    elif bearish > bullish:
        overall_signal = "bearish"
        overall_confidence = bearish / max(evaluated, 1)
    else:
        overall_signal = "neutral"
        overall_confidence = 0.5

    # Collect metrics
    all_metrics: dict = {}
    for name, (sig, conf, metrics) in pillars.items():
        all_metrics[name] = {"signal": sig, "confidence": conf, **metrics}

    # Build reasoning
    parts = [f"{name}={sig}({conf:.0%})" for name, (sig, conf, _) in pillars.items()]
    reasoning = f"{overall_signal} ({overall_confidence:.0%}): " + ", ".join(parts)

    return AnalystSignal(
        agent_id="fundamental",
        signal=overall_signal,
        confidence=overall_confidence,
        reasoning=reasoning[:200],
        metrics=all_metrics,
    )
