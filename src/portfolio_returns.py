"""Pure functions for the percent-first portfolio return series.

Computes a flow-free "current-holdings price performance" index: the weighted
price return of the stocks you currently hold over a window, normalized to 0%
at the window start. No cash / contribution data is involved, so deposits and
new buys cannot inflate the number.

Kept free of FastAPI / pydantic / DB imports so it is trivially unit-testable.
"""

from __future__ import annotations

from datetime import date, timedelta


def period_window(period: str, today: date) -> date:
    """Return the window-start date for a UI period tab.

    Unknown values fall back to the 1M window.
    """
    p = (period or "").strip().upper()
    if p == "1W":
        return today - timedelta(days=7)
    if p == "3M":
        return today - timedelta(days=90)
    if p == "YTD":
        return date(today.year, 1, 1)
    if p == "1Y":
        return today - timedelta(days=365)
    if p == "ALL":
        return today - timedelta(days=730)
    return today - timedelta(days=30)  # "1M" and default


def _ffill_on_grid(series: dict[str, float], grid: list[str]) -> list[float | None]:
    """Align a {date: price} series onto a sorted date grid with forward-fill.

    For each grid date, returns the most recent observed price at or before it,
    or None for grid dates before the series' first observation.
    """
    items = sorted(series.items())
    out: list[float | None] = []
    last: float | None = None
    i = 0
    n = len(items)
    for d in grid:
        while i < n and items[i][0] <= d:
            last = items[i][1]
            i += 1
        out.append(last)
    return out


def compute_return_series(
    quantities: dict[str, float],
    price_series: dict[str, dict[str, float]],
) -> tuple[list[dict[str, float]], float]:
    """Weighted normalized-return index for the current basket.

    Args:
        quantities: current share quantity per symbol.
        price_series: {symbol: {iso_date: close_price}} over the window.

    Returns:
        (points, period_return_pct), where points is a list of
        {"date": iso_date, "returnPct": pct} ascending by date, and
        period_return_pct is the last point's value (0.0 if empty).
    """
    included = [s for s, q in quantities.items() if q > 0 and price_series.get(s)]
    if not included:
        return [], 0.0

    # Fixed weights from current holdings: qty * latest price in the window.
    last_price = {s: price_series[s][max(price_series[s])] for s in included}
    raw_weights = {s: quantities[s] * last_price[s] for s in included}
    total = sum(raw_weights.values())
    if total <= 0:
        return [], 0.0
    weights = {s: raw_weights[s] / total for s in included}

    baselines = {s: price_series[s][min(price_series[s])] for s in included}

    grid_set: set[str] = set()
    for s in included:
        grid_set.update(price_series[s].keys())
    grid = sorted(grid_set)

    ffilled = {s: _ffill_on_grid(price_series[s], grid) for s in included}

    points: list[dict[str, float]] = []
    for idx, d in enumerate(grid):
        num = 0.0
        wsum = 0.0
        for s in included:
            p = ffilled[s][idx]
            base = baselines[s]
            if p is None or base <= 0:
                continue
            num += weights[s] * (p / base - 1.0)
            wsum += weights[s]
        ret = (num / wsum) if wsum > 0 else 0.0
        points.append({"date": d, "returnPct": round(ret * 100.0, 4)})

    period_return = points[-1]["returnPct"] if points else 0.0
    return points, period_return
