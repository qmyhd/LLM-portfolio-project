# Percent-First Portfolio Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the big dollar account value (and cash/buying-power) in the portfolio UI with cash-free percentage performance — a flow-free "current-holdings price performance" return series for the hero and curve, % weight + % returns in tables, and VaR shown as a percentage.

**Architecture:** One new pure backend module (`src/portfolio_returns.py`) computes a weighted normalized-return index from current holdings' price history; a new `/portfolio/return-series` endpoint wires holdings + price sources into it; the risk report exposes its already-computed VaR percentage; the frontend stops rendering dollar totals and renders the new percentage data. `cash`/`buyingPower` remain in the API payload but go unrendered.

**Tech Stack:** Python 3.11 / FastAPI / SQLAlchemy / pandas / pytest (backend, repo root `c:\Users\qaism\OneDrive\Documents\Github\LLM-portfolio-project`). Next.js 14 / React 18 / TypeScript / SWR / lightweight-charts (frontend, nested at `c:\Users\qaism\OneDrive\Documents\Github\LLM-portfolio-frontend\frontend`). **Branch:** `design/portfolio-percent-first-and-ai-profiling`.

**Spec:** `docs/superpowers/specs/2026-06-01-percent-first-portfolio-design.md`

---

## Conventions

- **Backend tests:** `pytest tests/ -v -m "not openai and not integration"`. FastAPI routes are tested with `TestClient` + `DISABLE_AUTH=true`; DB and price functions are mocked by patching the **name as imported into the route module** (e.g. `app.routes.portfolio.execute_sql`). Mock rows expose a `._mapping` dict (see `_mock_row`).
- **Frontend:** there is **no JS test runner** in this repo (no jest/vitest — confirmed in `package.json`). Adding one is **out of scope** for this project. Frontend verification = `npm run lint` and `npm run build` (TypeScript type-check) from the `frontend/` directory, plus the manual visual checklist in each task.
- **Every commit message ends with the trailer:**
  `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`
- All frontend paths are relative to `c:\Users\qaism\OneDrive\Documents\Github\LLM-portfolio-frontend\frontend\`.

## File Structure

**Backend (create):**
- `src/portfolio_returns.py` — pure functions: `period_window()`, `compute_return_series()`, `_ffill_on_grid()`. No FastAPI/DB/pydantic imports.
- `tests/test_portfolio_returns.py`, `tests/test_crypto_price_series.py`, `tests/test_return_series_route.py`, `tests/test_risk_var_pct.py`.

**Backend (modify):**
- `src/market_data_service.py` — add `get_crypto_price_series()` (+ a daily-close TTL cache).
- `app/routes/portfolio.py` — add `ReturnSeriesPoint`/`ReturnSeriesResponse` models + the `/return-series` endpoint + imports.
- `src/analysis/models.py` — add `var_95_1d_pct`/`var_95_5d_pct` to `PortfolioRiskReport`.
- `src/analysis/risk.py` — populate those two fields.

**Frontend (create):**
- `src/app/api/portfolio/return-series/route.ts` — proxy to the backend endpoint.

**Frontend (modify):**
- `src/types/api.ts` — add `ReturnSeriesPoint`/`ReturnSeriesResponse`; add the two VaR pct fields to `PortfolioRiskReport`.
- `src/components/dashboard/RobinhoodHeader.tsx` — hero = period return; drop $ value/cash/buying-power; clarity tooltip.
- `src/components/portfolio/EquityCurveCard.tsx` — % return curve (0% baseline).
- `src/components/dashboard/HoldingsTable.tsx` — % weight + % day change (drop $).
- `src/components/dashboard/PortfolioRiskCard.tsx` — VaR as %.
- `src/components/stock/RobinhoodPositionCard.tsx` — % return / weight (drop $ value & P/L$).

---

## Task 1: Pure return-series module (`src/portfolio_returns.py`)

**Files:**
- Create: `src/portfolio_returns.py`
- Test: `tests/test_portfolio_returns.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_portfolio_returns.py`:

```python
from datetime import date

from src.portfolio_returns import compute_return_series, period_window


def test_period_window_basic():
    today = date(2026, 6, 1)
    assert period_window("1W", today) == date(2026, 5, 25)
    assert period_window("YTD", today) == date(2026, 1, 1)
    assert period_window("1M", today) == date(2026, 5, 2)
    assert period_window("unknown", today) == date(2026, 5, 2)  # default 1M


def test_single_holding_equals_price_return():
    points, period = compute_return_series(
        {"AAPL": 10.0},
        {"AAPL": {"2026-05-01": 100.0, "2026-05-02": 110.0}},
    )
    assert points[0] == {"date": "2026-05-01", "returnPct": 0.0}
    assert points[-1]["returnPct"] == 10.0
    assert period == 10.0


def test_quantity_scaling_is_invariant_flow_free():
    series = {
        "AAPL": {"2026-05-01": 100.0, "2026-05-02": 110.0},
        "MSFT": {"2026-05-01": 200.0, "2026-05-02": 210.0},
    }
    a, ra = compute_return_series({"AAPL": 10, "MSFT": 5}, series)
    b, rb = compute_return_series({"AAPL": 1000, "MSFT": 500}, series)
    assert a == b and ra == rb


def test_baseline_is_zero_at_window_start():
    points, _ = compute_return_series(
        {"AAPL": 1.0, "MSFT": 1.0},
        {
            "AAPL": {"2026-05-01": 100.0, "2026-05-02": 110.0},
            "MSFT": {"2026-05-01": 50.0, "2026-05-02": 55.0},
        },
    )
    assert points[0]["returnPct"] == 0.0


def test_short_history_holding_renormalizes_no_jump():
    points, _ = compute_return_series(
        {"AAPL": 1.0, "NEW": 1.0},
        {
            "AAPL": {"2026-05-01": 100.0, "2026-05-02": 100.0, "2026-05-03": 110.0},
            "NEW": {"2026-05-03": 200.0},  # only present on the last day
        },
    )
    # Early dates: only AAPL has data -> reflects AAPL alone (flat 0%).
    assert points[0]["returnPct"] == 0.0
    assert points[1]["returnPct"] == 0.0
    # Last date: AAPL +10% (weight 110), NEW 0% (weight 200) -> blended.
    assert points[2]["returnPct"] == round((110 / 310) * 10.0, 4)


def test_empty_inputs_return_zero():
    assert compute_return_series({}, {}) == ([], 0.0)
    assert compute_return_series({"AAPL": 5}, {}) == ([], 0.0)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_portfolio_returns.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.portfolio_returns'`.

- [ ] **Step 3: Write the implementation**

Create `src/portfolio_returns.py`:

```python
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_portfolio_returns.py -v`
Expected: PASS (6 passed).

- [ ] **Step 5: Commit**

```bash
git add src/portfolio_returns.py tests/test_portfolio_returns.py
git commit -m "feat(portfolio): flow-free weighted normalized-return index

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Crypto daily price-series helper (`src/market_data_service.py`)

**Files:**
- Modify: `src/market_data_service.py` (add import + cache + two functions)
- Test: `tests/test_crypto_price_series.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_crypto_price_series.py`:

```python
from datetime import date
from unittest.mock import MagicMock, patch

import pandas as pd


def test_get_crypto_price_series_maps_symbol_and_returns_closes():
    idx = pd.to_datetime(["2026-05-01", "2026-05-02"])
    hist = pd.DataFrame({"Close": [100.0, 110.0]}, index=idx)
    mock_ticker = MagicMock()
    mock_ticker.history.return_value = hist
    mock_yf = MagicMock()
    mock_yf.Ticker.return_value = mock_ticker

    with patch.dict("sys.modules", {"yfinance": mock_yf}):
        import importlib

        import src.market_data_service as mds
        importlib.reload(mds)  # ensure a clean cache for the assertion
        series = mds.get_crypto_price_series("BTC", date(2026, 5, 1), date(2026, 5, 2))

    assert series == {"2026-05-01": 100.0, "2026-05-02": 110.0}
    # _yf_symbol maps BTC -> BTC-USD
    mock_yf.Ticker.assert_called_once_with("BTC-USD")


def test_get_crypto_price_series_empty_on_failure():
    mock_yf = MagicMock()
    mock_yf.Ticker.side_effect = RuntimeError("network down")
    with patch.dict("sys.modules", {"yfinance": mock_yf}):
        import importlib

        import src.market_data_service as mds
        importlib.reload(mds)
        series = mds.get_crypto_price_series("ETH", date(2026, 5, 1), date(2026, 5, 2))
    assert series == {}
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_crypto_price_series.py -v`
Expected: FAIL with `AttributeError: module 'src.market_data_service' has no attribute 'get_crypto_price_series'`.

- [ ] **Step 3: Add the import for date/timedelta**

In `src/market_data_service.py`, the top imports currently are:

```python
import logging
import threading
from typing import Optional
```

Add a datetime import directly below `import threading`:

```python
import logging
import threading
from datetime import date, timedelta
from typing import Optional
```

- [ ] **Step 4: Add the cache + functions**

In `src/market_data_service.py`, the cache block currently ends with:

```python
_search_cache = TTLCache(maxsize=200, ttl=3_600)  # 1 h
_search_lock = threading.Lock()
```

Add directly below it:

```python
_crypto_series_cache = TTLCache(maxsize=200, ttl=3_600)  # 1 h
_crypto_series_lock = threading.Lock()
```

Then add these two functions near the other `get_*` functions (e.g. after `get_return_metrics`):

```python
@hardened_retry(max_retries=2, delay=1)
def _fetch_crypto_price_series(symbol: str, start: date, end: date) -> dict[str, float]:
    import yfinance as yf

    ticker = yf.Ticker(_yf_symbol(symbol))
    # yfinance treats `end` as exclusive; add a day so `end` is included.
    hist = ticker.history(
        start=start.isoformat(),
        end=(end + timedelta(days=1)).isoformat(),
        interval="1d",
    )
    if hist is None or hist.empty:
        return {}
    out: dict[str, float] = {}
    for ts, close in hist["Close"].items():
        out[ts.date().isoformat()] = float(close)
    return out


def get_crypto_price_series(symbol: str, start: date, end: date) -> dict[str, float]:
    """Daily close series for a crypto symbol over [start, end] inclusive.

    Returns ``{iso_date: close}``; an empty dict on any failure (never raises),
    consistent with the rest of this module.
    """
    symbol = symbol.upper().strip()
    key = (symbol, start.isoformat(), end.isoformat())
    with _crypto_series_lock:
        cached = _crypto_series_cache.get(key)
        if cached is not None:
            return cached
    try:
        result = _fetch_crypto_price_series(symbol, start, end)
    except Exception as e:
        logger.warning("crypto price series failed for %s: %s", symbol, e)
        return {}
    with _crypto_series_lock:
        _crypto_series_cache[key] = result
    return result
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `pytest tests/test_crypto_price_series.py -v`
Expected: PASS (2 passed).

- [ ] **Step 6: Commit**

```bash
git add src/market_data_service.py tests/test_crypto_price_series.py
git commit -m "feat(market-data): get_crypto_price_series daily-close helper

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: `/portfolio/return-series` endpoint (`app/routes/portfolio.py`)

**Files:**
- Modify: `app/routes/portfolio.py` (imports, models, endpoint)
- Test: `tests/test_return_series_route.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_return_series_route.py`:

```python
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest


@pytest.fixture
def client():
    with patch.dict("os.environ", {"DISABLE_AUTH": "true"}):
        from fastapi.testclient import TestClient

        from app.main import app
        with TestClient(app) as c:
            yield c


def _mock_row(data: dict):
    row = MagicMock()
    row._mapping = data
    return row


@patch("app.routes.portfolio.get_crypto_price_series")
@patch("app.routes.portfolio.get_ohlcv")
@patch("app.routes.portfolio.execute_sql")
def test_return_series_equity_only(mock_sql, mock_ohlcv, mock_crypto, client):
    mock_sql.return_value = [_mock_row({"symbol": "AAPL", "quantity": 10})]
    df = pd.DataFrame(
        {
            "Open": [100.0, 110.0], "High": [100.0, 110.0], "Low": [100.0, 110.0],
            "Close": [100.0, 110.0], "Volume": [1, 1],
        },
        index=pd.to_datetime(["2026-05-01", "2026-05-02"]),
    )
    mock_ohlcv.return_value = df
    mock_crypto.return_value = {}

    resp = client.get("/portfolio/return-series?period=1M")
    assert resp.status_code == 200
    data = resp.json()
    assert data["period"] == "1M"
    assert data["points"][0]["returnPct"] == 0.0
    assert data["periodReturnPct"] == 10.0
    mock_crypto.assert_not_called()  # equity symbol must not hit crypto fetch


@patch("app.routes.portfolio.get_crypto_price_series")
@patch("app.routes.portfolio.get_ohlcv")
@patch("app.routes.portfolio.execute_sql")
def test_return_series_routes_crypto(mock_sql, mock_ohlcv, mock_crypto, client):
    mock_sql.return_value = [_mock_row({"symbol": "BTC", "quantity": 2})]
    mock_ohlcv.return_value = pd.DataFrame()
    mock_crypto.return_value = {"2026-05-01": 100.0, "2026-05-02": 120.0}

    resp = client.get("/portfolio/return-series?period=1W")
    assert resp.status_code == 200
    data = resp.json()
    assert data["periodReturnPct"] == 20.0
    mock_crypto.assert_called_once()
    mock_ohlcv.assert_not_called()  # crypto symbol must not hit Databento OHLCV


@patch("app.routes.portfolio.get_crypto_price_series")
@patch("app.routes.portfolio.get_ohlcv")
@patch("app.routes.portfolio.execute_sql")
def test_return_series_empty_portfolio(mock_sql, mock_ohlcv, mock_crypto, client):
    mock_sql.return_value = []
    resp = client.get("/portfolio/return-series?period=3M")
    assert resp.status_code == 200
    data = resp.json()
    assert data["points"] == []
    assert data["periodReturnPct"] == 0.0
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_return_series_route.py -v`
Expected: FAIL (404 on the route, or ImportError for the patched names).

- [ ] **Step 3: Extend the imports**

In `app/routes/portfolio.py`, the imports currently include:

```python
from src.bucket import BucketQuery, bucket_filter_sql, validate_bucket
from src.db import execute_sql
from src.market_data_service import _CRYPTO_SYMBOLS, CRYPTO_IDENTITY, get_realtime_quotes_batch, get_return_metrics
from src.price_service import get_latest_closes_batch, get_previous_closes_batch
from src.snaptrade_collector import SnapTradeCollector
```

Replace those five lines with (adds `get_ohlcv`, `get_crypto_price_series`, and the new module):

```python
from src.bucket import BucketQuery, bucket_filter_sql, validate_bucket
from src.db import execute_sql
from src.market_data_service import (
    _CRYPTO_SYMBOLS,
    CRYPTO_IDENTITY,
    get_crypto_price_series,
    get_realtime_quotes_batch,
    get_return_metrics,
)
from src.portfolio_returns import compute_return_series, period_window
from src.price_service import get_latest_closes_batch, get_ohlcv, get_previous_closes_batch
from src.snaptrade_collector import SnapTradeCollector
```

- [ ] **Step 4: Add the response models**

In `app/routes/portfolio.py`, directly below the existing `EquityPoint` model:

```python
class EquityPoint(BaseModel):
    """One day's total portfolio equity for the active bucket scope."""

    date: str  # ISO date (YYYY-MM-DD)
    equity: float
```

add:

```python
class ReturnSeriesPoint(BaseModel):
    """One day's cumulative % return vs the window start."""

    date: str  # ISO date (YYYY-MM-DD)
    returnPct: float


class ReturnSeriesResponse(BaseModel):
    """Flow-free current-holdings price-performance series for a window."""

    period: str
    asOf: str
    periodReturnPct: float
    points: list[ReturnSeriesPoint]
```

- [ ] **Step 5: Add the endpoint**

In `app/routes/portfolio.py`, directly above the `get_equity_curve` function, add:

```python
@router.get("/return-series", response_model=ReturnSeriesResponse)
async def get_return_series(
    period: str = Query("1M", description="One of: 1W, 1M, 3M, YTD, 1Y, ALL"),
    bucket: str | None = BucketQuery,
):
    """Flow-free % return curve for the current holdings over the window.

    Holds today's quantities constant and reprices them over the period, so a
    mid-window deposit or new buy cannot inflate the number. Equities are priced
    from `ohlcv_daily`; crypto from `get_crypto_price_series`. Normalized to 0%
    at the window start. This is current-holdings performance, NOT actual
    account history.
    """
    bucket = validate_bucket(bucket)
    today = date.today()
    start = period_window(period, today)

    clause, bp = bucket_filter_sql(bucket, alias="acc")
    rows = execute_sql(
        f"""
        SELECT p.symbol AS symbol,
               SUM(p.quantity) AS quantity
        FROM positions p
        LEFT JOIN accounts acc ON acc.id = p.account_id
        WHERE p.quantity > 0
          AND COALESCE(acc.connection_status, 'connected') != 'deleted'
          {clause}
        GROUP BY p.symbol
        """,
        params={**bp},
        fetch_results=True,
    ) or []

    quantities: dict[str, float] = {}
    price_series: dict[str, dict[str, float]] = {}
    for r in rows:
        rd = dict(r._mapping) if hasattr(r, "_mapping") else dict(r)  # type: ignore[arg-type]
        sym = str(rd["symbol"]).upper().strip()
        qty = float(rd["quantity"] or 0)
        if qty <= 0:
            continue
        quantities[sym] = qty

        if sym in _CRYPTO_SYMBOLS:
            series = get_crypto_price_series(sym, start, today)
        else:
            df = get_ohlcv(sym, start, today)
            series = {}
            if not df.empty:
                for idx, row in df.iterrows():
                    series[idx.date().isoformat()] = float(row["Close"])
        if series:
            price_series[sym] = series

    points, period_return = compute_return_series(quantities, price_series)
    return ReturnSeriesResponse(
        period=period.upper(),
        asOf=today.isoformat(),
        periodReturnPct=period_return,
        points=[ReturnSeriesPoint(date=p["date"], returnPct=p["returnPct"]) for p in points],
    )
```

- [ ] **Step 6: Run the test to verify it passes**

Run: `pytest tests/test_return_series_route.py -v`
Expected: PASS (3 passed).

- [ ] **Step 7: Commit**

```bash
git add app/routes/portfolio.py tests/test_return_series_route.py
git commit -m "feat(portfolio): GET /portfolio/return-series endpoint

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Expose VaR percentage on the risk report

**Files:**
- Modify: `src/analysis/models.py` (add two fields)
- Modify: `src/analysis/risk.py` (populate them)
- Test: `tests/test_risk_var_pct.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_risk_var_pct.py`:

```python
from datetime import datetime


def test_portfolio_risk_report_has_var_pct_fields():
    from src.analysis.models import PortfolioRiskReport

    r = PortfolioRiskReport(
        var_95_1d=100.0,
        var_95_5d=224.0,
        var_95_1d_pct=2.5,
        var_95_5d_pct=5.59,
        concentration_hhi=0.10,
        diversification_ratio=1.2,
        correlation_matrix={},
        top_risk_contributors=[],
        sector_exposure={},
        computed_at=datetime(2026, 6, 1),
        data_sources=["ohlcv"],
    )
    assert r.var_95_1d_pct == 2.5
    assert r.var_95_5d_pct == 5.59


def test_var_pct_defaults_are_non_breaking():
    # Existing construction sites that omit the new fields must still work.
    from src.analysis.models import PortfolioRiskReport

    r = PortfolioRiskReport(
        var_95_1d=0.0,
        var_95_5d=0.0,
        concentration_hhi=0.0,
        diversification_ratio=0.0,
        correlation_matrix={},
        top_risk_contributors=[],
        sector_exposure={},
        computed_at=datetime(2026, 6, 1),
        data_sources=[],
    )
    assert r.var_95_1d_pct == 0.0
    assert r.var_95_5d_pct == 0.0
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_risk_var_pct.py -v`
Expected: FAIL (`var_95_1d_pct` is not a field / unexpected keyword).

- [ ] **Step 3: Add the fields to the model**

In `src/analysis/models.py`, the `PortfolioRiskReport` currently starts:

```python
class PortfolioRiskReport(BaseModel):
    """Portfolio-wide risk analysis report."""

    var_95_1d: float
    var_95_5d: float
    concentration_hhi: float
```

Insert the two fields after `var_95_5d`:

```python
class PortfolioRiskReport(BaseModel):
    """Portfolio-wide risk analysis report."""

    var_95_1d: float
    var_95_5d: float
    var_95_1d_pct: float = 0.0  # |VaR| as % of portfolio (percent-first display)
    var_95_5d_pct: float = 0.0
    concentration_hhi: float
```

- [ ] **Step 4: Populate them in `risk.py`**

In `src/analysis/risk.py`, the construction currently reads:

```python
    return PortfolioRiskReport(
        var_95_1d=round(var_95_1d, 2),
        var_95_5d=round(var_95_5d, 2),
        concentration_hhi=round(hhi, 4),
```

Replace those three lines with (the local `var_95_1d_pct` here is the fraction from `np.percentile`):

```python
    return PortfolioRiskReport(
        var_95_1d=round(var_95_1d, 2),
        var_95_5d=round(var_95_5d, 2),
        var_95_1d_pct=round(abs(var_95_1d_pct) * 100.0, 2),
        var_95_5d_pct=round(abs(var_95_1d_pct) * 100.0 * float(np.sqrt(5)), 2),
        concentration_hhi=round(hhi, 4),
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `pytest tests/test_risk_var_pct.py -v`
Expected: PASS (2 passed).

- [ ] **Step 6: Run the full backend suite + lint/type-check**

Run: `pytest tests/ -v -m "not openai and not integration"` → Expected: all pass.
Run: `ruff check src/ app/ tests/` → Expected: no errors.
Run: `pyright src/` → Expected: no new errors in changed files.

- [ ] **Step 7: Commit**

```bash
git add src/analysis/models.py src/analysis/risk.py tests/test_risk_var_pct.py
git commit -m "feat(risk): expose VaR percentage (var_95_1d_pct / var_95_5d_pct)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Frontend API types (`src/types/api.ts`)

**Files:**
- Modify: `frontend/src/types/api.ts`

- [ ] **Step 1: Add the return-series types**

In `frontend/src/types/api.ts`, add (near the other portfolio types):

```typescript
export interface ReturnSeriesPoint {
  date: string;      // ISO date
  returnPct: number; // cumulative % return vs window start
}

export interface ReturnSeriesResponse {
  period: string;
  asOf: string;
  periodReturnPct: number;
  points: ReturnSeriesPoint[];
}
```

- [ ] **Step 2: Add the VaR pct fields to `PortfolioRiskReport`**

The interface currently is:

```typescript
export interface PortfolioRiskReport {
  var_95_1d: number;
  var_95_5d: number;
  concentration_hhi: number;
```

Insert the two fields after `var_95_5d`:

```typescript
export interface PortfolioRiskReport {
  var_95_1d: number;
  var_95_5d: number;
  var_95_1d_pct: number;
  var_95_5d_pct: number;
  concentration_hhi: number;
```

- [ ] **Step 3: Verify type-check**

From `frontend/`: `npm run lint` → Expected: no new errors. (A full `npm run build` runs at the end in Task 11.)

- [ ] **Step 4: Commit**

```bash
git add frontend/src/types/api.ts
git commit -m "feat(types): ReturnSeriesResponse + VaR pct fields

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: Next proxy route (`return-series/route.ts`)

**Files:**
- Create: `frontend/src/app/api/portfolio/return-series/route.ts`

- [ ] **Step 1: Create the proxy (mirrors the equity-curve proxy)**

Create `frontend/src/app/api/portfolio/return-series/route.ts`:

```typescript
export const dynamic = 'force-dynamic';
import { NextRequest, NextResponse } from 'next/server';
import type { ApiError } from '@/types/api';
import { backendFetch, authGuard } from '@/lib/api-client';
import { forwardBucket } from '@/lib/bucket';

// GET /api/portfolio/return-series?period=1M&bucket=long_term
// Proxies to backend GET /portfolio/return-series (flow-free % return curve).
export async function GET(request: NextRequest) {
  try {
    await authGuard();

    const params = new URLSearchParams();
    params.set('period', request.nextUrl.searchParams.get('period') || '1M');
    forwardBucket(request, params);

    const response = await backendFetch(
      `/portfolio/return-series?${params.toString()}`,
      { next: { revalidate: 300 } },
    );

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      return NextResponse.json(
        { error: errorData.detail || 'Failed to fetch return series' } as ApiError,
        { status: response.status },
      );
    }

    return NextResponse.json(await response.json());
  } catch (error) {
    if (error instanceof Response) return error;
    return NextResponse.json(
      { error: 'Failed to connect to backend API' } as ApiError,
      { status: 502 },
    );
  }
}
```

- [ ] **Step 2: Verify**

From `frontend/`: `npm run lint` → Expected: no new errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/app/api/portfolio/return-series/route.ts
git commit -m "feat(api): /api/portfolio/return-series proxy route

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: Reframe the portfolio header (`RobinhoodHeader.tsx`)

**Files:**
- Modify (full replace): `frontend/src/components/dashboard/RobinhoodHeader.tsx`

- [ ] **Step 1: Replace the file contents**

Replace the entire contents of `frontend/src/components/dashboard/RobinhoodHeader.tsx` with:

```tsx
'use client';

import useSWR from 'swr';
import {
  ArrowTrendingUpIcon,
  ArrowTrendingDownIcon,
  InformationCircleIcon,
} from '@heroicons/react/24/outline';
import { usePortfolio } from '@/hooks';
import { useTimeRange, type TimeRange } from '@/hooks/useTimeRange';
import { useBucket, withBucket } from '@/contexts/BucketContext';
import { formatPercent } from '@/lib/format';
import { pnlTextColor, trendDirection } from '@/lib/colors';
import { TimeRangeTabs } from '@/components/ui/TimeRangeTabs';
import type { ReturnSeriesResponse } from '@/types/api';

const RANGES: TimeRange[] = ['1W', '1M', '3M', 'YTD', '1Y', 'ALL'];

const RANGE_LABEL: Record<TimeRange, string> = {
  '1W': '1W',
  '1M': '1M',
  '3M': '3M',
  YTD: 'YTD',
  '1Y': '1Y',
  ALL: 'All time',
};

const CLARITY_NOTE =
  'Performance of the stocks you currently hold, repriced over this period — not your actual account history.';

const returnFetcher = async (url: string): Promise<ReturnSeriesResponse> => {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`return-series ${res.status}`);
  return res.json();
};

export function RobinhoodHeader() {
  const { data, error, isLoading } = usePortfolio();
  const { range, setRange } = useTimeRange();
  const bucket = useBucket();

  // Flow-free current-holdings return for the selected period drives the hero.
  const { data: series } = useSWR<ReturnSeriesResponse>(
    withBucket(`/api/portfolio/return-series?period=${range}`, bucket),
    returnFetcher,
    { revalidateOnFocus: false, dedupingInterval: 60_000 },
  );

  if (isLoading) {
    return (
      <div className="mb-6 animate-pulse">
        <div className="h-4 w-32 bg-background-hover rounded mb-2" />
        <div className="h-10 w-48 bg-background-hover rounded mb-2" />
        <div className="h-5 w-40 bg-background-hover rounded mb-4" />
        <div className="h-8 w-80 bg-background-hover rounded" />
      </div>
    );
  }

  if (error || !data?.summary) {
    return (
      <div className="mb-6">
        <p className="text-foreground-muted text-sm">
          {error ? 'Failed to load portfolio' : 'No portfolio data'}
        </p>
      </div>
    );
  }

  const { summary } = data;
  const periodPct = series?.periodReturnPct ?? 0;
  const trend = trendDirection(periodPct);
  const TrendIcon = trend === 'down' ? ArrowTrendingDownIcon : ArrowTrendingUpIcon;

  return (
    <div className="mb-6">
      {/* Section label */}
      <p className="text-sm text-foreground-muted font-medium mb-1">Stocks &amp; ETFs</p>

      {/* Hero: selected-period return % */}
      <div className="flex items-center gap-2">
        <h1 className={`text-4xl font-bold font-mono tracking-tight ${pnlTextColor(periodPct)}`}>
          {formatPercent(periodPct, 2, { showSign: true })}
        </h1>
        <span className="text-foreground-subtle" title={CLARITY_NOTE} aria-label={CLARITY_NOTE}>
          <InformationCircleIcon className="w-4 h-4" />
        </span>
        <span className="text-sm text-foreground-muted">{RANGE_LABEL[range]}</span>
      </div>

      {/* Context subline: all-time + today */}
      <div className="flex items-center gap-1.5 mt-1">
        <TrendIcon className={`w-4 h-4 ${pnlTextColor(periodPct)}`} />
        <span className="text-xs text-foreground-muted">
          all-time {formatPercent(summary.unrealizedPLPercent, 2, { showSign: true })}
          {' · '}today {formatPercent(summary.dayChangePercent, 2, { showSign: true })}
        </span>
        <span className="text-border">|</span>
        <span className="text-xs text-foreground-muted">{summary.positionsCount} positions</span>
      </div>

      {/* Clarity caption */}
      <p className="text-[11px] text-foreground-subtle mt-1 max-w-md">{CLARITY_NOTE}</p>

      {/* Time range tabs */}
      <TimeRangeTabs ranges={RANGES} value={range} onChange={setRange} className="mt-4" />
    </div>
  );
}
```

- [ ] **Step 2: Verify**

From `frontend/`: `npm run lint` → Expected: no new errors (note: `formatMoney`, `formatSignedMoney`, equity-curve interfaces, `rangeToDays`, and `getChangeForRange` are intentionally gone).

Manual check (when running the app): the header shows a big **%** that changes with the tab, an `all-time … · today …` subline, an (i) tooltip with the clarity note, and **no** dollar value / cash / buying-power line.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/dashboard/RobinhoodHeader.tsx
git commit -m "feat(header): percent-first hero + clarity note, drop \$ value/cash

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 8: Percent return curve (`EquityCurveCard.tsx`)

**Files:**
- Modify (full replace): `frontend/src/components/portfolio/EquityCurveCard.tsx`

- [ ] **Step 1: Replace the file contents**

Replace the entire contents of `frontend/src/components/portfolio/EquityCurveCard.tsx` with:

```tsx
'use client';

import { useEffect, useRef, useState } from 'react';
import useSWR from 'swr';
import { clsx } from 'clsx';
import { ArrowTrendingUpIcon, ArrowTrendingDownIcon } from '@heroicons/react/24/outline';
import { Skeleton } from '@/components/ui/Skeleton';
import { formatSignedPct } from '@/lib/format';
import { useBucket, withBucket } from '@/contexts/BucketContext';
import { BUCKET_LABELS } from '@/lib/bucket';
import type { ReturnSeriesResponse } from '@/types/api';

type RangeOption = '1W' | '1M' | '3M' | 'YTD' | '1Y' | 'ALL';

const RANGES: { key: RangeOption; label: string }[] = [
  { key: '1W', label: '1W' },
  { key: '1M', label: '1M' },
  { key: '3M', label: '3M' },
  { key: 'YTD', label: 'YTD' },
  { key: '1Y', label: '1Y' },
  { key: 'ALL', label: 'ALL' },
];

const CLARITY_NOTE =
  'Performance of the stocks you currently hold, repriced over this period — not your actual account history.';

const fetcher = async (url: string): Promise<ReturnSeriesResponse> => {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`Return series fetch failed (${res.status})`);
  return res.json();
};

/**
 * Flow-free % return curve for the active bucket's current holdings, normalized
 * to 0% at the window start (baseline series: green above 0, red below).
 */
export function EquityCurveCard() {
  const bucket = useBucket();
  const [range, setRange] = useState<RangeOption>('3M');
  const chartContainerRef = useRef<HTMLDivElement>(null);

  const url = withBucket(`/api/portfolio/return-series?period=${range}`, bucket);
  const { data, error, isLoading } = useSWR<ReturnSeriesResponse>(url, fetcher, {
    revalidateOnFocus: false,
    dedupingInterval: 300_000,
  });

  const points = data?.points ?? [];
  const periodChange = data?.periodReturnPct ?? null;
  const isPositive = (periodChange ?? 0) >= 0;

  useEffect(() => {
    if (!chartContainerRef.current || points.length < 2) return;

    let cancelled = false;
    let cleanup: (() => void) | undefined;

    const init = async () => {
      const { createChart, ColorType, LineStyle } = await import('lightweight-charts');
      if (cancelled || !chartContainerRef.current) return;

      chartContainerRef.current.innerHTML = '';
      const chart = createChart(chartContainerRef.current, {
        layout: {
          background: { type: ColorType.Solid, color: 'transparent' },
          textColor: '#a0a0a0',
          fontFamily: "'Inter', sans-serif",
          fontSize: 11,
        },
        grid: {
          vertLines: { visible: false },
          horzLines: { color: '#2a2d3120', style: LineStyle.Dotted },
        },
        rightPriceScale: { borderColor: '#2a2d31' },
        timeScale: { borderColor: '#2a2d31', timeVisible: false, fixLeftEdge: true, fixRightEdge: true },
        crosshair: { mode: 1 },
        width: chartContainerRef.current.clientWidth,
        height: chartContainerRef.current.clientHeight,
        handleScroll: false,
        handleScale: false,
      });

      // Baseline series anchored at 0% — green above, red below.
      const series = chart.addBaselineSeries({
        baseValue: { type: 'price', price: 0 },
        topLineColor: '#3ba55d',
        topFillColor1: 'rgba(59,165,93,0.4)',
        topFillColor2: 'rgba(59,165,93,0.05)',
        bottomLineColor: '#ed4245',
        bottomFillColor1: 'rgba(237,66,69,0.05)',
        bottomFillColor2: 'rgba(237,66,69,0.4)',
        lineWidth: 2,
        priceFormat: { type: 'percent', precision: 2 },
      });

      series.setData(
        points.map((p) => ({
          time: p.date as unknown as never, // lightweight-charts accepts YYYY-MM-DD
          value: p.returnPct,
        })),
      );
      chart.timeScale().fitContent();

      const onResize = () => {
        if (chartContainerRef.current) {
          chart.applyOptions({ width: chartContainerRef.current.clientWidth });
        }
      };
      window.addEventListener('resize', onResize);

      cleanup = () => {
        window.removeEventListener('resize', onResize);
        chart.remove();
      };
    };

    init().catch((e) => {
      console.error('Return curve init failed:', e);
    });

    return () => {
      cancelled = true;
      cleanup?.();
    };
  }, [points]);

  const bucketLabel = bucket ? BUCKET_LABELS[bucket] : 'All buckets';

  return (
    <div className="card p-4 space-y-3">
      {/* Header */}
      <div className="flex items-start justify-between gap-2">
        <div>
          <p className="text-xs uppercase tracking-wider text-foreground-muted">
            Return · {bucketLabel}
          </p>
          {periodChange != null ? (
            <p
              className={clsx(
                'text-2xl font-semibold tabular-nums mt-0.5 flex items-center gap-1',
                isPositive ? 'text-profit' : 'text-loss',
              )}
            >
              {isPositive ? (
                <ArrowTrendingUpIcon className="h-4 w-4" />
              ) : (
                <ArrowTrendingDownIcon className="h-4 w-4" />
              )}
              {formatSignedPct(periodChange)}
              <span className="text-xs font-normal text-foreground-muted">over {range}</span>
            </p>
          ) : (
            <Skeleton.Line className="h-7 w-32 mt-1" />
          )}
          <p className="text-[10px] text-foreground-subtle mt-0.5 max-w-xs">{CLARITY_NOTE}</p>
        </div>

        {/* Time-range tabs */}
        <div className="flex gap-1">
          {RANGES.map((r) => (
            <button
              key={r.key}
              onClick={() => setRange(r.key)}
              className={clsx(
                'px-2 py-0.5 text-xs rounded-md transition-colors',
                range === r.key
                  ? 'bg-primary/10 text-primary'
                  : 'text-foreground-muted hover:text-foreground hover:bg-background-hover',
              )}
            >
              {r.label}
            </button>
          ))}
        </div>
      </div>

      {/* Chart container */}
      <div className="relative h-48">
        {isLoading && (
          <div className="absolute inset-0 flex items-center justify-center">
            <Skeleton.Line className="h-full w-full" />
          </div>
        )}
        {!isLoading && !error && points.length < 2 && (
          <div className="absolute inset-0 flex flex-col items-center justify-center text-center px-4">
            <p className="text-sm text-foreground-muted">Not enough price history yet</p>
            <p className="text-xs text-foreground-subtle mt-1">
              The return curve needs at least two trading days of data for your current holdings.
            </p>
          </div>
        )}
        {error && (
          <div className="absolute inset-0 flex items-center justify-center">
            <p className="text-sm text-loss">Couldn&apos;t load the return curve.</p>
          </div>
        )}
        <div ref={chartContainerRef} className="h-full w-full" />
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Verify**

From `frontend/`: `npm run lint` → Expected: no new errors. Manual: the card title reads "Return · …", shows a signed % over the range, the chart is anchored at 0% (green above / red below), and the clarity note appears.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/portfolio/EquityCurveCard.tsx
git commit -m "feat(equity-curve): percent return curve with 0% baseline

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 9: Percent-first holdings table (`HoldingsTable.tsx`)

**Files:**
- Modify: `frontend/src/components/dashboard/HoldingsTable.tsx` (4 small edits)

- [ ] **Step 1: Relabel columns**

Replace the `equity` and `dayChange` column definitions in the `COLUMNS` array:

Old:
```tsx
  { key: 'equity', label: 'Market Value', shortLabel: 'Value', align: 'right', sortable: true },
```
New:
```tsx
  { key: 'equity', label: 'Weight', shortLabel: 'Weight', align: 'right', sortable: true },
```

Old:
```tsx
  { key: 'dayChange', label: "Today", align: 'right', hideClass: 'hidden lg:table-cell', sortable: true },
```
New:
```tsx
  { key: 'dayChange', label: 'Today %', shortLabel: 'Today', align: 'right', hideClass: 'hidden lg:table-cell', sortable: true },
```

(Sorting still uses the underlying `equity` / `dayChange` numeric values, which order identically to weight / day-%.)

- [ ] **Step 2: Drop the now-unused import**

Old:
```tsx
import { formatMoney, formatPercent, formatSignedMoney, formatQuantity } from '@/lib/format';
```
New:
```tsx
import { formatMoney, formatPercent, formatQuantity } from '@/lib/format';
```

- [ ] **Step 3: Render weight % instead of market value $**

Old:
```tsx
                  {/* Market Value + shares on mobile */}
                  <td className="px-3 py-2.5 text-right">
                    <div className="font-mono text-sm tabular-nums">
                      {formatMoney(position.equity)}
                    </div>
                    <div className="sm:hidden text-[10px] text-foreground-muted font-mono tabular-nums mt-0.5">
                      {formatQuantity(position.quantity)} shares
                    </div>
                  </td>
```
New:
```tsx
                  {/* Weight (% of portfolio) + shares on mobile */}
                  <td className="px-3 py-2.5 text-right">
                    <div className="font-mono text-sm tabular-nums">
                      {formatPercent(position.portfolioDiversity, 1)}
                    </div>
                    <div className="sm:hidden text-[10px] text-foreground-muted font-mono tabular-nums mt-0.5">
                      {formatQuantity(position.quantity)} shares
                    </div>
                  </td>
```

- [ ] **Step 4: Render today % instead of today $**

Old:
```tsx
                  {/* Today's Change */}
                  <td className={clsx(
                    'hidden lg:table-cell px-3 py-2.5 text-right font-mono text-sm tabular-nums',
                    pnlTextColor(position.dayChange),
                  )}>
                    {formatSignedMoney(position.dayChange)}
                  </td>
```
New:
```tsx
                  {/* Today's Change % */}
                  <td className={clsx(
                    'hidden lg:table-cell px-3 py-2.5 text-right font-mono text-sm tabular-nums',
                    pnlTextColor(position.dayChangePercent),
                  )}>
                    {formatPercent(position.dayChangePercent, 2, { showSign: true })}
                  </td>
```

- [ ] **Step 5: Verify**

From `frontend/`: `npm run lint` → Expected: no new errors (no unused `formatSignedMoney`). Manual: the table's second column shows a % weight, the last column shows today's %; price, avg cost, shares, and P/L % are unchanged.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/dashboard/HoldingsTable.tsx
git commit -m "feat(holdings): show % weight and today % instead of \$ values

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 10: VaR as a percentage (`PortfolioRiskCard.tsx`)

**Files:**
- Modify: `frontend/src/components/dashboard/PortfolioRiskCard.tsx` (import + two renders)

- [ ] **Step 1: Add `formatPercent` to the import**

Old:
```tsx
import { formatNumber } from '@/lib/format';
```
New:
```tsx
import { formatNumber, formatPercent } from '@/lib/format';
```

- [ ] **Step 2: Render the 1-day VaR as %**

Old:
```tsx
          <span className="font-mono text-loss">
            -${formatNumber(risk.var_95_1d, 0)}
          </span>
```
New:
```tsx
          <span className="font-mono text-loss">
            -{formatPercent(risk.var_95_1d_pct, 1)}
          </span>
```

- [ ] **Step 3: Render the 5-day VaR as %**

Old:
```tsx
          <span className="font-mono text-loss">
            -${formatNumber(risk.var_95_5d, 0)}
          </span>
```
New:
```tsx
          <span className="font-mono text-loss">
            -{formatPercent(risk.var_95_5d_pct, 1)}
          </span>
```

- [ ] **Step 4: Verify**

From `frontend/`: `npm run lint` → Expected: no new errors. Manual: the risk card's VaR rows show e.g. `-2.5%` / `-5.6%` rather than dollar amounts.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/dashboard/PortfolioRiskCard.tsx
git commit -m "feat(risk-card): render VaR as percent of portfolio

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 11: Percent-first position card (`RobinhoodPositionCard.tsx`)

**Files:**
- Modify (full replace): `frontend/src/components/stock/RobinhoodPositionCard.tsx`

- [ ] **Step 1: Replace the file contents**

Replace the entire contents of `frontend/src/components/stock/RobinhoodPositionCard.tsx` with:

```tsx
'use client';

import { useState, useEffect } from 'react';
import { BanknotesIcon } from '@heroicons/react/24/outline';
import type { Position } from '@/types/api';
import { formatMoney, formatPercent, formatQuantity } from '@/lib/format';
import { pnlTextColor } from '@/lib/colors';
import { useBucket, withBucket } from '@/contexts/BucketContext';

interface RobinhoodPositionCardProps {
  ticker: string;
}

interface AggregatedPosition {
  totalShares: number;
  totalValue: number;
  totalCost: number;
  weightedAvgCost: number;
  dayChange: number;
  dayChangePct: number | null;
  unrealizedPL: number;
  unrealizedPLPct: number;
  diversity: number | null;
  accounts: { name: string; shares: number; value: number }[];
}

function aggregatePositions(positions: Position[], totalEquity: number): AggregatedPosition {
  const totalShares = positions.reduce((s, p) => s + p.quantity, 0);
  const totalValue = positions.reduce((s, p) => s + p.equity, 0);
  const totalCost = positions.reduce((s, p) => s + p.quantity * p.averageBuyPrice, 0);
  const weightedAvgCost = totalShares > 0 ? totalCost / totalShares : 0;
  const dayChange = positions.reduce((s, p) => s + (p.dayChange ?? 0), 0);
  const unrealizedPL = totalValue - totalCost;
  const unrealizedPLPct = totalCost > 0 ? (unrealizedPL / totalCost) * 100 : 0;

  // Day change pct: weighted by equity
  let dayChangePct: number | null = null;
  const positionsWithDay = positions.filter((p) => p.dayChangePercent != null);
  if (positionsWithDay.length > 0) {
    const weightedSum = positionsWithDay.reduce((s, p) => s + (p.dayChangePercent ?? 0) * p.equity, 0);
    const totalEq = positionsWithDay.reduce((s, p) => s + p.equity, 0);
    dayChangePct = totalEq > 0 ? weightedSum / totalEq : null;
  }

  const diversity = totalEquity > 0 ? (totalValue / totalEquity) * 100 : null;

  const accounts = positions.map((p) => ({
    name: p.accountId,
    shares: p.quantity,
    value: p.equity,
  }));

  return { totalShares, totalValue, totalCost, weightedAvgCost, dayChange, dayChangePct, unrealizedPL, unrealizedPLPct, diversity, accounts };
}

export function RobinhoodPositionCard({ ticker }: RobinhoodPositionCardProps) {
  const [agg, setAgg] = useState<AggregatedPosition | null>(null);
  const [loading, setLoading] = useState(true);
  const bucket = useBucket();

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    const fetchData = async () => {
      try {
        const res = await fetch(withBucket('/api/portfolio', bucket));
        if (cancelled) return;
        if (!res.ok) { setAgg(null); return; }
        const data = await res.json();
        if (cancelled) return;
        const positions: Position[] = (data.positions || []).filter(
          (p: Position) => p.symbol === ticker,
        );
        if (positions.length === 0) { setAgg(null); return; }
        const totalEquity = data.summary?.totalEquity ?? 0;
        setAgg(aggregatePositions(positions, totalEquity));
      } catch {
        if (!cancelled) setAgg(null);
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    fetchData();
    return () => {
      cancelled = true;
    };
  }, [ticker, bucket]);

  if (loading) {
    return (
      <div className="card p-4 animate-pulse">
        <div className="skeleton h-4 w-24 mb-3 rounded" />
        <div className="skeleton h-6 w-32 mb-2 rounded" />
        <div className="skeleton h-3 w-full rounded" />
      </div>
    );
  }

  if (!agg) {
    return (
      <div className="card p-4">
        <div className="flex items-center gap-2 text-foreground-muted mb-2">
          <BanknotesIcon className="h-4 w-4" />
          <span className="text-sm font-medium">Your Position</span>
        </div>
        <p className="text-sm text-foreground-muted">No position in {ticker}</p>
      </div>
    );
  }

  return (
    <div className="card p-4">
      {/* Header */}
      <div className="flex items-center gap-2 text-foreground-muted mb-3">
        <BanknotesIcon className="h-4 w-4" />
        <span className="text-xs font-semibold uppercase tracking-wider">Your Position</span>
      </div>

      {/* Hero: Total Return % */}
      <div className="text-center mb-4 py-2">
        <p className={`text-2xl font-bold font-mono tabular-nums ${pnlTextColor(agg.unrealizedPL)}`}>
          {agg.unrealizedPL >= 0 ? '▲' : '▼'} {formatPercent(agg.unrealizedPLPct, 2, { showSign: true })}
        </p>
        <p className="text-xs text-foreground-muted mt-0.5">Total return</p>
      </div>

      {/* 2×2 Stats grid (no $ totals; avg cost kept as a factual price) */}
      <div className="grid grid-cols-2 gap-px bg-border rounded-lg overflow-hidden mb-3">
        <div className="bg-background p-3">
          <p className="text-lg font-bold font-mono tabular-nums">{formatQuantity(agg.totalShares)}</p>
          <p className="text-xs text-foreground-muted mt-0.5">Shares</p>
        </div>
        <div className="bg-background p-3">
          <p className={`text-lg font-bold font-mono tabular-nums ${pnlTextColor(agg.dayChangePct ?? 0)}`}>
            {agg.dayChangePct != null ? formatPercent(agg.dayChangePct, 2, { showSign: true }) : '—'}
          </p>
          <p className="text-xs text-foreground-muted mt-0.5">Today</p>
        </div>
        <div className="bg-background p-3">
          <p className="text-lg font-bold font-mono tabular-nums">{formatMoney(agg.weightedAvgCost)}</p>
          <p className="text-xs text-foreground-muted mt-0.5">Avg Cost</p>
        </div>
        <div className="bg-background p-3">
          {agg.diversity != null ? (
            <>
              <p className="text-lg font-bold font-mono tabular-nums">{formatPercent(agg.diversity, 1)}</p>
              <p className="text-xs text-foreground-muted mt-0.5">Portfolio</p>
            </>
          ) : (
            <>
              <p className="text-lg font-bold font-mono tabular-nums text-foreground-muted">—</p>
              <p className="text-xs text-foreground-muted mt-0.5">Portfolio</p>
            </>
          )}
        </div>
      </div>

      {/* Per-account breakdown (only if multiple accounts) — shares only, no $ */}
      {agg.accounts.length > 1 && (
        <div className="pt-3 mt-3 border-t border-border">
          <p className="text-xs text-foreground-muted mb-2">Accounts</p>
          <div className="space-y-1.5">
            {agg.accounts.map((acct) => (
              <div key={acct.name} className="flex items-center justify-between text-xs">
                <span className="text-foreground-muted truncate max-w-[120px]" title={acct.name}>
                  {acct.name.length > 8 ? `${acct.name.slice(0, 8)}…` : acct.name}
                </span>
                <span className="font-mono tabular-nums text-foreground-muted">
                  {formatQuantity(acct.shares)} sh
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Final frontend verification (type-check + lint)**

From `frontend/`:
- `npm run lint` → Expected: no errors.
- `npm run build` → Expected: successful production build (TypeScript compiles; this is the type-check safety net for all frontend tasks).

Manual: on a stock detail page, "Your Position" shows total return as **%** (no $ headline), a Shares / Today% / Avg Cost / Portfolio% grid, and per-account rows with shares only.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/stock/RobinhoodPositionCard.tsx
git commit -m "feat(position-card): percent-first position summary, drop \$ totals

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 12: Hide P/L dollars on trade cards (`BlossomTradeCard.tsx`)

`ActivityFeed` and `TradeRecap` both render `BlossomTradeCard`, so this one component
covers all three. Per the cross-project rule: keep the notional `@ $price`, Avg Cost, Fee,
and Portfolio % (all factual), but show **realized / unrealized P/L as % only** — no P/L$.

**Files:**
- Modify: `frontend/src/components/trade/BlossomTradeCard.tsx` (2 edits)
- Modify: `frontend/src/types/api.ts` (ensure one field exists)

- [ ] **Step 1: Ensure `unrealizedPnlPct` exists on `EnrichedTrade`**

In `frontend/src/types/api.ts`, find the `EnrichedTrade` interface. It already uses
`realizedPnlPct` and `portfolioPct` (referenced in `BlossomTradeCard`). Confirm it also has:

```typescript
  unrealizedPnlPct: number | null;
```

If that field is absent, add it next to `realizedPnlPct` (the backend `_enrich_trade`
already returns it). If present, skip.

- [ ] **Step 2: Realized P/L line → percent only**

Old:
```tsx
      {/* Realized P/L line for SELL trades */}
      {isSell && trade.realizedPnl != null && (
        <p className={clsx('text-sm font-medium font-mono mt-1', pnlTextColor(trade.realizedPnl))}>
          {trade.realizedPnl >= 0 ? '+' : ''}{formatMoney(trade.realizedPnl)}
          {trade.realizedPnlPct != null && (
            <span className="text-xs ml-1">
              ({trade.realizedPnlPct >= 0 ? '+' : ''}{formatPercent(trade.realizedPnlPct, 1)})
            </span>
          )}
        </p>
      )}
```
New:
```tsx
      {/* Realized P/L for SELL trades — percent only (no P/L $) */}
      {isSell && trade.realizedPnlPct != null && (
        <p className={clsx('text-sm font-medium font-mono mt-1', pnlTextColor(trade.realizedPnlPct))}>
          {formatPercent(trade.realizedPnlPct, 2, { showSign: true })}
          <span className="text-xs ml-1 text-foreground-muted">realized</span>
        </p>
      )}
```

- [ ] **Step 3: Position P/L box → percent only**

Old:
```tsx
              {/* Position P/L */}
              <div className="bg-background-tertiary/50 rounded-lg px-3 py-2">
                <p className="text-2xs text-foreground-subtle">Position P/L</p>
                <p className={clsx('text-sm font-mono font-medium', pnlTextColor(trade.unrealizedPnl))}>
                  {trade.unrealizedPnl != null ? (
                    <>
                      {trade.unrealizedPnl >= 0 ? '+' : ''}{formatMoney(trade.unrealizedPnl)}
                    </>
                  ) : (
                    '—'
                  )}
                </p>
              </div>
```
New:
```tsx
              {/* Position P/L — percent only (no P/L $) */}
              <div className="bg-background-tertiary/50 rounded-lg px-3 py-2">
                <p className="text-2xs text-foreground-subtle">Position P/L</p>
                <p className={clsx('text-sm font-mono font-medium', pnlTextColor(trade.unrealizedPnlPct))}>
                  {trade.unrealizedPnlPct != null
                    ? formatPercent(trade.unrealizedPnlPct, 2, { showSign: true })
                    : '—'}
                </p>
              </div>
```

(The action text `Bought N shares @ $price`, the Avg Cost box, Portfolio %, and the Fee
line are intentionally left as-is — they are factual notional values, not P/L tallies.
`formatMoney` is still used by those, so its import stays. `getTradeStyle` still reads
`trade.realizedPnl` internally for the border color, which is fine — it isn't displayed.)

- [ ] **Step 4: Verify**

From `frontend/`: `npm run lint` → Expected: no new errors. Manual: a SELL card shows
`+X.XX% realized` (no dollar P/L); a BUY card's "Position P/L" box shows a %; "Bought …
@ $price", Avg Cost, Portfolio %, and Fee remain.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/trade/BlossomTradeCard.tsx frontend/src/types/api.ts
git commit -m "feat(trade-card): show realized/position P/L as percent, drop P/L \$

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 13: Full verification sweep

**Files:** none (verification only)

- [ ] **Step 1: Backend tests**

Run: `pytest tests/ -v -m "not openai and not integration"`
Expected: all pass (including the four new test files).

- [ ] **Step 2: Backend lint + type-check**

Run: `ruff check src/ app/ tests/` → Expected: clean.
Run: `pyright src/ app/` → Expected: no new errors in changed files.

- [ ] **Step 3: Frontend lint + build**

From `frontend/`: `npm run lint` then `npm run build` → Expected: both succeed.

- [ ] **Step 4: Manual smoke (optional, when the app is running)**

- Portfolio page: header shows a **%** hero that tracks the tab; no $ total / cash / buying power; clarity note present.
- Equity curve: % curve anchored at 0%.
- Holdings table: weight % + today % columns; price / avg cost / shares intact.
- Risk card: VaR shown as %.
- Stock page position card: total return %, no $ headline.

- [ ] **Step 5: No commit needed** (verification only). The branch `design/portfolio-percent-first-and-ai-profiling` now contains the full Project A implementation.

---

## Notes for the executor

- **Do not** remove `cashBalance` / `buyingPower` from the backend payload or delete `/portfolio/equity-curve` — out of scope; other views/tests may rely on them.
- The crypto daily-series fetcher (`get_crypto_price_series`) is **new** and uses yfinance `.history` over a date range — it is the intended source for crypto in the return series (equities use `ohlcv_daily`). If you prefer to source crypto from `position_snapshots` instead, that's a valid alternative noted in the spec, but it is a different (flow-contaminated) basis and is **not** what this plan implements.
- If `npm run build` flags `addBaselineSeries` typing on lightweight-charts 4.2.0, confirm the method name against the installed version (it exists in v4); fall back to `addAreaSeries` plotting `returnPct` with a manual 0 reference line only if necessary.
