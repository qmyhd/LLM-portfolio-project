"""Tests for src/analysis/models.py shared Pydantic models."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from src.analysis.models import (
    AnalysisInput,
    AnalystSignal,
    ConsensusReport,
    IdeaData,
    NewsItem,
    OHLCVBar,
    PortfolioRiskReport,
    PositionData,
)


# ---------------------------------------------------------------------------
# AnalystSignal
# ---------------------------------------------------------------------------

class TestAnalystSignal:
    """AnalystSignal validation and confidence clamping."""

    def test_valid_signal(self):
        sig = AnalystSignal(
            agent_id="technical",
            signal="bullish",
            confidence=0.85,
            reasoning="Strong uptrend on daily chart.",
        )
        assert sig.agent_id == "technical"
        assert sig.signal == "bullish"
        assert sig.confidence == 0.85
        assert sig.reasoning == "Strong uptrend on daily chart."
        assert sig.metrics == {}

    def test_confidence_clamped_above_one(self):
        sig = AnalystSignal(
            agent_id="fundamental",
            signal="bearish",
            confidence=1.5,
            reasoning="Overvalued.",
        )
        assert sig.confidence == 1.0

    def test_confidence_clamped_below_zero(self):
        sig = AnalystSignal(
            agent_id="sentiment",
            signal="neutral",
            confidence=-0.3,
            reasoning="Mixed signals.",
        )
        assert sig.confidence == 0.0

    def test_confidence_edge_values(self):
        sig_zero = AnalystSignal(agent_id="a", signal="neutral", confidence=0.0, reasoning="x")
        assert sig_zero.confidence == 0.0

        sig_one = AnalystSignal(agent_id="a", signal="bullish", confidence=1.0, reasoning="x")
        assert sig_one.confidence == 1.0

    def test_metrics_optional(self):
        sig = AnalystSignal(
            agent_id="tech",
            signal="bullish",
            confidence=0.7,
            reasoning="RSI low.",
            metrics={"rsi": 28.5, "macd_cross": True},
        )
        assert sig.metrics["rsi"] == 28.5
        assert sig.metrics["macd_cross"] is True

    def test_invalid_signal_literal(self):
        with pytest.raises(ValidationError):
            AnalystSignal(
                agent_id="x",
                signal="super_bullish",
                confidence=0.5,
                reasoning="nope",
            )


# ---------------------------------------------------------------------------
# ConsensusReport
# ---------------------------------------------------------------------------

class TestConsensusReport:
    """ConsensusReport required fields and structure."""

    @pytest.fixture()
    def sample_report(self) -> ConsensusReport:
        now = datetime.now(tz=timezone.utc)
        return ConsensusReport(
            ticker="AAPL",
            overall_signal="buy",
            overall_confidence=0.82,
            bull_bear_score=0.45,
            agent_signals=[
                AnalystSignal(agent_id="tech", signal="bullish", confidence=0.9, reasoning="Up"),
                AnalystSignal(agent_id="fund", signal="neutral", confidence=0.6, reasoning="Fair"),
            ],
            summary="Mostly bullish outlook.",
            data_sources=["ohlcv", "fundamentals"],
            computed_at=now,
            model_used="gpt-4o-mini",
        )

    def test_all_fields_present(self, sample_report: ConsensusReport):
        assert sample_report.ticker == "AAPL"
        assert sample_report.overall_signal == "buy"
        assert 0.0 <= sample_report.overall_confidence <= 1.0
        assert -1.0 <= sample_report.bull_bear_score <= 1.0
        assert len(sample_report.agent_signals) == 2
        assert sample_report.summary == "Mostly bullish outlook."
        assert sample_report.data_sources == ["ohlcv", "fundamentals"]
        assert isinstance(sample_report.computed_at, datetime)
        assert sample_report.model_used == "gpt-4o-mini"

    def test_overall_confidence_clamped(self):
        now = datetime.now(tz=timezone.utc)
        report = ConsensusReport(
            ticker="TSLA",
            overall_signal="strong_buy",
            overall_confidence=2.0,
            bull_bear_score=0.0,
            agent_signals=[],
            summary="s",
            data_sources=[],
            computed_at=now,
            model_used="m",
        )
        assert report.overall_confidence == 1.0

    def test_bull_bear_score_clamped(self):
        now = datetime.now(tz=timezone.utc)
        report = ConsensusReport(
            ticker="TSLA",
            overall_signal="strong_sell",
            overall_confidence=0.5,
            bull_bear_score=-5.0,
            agent_signals=[],
            summary="s",
            data_sources=[],
            computed_at=now,
            model_used="m",
        )
        assert report.bull_bear_score == -1.0

    def test_invalid_overall_signal(self):
        with pytest.raises(ValidationError):
            ConsensusReport(
                ticker="X",
                overall_signal="mega_buy",
                overall_confidence=0.5,
                bull_bear_score=0.0,
                agent_signals=[],
                summary="",
                data_sources=[],
                computed_at=datetime.now(tz=timezone.utc),
                model_used="m",
            )


# ---------------------------------------------------------------------------
# AnalysisInput
# ---------------------------------------------------------------------------

class TestAnalysisInput:
    """AnalysisInput with None/empty optionals."""

    def test_minimal_input(self):
        inp = AnalysisInput(ticker="MSFT")
        assert inp.ticker == "MSFT"
        assert inp.ohlcv == []
        assert inp.fundamentals is None
        assert inp.position is None
        assert inp.ideas == []
        assert inp.news == []
        assert inp.portfolio_value == 0.0

    def test_full_input(self):
        inp = AnalysisInput(
            ticker="GOOG",
            ohlcv=[OHLCVBar(date="2026-03-01", open=150.0, high=155.0, low=149.0, close=153.0, volume=1_000_000)],
            fundamentals={"pe_ratio": 22.5, "market_cap": 2e12},
            position=PositionData(
                quantity=100, avg_cost=140.0, current_price=153.0,
                market_value=15300.0, unrealized_pnl=1300.0, unrealized_pnl_pct=9.29,
            ),
            ideas=[
                IdeaData(
                    direction="long", confidence=0.8, labels=["earnings"],
                    idea_text="Buy before earnings.", created_at="2026-02-28", author="user1",
                ),
            ],
            news=[
                NewsItem(title="Google beats earnings", date="2026-03-01", source="Reuters", sentiment_score=0.7),
            ],
            portfolio_value=250_000.0,
        )
        assert len(inp.ohlcv) == 1
        assert inp.ohlcv[0].close == 153.0
        assert inp.fundamentals["pe_ratio"] == 22.5
        assert inp.position.quantity == 100
        assert len(inp.ideas) == 1
        assert inp.ideas[0].direction == "long"
        assert len(inp.news) == 1
        assert inp.news[0].sentiment_score == 0.7
        assert inp.portfolio_value == 250_000.0

    def test_news_item_defaults(self):
        item = NewsItem(title="Test", date="2026-01-01")
        assert item.text == ""
        assert item.source == ""
        assert item.sentiment_score is None


# ---------------------------------------------------------------------------
# PortfolioRiskReport
# ---------------------------------------------------------------------------

class TestPortfolioRiskReport:
    """PortfolioRiskReport validation."""

    def test_valid_report(self):
        now = datetime.now(tz=timezone.utc)
        report = PortfolioRiskReport(
            var_95_1d=1200.50,
            var_95_5d=2800.00,
            concentration_hhi=0.15,
            diversification_ratio=1.35,
            correlation_matrix={
                "AAPL": {"AAPL": 1.0, "MSFT": 0.72},
                "MSFT": {"AAPL": 0.72, "MSFT": 1.0},
            },
            top_risk_contributors=[
                {"ticker": "AAPL", "contribution_pct": 35.2},
                {"ticker": "MSFT", "contribution_pct": 22.1},
            ],
            sector_exposure={"Technology": 0.57, "Healthcare": 0.18},
            computed_at=now,
            data_sources=["ohlcv", "positions"],
        )
        assert report.var_95_1d == 1200.50
        assert report.var_95_5d == 2800.00
        assert report.concentration_hhi == 0.15
        assert report.diversification_ratio == 1.35
        assert "AAPL" in report.correlation_matrix
        assert len(report.top_risk_contributors) == 2
        assert report.sector_exposure["Technology"] == 0.57
        assert isinstance(report.computed_at, datetime)
        assert report.data_sources == ["ohlcv", "positions"]

    def test_empty_collections(self):
        now = datetime.now(tz=timezone.utc)
        report = PortfolioRiskReport(
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
        assert report.correlation_matrix == {}
        assert report.top_risk_contributors == []
        assert report.sector_exposure == {}
