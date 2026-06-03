"""Tests for credibility weighting in the Discord-ideas sentiment source."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.analysis.credibility import CredibilityResult
from src.analysis.models import AnalysisInput, IdeaData
from src.analysis.sentiment import _score_discord_ideas, run

# Always-recent date so ideas stay inside the 30-day scoring window regardless
# of when the suite runs (avoids time-bomb flakiness).
RECENT = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")


def _idea(direction, conf, author_id, created=RECENT):
    return IdeaData(direction=direction, confidence=conf, labels=[], idea_text="x",
                    created_at=created, author="a", author_id=author_id)


class _Resolver:
    """Stub resolver: author_id -> CredibilityResult (default neutral)."""
    def __init__(self, table):
        self.table = table

    def multiplier(self, author_id):
        return self.table.get(author_id, CredibilityResult(multiplier=1.0))


def test_neutral_resolver_matches_baseline():
    ideas = [_idea("long", 0.8, "1"), _idea("short", 0.6, "2")]
    sig_n, conf_n, m_n = _score_discord_ideas(ideas, symbol="AAPL", resolver=None)
    sig_r, conf_r, m_r = _score_discord_ideas(ideas, symbol="AAPL", resolver=_Resolver({}))
    assert m_r["credibility"]["delta"] == 0.0
    assert m_r["credibility"]["adjusted_score"] == m_r["credibility"]["baseline_score"]
    assert (sig_r, round(conf_r, 6)) == (sig_n, round(conf_n, 6))
    assert m_r["weighted_score"] == m_n["weighted_score"]
    assert m_r["credibility"]["contributors"] == []


def test_high_cred_bullish_moves_adjusted_up():
    ideas = [_idea("long", 0.8, "1"), _idea("short", 0.8, "2")]
    res = _Resolver({"1": CredibilityResult(multiplier=1.35, person_id=7, person_name="A", tiers={"markets": "S"})})
    _, _, m = _score_discord_ideas(ideas, symbol="AAPL", resolver=res)
    assert m["credibility"]["adjusted_score"] > m["credibility"]["baseline_score"]
    assert m["credibility"]["delta"] > 0
    assert any(c["author_id"] == "1" for c in m["credibility"]["contributors"])


def test_high_cred_bearish_moves_adjusted_down():
    ideas = [_idea("long", 0.8, "1"), _idea("short", 0.8, "2")]
    res = _Resolver({"2": CredibilityResult(multiplier=1.35, person_id=9, person_name="B", tiers={"markets": "S"})})
    _, _, m = _score_discord_ideas(ideas, symbol="AAPL", resolver=res)
    assert m["credibility"]["adjusted_score"] < m["credibility"]["baseline_score"]
    assert m["credibility"]["delta"] < 0


def test_muted_author_dropped_from_adjusted():
    ideas = [_idea("long", 0.8, "1"), _idea("short", 0.9, "2")]
    res = _Resolver({"2": CredibilityResult(multiplier=0.0, muted_out=True, person_id=9, person_name="B")})
    sig, conf, m = _score_discord_ideas(ideas, symbol="AAPL", resolver=res)
    assert sig == "bullish"
    assert m["credibility"]["adjusted_score"] > 0.2


def test_all_muted_returns_neutral_zero_conf():
    ideas = [_idea("long", 0.8, "1"), _idea("short", 0.9, "2")]
    res = _Resolver({
        "1": CredibilityResult(multiplier=0.0, muted_out=True, person_id=7),
        "2": CredibilityResult(multiplier=0.0, muted_out=True, person_id=9),
    })
    sig, conf, m = _score_discord_ideas(ideas, symbol="AAPL", resolver=res)
    assert sig == "neutral" and conf == 0.0
    assert m["credibility"]["adjusted_score"] == 0.0


def test_metrics_credibility_shape():
    ideas = [_idea("long", 0.8, "1")]
    _, _, m = _score_discord_ideas(ideas, symbol="AAPL", resolver=_Resolver({}))
    cred = m["credibility"]
    assert {"baseline_score", "adjusted_score", "delta", "contributors"}.issubset(cred.keys())


@pytest.mark.anyio
async def test_run_calls_for_ideas_with_ticker_and_author_ids():
    from unittest.mock import MagicMock, patch
    ideas = [_idea("long", 0.8, "111"), _idea("bullish", 0.7, "222")]
    inp = AnalysisInput(ticker="LMT", ohlcv=[], ideas=ideas, news=[], portfolio_value=0.0)
    fake = MagicMock()
    fake.multiplier.return_value = CredibilityResult(multiplier=1.0)
    with patch("src.analysis.sentiment.CredibilityResolver.for_ideas", return_value=fake) as for_ideas:
        result = await run(inp)
    for_ideas.assert_called_once_with("LMT", ["111", "222"])
    assert "credibility" in result.metrics["discord_ideas"]


@pytest.mark.anyio
async def test_run_resolver_failure_falls_back_to_neutral():
    from unittest.mock import patch
    ideas = [_idea("long", 0.8, "111")]
    inp = AnalysisInput(ticker="LMT", ohlcv=[], ideas=ideas, news=[], portfolio_value=0.0)
    with patch("src.analysis.sentiment.CredibilityResolver.for_ideas", side_effect=RuntimeError("boom")):
        result = await run(inp)  # must NOT raise
    assert result.metrics["discord_ideas"]["credibility"]["delta"] == 0.0


@pytest.mark.anyio
async def test_run_without_author_ids_skips_resolver():
    from unittest.mock import patch
    # ideas with NO author_id -> resolver must not even be built (no DB touch).
    ideas = [_idea("long", 0.8, "")]
    inp = AnalysisInput(ticker="LMT", ohlcv=[], ideas=ideas, news=[], portfolio_value=0.0)
    with patch("src.analysis.sentiment.CredibilityResolver.for_ideas", side_effect=AssertionError("should not be called")):
        result = await run(inp)  # must NOT raise / must not call for_ideas
    assert "credibility" in result.metrics["discord_ideas"]


@pytest.mark.anyio
async def test_run_exposes_top_level_credibility():
    """Spec §7: the breakdown must be at top-level metrics["credibility"] for
    API/frontend consumers, mirrored from the discord_ideas source."""
    from unittest.mock import MagicMock, patch
    ideas = [_idea("long", 0.8, "111"), _idea("short", 0.6, "222")]
    inp = AnalysisInput(ticker="LMT", ohlcv=[], ideas=ideas, news=[], portfolio_value=0.0)
    fake = MagicMock()
    fake.multiplier.return_value = CredibilityResult(multiplier=1.0)
    with patch("src.analysis.sentiment.CredibilityResolver.for_ideas", return_value=fake):
        result = await run(inp)

    assert "credibility" in result.metrics
    cred = result.metrics["credibility"]
    assert {"baseline_score", "adjusted_score", "delta", "contributors"}.issubset(cred.keys())
    # Top-level mirror is the same payload as the source-level copy.
    assert cred == result.metrics["discord_ideas"]["credibility"]
    # discord_ideas weighted_score remains the adjusted Discord-ideas score.
    assert result.metrics["discord_ideas"]["weighted_score"] == cred["adjusted_score"]


@pytest.mark.anyio
async def test_run_top_level_credibility_present_even_with_no_ideas():
    """metrics["credibility"] must always exist for consumers, even with no ideas."""
    inp = AnalysisInput(ticker="LMT", ohlcv=[], ideas=[], news=[], portfolio_value=0.0)
    result = await run(inp)
    assert "credibility" in result.metrics
    assert result.metrics["credibility"]["delta"] == 0.0
