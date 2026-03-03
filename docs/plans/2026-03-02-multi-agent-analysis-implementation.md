# Multi-Agent Stock Analysis System — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a 5-agent AI stock analysis system with technical indicators, fundamental scoring, DCF valuation, sentiment aggregation, risk analytics, and LLM consensus — cached in PostgreSQL, served via FastAPI.

**Architecture:** Plain Python modules with standardized `async def run(input) -> AnalystSignal` contract. FastAPI routes orchestrate parallel agent execution via `asyncio.gather()`. DB cache with stale-while-revalidate. Only the consensus aggregator calls OpenAI (gpt-5-mini). LangGraph-ready interface.

**Tech Stack:** Python 3.11+ | FastAPI | PostgreSQL/Supabase | OpenAI Responses API | numpy/pandas | Existing services (price_service, openbb_service, market_data_service)

**Design Doc:** `docs/plans/2026-03-02-multi-agent-analysis-design.md`

---

## Task 1: Database Schema — Cache Tables

**Files:**
- Create: `schema/067_analysis_cache.sql`

**Step 1: Write the migration SQL**

```sql
-- schema/067_analysis_cache.sql
-- Analysis cache tables for multi-agent stock analysis system

-- Cache for per-stock analysis results
CREATE TABLE IF NOT EXISTS stock_analysis_cache (
    ticker TEXT NOT NULL,
    analysis_type TEXT NOT NULL DEFAULT 'full',
    result JSONB NOT NULL,
    agent_signals JSONB NOT NULL,
    model_used TEXT NOT NULL,
    data_sources TEXT[] NOT NULL,
    computed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (ticker, analysis_type)
);

CREATE INDEX IF NOT EXISTS idx_analysis_cache_expires
    ON stock_analysis_cache (expires_at);

-- Cache for portfolio-wide risk analysis
CREATE TABLE IF NOT EXISTS portfolio_risk_cache (
    portfolio_id TEXT NOT NULL DEFAULT 'default',
    result JSONB NOT NULL,
    computed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (portfolio_id)
);

-- Enable RLS (required by project convention)
ALTER TABLE stock_analysis_cache ENABLE ROW LEVEL SECURITY;
ALTER TABLE portfolio_risk_cache ENABLE ROW LEVEL SECURITY;
```

**Step 2: Deploy the migration**

Run: `python scripts/deploy_database.py`

Or manually via Supabase SQL editor if deploy script isn't configured for new migrations.

**Step 3: Verify tables exist**

Run: `python -c "from src.db import execute_sql; print(execute_sql('SELECT count(*) FROM stock_analysis_cache', fetch_results=True))"`
Expected: `[(0,)]`

**Step 4: Commit**

```bash
git add schema/067_analysis_cache.sql
git commit -m "schema: add analysis cache tables (067)"
```

---

## Task 2: Shared Pydantic Models

**Files:**
- Create: `src/analysis/__init__.py`
- Create: `src/analysis/models.py`
- Test: `tests/test_analysis_models.py`

**Step 1: Write the failing test**

```python
# tests/test_analysis_models.py
"""Tests for analysis shared Pydantic models."""
import pytest
from datetime import datetime, timezone


def test_analyst_signal_validation():
    """AnalystSignal enforces valid signal values and confidence range."""
    from src.analysis.models import AnalystSignal

    sig = AnalystSignal(
        agent_id="technical",
        signal="bullish",
        confidence=0.85,
        reasoning="Strong uptrend with EMA alignment",
        metrics={"rsi_14": 62.5, "macd_histogram": 1.23},
    )
    assert sig.agent_id == "technical"
    assert sig.confidence == 0.85
    assert sig.metrics["rsi_14"] == 62.5


def test_analyst_signal_clamps_confidence():
    """Confidence is clamped to 0.0-1.0 range."""
    from src.analysis.models import AnalystSignal

    sig = AnalystSignal(
        agent_id="test",
        signal="neutral",
        confidence=1.5,
        reasoning="test",
        metrics={},
    )
    assert sig.confidence == 1.0

    sig2 = AnalystSignal(
        agent_id="test",
        signal="neutral",
        confidence=-0.3,
        reasoning="test",
        metrics={},
    )
    assert sig2.confidence == 0.0


def test_consensus_report_structure():
    """ConsensusReport contains all required fields."""
    from src.analysis.models import AnalystSignal, ConsensusReport

    signals = [
        AnalystSignal(agent_id="technical", signal="bullish", confidence=0.8,
                      reasoning="test", metrics={}),
    ]
    report = ConsensusReport(
        ticker="AAPL",
        overall_signal="buy",
        overall_confidence=0.75,
        bull_bear_score=0.3,
        agent_signals=signals,
        summary="Test summary",
        data_sources=["Databento OHLCV"],
        computed_at=datetime.now(timezone.utc),
        model_used="gpt-5-mini",
    )
    assert report.ticker == "AAPL"
    assert len(report.agent_signals) == 1
    assert report.data_sources == ["Databento OHLCV"]


def test_analysis_input_accepts_empty_optionals():
    """AnalysisInput works with None position and empty lists."""
    from src.analysis.models import AnalysisInput

    inp = AnalysisInput(
        ticker="AAPL",
        ohlcv=[],
        fundamentals=None,
        position=None,
        ideas=[],
        news=[],
        portfolio_value=50000.0,
    )
    assert inp.ticker == "AAPL"
    assert inp.fundamentals is None
    assert inp.portfolio_value == 50000.0


def test_portfolio_risk_report_structure():
    """PortfolioRiskReport validates correctly."""
    from src.analysis.models import PortfolioRiskReport

    report = PortfolioRiskReport(
        var_95_1d=0.023,
        var_95_5d=0.051,
        concentration_hhi=0.12,
        diversification_ratio=1.35,
        correlation_matrix={"AAPL": {"MSFT": 0.72}},
        top_risk_contributors=[{"ticker": "NVDA", "marginal_var": 0.008}],
        sector_exposure={"Technology": 0.45, "Healthcare": 0.20},
        computed_at=datetime.now(timezone.utc),
        data_sources=["Databento OHLCV", "Portfolio positions"],
    )
    assert report.var_95_1d == 0.023
    assert "Technology" in report.sector_exposure
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_analysis_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.analysis'`

**Step 3: Write the models**

```python
# src/analysis/__init__.py
"""Multi-agent stock analysis system."""
```

```python
# src/analysis/models.py
"""
Shared Pydantic models for the multi-agent analysis system.

Every agent consumes AnalysisInput and produces AnalystSignal.
The consensus aggregator produces ConsensusReport.
This standardized contract enables future LangGraph migration.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Sub-models for AnalysisInput
# ---------------------------------------------------------------------------

class OHLCVBar(BaseModel):
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: float


class PositionData(BaseModel):
    quantity: float
    avg_cost: float
    current_price: float
    market_value: float
    unrealized_pnl: float
    unrealized_pnl_pct: float


class IdeaData(BaseModel):
    direction: str  # bullish, bearish, neutral, mixed
    confidence: float
    labels: list[str]
    idea_text: str
    created_at: str
    author: str


class NewsItem(BaseModel):
    title: str
    text: str = ""
    date: str
    source: str = ""
    sentiment_score: float | None = None


# ---------------------------------------------------------------------------
# Agent Input / Output Protocol
# ---------------------------------------------------------------------------

class AnalysisInput(BaseModel):
    """Standard input assembled by the orchestrator, consumed by every agent."""
    ticker: str
    ohlcv: list[OHLCVBar] = Field(default_factory=list)
    fundamentals: dict[str, Any] | None = None
    position: PositionData | None = None
    ideas: list[IdeaData] = Field(default_factory=list)
    news: list[NewsItem] = Field(default_factory=list)
    portfolio_value: float = 0.0


class AnalystSignal(BaseModel):
    """Standard output — every agent returns this exact shape."""
    agent_id: str
    signal: Literal["bullish", "bearish", "neutral"]
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str
    metrics: dict[str, Any] = Field(default_factory=dict)

    @field_validator("confidence", mode="before")
    @classmethod
    def clamp_confidence(cls, v: float) -> float:
        return max(0.0, min(1.0, float(v)))


class ConsensusReport(BaseModel):
    """Final aggregated output from the consensus agent."""
    ticker: str
    overall_signal: Literal["strong_buy", "buy", "hold", "sell", "strong_sell"]
    overall_confidence: float = Field(ge=0.0, le=1.0)
    bull_bear_score: float = Field(ge=-1.0, le=1.0)
    agent_signals: list[AnalystSignal]
    summary: str
    data_sources: list[str]
    computed_at: datetime
    model_used: str

    @field_validator("overall_confidence", mode="before")
    @classmethod
    def clamp_overall_confidence(cls, v: float) -> float:
        return max(0.0, min(1.0, float(v)))

    @field_validator("bull_bear_score", mode="before")
    @classmethod
    def clamp_bull_bear(cls, v: float) -> float:
        return max(-1.0, min(1.0, float(v)))


class PortfolioRiskReport(BaseModel):
    """Portfolio-wide risk analytics."""
    var_95_1d: float
    var_95_5d: float
    concentration_hhi: float
    diversification_ratio: float
    correlation_matrix: dict[str, dict[str, float]]
    top_risk_contributors: list[dict[str, Any]]
    sector_exposure: dict[str, float]
    computed_at: datetime
    data_sources: list[str]
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_analysis_models.py -v`
Expected: All 5 tests PASS

**Step 5: Commit**

```bash
git add src/analysis/__init__.py src/analysis/models.py tests/test_analysis_models.py
git commit -m "feat(analysis): add shared Pydantic models for agent protocol"
```

---

## Task 3: Indicator Math Library

**Files:**
- Create: `src/analysis/indicators.py`
- Test: `tests/test_analysis_indicators.py`

**Step 1: Write the failing test**

```python
# tests/test_analysis_indicators.py
"""Tests for technical indicator calculations."""
import pytest
import numpy as np
import pandas as pd


@pytest.fixture
def sample_ohlcv():
    """Generate 200 days of synthetic OHLCV data for testing."""
    np.random.seed(42)
    n = 200
    dates = pd.date_range("2025-01-01", periods=n, freq="B")
    close = 100.0 + np.cumsum(np.random.randn(n) * 1.5)
    close = np.maximum(close, 10.0)  # floor at $10
    high = close + np.abs(np.random.randn(n)) * 1.0
    low = close - np.abs(np.random.randn(n)) * 1.0
    open_ = close + np.random.randn(n) * 0.5
    volume = np.random.randint(1_000_000, 10_000_000, size=n).astype(float)
    return pd.DataFrame({
        "date": dates,
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    }).set_index("date")


def test_ema_basic(sample_ohlcv):
    """EMA returns series of correct length and is not all NaN."""
    from src.analysis.indicators import calculate_ema
    ema = calculate_ema(sample_ohlcv["close"], period=21)
    assert len(ema) == len(sample_ohlcv)
    assert not ema.isna().all()
    assert ema.isna().sum() < 21  # only leading NaNs


def test_rsi_range(sample_ohlcv):
    """RSI values are bounded between 0 and 100."""
    from src.analysis.indicators import calculate_rsi
    rsi = calculate_rsi(sample_ohlcv["close"], period=14)
    valid = rsi.dropna()
    assert len(valid) > 0
    assert valid.min() >= 0.0
    assert valid.max() <= 100.0


def test_bollinger_bands_contain_price(sample_ohlcv):
    """Bollinger upper > middle > lower, and middle ~ SMA."""
    from src.analysis.indicators import calculate_bollinger_bands
    upper, middle, lower = calculate_bollinger_bands(
        sample_ohlcv["close"], period=20, std_dev=2.0
    )
    valid_mask = ~(upper.isna() | middle.isna() | lower.isna())
    assert (upper[valid_mask] >= middle[valid_mask]).all()
    assert (middle[valid_mask] >= lower[valid_mask]).all()


def test_macd_structure(sample_ohlcv):
    """MACD returns macd_line, signal_line, histogram as Series."""
    from src.analysis.indicators import calculate_macd
    macd_line, signal_line, histogram = calculate_macd(sample_ohlcv["close"])
    assert len(macd_line) == len(sample_ohlcv)
    assert len(signal_line) == len(sample_ohlcv)
    assert len(histogram) == len(sample_ohlcv)
    # Histogram = macd - signal
    valid = ~(macd_line.isna() | signal_line.isna())
    np.testing.assert_allclose(
        histogram[valid].values,
        (macd_line[valid] - signal_line[valid]).values,
        atol=1e-10,
    )


def test_adx_range(sample_ohlcv):
    """ADX values are bounded between 0 and 100."""
    from src.analysis.indicators import calculate_adx
    adx = calculate_adx(
        sample_ohlcv["high"], sample_ohlcv["low"],
        sample_ohlcv["close"], period=14
    )
    valid = adx.dropna()
    assert len(valid) > 0
    assert valid.min() >= 0.0
    assert valid.max() <= 100.0


def test_atr_positive(sample_ohlcv):
    """ATR is always positive."""
    from src.analysis.indicators import calculate_atr
    atr = calculate_atr(
        sample_ohlcv["high"], sample_ohlcv["low"],
        sample_ohlcv["close"], period=14
    )
    valid = atr.dropna()
    assert (valid > 0).all()


def test_hurst_exponent_range(sample_ohlcv):
    """Hurst exponent is between 0 and 1."""
    from src.analysis.indicators import calculate_hurst_exponent
    h = calculate_hurst_exponent(sample_ohlcv["close"], max_lag=20)
    assert 0.0 <= h <= 1.0


def test_ema_short_series():
    """EMA handles series shorter than period gracefully."""
    from src.analysis.indicators import calculate_ema
    short = pd.Series([100.0, 101.0, 102.0])
    ema = calculate_ema(short, period=50)
    # Should return something without crashing
    assert len(ema) == 3
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_analysis_indicators.py -v`
Expected: FAIL — `ModuleNotFoundError`

**Step 3: Write the indicators library**

```python
# src/analysis/indicators.py
"""
Shared technical indicator calculations.

All functions are pure math operating on pandas Series/DataFrames.
No external API calls, no database access, no LLM calls.

Adapted from: ai-hedge-fund technicals.py (virattt/ai-hedge-fund)
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def calculate_ema(series: pd.Series, period: int) -> pd.Series:
    """Exponential Moving Average."""
    return series.ewm(span=period, adjust=False).mean()


def calculate_sma(series: pd.Series, period: int) -> pd.Series:
    """Simple Moving Average."""
    return series.rolling(window=period).mean()


def calculate_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """Relative Strength Index (Wilder's smoothing)."""
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100.0 - (100.0 / (1.0 + rs))
    return rsi.clip(0.0, 100.0)


def calculate_bollinger_bands(
    series: pd.Series, period: int = 20, std_dev: float = 2.0,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Bollinger Bands. Returns (upper, middle, lower)."""
    middle = calculate_sma(series, period)
    rolling_std = series.rolling(window=period).std()
    upper = middle + std_dev * rolling_std
    lower = middle - std_dev * rolling_std
    return upper, middle, lower


def calculate_macd(
    series: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal_period: int = 9,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """MACD. Returns (macd_line, signal_line, histogram)."""
    ema_fast = calculate_ema(series, fast)
    ema_slow = calculate_ema(series, slow)
    macd_line = ema_fast - ema_slow
    signal_line = calculate_ema(macd_line, signal_period)
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def calculate_adx(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    period: int = 14,
) -> pd.Series:
    """Average Directional Index."""
    plus_dm = high.diff()
    minus_dm = -low.diff()
    plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0.0)
    minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0.0)

    atr = calculate_atr(high, low, close, period)

    plus_di = 100.0 * (plus_dm.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean() / atr)
    minus_di = 100.0 * (minus_dm.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean() / atr)

    dx = 100.0 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx = dx.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
    return adx.clip(0.0, 100.0)


def calculate_atr(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    period: int = 14,
) -> pd.Series:
    """Average True Range."""
    prev_close = close.shift(1)
    tr = pd.concat([
        (high - low),
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()


def calculate_hurst_exponent(series: pd.Series, max_lag: int = 20) -> float:
    """
    Hurst exponent via R/S (Rescaled Range) method.
    H < 0.5: mean-reverting, H = 0.5: random walk, H > 0.5: trending.
    """
    vals = series.dropna().values
    if len(vals) < max_lag * 2:
        return 0.5  # insufficient data, return random walk

    lags = range(2, max_lag + 1)
    rs_values = []

    for lag in lags:
        rs_list = []
        for start in range(0, len(vals) - lag, lag):
            chunk = vals[start : start + lag]
            mean_chunk = np.mean(chunk)
            deviations = chunk - mean_chunk
            cumulative = np.cumsum(deviations)
            r = np.max(cumulative) - np.min(cumulative)
            s = np.std(chunk, ddof=1)
            if s > 0:
                rs_list.append(r / s)
        if rs_list:
            rs_values.append((np.log(lag), np.log(np.mean(rs_list))))

    if len(rs_values) < 2:
        return 0.5

    log_lags, log_rs = zip(*rs_values)
    coeffs = np.polyfit(log_lags, log_rs, 1)
    hurst = float(coeffs[0])
    return max(0.0, min(1.0, hurst))
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_analysis_indicators.py -v`
Expected: All 9 tests PASS

**Step 5: Commit**

```bash
git add src/analysis/indicators.py tests/test_analysis_indicators.py
git commit -m "feat(analysis): add technical indicator math library"
```

---

## Task 4: Technical Agent

**Files:**
- Create: `src/analysis/technical.py`
- Test: `tests/test_analysis_technical.py`

**Step 1: Write the failing test**

```python
# tests/test_analysis_technical.py
"""Tests for the technical analysis agent."""
import pytest
import numpy as np
import pandas as pd
from src.analysis.models import AnalysisInput, OHLCVBar


@pytest.fixture
def bullish_ohlcv_input():
    """Generate AnalysisInput with a strong uptrend (200 days)."""
    np.random.seed(42)
    n = 200
    # Strong uptrend: cumulative positive drift
    base = 100.0 + np.arange(n) * 0.5 + np.cumsum(np.random.randn(n) * 0.3)
    bars = []
    for i in range(n):
        d = (pd.Timestamp("2025-01-01") + pd.Timedelta(days=i)).strftime("%Y-%m-%d")
        c = float(base[i])
        bars.append(OHLCVBar(
            date=d, open=c - 0.3, high=c + 1.0, low=c - 1.0,
            close=c, volume=5_000_000.0,
        ))
    return AnalysisInput(ticker="TEST", ohlcv=bars, portfolio_value=100000.0)


@pytest.fixture
def short_ohlcv_input():
    """Only 10 days of data — should degrade gracefully."""
    bars = [
        OHLCVBar(date=f"2025-01-{i+1:02d}", open=100.0, high=101.0,
                 low=99.0, close=100.0 + i * 0.1, volume=1_000_000.0)
        for i in range(10)
    ]
    return AnalysisInput(ticker="SHORT", ohlcv=bars, portfolio_value=50000.0)


@pytest.fixture
def empty_ohlcv_input():
    """No OHLCV data at all."""
    return AnalysisInput(ticker="EMPTY", ohlcv=[], portfolio_value=50000.0)


@pytest.mark.asyncio
async def test_technical_bullish_trend(bullish_ohlcv_input):
    """Strong uptrend should produce bullish or neutral signal."""
    from src.analysis.technical import run
    signal = await run(bullish_ohlcv_input)
    assert signal.agent_id == "technical"
    assert signal.signal in ("bullish", "bearish", "neutral")
    assert 0.0 <= signal.confidence <= 1.0
    assert len(signal.reasoning) > 0
    # Metrics should include key indicators
    assert "rsi_14" in signal.metrics
    assert "macd_histogram" in signal.metrics


@pytest.mark.asyncio
async def test_technical_short_data_degrades(short_ohlcv_input):
    """Short data returns neutral with low confidence."""
    from src.analysis.technical import run
    signal = await run(short_ohlcv_input)
    assert signal.agent_id == "technical"
    assert signal.signal == "neutral"
    assert signal.confidence <= 0.3


@pytest.mark.asyncio
async def test_technical_empty_data(empty_ohlcv_input):
    """Empty OHLCV returns neutral with zero confidence."""
    from src.analysis.technical import run
    signal = await run(empty_ohlcv_input)
    assert signal.agent_id == "technical"
    assert signal.signal == "neutral"
    assert signal.confidence == 0.0


@pytest.mark.asyncio
async def test_technical_metrics_structure(bullish_ohlcv_input):
    """Metrics contain all expected indicator values."""
    from src.analysis.technical import run
    signal = await run(bullish_ohlcv_input)
    expected_keys = [
        "rsi_14", "macd_histogram", "macd_signal",
        "bb_position", "adx", "ema_8", "ema_21", "ema_55",
        "momentum_1m", "hurst_exponent",
        "strategies",  # per-strategy breakdown
    ]
    for key in expected_keys:
        assert key in signal.metrics, f"Missing metric: {key}"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_analysis_technical.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.analysis.technical'`

**Step 3: Write the technical agent**

Create `src/analysis/technical.py` implementing:
- 5 strategy functions: `_trend_following()`, `_mean_reversion()`, `_momentum()`, `_volatility_analysis()`, `_statistical_arbitrage()`
- Each returns `(signal_str, confidence_float, metrics_dict)`
- `_weighted_signal_combination()` aggregates with weights {trend: 0.25, mean_reversion: 0.20, momentum: 0.25, volatility: 0.15, stat_arb: 0.15}
- Main `async def run(input: AnalysisInput) -> AnalystSignal`
- Converts `input.ohlcv` list → pandas DataFrame at the top
- Returns neutral/0.0 confidence if < 20 bars
- Gracefully skips strategies that need more data than available

Key implementation details:
- Trend: EMA(8) > EMA(21) > EMA(55) = bullish; reversed = bearish. Confidence = ADX/100
- Mean reversion: Z-score of price vs 50d SMA. Z < -2 AND below BB 20% = bullish. Confidence = min(abs(z)/4, 1.0)
- Momentum: score = 0.4 * 1m + 0.3 * 3m + 0.3 * 6m. Score > 0.05 with volume confirm = bullish. Confidence = min(abs(score)*5, 1.0)
- Volatility: HV regime = current / 63d MA. Low regime (<0.8) AND z < -1 = bullish
- Stat arb: Hurst < 0.4 AND positive skew = bullish

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_analysis_technical.py -v`
Expected: All 4 tests PASS

**Step 5: Commit**

```bash
git add src/analysis/technical.py tests/test_analysis_technical.py
git commit -m "feat(analysis): add technical analysis agent (5 strategies)"
```

---

## Task 5: Fundamental Agent

**Files:**
- Create: `src/analysis/fundamental.py`
- Test: `tests/test_analysis_fundamental.py`

**Step 1: Write the failing test**

```python
# tests/test_analysis_fundamental.py
"""Tests for the fundamental analysis agent."""
import pytest
from src.analysis.models import AnalysisInput


@pytest.fixture
def strong_fundamentals_input():
    """Input with strong fundamental metrics (high ROE, low debt, growth)."""
    return AnalysisInput(
        ticker="AAPL",
        ohlcv=[],
        fundamentals={
            "returnOnEquity": 0.25,   # > 15%
            "peRatio": 18.0,           # < 25
            "priceToBook": 2.0,        # < 3
            "priceToSales": 3.5,       # < 5
            "debtToEquity": 0.3,       # < 0.5
            "currentRatio": 2.0,       # > 1.5
            "revenuePerShare": 25.0,
            "epsActual": 6.5,
            "freeCashFlowPerShare": 6.0,  # > 0.8 * EPS
            "marketCap": 3_000_000_000_000,
            "pegRatio": 1.2,
            "bookValuePerShare": 20.0,
            "returnOnAssets": 0.18,
            "dividendYield": 0.005,
        },
        portfolio_value=100000.0,
    )


@pytest.fixture
def weak_fundamentals_input():
    """Input with weak fundamentals (high debt, overvalued, no growth)."""
    return AnalysisInput(
        ticker="WEAK",
        ohlcv=[],
        fundamentals={
            "returnOnEquity": 0.05,
            "peRatio": 45.0,
            "priceToBook": 8.0,
            "priceToSales": 12.0,
            "debtToEquity": 2.5,
            "currentRatio": 0.8,
            "epsActual": 0.50,
            "freeCashFlowPerShare": 0.10,
            "marketCap": 500_000_000,
        },
        portfolio_value=100000.0,
    )


@pytest.mark.asyncio
async def test_fundamental_strong(strong_fundamentals_input):
    """Strong fundamentals produce bullish signal."""
    from src.analysis.fundamental import run
    signal = await run(strong_fundamentals_input)
    assert signal.agent_id == "fundamental"
    assert signal.signal == "bullish"
    assert signal.confidence > 0.5


@pytest.mark.asyncio
async def test_fundamental_weak(weak_fundamentals_input):
    """Weak fundamentals produce bearish signal."""
    from src.analysis.fundamental import run
    signal = await run(weak_fundamentals_input)
    assert signal.agent_id == "fundamental"
    assert signal.signal == "bearish"
    assert signal.confidence > 0.3


@pytest.mark.asyncio
async def test_fundamental_no_data():
    """None fundamentals return neutral."""
    from src.analysis.fundamental import run
    inp = AnalysisInput(ticker="NONE", ohlcv=[], fundamentals=None, portfolio_value=0)
    signal = await run(inp)
    assert signal.signal == "neutral"
    assert signal.confidence == 0.0


@pytest.mark.asyncio
async def test_fundamental_metrics_include_pillars(strong_fundamentals_input):
    """Metrics include per-pillar scores."""
    from src.analysis.fundamental import run
    signal = await run(strong_fundamentals_input)
    assert "profitability" in signal.metrics
    assert "growth" in signal.metrics
    assert "financial_health" in signal.metrics
    assert "valuation" in signal.metrics
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_analysis_fundamental.py -v`
Expected: FAIL — `ModuleNotFoundError`

**Step 3: Write the fundamental agent**

Create `src/analysis/fundamental.py` implementing:
- 4 pillar scoring functions: `_score_profitability()`, `_score_growth()`, `_score_financial_health()`, `_score_valuation()`
- Each takes the fundamentals dict, returns `(signal_str, confidence, metrics_dict)`
- Gracefully handles None/missing values: skip metric, adjust threshold denominator
- Overall: majority of pillar signals determines direction
- Confidence = max(bullish_count, bearish_count) / total_evaluated_pillars
- Main `async def run(input: AnalysisInput) -> AnalystSignal`

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_analysis_fundamental.py -v`
Expected: All 4 tests PASS

**Step 5: Commit**

```bash
git add src/analysis/fundamental.py tests/test_analysis_fundamental.py
git commit -m "feat(analysis): add fundamental scoring agent (4 pillars)"
```

---

## Task 6: Valuation Agent (DCF)

**Files:**
- Create: `src/analysis/valuation.py`
- Test: `tests/test_analysis_valuation.py`

**Step 1: Write the failing test**

```python
# tests/test_analysis_valuation.py
"""Tests for the valuation / DCF agent."""
import pytest
from src.analysis.models import AnalysisInput, OHLCVBar


@pytest.fixture
def undervalued_input():
    """Stock trading at $100 with fundamentals suggesting $150+ intrinsic value."""
    bars = [OHLCVBar(date="2025-06-01", open=100, high=101, low=99, close=100, volume=5e6)]
    return AnalysisInput(
        ticker="UVAL",
        ohlcv=bars,
        fundamentals={
            "marketCap": 50_000_000_000,
            "peRatio": 12.0,
            "priceToBook": 1.5,
            "priceToSales": 2.0,
            "epsActual": 8.33,
            "returnOnEquity": 0.22,
            "debtToEquity": 0.4,
            "freeCashFlowPerShare": 7.5,
            "bookValuePerShare": 66.67,
            "revenuePerShare": 50.0,
            "pegRatio": 0.8,
        },
        portfolio_value=100000.0,
    )


@pytest.mark.asyncio
async def test_valuation_produces_signal(undervalued_input):
    """Valuation agent returns valid signal with intrinsic value."""
    from src.analysis.valuation import run
    signal = await run(undervalued_input)
    assert signal.agent_id == "valuation"
    assert signal.signal in ("bullish", "bearish", "neutral")
    assert 0.0 <= signal.confidence <= 1.0
    assert "weighted_intrinsic_value" in signal.metrics
    assert "current_price" in signal.metrics
    assert "gap_pct" in signal.metrics


@pytest.mark.asyncio
async def test_valuation_no_fundamentals():
    """No fundamentals returns neutral."""
    from src.analysis.valuation import run
    inp = AnalysisInput(ticker="NONE", ohlcv=[], fundamentals=None, portfolio_value=0)
    signal = await run(inp)
    assert signal.signal == "neutral"
    assert signal.confidence == 0.0


@pytest.mark.asyncio
async def test_valuation_models_in_metrics(undervalued_input):
    """Metrics include per-model intrinsic values."""
    from src.analysis.valuation import run
    signal = await run(undervalued_input)
    models = signal.metrics.get("models", {})
    # At least one model should have computed a value
    assert len(models) > 0
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_analysis_valuation.py -v`
Expected: FAIL

**Step 3: Write the valuation agent**

Create `src/analysis/valuation.py` implementing:
- `_calculate_owner_earnings_value()` — Buffett method, 5yr projection, 15% discount, 25% margin of safety
- `_calculate_dcf_value()` — 3-stage: high growth (3yr, capped 25%; large-cap 10%) → transition (4yr) → terminal (min 3%). WACC via CAPM (risk-free 4.5%, ERP 6%, floor 6%, cap 20%). Bear/base/bull scenarios weighted 20/60/20.
- `_calculate_ev_ebitda_value()` — Median historical multiple × current EBITDA - net debt
- `_calculate_residual_income_value()` — Book value + PV of excess returns, 20% margin of safety
- `_calculate_wacc()` — Cost of equity = Rf + beta × ERP. Cost of debt from interest coverage. Weighted.
- Overall: Weighted gap (owner_earnings 0.35, dcf 0.35, ev_ebitda 0.20, residual 0.10). Gap > 15% = bullish. Confidence = min(abs(gap) / 0.30, 1.0).
- Main `async def run(input: AnalysisInput) -> AnalystSignal`
- Get current price from last OHLCV bar close, or return neutral if no price available
- Each model returns None if insufficient data; overall uses only models that succeeded

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_analysis_valuation.py -v`
Expected: All 3 tests PASS

**Step 5: Commit**

```bash
git add src/analysis/valuation.py tests/test_analysis_valuation.py
git commit -m "feat(analysis): add valuation agent (DCF, owner earnings, multiples)"
```

---

## Task 7: Sentiment Agent

**Files:**
- Create: `src/analysis/sentiment.py`
- Test: `tests/test_analysis_sentiment.py`

**Step 1: Write the failing test**

```python
# tests/test_analysis_sentiment.py
"""Tests for the sentiment analysis agent."""
import pytest
from src.analysis.models import AnalysisInput, IdeaData, NewsItem


@pytest.fixture
def bullish_sentiment_input():
    """Input with mostly bullish ideas and positive news."""
    ideas = [
        IdeaData(direction="bullish", confidence=0.9, labels=["trade_plan"],
                 idea_text="Long AAPL to 200", created_at="2026-03-01", author="trader1"),
        IdeaData(direction="bullish", confidence=0.7, labels=["technical_analysis"],
                 idea_text="Breakout above resistance", created_at="2026-03-02", author="trader2"),
        IdeaData(direction="neutral", confidence=0.5, labels=["general_discussion"],
                 idea_text="Watching AAPL", created_at="2026-02-20", author="trader3"),
    ]
    news = [
        NewsItem(title="Apple Reports Record Revenue", date="2026-03-01", source="Reuters"),
        NewsItem(title="Apple Stock Surges on Strong Earnings", date="2026-03-01", source="Bloomberg"),
    ]
    return AnalysisInput(
        ticker="AAPL", ohlcv=[], ideas=ideas, news=news, portfolio_value=100000.0,
    )


@pytest.mark.asyncio
async def test_sentiment_bullish(bullish_sentiment_input):
    """Mostly bullish ideas produce bullish signal."""
    from src.analysis.sentiment import run
    signal = await run(bullish_sentiment_input)
    assert signal.agent_id == "sentiment"
    assert signal.signal == "bullish"
    assert signal.confidence > 0.3
    assert "idea_count" in signal.metrics
    assert "bullish_pct" in signal.metrics


@pytest.mark.asyncio
async def test_sentiment_no_data():
    """No ideas and no news returns neutral."""
    from src.analysis.sentiment import run
    inp = AnalysisInput(ticker="NONE", ohlcv=[], portfolio_value=0)
    signal = await run(inp)
    assert signal.signal == "neutral"
    assert signal.confidence == 0.0


@pytest.mark.asyncio
async def test_sentiment_news_only():
    """News-only input still produces a signal."""
    from src.analysis.sentiment import run
    news = [
        NewsItem(title="Company faces major lawsuit", date="2026-03-01"),
        NewsItem(title="Stock plunges on weak guidance", date="2026-03-01"),
    ]
    inp = AnalysisInput(ticker="BAD", ohlcv=[], news=news, portfolio_value=0)
    signal = await run(inp)
    assert signal.agent_id == "sentiment"
    assert signal.signal in ("bullish", "bearish", "neutral")
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_analysis_sentiment.py -v`
Expected: FAIL

**Step 3: Write the sentiment agent**

Create `src/analysis/sentiment.py` implementing:
- `_score_discord_ideas()` — Count bullish/bearish/neutral. Weight by confidence. Recent (7d) ideas weighted 2x vs older (30d). Returns (signal, confidence, metrics).
- `_score_news_headlines()` — Keyword-based headline classification using positive/negative word lists. No LLM. Words like "surges", "record", "beats" → positive; "plunges", "lawsuit", "misses" → negative. Returns (signal, confidence, metrics).
- Weights: ideas 0.50, news 0.30, discord_sentiment 0.20 (discord_sentiment skipped if no raw sentiment data available; weights redistributed)
- Main `async def run(input: AnalysisInput) -> AnalystSignal`

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_analysis_sentiment.py -v`
Expected: All 3 tests PASS

**Step 5: Commit**

```bash
git add src/analysis/sentiment.py tests/test_analysis_sentiment.py
git commit -m "feat(analysis): add sentiment agent (Discord ideas + news)"
```

---

## Task 8: Risk Agent

**Files:**
- Create: `src/analysis/risk.py`
- Test: `tests/test_analysis_risk.py`

**Step 1: Write the failing test**

```python
# tests/test_analysis_risk.py
"""Tests for the risk analysis agent."""
import pytest
import numpy as np
import pandas as pd
from src.analysis.models import AnalysisInput, OHLCVBar, PositionData


@pytest.fixture
def risk_input():
    """200 days of OHLCV with a position."""
    np.random.seed(42)
    n = 200
    close = 100.0 + np.cumsum(np.random.randn(n) * 1.5)
    close = np.maximum(close, 10.0)
    bars = []
    for i in range(n):
        d = (pd.Timestamp("2025-01-01") + pd.Timedelta(days=i)).strftime("%Y-%m-%d")
        c = float(close[i])
        bars.append(OHLCVBar(
            date=d, open=c - 0.3, high=c + 1.0, low=c - 1.0,
            close=c, volume=5_000_000.0,
        ))
    position = PositionData(
        quantity=100, avg_cost=95.0, current_price=float(close[-1]),
        market_value=float(close[-1]) * 100,
        unrealized_pnl=(float(close[-1]) - 95.0) * 100,
        unrealized_pnl_pct=((float(close[-1]) - 95.0) / 95.0) * 100,
    )
    return AnalysisInput(
        ticker="TEST", ohlcv=bars, position=position, portfolio_value=100000.0,
    )


@pytest.mark.asyncio
async def test_risk_produces_signal(risk_input):
    """Risk agent returns valid signal with risk metrics."""
    from src.analysis.risk import run
    signal = await run(risk_input)
    assert signal.agent_id == "risk"
    assert signal.signal in ("bullish", "bearish", "neutral")
    assert 0.0 <= signal.confidence <= 1.0


@pytest.mark.asyncio
async def test_risk_metrics_structure(risk_input):
    """Risk metrics include volatility, drawdown, and sizing."""
    from src.analysis.risk import run
    signal = await run(risk_input)
    assert "annualized_volatility" in signal.metrics
    assert "max_drawdown" in signal.metrics
    assert "volatility_percentile" in signal.metrics
    assert "position_size_recommendation_pct" in signal.metrics


@pytest.mark.asyncio
async def test_risk_no_data():
    """Empty OHLCV returns neutral."""
    from src.analysis.risk import run
    inp = AnalysisInput(ticker="EMPTY", ohlcv=[], portfolio_value=50000.0)
    signal = await run(inp)
    assert signal.signal == "neutral"
    assert signal.confidence == 0.0


@pytest.mark.asyncio
async def test_portfolio_risk_report():
    """Portfolio risk computation returns valid report."""
    from src.analysis.risk import compute_portfolio_risk
    from src.analysis.models import PortfolioRiskReport

    # Minimal test: single stock
    np.random.seed(42)
    n = 100
    returns_data = {"AAPL": np.random.randn(n) * 0.02}
    weights = {"AAPL": 1.0}
    sector_map = {"AAPL": "Technology"}

    report = compute_portfolio_risk(
        returns_data=returns_data,
        weights=weights,
        sector_map=sector_map,
        total_value=100000.0,
    )
    assert isinstance(report, PortfolioRiskReport)
    assert report.var_95_1d > 0
    assert "Technology" in report.sector_exposure
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_analysis_risk.py -v`
Expected: FAIL

**Step 3: Write the risk agent**

Create `src/analysis/risk.py` implementing:

Per-stock `run()`:
- Convert OHLCV to DataFrame, compute daily returns
- `annualized_volatility`: 60d rolling std × √252
- `volatility_percentile`: current vol rank vs 252d history
- `max_drawdown`: cumulative max → drawdown series → min
- `position_size_recommendation_pct`: volatility-adjusted (low <15%: 25%, medium 15-30%: 12.5-20%, high 30-50%: 5-15%, very high >50%: max 10%)
- Signal: low vol = bullish (favorable risk profile), high vol = bearish. Neutral if moderate.

Portfolio-wide `compute_portfolio_risk()`:
- Takes `returns_data` dict[ticker, array], `weights`, `sector_map`, `total_value`
- VaR 95% (1d, 5d): historical simulation — weighted portfolio returns, 5th percentile
- Concentration HHI: sum of squared weights
- Correlation matrix: pairwise from returns
- Diversification ratio: weighted avg individual vol / portfolio vol
- Sector exposure: aggregate weights by sector
- Returns `PortfolioRiskReport`

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_analysis_risk.py -v`
Expected: All 4 tests PASS

**Step 5: Commit**

```bash
git add src/analysis/risk.py tests/test_analysis_risk.py
git commit -m "feat(analysis): add risk agent (volatility, VaR, portfolio risk)"
```

---

## Task 9: Consensus Aggregator

**Files:**
- Create: `src/analysis/consensus.py`
- Test: `tests/test_analysis_consensus.py`

**Step 1: Write the failing test**

```python
# tests/test_analysis_consensus.py
"""Tests for the consensus aggregator agent."""
import pytest
from unittest.mock import patch, MagicMock
from src.analysis.models import AnalysisInput, AnalystSignal


@pytest.fixture
def bullish_signals():
    """5 agent signals, mostly bullish."""
    return [
        AnalystSignal(agent_id="technical", signal="bullish", confidence=0.8,
                      reasoning="Strong uptrend", metrics={}),
        AnalystSignal(agent_id="fundamental", signal="bullish", confidence=0.7,
                      reasoning="Good profitability", metrics={}),
        AnalystSignal(agent_id="valuation", signal="bullish", confidence=0.6,
                      reasoning="Undervalued by 20%", metrics={}),
        AnalystSignal(agent_id="sentiment", signal="neutral", confidence=0.4,
                      reasoning="Mixed sentiment", metrics={}),
        AnalystSignal(agent_id="risk", signal="neutral", confidence=0.5,
                      reasoning="Moderate volatility", metrics={}),
    ]


@pytest.fixture
def bearish_signals():
    """5 agent signals, mostly bearish."""
    return [
        AnalystSignal(agent_id="technical", signal="bearish", confidence=0.9,
                      reasoning="Downtrend", metrics={}),
        AnalystSignal(agent_id="fundamental", signal="bearish", confidence=0.8,
                      reasoning="Weak financials", metrics={}),
        AnalystSignal(agent_id="valuation", signal="bearish", confidence=0.7,
                      reasoning="Overvalued by 30%", metrics={}),
        AnalystSignal(agent_id="sentiment", signal="bearish", confidence=0.6,
                      reasoning="Negative sentiment", metrics={}),
        AnalystSignal(agent_id="risk", signal="bearish", confidence=0.8,
                      reasoning="High volatility", metrics={}),
    ]


def test_deterministic_scoring_bullish(bullish_signals):
    """Mostly bullish signals produce positive bull_bear_score."""
    from src.analysis.consensus import compute_deterministic_score
    score, verdict = compute_deterministic_score(bullish_signals)
    assert score > 0.0
    assert verdict in ("strong_buy", "buy")


def test_deterministic_scoring_bearish(bearish_signals):
    """Mostly bearish signals produce negative bull_bear_score."""
    from src.analysis.consensus import compute_deterministic_score
    score, verdict = compute_deterministic_score(bearish_signals)
    assert score < 0.0
    assert verdict in ("strong_sell", "sell")


@pytest.mark.asyncio
@pytest.mark.openai
async def test_consensus_full_run(bullish_signals):
    """Full consensus run with mocked OpenAI call."""
    from src.analysis.consensus import run

    # Mock the OpenAI call
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_choice = MagicMock()
    mock_choice.message.content = "AAPL shows strong technical momentum backed by solid fundamentals."
    mock_response.choices = [mock_choice]
    mock_client.chat.completions.create.return_value = mock_response

    with patch("src.analysis.consensus.OpenAI", return_value=mock_client), \
         patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}):
        report = await run(
            ticker="AAPL",
            signals=bullish_signals,
            data_sources=["Databento OHLCV", "OpenBB/FMP"],
        )

    assert report.ticker == "AAPL"
    assert report.overall_signal in ("strong_buy", "buy", "hold", "sell", "strong_sell")
    assert report.bull_bear_score > 0
    assert len(report.agent_signals) == 5
    assert len(report.data_sources) == 2
    assert report.model_used.startswith("gpt-")
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_analysis_consensus.py -v -m "not openai"`
Expected: FAIL

**Step 3: Write the consensus agent**

Create `src/analysis/consensus.py` implementing:

- `AGENT_WEIGHTS = {"technical": 0.25, "fundamental": 0.20, "valuation": 0.25, "sentiment": 0.15, "risk": 0.15}`
- `SIGNAL_MAP = {"bullish": 1.0, "neutral": 0.0, "bearish": -1.0}`
- `compute_deterministic_score(signals) -> (bull_bear_score, verdict)`:
  - Score = sum(signal_numeric × weight × confidence) / sum(weight × confidence)
  - Verdict: > 0.4 strong_buy, > 0.15 buy, > -0.15 hold, > -0.4 sell, else strong_sell
- `_should_escalate(signals) -> bool`:
  - True if max confidence spread > 0.6 AND >= 3 different signal directions
- `_generate_narrative(ticker, signals, score, verdict) -> (summary, model_used)`:
  - OpenAI `client.chat.completions.create()` with system prompt + compact signal summary
  - Model: gpt-5-mini default, gpt-5 if `_should_escalate()`
  - Returns fallback narrative on failure (no crash)
- `async def run(ticker, signals, data_sources) -> ConsensusReport`:
  - Compute deterministic score
  - Generate narrative
  - Assemble ConsensusReport

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_analysis_consensus.py -v -m "not openai"`
Expected: 2 deterministic tests PASS. The `test_consensus_full_run` is marked `openai` so it only runs with `pytest -m openai`.

To verify the OpenAI-dependent test too:
Run: `pytest tests/test_analysis_consensus.py::test_consensus_full_run -v`
Expected: PASS (uses mocked OpenAI)

**Step 5: Commit**

```bash
git add src/analysis/consensus.py tests/test_analysis_consensus.py
git commit -m "feat(analysis): add consensus aggregator (deterministic + LLM narrative)"
```

---

## Task 10: Orchestrator (Data Assembly + Caching + Dispatch)

**Files:**
- Create: `src/analysis/orchestrator.py`
- Test: `tests/test_analysis_orchestrator.py`

**Step 1: Write the failing test**

```python
# tests/test_analysis_orchestrator.py
"""Tests for the analysis orchestrator."""
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from datetime import datetime, timezone, timedelta


@pytest.mark.asyncio
async def test_orchestrator_cache_hit():
    """Returns cached result without running agents if fresh."""
    from src.analysis.orchestrator import get_stock_analysis
    from src.analysis.models import ConsensusReport

    cached = {
        "ticker": "AAPL",
        "overall_signal": "buy",
        "overall_confidence": 0.75,
        "bull_bear_score": 0.3,
        "agent_signals": [],
        "summary": "cached",
        "data_sources": [],
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "model_used": "gpt-5-mini",
    }
    mock_row = MagicMock()
    mock_row._mapping = {
        "result": cached,
        "expires_at": datetime.now(timezone.utc) + timedelta(hours=2),
    }

    with patch("src.analysis.orchestrator.execute_sql", return_value=[mock_row]):
        report = await get_stock_analysis("AAPL", refresh=False)
    assert report["ticker"] == "AAPL"
    assert report["summary"] == "cached"


@pytest.mark.asyncio
async def test_orchestrator_cache_miss_runs_agents():
    """Cache miss triggers full agent pipeline."""
    from src.analysis.orchestrator import get_stock_analysis
    from src.analysis.models import AnalystSignal

    mock_signal = AnalystSignal(
        agent_id="technical", signal="neutral", confidence=0.5,
        reasoning="test", metrics={},
    )

    with patch("src.analysis.orchestrator.execute_sql", return_value=[]), \
         patch("src.analysis.orchestrator._assemble_input") as mock_assemble, \
         patch("src.analysis.orchestrator._run_agents", new_callable=AsyncMock,
               return_value=[mock_signal] * 5) as mock_run, \
         patch("src.analysis.orchestrator._run_consensus", new_callable=AsyncMock) as mock_consensus, \
         patch("src.analysis.orchestrator._cache_result"):

        mock_assemble.return_value = (MagicMock(), ["Databento OHLCV"])
        mock_consensus.return_value = {
            "ticker": "AAPL", "overall_signal": "hold",
            "overall_confidence": 0.5, "bull_bear_score": 0.0,
            "agent_signals": [], "summary": "test",
            "data_sources": ["Databento OHLCV"],
            "computed_at": datetime.now(timezone.utc).isoformat(),
            "model_used": "gpt-5-mini",
        }

        report = await get_stock_analysis("AAPL", refresh=False)

    assert report["ticker"] == "AAPL"
    mock_run.assert_called_once()
    mock_consensus.assert_called_once()
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_analysis_orchestrator.py -v`
Expected: FAIL

**Step 3: Write the orchestrator**

Create `src/analysis/orchestrator.py` implementing:

- `_check_cache(ticker, analysis_type) -> dict | None`:
  - Query `stock_analysis_cache` WHERE ticker AND analysis_type AND expires_at > NOW()
  - Return `result` JSONB if found, else None
- `_assemble_input(ticker) -> (AnalysisInput, list[str])`:
  - Parallel data fetch using existing services:
    - `price_service.get_ohlcv(ticker, 1yr)` → convert DataFrame to list[OHLCVBar]
    - `openbb_service.get_fundamentals(ticker)`
    - `openbb_service.get_company_news(ticker)`
    - DB query: `discord_parsed_ideas` for ticker
    - DB query: `positions` for ticker
    - DB query: `account_balances` for total portfolio value
  - Track which sources returned data → `data_sources` list
  - Handle crypto via `_CRYPTO_SYMBOLS` guard (skip Databento, use yfinance)
- `_run_agents(input) -> list[AnalystSignal]`:
  - `asyncio.gather(technical.run(input), fundamental.run(input), valuation.run(input), sentiment.run(input), risk.run(input))`
  - Wrap each in try/except — if agent fails, return neutral signal with error in reasoning
- `_run_consensus(ticker, signals, data_sources) -> dict`:
  - Call `consensus.run(ticker, signals, data_sources)`
  - Return `.model_dump()` for JSON serialization
- `_cache_result(ticker, analysis_type, result, agent_signals, model, sources)`:
  - UPSERT into `stock_analysis_cache` with TTL (4h equity, 1h crypto)
  - Uses `ON CONFLICT (ticker, analysis_type) DO UPDATE`
- `async def get_stock_analysis(ticker, refresh=False, agents=None) -> dict`:
  - Main entry point for the route
  - Check cache (unless refresh=True)
  - Assemble input → run agents → run consensus → cache → return
- `async def get_portfolio_risk() -> dict`:
  - Fetch all positions + OHLCV for top 15 holdings
  - Call `risk.compute_portfolio_risk()`
  - Cache in `portfolio_risk_cache`

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_analysis_orchestrator.py -v`
Expected: All 2 tests PASS

**Step 5: Commit**

```bash
git add src/analysis/orchestrator.py tests/test_analysis_orchestrator.py
git commit -m "feat(analysis): add orchestrator (data assembly, caching, dispatch)"
```

---

## Task 11: API Routes

**Files:**
- Create: `app/routes/analysis.py`
- Modify: `app/main.py` (add router registration)
- Test: `tests/test_analysis_routes.py`

**Step 1: Write the failing test**

```python
# tests/test_analysis_routes.py
"""Tests for analysis API routes."""
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from datetime import datetime, timezone


@pytest.fixture
def client():
    """Create test client with auth disabled."""
    with patch.dict("os.environ", {"DISABLE_AUTH": "true"}):
        from app.main import app
        from fastapi.testclient import TestClient
        with TestClient(app) as c:
            yield c


def test_get_stock_analysis(client):
    """GET /stocks/{ticker}/analysis returns consensus report."""
    mock_report = {
        "ticker": "AAPL",
        "overall_signal": "buy",
        "overall_confidence": 0.75,
        "bull_bear_score": 0.3,
        "agent_signals": [],
        "summary": "Strong buy signal",
        "data_sources": ["Databento OHLCV"],
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "model_used": "gpt-5-mini",
    }

    with patch("app.routes.analysis.get_stock_analysis",
               new_callable=AsyncMock, return_value=mock_report):
        resp = client.get("/stocks/AAPL/analysis")

    assert resp.status_code == 200
    data = resp.json()
    assert data["ticker"] == "AAPL"
    assert data["overall_signal"] == "buy"


def test_get_stock_analysis_refresh(client):
    """?refresh=true bypasses cache."""
    mock_report = {
        "ticker": "AAPL", "overall_signal": "hold",
        "overall_confidence": 0.5, "bull_bear_score": 0.0,
        "agent_signals": [], "summary": "Fresh analysis",
        "data_sources": [], "computed_at": datetime.now(timezone.utc).isoformat(),
        "model_used": "gpt-5-mini",
    }

    with patch("app.routes.analysis.get_stock_analysis",
               new_callable=AsyncMock, return_value=mock_report) as mock_fn:
        resp = client.get("/stocks/AAPL/analysis?refresh=true")

    assert resp.status_code == 200
    mock_fn.assert_called_once_with("AAPL", refresh=True, agents=None)


def test_get_portfolio_risk(client):
    """GET /portfolio/risk returns portfolio risk report."""
    mock_report = {
        "var_95_1d": 0.023, "var_95_5d": 0.051,
        "concentration_hhi": 0.12, "diversification_ratio": 1.35,
        "correlation_matrix": {}, "top_risk_contributors": [],
        "sector_exposure": {"Technology": 0.45},
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "data_sources": ["Databento OHLCV"],
    }

    with patch("app.routes.analysis.get_portfolio_risk",
               new_callable=AsyncMock, return_value=mock_report):
        resp = client.get("/portfolio/risk")

    assert resp.status_code == 200
    data = resp.json()
    assert "var_95_1d" in data
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_analysis_routes.py -v`
Expected: FAIL — either import error or 404

**Step 3: Write the route file**

```python
# app/routes/analysis.py
"""
Analysis API routes.

Endpoints:
- GET /stocks/{ticker}/analysis          - Full multi-agent consensus report
- GET /stocks/{ticker}/analysis/technical - Technical analysis only
- GET /stocks/{ticker}/analysis/risk      - Per-stock risk analysis only
- GET /portfolio/risk                     - Portfolio-wide risk analytics
"""

import logging
from typing import Optional

from fastapi import APIRouter, Path, Query
from fastapi.responses import JSONResponse

from src.analysis.orchestrator import get_stock_analysis, get_portfolio_risk

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/stocks/{ticker}/analysis")
async def stock_analysis(
    ticker: str = Path(..., description="Stock ticker symbol"),
    refresh: bool = Query(False, description="Bypass cache and force recompute"),
    agents: Optional[str] = Query(None, description="Comma-separated agent subset"),
):
    """Get full multi-agent consensus analysis for a stock."""
    agent_list = agents.split(",") if agents else None
    result = await get_stock_analysis(
        ticker.upper(), refresh=refresh, agents=agent_list,
    )
    return JSONResponse(content=result)


@router.get("/stocks/{ticker}/analysis/technical")
async def stock_technical_analysis(
    ticker: str = Path(..., description="Stock ticker symbol"),
):
    """Get technical analysis only (no LLM call)."""
    result = await get_stock_analysis(
        ticker.upper(), refresh=False, agents=["technical"],
    )
    # Extract just the technical signal from agent_signals
    for sig in result.get("agent_signals", []):
        if sig.get("agent_id") == "technical":
            return JSONResponse(content=sig)
    return JSONResponse(content=result)


@router.get("/stocks/{ticker}/analysis/risk")
async def stock_risk_analysis(
    ticker: str = Path(..., description="Stock ticker symbol"),
):
    """Get per-stock risk analysis only (no LLM call)."""
    result = await get_stock_analysis(
        ticker.upper(), refresh=False, agents=["risk"],
    )
    for sig in result.get("agent_signals", []):
        if sig.get("agent_id") == "risk":
            return JSONResponse(content=sig)
    return JSONResponse(content=result)


@router.get("/portfolio/risk")
async def portfolio_risk(
    refresh: bool = Query(False, description="Bypass cache and force recompute"),
):
    """Get portfolio-wide risk analytics (VaR, correlation, concentration)."""
    result = await get_portfolio_risk(refresh=refresh)
    return JSONResponse(content=result)
```

**Step 4: Register the router in main.py**

Add to `app/main.py` imports:
```python
from app.routes import analysis as analysis_routes
```

Add router registration (after existing routers):
```python
app.include_router(
    analysis_routes.router,
    tags=["Analysis"],
    dependencies=[Depends(require_api_key)],
)
```

Note: The analysis router does NOT use a prefix because its paths already include `/stocks/` and `/portfolio/` prefixes to match existing URL patterns.

**Step 5: Run test to verify it passes**

Run: `pytest tests/test_analysis_routes.py -v`
Expected: All 3 tests PASS

**Step 6: Commit**

```bash
git add app/routes/analysis.py tests/test_analysis_routes.py app/main.py
git commit -m "feat(analysis): add API routes and register in app"
```

---

## Task 12: Self-Reflection Pattern for Idea Refinement

**Files:**
- Modify: `app/routes/ideas.py` (the `/refine` endpoint)
- Test: `tests/test_ideas_refine_reflection.py`

**Step 1: Write the failing test**

```python
# tests/test_ideas_refine_reflection.py
"""Tests for the self-reflection pattern on idea refinement."""
import json
import pytest
from unittest.mock import patch, MagicMock


SAMPLE_UUID = "12345678-1234-1234-1234-123456789abc"


def _mock_row(data: dict):
    row = MagicMock()
    row._mapping = data
    return row


@pytest.fixture
def client():
    with patch.dict("os.environ", {"DISABLE_AUTH": "true"}):
        from app.main import app
        from fastapi.testclient import TestClient
        with TestClient(app) as c:
            yield c


def test_refine_uses_reflection(client):
    """Refine endpoint now performs reflection pass."""
    idea_row = _mock_row({
        "id": SAMPLE_UUID, "content": "Long AAPL above 200",
        "symbol": "AAPL", "symbols": ["AAPL"], "tags": [], "status": "draft",
    })

    refine_result = json.dumps({
        "refinedContent": "Buy AAPL above $200 with target $220",
        "extractedSymbols": ["AAPL"],
        "suggestedTags": ["trade_plan"],
        "changesSummary": "Added price target",
    })

    reflection_result = json.dumps({
        "issues_found": False,
        "critique": "The refinement is well-structured with clear entry and target."
    })

    mock_client = MagicMock()
    # First call: refine. Second call: reflect.
    mock_client.chat.completions.create.side_effect = [
        MagicMock(choices=[MagicMock(message=MagicMock(content=refine_result))]),
        MagicMock(choices=[MagicMock(message=MagicMock(content=reflection_result))]),
    ]

    with patch("app.routes.ideas.execute_sql", return_value=[idea_row]), \
         patch("openai.OpenAI", return_value=mock_client), \
         patch.dict("os.environ", {"OPENAI_API_KEY": "fake"}):
        resp = client.post(f"/ideas/{SAMPLE_UUID}/refine")

    assert resp.status_code == 200
    data = resp.json()
    assert data["refinedContent"] == "Buy AAPL above $200 with target $220"
    # Should have called OpenAI twice: refine + reflect
    assert mock_client.chat.completions.create.call_count == 2


def test_refine_re_refines_on_issues(client):
    """If reflection finds issues, a third call re-refines."""
    idea_row = _mock_row({
        "id": SAMPLE_UUID, "content": "Buy something",
        "symbol": None, "symbols": [], "tags": [], "status": "draft",
    })

    refine_result = json.dumps({
        "refinedContent": "Buy TGT at $150",
        "extractedSymbols": ["TGT"],
        "suggestedTags": ["trade_plan"],
        "changesSummary": "Added ticker and price",
    })

    reflection_with_issues = json.dumps({
        "issues_found": True,
        "critique": "TGT ticker may be incorrect - 'target' is a common word. Verify the user meant Target Corp."
    })

    re_refined_result = json.dumps({
        "refinedContent": "Buy Target Corp (TGT) at $150 - verify ticker intent",
        "extractedSymbols": ["TGT"],
        "suggestedTags": ["trade_plan", "needs_review"],
        "changesSummary": "Added company name clarification",
    })

    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = [
        MagicMock(choices=[MagicMock(message=MagicMock(content=refine_result))]),
        MagicMock(choices=[MagicMock(message=MagicMock(content=reflection_with_issues))]),
        MagicMock(choices=[MagicMock(message=MagicMock(content=re_refined_result))]),
    ]

    with patch("app.routes.ideas.execute_sql", return_value=[idea_row]), \
         patch("openai.OpenAI", return_value=mock_client), \
         patch.dict("os.environ", {"OPENAI_API_KEY": "fake"}):
        resp = client.post(f"/ideas/{SAMPLE_UUID}/refine")

    assert resp.status_code == 200
    data = resp.json()
    assert "Target Corp" in data["refinedContent"]
    # 3 calls: refine + reflect + re-refine
    assert mock_client.chat.completions.create.call_count == 3
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_ideas_refine_reflection.py -v`
Expected: FAIL — second OpenAI call not happening yet

**Step 3: Modify the refine endpoint**

In `app/routes/ideas.py`, modify the `refine_idea()` function to add a reflection pass after the initial refinement. Add a `_call_reflection()` inner function alongside the existing `_call_openai()`:

- After getting `refine_result` from the first call, make a second call with a reflection system prompt:
  - "You are a quality reviewer for trading ideas. Critique this refinement..."
  - Check for: hallucinated price targets, incorrect tickers (false positives from common words), direction not supported by text, missing stop loss if entry exists
  - Return JSON: `{"issues_found": bool, "critique": str}`
- If `issues_found` is True, make a third call that includes the original content + first refinement + critique
- If `issues_found` is False, return the first refinement as-is
- Wrap reflection in try/except — if reflection fails, still return original refinement (graceful degradation)
- Use same model (`OPENAI_MODEL_REFINE` env var, default gpt-4o-mini)

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_ideas_refine_reflection.py -v`
Expected: All 2 tests PASS

Also run existing refine tests to verify no regression:
Run: `pytest tests/test_ideas_route.py -v -k refine`
Expected: Existing tests still PASS

**Step 5: Commit**

```bash
git add app/routes/ideas.py tests/test_ideas_refine_reflection.py
git commit -m "feat(ideas): add self-reflection pattern to /refine endpoint"
```

---

## Task 13: Integration Test — Full Pipeline

**Files:**
- Create: `tests/test_analysis_integration.py`

**Step 1: Write integration test**

```python
# tests/test_analysis_integration.py
"""Integration test: full pipeline from OHLCV to consensus report."""
import pytest
import numpy as np
import pandas as pd
from unittest.mock import patch, MagicMock
from src.analysis.models import AnalysisInput, OHLCVBar, IdeaData, NewsItem


@pytest.fixture
def full_input():
    """Realistic AnalysisInput with all data populated."""
    np.random.seed(42)
    n = 200
    close = 150.0 + np.cumsum(np.random.randn(n) * 2.0)
    close = np.maximum(close, 50.0)
    bars = []
    for i in range(n):
        d = (pd.Timestamp("2025-01-01") + pd.Timedelta(days=i)).strftime("%Y-%m-%d")
        c = float(close[i])
        bars.append(OHLCVBar(
            date=d, open=c - 0.5, high=c + 1.5, low=c - 1.5,
            close=c, volume=8_000_000.0,
        ))

    return AnalysisInput(
        ticker="AAPL",
        ohlcv=bars,
        fundamentals={
            "returnOnEquity": 0.25, "peRatio": 20.0, "priceToBook": 2.5,
            "priceToSales": 4.0, "debtToEquity": 0.3, "currentRatio": 1.8,
            "epsActual": 7.5, "freeCashFlowPerShare": 6.0,
            "marketCap": 3_000_000_000_000, "bookValuePerShare": 60.0,
            "revenuePerShare": 37.5, "pegRatio": 1.1,
        },
        ideas=[
            IdeaData(direction="bullish", confidence=0.8, labels=["trade_plan"],
                     idea_text="Long AAPL", created_at="2026-03-01", author="test"),
        ],
        news=[
            NewsItem(title="Apple beats earnings expectations", date="2026-03-01"),
        ],
        portfolio_value=200000.0,
    )


@pytest.mark.asyncio
async def test_all_agents_run_without_error(full_input):
    """Every agent produces a valid AnalystSignal from realistic data."""
    from src.analysis import technical, fundamental, valuation, sentiment, risk

    results = []
    for agent in [technical, fundamental, valuation, sentiment, risk]:
        sig = await agent.run(full_input)
        assert sig.signal in ("bullish", "bearish", "neutral")
        assert 0.0 <= sig.confidence <= 1.0
        assert len(sig.reasoning) > 0
        results.append(sig)

    # All 5 agents returned
    assert len(results) == 5
    agent_ids = {s.agent_id for s in results}
    assert agent_ids == {"technical", "fundamental", "valuation", "sentiment", "risk"}


@pytest.mark.asyncio
async def test_full_pipeline_with_mocked_llm(full_input):
    """Full pipeline: 5 agents → consensus with mocked LLM."""
    from src.analysis import technical, fundamental, valuation, sentiment, risk
    from src.analysis.consensus import run as consensus_run

    # Run all agents
    signals = []
    for agent in [technical, fundamental, valuation, sentiment, risk]:
        signals.append(await agent.run(full_input))

    # Mock the LLM for consensus
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(
            content="AAPL shows strong fundamentals with solid technical momentum."
        ))]
    )

    with patch("src.analysis.consensus.OpenAI", return_value=mock_client), \
         patch.dict("os.environ", {"OPENAI_API_KEY": "test"}):
        report = await consensus_run(
            ticker="AAPL",
            signals=signals,
            data_sources=["Databento OHLCV (200 days)", "OpenBB/FMP fundamentals"],
        )

    assert report.ticker == "AAPL"
    assert report.overall_signal in ("strong_buy", "buy", "hold", "sell", "strong_sell")
    assert -1.0 <= report.bull_bear_score <= 1.0
    assert len(report.agent_signals) == 5
    assert report.model_used.startswith("gpt-")
```

**Step 2: Run the integration test**

Run: `pytest tests/test_analysis_integration.py -v`
Expected: All 2 tests PASS

**Step 3: Run the full test suite to verify no regressions**

Run: `pytest tests/ -v -m "not openai and not integration" --tb=short`
Expected: All existing tests still PASS

**Step 4: Commit**

```bash
git add tests/test_analysis_integration.py
git commit -m "test(analysis): add full pipeline integration tests"
```

---

## Task 14: Final Verification & Documentation

**Step 1: Run full test suite**

Run: `pytest tests/ -v -m "not openai and not integration" --cov=src/analysis --cov-report=term-missing`
Expected: All analysis tests PASS, good coverage on `src/analysis/`

**Step 2: Verify API endpoints via test client**

Run: `pytest tests/test_analysis_routes.py -v`
Expected: All route tests PASS

**Step 3: Lint check**

Run: `ruff check src/analysis/ app/routes/analysis.py tests/test_analysis_*.py`
Expected: No errors

**Step 4: Commit any cleanup**

```bash
git add -A
git commit -m "chore(analysis): lint cleanup and final verification"
```

---

## Summary

| Task | Files | Agent/Component | LLM? | Data Source |
|------|-------|----------------|------|-------------|
| 1 | `schema/067_analysis_cache.sql` | DB schema | No | — |
| 2 | `src/analysis/models.py` | Shared models | No | — |
| 3 | `src/analysis/indicators.py` | Math library | No | — |
| 4 | `src/analysis/technical.py` | Technical agent | **No** | Databento OHLCV |
| 5 | `src/analysis/fundamental.py` | Fundamental agent | **No** | OpenBB/FMP |
| 6 | `src/analysis/valuation.py` | Valuation agent | **No** | OpenBB/FMP + Databento |
| 7 | `src/analysis/sentiment.py` | Sentiment agent | **No** | Discord NLP + OpenBB news |
| 8 | `src/analysis/risk.py` | Risk agent | **No** | Databento OHLCV + positions |
| 9 | `src/analysis/consensus.py` | Consensus aggregator | **Yes** (gpt-5-mini) | All agent signals |
| 10 | `src/analysis/orchestrator.py` | Orchestration + cache | No | All services |
| 11 | `app/routes/analysis.py` + `app/main.py` | API routes | No | Orchestrator |
| 12 | `app/routes/ideas.py` | Self-reflection | **Yes** (gpt-5-mini) | Existing idea |
| 13 | `tests/test_analysis_integration.py` | Integration test | Mocked | All |
| 14 | — | Verification | — | — |

**Total new files:** 12 source + 8 test + 1 schema = 21 files
**Modified files:** 2 (app/main.py, app/routes/ideas.py)
**New dependencies:** None
**LLM cost per analysis:** ~$0.003 (one gpt-5-mini call)
