"""Sentiment agent — 3-source sentiment aggregation.

Entirely deterministic (no LLM calls). Aggregates sentiment from
Discord ideas, Discord message sentiment, and company news.

Data sources: discord_parsed_ideas, Discord messages (vaderSentiment), OpenBB news
"""

from __future__ import annotations

from datetime import datetime, timezone

from src.analysis.models import AnalysisInput, AnalystSignal, IdeaData, NewsItem


# Source weights
SOURCE_WEIGHTS: dict[str, float] = {
    "discord_ideas": 0.50,
    "discord_sentiment": 0.20,
    "news": 0.30,
}

# Simple keyword lists for news headline sentiment
_BULLISH_KEYWORDS = frozenset({
    "beat", "beats", "surge", "surges", "rally", "rallies", "soar", "soars",
    "upgrade", "upgraded", "outperform", "buy", "bullish", "record", "high",
    "growth", "strong", "profit", "gains", "positive", "exceeds", "exceeded",
})

_BEARISH_KEYWORDS = frozenset({
    "miss", "misses", "plunge", "plunges", "crash", "crashes", "tank", "tanks",
    "downgrade", "downgraded", "underperform", "sell", "bearish", "low",
    "decline", "weak", "loss", "losses", "negative", "fails", "failed", "warning",
    "layoff", "layoffs", "cut", "cuts", "recall",
})


def _parse_idea_date(date_str: str) -> datetime | None:
    """Parse idea date string to datetime. Returns None on failure."""
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            dt = datetime.strptime(date_str, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    return None


def _score_discord_ideas(ideas: list[IdeaData]) -> tuple[str, float, dict]:
    """Score sentiment from Discord parsed ideas.

    Recent ideas (<7d) get 2x weight. Direction mapping:
    - long/bullish -> +1
    - short/bearish -> -1
    - neutral/mixed -> 0
    """
    if not ideas:
        return "neutral", 0.0, {"idea_count": 0}

    now = datetime.now(tz=timezone.utc)
    direction_map = {"long": 1.0, "bullish": 1.0, "short": -1.0, "bearish": -1.0}

    weighted_sum = 0.0
    total_weight = 0.0
    bullish_count = 0
    bearish_count = 0

    for idea in ideas:
        # Time weighting: recent ideas get 2x weight
        time_weight = 1.0
        parsed_date = _parse_idea_date(idea.created_at)
        if parsed_date is not None:
            days_old = (now - parsed_date).days
            if days_old <= 7:
                time_weight = 2.0
            elif days_old > 30:
                continue  # Skip ideas older than 30 days

        direction_score = direction_map.get(idea.direction.lower(), 0.0)
        confidence = max(0.0, min(idea.confidence, 1.0))

        weighted_sum += direction_score * confidence * time_weight
        total_weight += confidence * time_weight

        if direction_score > 0:
            bullish_count += 1
        elif direction_score < 0:
            bearish_count += 1

    if total_weight == 0:
        return "neutral", 0.0, {"idea_count": len(ideas), "bullish_count": 0, "bearish_count": 0}

    score = weighted_sum / total_weight  # -1 to +1

    if score > 0.2:
        signal = "bullish"
    elif score < -0.2:
        signal = "bearish"
    else:
        signal = "neutral"

    confidence = min(abs(score), 1.0)

    total_ideas = len(ideas)
    metrics = {
        "idea_count": total_ideas,
        "bullish_count": bullish_count,
        "bearish_count": bearish_count,
        "bullish_pct": round(bullish_count / total_ideas * 100, 1) if total_ideas > 0 else 0.0,
        "avg_confidence": round(sum(i.confidence for i in ideas) / total_ideas, 3) if total_ideas > 0 else 0.0,
        "weighted_score": round(score, 4),
    }
    return signal, confidence, metrics


def _score_discord_sentiment(ideas: list[IdeaData]) -> tuple[str, float, dict]:
    """Proxy for Discord message sentiment using idea confidence and direction.

    In production this would use vaderSentiment on raw messages.
    For now, derive a sentiment score from idea text patterns.
    """
    if not ideas:
        return "neutral", 0.0, {"message_count": 0, "compound_score": 0.0}

    # Simple proxy: use idea direction + confidence as sentiment
    scores = []
    for idea in ideas:
        direction_map = {"long": 0.5, "bullish": 0.5, "short": -0.5, "bearish": -0.5}
        base_score = direction_map.get(idea.direction.lower(), 0.0)
        scores.append(base_score * idea.confidence)

    avg_score = sum(scores) / len(scores) if scores else 0.0

    if avg_score > 0.1:
        signal = "bullish"
    elif avg_score < -0.1:
        signal = "bearish"
    else:
        signal = "neutral"

    confidence = min(abs(avg_score) * 2, 1.0)

    return signal, confidence, {"message_count": len(ideas), "compound_score": round(avg_score, 4)}


def _classify_headline(title: str) -> float:
    """Simple keyword-based headline sentiment. Returns -1 to +1."""
    words = set(title.lower().split())
    bull = len(words & _BULLISH_KEYWORDS)
    bear = len(words & _BEARISH_KEYWORDS)
    if bull + bear == 0:
        return 0.0
    return (bull - bear) / (bull + bear)


def _score_news(news: list[NewsItem]) -> tuple[str, float, dict]:
    """Score sentiment from company news headlines."""
    if not news:
        return "neutral", 0.0, {"article_count": 0, "avg_sentiment": 0.0}

    scores = []
    for item in news:
        if item.sentiment_score is not None:
            scores.append(item.sentiment_score)
        else:
            scores.append(_classify_headline(item.title))

    avg_score = sum(scores) / len(scores) if scores else 0.0

    if avg_score > 0.2:
        signal = "bullish"
    elif avg_score < -0.2:
        signal = "bearish"
    else:
        signal = "neutral"

    confidence = min(abs(avg_score), 1.0)

    return signal, confidence, {"article_count": len(news), "avg_sentiment": round(avg_score, 4)}


async def run(input: AnalysisInput) -> AnalystSignal:
    """Run sentiment analysis across 3 sources.

    Deterministic — no LLM or network calls.
    """
    SIGNAL_MAP = {"bullish": 1.0, "neutral": 0.0, "bearish": -1.0}

    sources: dict[str, tuple[str, float, dict]] = {}
    sources["discord_ideas"] = _score_discord_ideas(input.ideas)
    sources["discord_sentiment"] = _score_discord_sentiment(input.ideas)
    sources["news"] = _score_news(input.news)

    # Weighted combination
    total_weighted_signal = 0.0
    total_weight = 0.0

    for name, (signal, confidence, _) in sources.items():
        weight = SOURCE_WEIGHTS[name]
        if confidence > 0:
            total_weighted_signal += SIGNAL_MAP[signal] * weight * confidence
            total_weight += weight * confidence

    if total_weight == 0:
        overall_signal = "neutral"
        overall_confidence = 0.0
    else:
        normalized = total_weighted_signal / total_weight
        if normalized > 0.2:
            overall_signal = "bullish"
        elif normalized < -0.2:
            overall_signal = "bearish"
        else:
            overall_signal = "neutral"
        overall_confidence = min(abs(normalized), 1.0)

    # Collect all metrics
    all_metrics: dict = {}
    for name, (sig, conf, metrics) in sources.items():
        all_metrics[name] = {"signal": sig, "confidence": conf, **metrics}

    parts = [f"{name}={sig}({conf:.0%})" for name, (sig, conf, _) in sources.items()]
    reasoning = f"{overall_signal} ({overall_confidence:.0%}): " + ", ".join(parts)

    return AnalystSignal(
        agent_id="sentiment",
        signal=overall_signal,
        confidence=overall_confidence,
        reasoning=reasoning[:200],
        metrics=all_metrics,
    )
