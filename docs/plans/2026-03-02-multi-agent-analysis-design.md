# Multi-Agent Stock Analysis System — Design Document

**Date**: 2026-03-02
**Status**: Approved
**Scope**: Backend (FastAPI + Python) — frontend integration endpoints only

## Overview

Add a 5-agent AI-powered stock analysis system that computes technical indicators, fundamental scores, DCF valuations, sentiment aggregation, and risk metrics — then synthesizes them into a consensus bull/bear report via LLM. Results are cached in PostgreSQL with configurable TTL.

## Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| LLM Provider | OpenAI (gpt-5-mini default, gpt-5 escalation) | Already configured; tiered routing matches NLP pipeline |
| Compute Model | On-demand + DB cache (4h equity, 1h crypto) | Best UX/cost balance; stale-while-revalidate |
| Risk Scope | Per-stock + portfolio-wide | Covers both stock detail and dashboard use cases |
| Agent Count | 5 focused + 1 consensus aggregator | Non-overlapping analysis dimensions, minimal LLM cost |
| Architecture | Plain modules + FastAPI routes | Simple, no new deps; LangGraph-ready interface contract |
| Data Sources | Existing only (Databento, OpenBB/FMP, Discord NLP, yfinance) | No new API subscriptions required |

## Agent Protocol

Every agent follows an identical contract for LangGraph future-proofing:

```python
async def run(input: AnalysisInput) -> AnalystSignal
```

### Shared Models (`src/analysis/models.py`)

```python
class AnalysisInput(BaseModel):
    ticker: str
    ohlcv: list[OHLCVBar]          # Databento via price_service
    fundamentals: dict | None       # OpenBB/FMP
    position: PositionData | None   # positions table
    ideas: list[IdeaData]           # discord_parsed_ideas
    news: list[NewsItem]            # OpenBB/FMP
    portfolio_value: float          # account_balances

class AnalystSignal(BaseModel):
    agent_id: str                   # "technical", "fundamental", etc.
    signal: Literal["bullish", "bearish", "neutral"]
    confidence: float               # 0.0 - 1.0
    reasoning: str                  # Max ~200 chars
    metrics: dict                   # Agent-specific computed values

class ConsensusReport(BaseModel):
    ticker: str
    overall_signal: Literal["strong_buy", "buy", "hold", "sell", "strong_sell"]
    overall_confidence: float
    bull_bear_score: float          # -1.0 to +1.0
    agent_signals: list[AnalystSignal]
    summary: str                    # LLM-generated narrative
    data_sources: list[str]         # Tracked per-report
    computed_at: datetime
    model_used: str

class PortfolioRiskReport(BaseModel):
    var_95_1d: float                # 1-day 95% VaR as % of portfolio
    var_95_5d: float                # 5-day 95% VaR
    concentration_hhi: float        # Herfindahl index (0-1)
    diversification_ratio: float
    correlation_matrix: dict        # {ticker: {ticker: corr}}
    top_risk_contributors: list[dict]
    sector_exposure: dict           # {sector: pct}
    computed_at: datetime
    data_sources: list[str]
```

## Agent Designs

### 1. Technical Agent (`src/analysis/technical.py`)

**LLM calls: None (pure math)**
**Data source: Databento OHLCV via `price_service.get_ohlcv()`**
**Adapted from: ai-hedge-fund `technicals.py`**

5 strategy categories with weighted aggregation:

| Strategy | Weight | Indicators |
|----------|--------|-----------|
| Trend Following | 0.25 | EMA(8), EMA(21), EMA(55), ADX(14) |
| Mean Reversion | 0.20 | Z-score vs 50d SMA, Bollinger(20,2), RSI(14), RSI(28) |
| Momentum | 0.25 | 1m/3m/6m price momentum, volume ratio |
| Volatility | 0.15 | Historical vol (21d), vol regime, vol z-score, ATR/price |
| Statistical Arb | 0.15 | Skewness, kurtosis, Hurst exponent |

Signal combination: Convert to numeric (-1/0/+1), weight × confidence, normalize. > 0.2 bullish, < -0.2 bearish.

Minimum data: ~126 trading days. Graceful degradation for shorter windows.

`metrics` output includes all indicator values for frontend rendering.

### 2. Fundamental Agent (`src/analysis/fundamental.py`)

**LLM calls: None (threshold scoring)**
**Data source: OpenBB/FMP via `openbb_service.get_fundamentals()`**
**Adapted from: ai-hedge-fund `fundamentals.py`**

4 scoring pillars (equal weight):

| Pillar | Metrics | Bullish Threshold |
|--------|---------|------------------|
| Profitability | ROE, net margin, operating margin | > 15%, > 20%, > 15% |
| Growth | Revenue, earnings, book value growth | Each > 10% |
| Financial Health | Current ratio, D/E, FCF/EPS | > 1.5, < 0.5, > 0.8 |
| Valuation | P/E, P/B, P/S | > 25, > 3, > 5 = bearish |

2+ of 3 metrics per pillar triggers direction. Graceful skip if metric is None.

### 3. Valuation Agent (`src/analysis/valuation.py`)

**LLM calls: None (financial math)**
**Data source: OpenBB/FMP fundamentals + Databento latest price**
**Adapted from: ai-hedge-fund `valuation.py` + dexter DCF skill**

4 valuation models:

| Model | Weight | Method |
|-------|--------|--------|
| Owner Earnings (Buffett) | 0.35 | net_income + depreciation - capex - wc_change, 5yr projection, 15% discount, 25% margin of safety |
| Enhanced DCF | 0.35 | 3-stage growth, WACC via CAPM, FCF quality adjustment, bear/base/bull scenarios (20/60/20) |
| EV/EBITDA Multiples | 0.20 | Median historical multiple × current EBITDA - net debt |
| Residual Income | 0.10 | Book value + PV of excess returns, 20% margin of safety |

Signal: Weighted gap > 15% = bullish (undervalued), < -15% = bearish (overvalued).

WACC calculation: Risk-free 4.5% + beta × 6% equity premium, debt cost from interest coverage. Floor 6%, cap 20%. Large-cap growth capped at 10%.

### 4. Sentiment Agent (`src/analysis/sentiment.py`)

**LLM calls: None (aggregation)**
**Data sources: Discord NLP (`discord_parsed_ideas`), Discord messages (vaderSentiment), OpenBB news**

3 sentiment sources:

| Source | Weight | Signal Extraction |
|--------|--------|------------------|
| Discord Ideas | 0.50 | Count directions (bullish/bearish/neutral/mixed), weight by confidence. 7d ideas weighted 2x vs 30d |
| Discord Sentiment | 0.20 | Aggregate vaderSentiment compound scores for ticker mentions |
| Company News | 0.30 | Headline sentiment classification (keyword-based, no LLM) |

`metrics` includes: idea_count, bullish_pct, avg_confidence, recent_trend, news_sentiment_score.

### 5. Risk Agent (`src/analysis/risk.py`)

**LLM calls: None (statistical)**
**Data source: Databento OHLCV + positions table + account_balances**
**Adapted from: ai-hedge-fund `risk_manager.py`**

Per-stock metrics:
- Annualized volatility (60d rolling std × √252)
- Volatility percentile (current vs 1yr history)
- Beta vs SPY (60d covariance/variance)
- Max drawdown (peak-to-trough over lookback)
- Correlation to portfolio (avg pairwise with top 10 holdings)
- Position size recommendation (volatility-adjusted × correlation multiplier)

Portfolio-wide metrics (`GET /portfolio/risk`):
- VaR 95% (1-day, 5-day) via historical simulation
- Concentration HHI (Herfindahl index)
- Correlation matrix (top 15 holdings)
- Marginal VaR contribution per position
- Diversification ratio (weighted individual vol / portfolio vol)
- Sector exposure (from yfinance company info)

### 6. Consensus Aggregator (`src/analysis/consensus.py`)

**LLM calls: 1 (gpt-5-mini, ~$0.003)**
**The only component that calls an LLM.**

Agent weights:

| Agent | Weight |
|-------|--------|
| Technical | 0.25 |
| Fundamental | 0.20 |
| Valuation | 0.25 |
| Sentiment | 0.15 |
| Risk | 0.15 |

Two-step process:
1. **Deterministic scoring**: Signals → numeric (-1/0/+1) × weight × confidence → bull_bear_score → 5-tier verdict
2. **LLM narrative**: gpt-5-mini generates 2-3 sentence summary from all agent signals/metrics

Model escalation: If agents heavily conflict (max_confidence_spread > 0.6 AND signal_disagreement >= 3), route to gpt-5.

## Orchestration (`src/analysis/orchestrator.py`)

```
Request → Cache check → [miss] → Assemble AnalysisInput (parallel data fetch)
  → Run 5 agents (asyncio.gather) → Consensus aggregator → Cache result → Return
```

Stale-while-revalidate: If cache exists but expired, return stale immediately and trigger background refresh via `asyncio.create_task()`.

## Caching

### stock_analysis_cache table

```sql
CREATE TABLE stock_analysis_cache (
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
CREATE INDEX idx_analysis_cache_expires ON stock_analysis_cache (expires_at);
```

### portfolio_risk_cache table

```sql
CREATE TABLE portfolio_risk_cache (
    portfolio_id TEXT NOT NULL DEFAULT 'default',
    result JSONB NOT NULL,
    computed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (portfolio_id)
);
```

TTL: Equities 4h, crypto 1h, portfolio risk 2h. Force refresh via `?refresh=true`.

## API Routes (`app/routes/analysis.py`)

```
GET  /stocks/{ticker}/analysis           → ConsensusReport
GET  /stocks/{ticker}/analysis/technical  → AnalystSignal (technical only)
GET  /stocks/{ticker}/analysis/risk       → AnalystSignal (per-stock risk)
GET  /portfolio/risk                      → PortfolioRiskReport
```

Query params: `?refresh=true` (bypass cache), `?agents=technical,sentiment` (subset).

## Self-Reflection Pattern (`app/routes/ideas.py` enhancement)

Upgrade `/ideas/{id}/refine` from single-pass to three-pass:
1. **Refine** (gpt-5-mini): Generate improved idea with structured fields
2. **Reflect** (gpt-5-mini): Critique — check for hallucinated targets, verify ticker, assess direction support
3. **Re-refine** (gpt-5-mini, only if issues found): Incorporate critique

Cost: ~$0.002 extra per refinement.

## File Structure

```
src/analysis/
  ├── __init__.py
  ├── models.py           # Shared Pydantic schemas
  ├── technical.py         # 5-strategy technical analysis
  ├── fundamental.py       # 4-pillar fundamental scoring
  ├── valuation.py         # 4-model DCF/valuation
  ├── sentiment.py         # Discord + news aggregation
  ├── risk.py              # Volatility, VaR, correlation
  ├── consensus.py         # LLM aggregator
  ├── orchestrator.py      # Data assembly, caching, dispatch
  └── indicators.py        # Shared math (EMA, RSI, MACD, etc.)

app/routes/
  ├── analysis.py          # New routes
  └── ideas.py             # Enhanced /refine
```

## Data Source Tracking

Every ConsensusReport includes `data_sources` listing exactly what contributed:
- "Databento OHLCV (126 days)" — technical, risk
- "OpenBB/FMP fundamentals" — fundamental, valuation
- "OpenBB/FMP news (N articles)" — sentiment
- "Discord NLP (N ideas, M messages)" — sentiment
- "Portfolio positions (N shares)" — risk
- "yfinance company info" — risk (sector), fundamental (fallback)

## Dependencies

No new external dependencies. Uses:
- `numpy` (already installed via pandas)
- `openai` (already installed)
- Existing services: `price_service`, `openbb_service`, `market_data_service`
- Existing DB: `execute_sql` with named `:param` placeholders

## LangGraph Migration Path

Each agent `run()` function has the signature `async def run(input: AnalysisInput) -> AnalystSignal`. To migrate:
1. Install `langgraph`
2. Define `AgentState(TypedDict)` containing `AnalysisInput` + `analyst_signals: dict`
3. Wrap each `run()` in a LangGraph node that reads input from state and writes signal to state
4. Replace `asyncio.gather` in orchestrator with LangGraph DAG
5. Agent logic stays identical — zero rewriting

## Cost Estimate

Per stock analysis: ~$0.001-0.003 (one gpt-5-mini call for consensus narrative)
Per idea refinement: ~$0.003-0.005 (2-3 gpt-5-mini calls for self-reflection)
Monthly estimate (assuming 50 analyses/day): ~$5-10/month
