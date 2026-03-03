"""Tests for the sentiment agent (3-source aggregation)."""

from __future__ import annotations

import pytest

from src.analysis.models import AnalysisInput, AnalystSignal, IdeaData, NewsItem
from src.analysis.sentiment import run


@pytest.fixture
def bullish_sentiment_input() -> AnalysisInput:
    """Input with bullish ideas and positive news."""
    return AnalysisInput(
        ticker="BULL",
        ohlcv=[],
        ideas=[
            IdeaData(
                direction="long",
                confidence=0.9,
                labels=["earnings"],
                idea_text="Buy BULL",
                created_at="2026-03-01",
                author="user1",
            ),
            IdeaData(
                direction="long",
                confidence=0.8,
                labels=["technical"],
                idea_text="Strong setup",
                created_at="2026-02-28",
                author="user2",
            ),
            IdeaData(
                direction="bullish",
                confidence=0.7,
                labels=["value"],
                idea_text="Undervalued",
                created_at="2026-02-25",
                author="user3",
            ),
        ],
        news=[
            NewsItem(title="BULL beats earnings expectations", date="2026-03-01", sentiment_score=0.8),
            NewsItem(title="Analysts upgrade BULL to buy", date="2026-02-28", sentiment_score=0.6),
        ],
        portfolio_value=100000.0,
    )


@pytest.fixture
def bearish_sentiment_input() -> AnalysisInput:
    """Input with bearish ideas and negative news."""
    return AnalysisInput(
        ticker="BEAR",
        ohlcv=[],
        ideas=[
            IdeaData(
                direction="short",
                confidence=0.85,
                labels=["risk"],
                idea_text="Sell BEAR",
                created_at="2026-03-01",
                author="user1",
            ),
            IdeaData(
                direction="bearish",
                confidence=0.9,
                labels=["fundamental"],
                idea_text="Overvalued",
                created_at="2026-02-27",
                author="user2",
            ),
        ],
        news=[
            NewsItem(title="BEAR misses earnings, stock plunges", date="2026-03-01", sentiment_score=-0.7),
            NewsItem(title="Analysts downgrade BEAR after warning", date="2026-02-28", sentiment_score=-0.5),
        ],
        portfolio_value=100000.0,
    )


@pytest.mark.anyio
async def test_sentiment_bullish(bullish_sentiment_input: AnalysisInput) -> None:
    """Bullish ideas + positive news should produce bullish signal."""
    result = await run(bullish_sentiment_input)
    assert isinstance(result, AnalystSignal)
    assert result.agent_id == "sentiment"
    assert result.signal == "bullish"
    assert result.confidence > 0.3


@pytest.mark.anyio
async def test_sentiment_bearish(bearish_sentiment_input: AnalysisInput) -> None:
    """Bearish ideas + negative news should produce bearish signal."""
    result = await run(bearish_sentiment_input)
    assert isinstance(result, AnalystSignal)
    assert result.agent_id == "sentiment"
    assert result.signal == "bearish"
    assert result.confidence > 0.3


@pytest.mark.anyio
async def test_sentiment_no_data() -> None:
    """No ideas or news should return neutral with zero confidence."""
    inp = AnalysisInput(ticker="EMPTY", ohlcv=[], ideas=[], news=[], portfolio_value=50000.0)
    result = await run(inp)
    assert result.agent_id == "sentiment"
    assert result.signal == "neutral"
    assert result.confidence == 0.0


@pytest.mark.anyio
async def test_sentiment_news_only() -> None:
    """News-only input should still produce a signal from the news source."""
    inp = AnalysisInput(
        ticker="NEWS",
        ohlcv=[],
        ideas=[],
        news=[
            NewsItem(title="Record gains for NEWS stock", date="2026-03-01", sentiment_score=0.9),
            NewsItem(title="Strong growth exceeds expectations", date="2026-02-28"),
        ],
        portfolio_value=50000.0,
    )
    result = await run(inp)
    assert result.agent_id == "sentiment"
    assert result.signal in ("bullish", "neutral")
    assert "news" in result.metrics


@pytest.mark.anyio
async def test_sentiment_metrics_structure(bullish_sentiment_input: AnalysisInput) -> None:
    """Metrics should contain all 3 source keys with expected sub-fields."""
    result = await run(bullish_sentiment_input)
    expected_sources = {"discord_ideas", "discord_sentiment", "news"}
    assert expected_sources.issubset(result.metrics.keys())

    ideas_metrics = result.metrics["discord_ideas"]
    assert "idea_count" in ideas_metrics
    assert "bullish_pct" in ideas_metrics
    assert "avg_confidence" in ideas_metrics
