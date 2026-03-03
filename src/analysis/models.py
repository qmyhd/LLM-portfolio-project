"""Shared Pydantic models for the multi-agent analysis protocol."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Sub-models for AnalysisInput
# ---------------------------------------------------------------------------


class OHLCVBar(BaseModel):
    """Single OHLCV bar (daily)."""

    date: str
    open: float
    high: float
    low: float
    close: float
    volume: float


class PositionData(BaseModel):
    """Current portfolio position for a ticker."""

    quantity: float
    avg_cost: float
    current_price: float
    market_value: float
    unrealized_pnl: float
    unrealized_pnl_pct: float


class IdeaData(BaseModel):
    """A parsed trading idea from Discord or user input."""

    direction: str
    confidence: float
    labels: list[str]
    idea_text: str
    created_at: str
    author: str


class NewsItem(BaseModel):
    """A news article or headline with optional sentiment."""

    title: str
    text: str = ""
    date: str
    source: str = ""
    sentiment_score: float | None = None


# ---------------------------------------------------------------------------
# AnalysisInput — data bundle passed to every analyst agent
# ---------------------------------------------------------------------------


class AnalysisInput(BaseModel):
    """Aggregated input data for analyst agents."""

    ticker: str
    ohlcv: list[OHLCVBar] = Field(default_factory=list)
    fundamentals: dict[str, Any] | None = None
    position: PositionData | None = None
    ideas: list[IdeaData] = Field(default_factory=list)
    news: list[NewsItem] = Field(default_factory=list)
    portfolio_value: float = 0.0


# ---------------------------------------------------------------------------
# AnalystSignal — output from a single analyst agent
# ---------------------------------------------------------------------------


class AnalystSignal(BaseModel):
    """Signal produced by a single analyst agent."""

    agent_id: str
    signal: Literal["bullish", "bearish", "neutral"]
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str
    metrics: dict[str, Any] = Field(default_factory=dict)

    @field_validator("confidence", mode="before")
    @classmethod
    def clamp_confidence(cls, v: float) -> float:
        return max(0.0, min(1.0, float(v)))


# ---------------------------------------------------------------------------
# ConsensusReport — synthesised output from the orchestrator
# ---------------------------------------------------------------------------


class ConsensusReport(BaseModel):
    """Final consensus report aggregating all analyst signals."""

    ticker: str
    overall_signal: Literal["strong_buy", "buy", "hold", "sell", "strong_sell"]
    overall_confidence: float
    bull_bear_score: float
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
    def clamp_bull_bear_score(cls, v: float) -> float:
        return max(-1.0, min(1.0, float(v)))


# ---------------------------------------------------------------------------
# PortfolioRiskReport — portfolio-level risk metrics
# ---------------------------------------------------------------------------


class PortfolioRiskReport(BaseModel):
    """Portfolio-wide risk analysis report."""

    var_95_1d: float
    var_95_5d: float
    concentration_hhi: float
    diversification_ratio: float
    correlation_matrix: dict[str, dict[str, float]]
    top_risk_contributors: list[dict[str, Any]]
    sector_exposure: dict[str, float]
    computed_at: datetime
    data_sources: list[str]
