"""Sentiment agent — 3-source sentiment aggregation.

Entirely deterministic (no LLM calls). Aggregates sentiment from
Discord ideas, Discord message sentiment, and company news.

Data sources: discord_parsed_ideas, Discord messages (vaderSentiment), OpenBB news
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from src.analysis.credibility import CredibilityResolver
from src.analysis.models import AnalysisInput, AnalystSignal, IdeaData, NewsItem

logger = logging.getLogger(__name__)


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


def _score_discord_ideas(
    ideas: list[IdeaData],
    symbol: str = "",
    resolver=None,
) -> tuple[str, float, dict]:
    """Score sentiment from Discord parsed ideas.

    Recent ideas (<7d) get 2x weight. Direction mapping:
    - long/bullish -> +1
    - short/bearish -> -1
    - neutral/mixed -> 0

    Credibility weighting (optional): when ``resolver`` is provided, each idea's
    weight is additionally scaled by its author's effective credibility
    multiplier for ``symbol`` (spec §5). A fully-muted author (multiplier 0.0)
    is dropped from the adjusted average entirely. ``resolver=None`` reproduces
    the legacy, credibility-free behaviour exactly. The returned signal and
    confidence use the credibility-ADJUSTED score; the unadjusted baseline is
    preserved under ``metrics["credibility"]`` for explainability.
    """
    now = datetime.now(tz=timezone.utc)
    direction_map = {"long": 1.0, "bullish": 1.0, "short": -1.0, "bearish": -1.0}

    base_num = 0.0  # baseline accumulators (all multipliers forced to 1.0)
    base_den = 0.0
    adj_num = 0.0  # credibility-adjusted accumulators
    adj_den = 0.0
    bullish_count = 0
    bearish_count = 0
    contributors: list[dict] = []

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
        base_w = confidence * time_weight

        # Baseline always accumulates with a neutral (1.0) credibility weight.
        base_num += direction_score * base_w
        base_den += base_w

        # Adjusted accumulates with the author's credibility multiplier.
        mult = 1.0
        if resolver is not None:
            res = resolver.multiplier(idea.author_id)
            mult = res.multiplier
            if res.person_id is not None and mult != 1.0:
                contributors.append({
                    "author_id": idea.author_id,
                    "person": res.person_name,
                    "tiers": res.tiers,
                    "effective_mult": round(mult, 4),
                })
        if mult != 0.0:
            adj_num += direction_score * base_w * mult
            adj_den += base_w * mult
        # mult == 0.0 (fully muted) -> idea dropped from the adjusted average

        if direction_score > 0:
            bullish_count += 1
        elif direction_score < 0:
            bearish_count += 1

    baseline_score = base_num / base_den if base_den > 0 else 0.0
    adjusted_score = adj_num / adj_den if adj_den > 0 else 0.0

    total_ideas = len(ideas)
    metrics = {
        "idea_count": total_ideas,
        "bullish_count": bullish_count,
        "bearish_count": bearish_count,
        "bullish_pct": round(bullish_count / total_ideas * 100, 1) if total_ideas > 0 else 0.0,
        "avg_confidence": round(sum(i.confidence for i in ideas) / total_ideas, 3) if total_ideas > 0 else 0.0,
        "weighted_score": round(adjusted_score, 4),
        "credibility": {
            "baseline_score": round(baseline_score, 4),
            "adjusted_score": round(adjusted_score, 4),
            "delta": round(adjusted_score - baseline_score, 4),
            "contributors": contributors[:5],
        },
    }

    # No surviving ideas (none in-window, or every author fully muted) -> no signal.
    if adj_den == 0:
        return "neutral", 0.0, metrics

    if adjusted_score > 0.2:
        signal = "bullish"
    elif adjusted_score < -0.2:
        signal = "bearish"
    else:
        signal = "neutral"
    confidence = min(abs(adjusted_score), 1.0)

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
