"""Valuation agent — 4-model weighted DCF and multiples analysis.

Entirely deterministic (no LLM calls). Uses fundamentals data from
OpenBB/FMP and latest price from OHLCV.

Data source: OpenBB/FMP via openbb_service.get_fundamentals()
"""

from __future__ import annotations

from src.analysis.models import AnalysisInput, AnalystSignal

MODEL_WEIGHTS: dict[str, float] = {
    "owner_earnings": 0.35,
    "dcf": 0.35,
    "ev_ebitda": 0.20,
    "residual_income": 0.10,
}


def _safe_get(d: dict, key: str) -> float | None:
    """Return d[key] as float, or None if missing/unconvertible."""
    v = d.get(key)
    if v is None:
        return None
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


def _get_current_price(input: AnalysisInput) -> float | None:
    """Get most recent close price from OHLCV data."""
    if input.ohlcv:
        return input.ohlcv[-1].close
    return None


def _calculate_wacc(f: dict) -> float:
    """WACC via CAPM. Risk-free 4.5% + beta * 6% equity premium. Floor 6%, cap 20%."""
    beta = _safe_get(f, "beta") or 1.0
    cost_of_equity = 0.045 + beta * 0.06

    # Simplified: assume 30% debt weight, 70% equity weight
    debt_to_equity = _safe_get(f, "debtToEquity") or 0.5
    debt_weight = debt_to_equity / (1 + debt_to_equity)
    equity_weight = 1 - debt_weight

    # Cost of debt from interest coverage
    interest_coverage = _safe_get(f, "interestCoverage")
    if interest_coverage and interest_coverage > 0:
        cost_of_debt = 0.045 + max(0.01, 0.06 / interest_coverage)
    else:
        cost_of_debt = 0.08

    wacc = equity_weight * cost_of_equity + debt_weight * cost_of_debt * 0.75  # 25% tax shield
    return max(0.06, min(wacc, 0.20))


def _owner_earnings_model(f: dict, current_price: float) -> tuple[float | None, dict]:
    """Buffett owner earnings model. Returns (intrinsic_value_per_share, metrics)."""
    net_income = _safe_get(f, "netIncome")
    depreciation = _safe_get(f, "depreciationAndAmortization") or 0.0
    capex = _safe_get(f, "capitalExpenditure") or 0.0
    wc_change = _safe_get(f, "changeInWorkingCapital") or 0.0
    shares = _safe_get(f, "sharesOutstanding")

    if net_income is None or shares is None or shares <= 0:
        return None, {"model": "owner_earnings", "status": "insufficient_data"}

    owner_earnings = net_income + depreciation - abs(capex) - wc_change

    # 5-year projection with 5% growth, 15% discount rate, 25% margin of safety
    growth_rate = 0.05
    discount_rate = 0.15
    terminal_growth = 0.03

    pv_sum = 0.0
    for year in range(1, 6):
        future_oe = owner_earnings * (1 + growth_rate) ** year
        pv_sum += future_oe / (1 + discount_rate) ** year

    # Terminal value
    terminal_oe = owner_earnings * (1 + growth_rate) ** 5 * (1 + terminal_growth)
    terminal_value = terminal_oe / (discount_rate - terminal_growth)
    pv_terminal = terminal_value / (1 + discount_rate) ** 5

    intrinsic_total = (pv_sum + pv_terminal) * 0.75  # 25% margin of safety
    intrinsic_per_share = intrinsic_total / shares

    metrics = {
        "model": "owner_earnings",
        "owner_earnings": round(owner_earnings, 2),
        "intrinsic_value": round(intrinsic_per_share, 2),
        "gap_pct": round((intrinsic_per_share - current_price) / current_price * 100, 2),
    }
    return intrinsic_per_share, metrics


def _dcf_model(f: dict, current_price: float) -> tuple[float | None, dict]:
    """Enhanced DCF with 3-stage growth and scenario weighting."""
    fcf = _safe_get(f, "freeCashFlow")
    shares = _safe_get(f, "sharesOutstanding")

    if fcf is None or shares is None or shares <= 0:
        return None, {"model": "dcf", "status": "insufficient_data"}

    wacc = _calculate_wacc(f)

    # Growth rates: stage 1 (years 1-3), stage 2 (years 4-7), stage 3 (terminal)
    # Base case
    scenarios = {
        "bear": {"g1": 0.02, "g2": 0.01, "terminal": 0.02, "weight": 0.20},
        "base": {"g1": 0.08, "g2": 0.05, "terminal": 0.03, "weight": 0.60},
        "bull": {"g1": 0.15, "g2": 0.08, "terminal": 0.03, "weight": 0.20},
    }

    weighted_value = 0.0
    scenario_results = {}

    for scenario_name, params in scenarios.items():
        pv_sum = 0.0
        projected_fcf = fcf

        for year in range(1, 8):
            if year <= 3:
                projected_fcf *= 1 + params["g1"]
            else:
                projected_fcf *= 1 + params["g2"]
            pv_sum += projected_fcf / (1 + wacc) ** year

        # Terminal value
        terminal_fcf = projected_fcf * (1 + params["terminal"])
        terminal_value = terminal_fcf / (wacc - params["terminal"])
        pv_terminal = terminal_value / (1 + wacc) ** 7

        total_value = pv_sum + pv_terminal
        value_per_share = total_value / shares
        weighted_value += value_per_share * params["weight"]
        scenario_results[scenario_name] = round(value_per_share, 2)

    metrics = {
        "model": "dcf",
        "wacc": round(wacc, 4),
        "scenarios": scenario_results,
        "intrinsic_value": round(weighted_value, 2),
        "gap_pct": round((weighted_value - current_price) / current_price * 100, 2),
    }
    return weighted_value, metrics


def _ev_ebitda_model(f: dict, current_price: float) -> tuple[float | None, dict]:
    """EV/EBITDA multiples valuation."""
    ebitda = _safe_get(f, "ebitda")
    shares = _safe_get(f, "sharesOutstanding")
    total_debt = _safe_get(f, "totalDebt") or 0.0
    cash = _safe_get(f, "cashAndEquivalents") or _safe_get(f, "cashAndShortTermInvestments") or 0.0

    if ebitda is None or shares is None or shares <= 0 or ebitda <= 0:
        return None, {"model": "ev_ebitda", "status": "insufficient_data"}

    # Use sector median of ~12x as default EV/EBITDA multiple
    ev_multiple = 12.0

    implied_ev = ebitda * ev_multiple
    equity_value = implied_ev - total_debt + cash
    value_per_share = equity_value / shares

    metrics = {
        "model": "ev_ebitda",
        "ebitda": round(ebitda, 2),
        "ev_multiple": ev_multiple,
        "intrinsic_value": round(value_per_share, 2),
        "gap_pct": round((value_per_share - current_price) / current_price * 100, 2),
    }
    return value_per_share, metrics


def _residual_income_model(f: dict, current_price: float) -> tuple[float | None, dict]:
    """Residual income model: book value + PV of excess returns."""
    book_value_ps = _safe_get(f, "bookValuePerShare")
    roe = _safe_get(f, "returnOnEquity")

    if book_value_ps is None or roe is None:
        return None, {"model": "residual_income", "status": "insufficient_data"}

    cost_of_equity = 0.045 + (_safe_get(f, "beta") or 1.0) * 0.06

    # 5-year residual income projection
    bv = book_value_ps
    pv_residual = 0.0
    for year in range(1, 6):
        residual = bv * (roe - cost_of_equity)
        pv_residual += residual / (1 + cost_of_equity) ** year
        bv *= 1 + roe * 0.5  # Assume 50% retention ratio

    intrinsic = (book_value_ps + pv_residual) * 0.80  # 20% margin of safety

    metrics = {
        "model": "residual_income",
        "book_value_ps": round(book_value_ps, 2),
        "roe": round(roe, 4),
        "intrinsic_value": round(intrinsic, 2),
        "gap_pct": round((intrinsic - current_price) / current_price * 100, 2),
    }
    return intrinsic, metrics


async def run(input: AnalysisInput) -> AnalystSignal:
    """Run valuation analysis using 4 weighted models.

    Deterministic — no LLM or network calls.
    """
    if not input.fundamentals:
        return AnalystSignal(
            agent_id="valuation",
            signal="neutral",
            confidence=0.0,
            reasoning="No fundamental data available for valuation",
            metrics={},
        )

    current_price = _get_current_price(input)
    if current_price is None or current_price <= 0:
        return AnalystSignal(
            agent_id="valuation",
            signal="neutral",
            confidence=0.0,
            reasoning="No current price available for valuation comparison",
            metrics={},
        )

    f = input.fundamentals
    models: dict[str, tuple[float | None, dict]] = {}

    models["owner_earnings"] = _owner_earnings_model(f, current_price)
    models["dcf"] = _dcf_model(f, current_price)
    models["ev_ebitda"] = _ev_ebitda_model(f, current_price)
    models["residual_income"] = _residual_income_model(f, current_price)

    # Weighted gap calculation
    total_weighted_gap = 0.0
    total_weight = 0.0
    valid_models = {}

    for name, (value, metrics) in models.items():
        if value is not None:
            gap = (value - current_price) / current_price
            weight = MODEL_WEIGHTS[name]
            total_weighted_gap += gap * weight
            total_weight += weight
            valid_models[name] = (value, gap, metrics)

    if total_weight == 0:
        return AnalystSignal(
            agent_id="valuation",
            signal="neutral",
            confidence=0.0,
            reasoning="Insufficient data for any valuation model",
            metrics={name: m for name, (_, m) in models.items()},
        )

    weighted_gap = total_weighted_gap / total_weight

    # Signal: >15% undervalued = bullish, <-15% overvalued = bearish
    if weighted_gap > 0.15:
        signal = "bullish"
    elif weighted_gap < -0.15:
        signal = "bearish"
    else:
        signal = "neutral"

    confidence = min(abs(weighted_gap) / 0.5, 1.0)  # Scale: 50% gap = max confidence

    # Collect all metrics
    all_metrics: dict = {
        "current_price": current_price,
        "weighted_gap_pct": round(weighted_gap * 100, 2),
        "models_used": list(valid_models.keys()),
    }
    for name, (_, m) in models.items():
        all_metrics[name] = m

    parts = [f"{name}={m.get('gap_pct', 'N/A')}%" for name, (_, m) in models.items()]
    reasoning = f"{signal} ({confidence:.0%}), gap={weighted_gap * 100:.1f}%: " + ", ".join(parts)

    return AnalystSignal(
        agent_id="valuation",
        signal=signal,
        confidence=confidence,
        reasoning=reasoning[:200],
        metrics=all_metrics,
    )
