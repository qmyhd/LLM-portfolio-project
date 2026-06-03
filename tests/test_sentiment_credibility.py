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
