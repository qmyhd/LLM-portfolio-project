"""Consensus aggregator — deterministic scoring + LLM narrative.

The only component that calls an LLM. Combines agent signals via
weighted scoring, then generates a 2-3 sentence summary via OpenAI.

Cost: ~$0.001-0.003 per analysis (one gpt-5-mini call).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from openai import OpenAI

from src.analysis.models import AnalystSignal, ConsensusReport
from src.config import settings

logger = logging.getLogger(__name__)

# Agent weights for signal aggregation
AGENT_WEIGHTS: dict[str, float] = {
    "technical": 0.25,
    "fundamental": 0.20,
    "valuation": 0.25,
    "sentiment": 0.15,
    "risk": 0.15,
}

SIGNAL_MAP: dict[str, float] = {
    "bullish": 1.0,
    "neutral": 0.0,
    "bearish": -1.0,
}


def compute_deterministic_score(signals: list[AnalystSignal]) -> tuple[float, str]:
    """Compute bull_bear_score and 5-tier verdict from agent signals.

    Score = sum(signal_numeric * weight * confidence) / sum(weight * confidence)

    Verdict thresholds:
    - > 0.4: strong_buy
    - > 0.15: buy
    - > -0.15: hold
    - > -0.4: sell
    - else: strong_sell

    Returns:
        (bull_bear_score, verdict)
    """
    total_weighted = 0.0
    total_weight = 0.0

    for sig in signals:
        weight = AGENT_WEIGHTS.get(sig.agent_id, 0.10)
        numeric = SIGNAL_MAP.get(sig.signal, 0.0)
        total_weighted += numeric * weight * sig.confidence
        total_weight += weight * sig.confidence

    if total_weight == 0:
        return 0.0, "hold"

    score = total_weighted / total_weight
    score = max(-1.0, min(1.0, score))

    if score > 0.4:
        verdict = "strong_buy"
    elif score > 0.15:
        verdict = "buy"
    elif score > -0.15:
        verdict = "hold"
    elif score > -0.4:
        verdict = "sell"
    else:
        verdict = "strong_sell"

    return score, verdict


def _should_escalate(signals: list[AnalystSignal]) -> bool:
    """Determine if we should escalate to a more capable model.

    True if:
    - Max confidence spread > 0.6 (agents very different in certainty)
    - AND >= 3 different signal directions present
    """
    if len(signals) < 3:
        return False

    confidences = [s.confidence for s in signals]
    max_spread = max(confidences) - min(confidences)

    unique_signals = len(set(s.signal for s in signals))

    return max_spread > 0.6 and unique_signals >= 3


def _generate_narrative(
    ticker: str,
    signals: list[AnalystSignal],
    score: float,
    verdict: str,
) -> tuple[str, str]:
    """Generate LLM narrative summary.

    Returns (summary, model_used). Falls back to deterministic narrative on failure.
    """
    model = "gpt-5" if _should_escalate(signals) else "gpt-5-mini"

    # Build compact signal summary for prompt
    signal_lines = []
    for sig in signals:
        signal_lines.append(
            f"- {sig.agent_id}: {sig.signal} ({sig.confidence:.0%}) — {sig.reasoning}"
        )
    signal_text = "\n".join(signal_lines)

    system_prompt = (
        "You are a financial analyst summarizing a multi-agent stock analysis. "
        "Write a concise 2-3 sentence summary of the consensus view. "
        "Be specific about key factors. Do not use disclaimers or hedging language."
    )

    user_prompt = (
        f"Ticker: {ticker}\n"
        f"Overall: {verdict} (score: {score:+.2f})\n\n"
        f"Agent signals:\n{signal_text}\n\n"
        f"Write 2-3 sentences summarizing the consensus view."
    )

    try:
        api_key = settings().OPENAI_API_KEY
        if not api_key:
            raise ValueError("No OPENAI_API_KEY configured")

        client = OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=200,
            temperature=0.3,
        )
        summary = response.choices[0].message.content.strip()
        return summary, model
    except Exception:
        logger.warning("OpenAI narrative generation failed for %s, using fallback", ticker, exc_info=True)
        # Fallback: deterministic summary
        bull_agents = [s.agent_id for s in signals if s.signal == "bullish"]
        bear_agents = [s.agent_id for s in signals if s.signal == "bearish"]

        parts = []
        if bull_agents:
            parts.append(f"Bullish signals from {', '.join(bull_agents)}.")
        if bear_agents:
            parts.append(f"Bearish signals from {', '.join(bear_agents)}.")
        if not parts:
            parts.append("Mixed signals across all agents.")

        fallback_summary = f"{ticker} consensus: {verdict}. " + " ".join(parts)
        return fallback_summary[:500], f"{model}-fallback"


async def run(
    ticker: str,
    signals: list[AnalystSignal],
    data_sources: list[str],
) -> ConsensusReport:
    """Run consensus aggregation: deterministic scoring + LLM narrative.

    Args:
        ticker: Stock ticker symbol
        signals: List of AnalystSignal from all agents
        data_sources: List of data sources used

    Returns:
        ConsensusReport with overall signal, score, and narrative
    """
    score, verdict = compute_deterministic_score(signals)
    summary, model_used = _generate_narrative(ticker, signals, score, verdict)

    # Overall confidence: average of agent confidences weighted by agent weights
    total_conf_weighted = 0.0
    total_weight = 0.0
    for sig in signals:
        weight = AGENT_WEIGHTS.get(sig.agent_id, 0.10)
        total_conf_weighted += sig.confidence * weight
        total_weight += weight
    overall_confidence = total_conf_weighted / total_weight if total_weight > 0 else 0.0

    return ConsensusReport(
        ticker=ticker,
        overall_signal=verdict,
        overall_confidence=overall_confidence,
        bull_bear_score=score,
        agent_signals=signals,
        summary=summary,
        data_sources=data_sources,
        computed_at=datetime.now(tz=timezone.utc),
        model_used=model_used,
    )
