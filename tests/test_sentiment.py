"""Tests for per-ticker sentiment isolation.

Verifies that sentiment summary returns different results for different tickers.
"""

import asyncio
from unittest.mock import patch, MagicMock


def _make_summary_row(total, bull, bear, neut, first_at=None, last_at=None):
    """Create a mock DB row for sentiment summary query."""
    row = MagicMock()
    row._mapping = {
        "total": total,
        "bull": bull,
        "bear": bear,
        "neut": neut,
        "first_at": first_at,
        "last_at": last_at,
    }
    return row


def test_sentiment_summary_per_ticker_isolation():
    """NVDA and MSFT sentiment should be computed independently."""
    from app.routes.sentiment import get_sentiment_summary

    def mock_execute_sql(query, params=None, fetch_results=False):
        symbol = (params or {}).get("symbol", "")
        if symbol == "NVDA":
            return [_make_summary_row(10, 7, 1, 2)]
        elif symbol == "MSFT":
            return [_make_summary_row(5, 1, 3, 1)]
        return [_make_summary_row(0, 0, 0, 0)]

    with patch("app.routes.sentiment.execute_sql", side_effect=mock_execute_sql):
        nvda = asyncio.run(get_sentiment_summary(ticker="NVDA", window="30d"))
        msft = asyncio.run(get_sentiment_summary(ticker="MSFT", window="30d"))

    # Different tickers
    assert nvda.ticker == "NVDA"
    assert msft.ticker == "MSFT"

    # Different totals
    assert nvda.totalMentions == 10
    assert msft.totalMentions == 5
    assert nvda.totalMentions != msft.totalMentions

    # NVDA is mostly bullish (7/10 = 70%)
    assert nvda.bullishPct == 70.0
    assert nvda.bearishPct == 10.0

    # MSFT is mostly bearish (3/5 = 60%)
    assert msft.bearishPct == 60.0
    assert msft.bullishPct == 20.0

    # Percentages are different
    assert nvda.bullishPct != msft.bullishPct


def test_sentiment_summary_empty_ticker():
    """Unknown ticker should return zero mentions."""
    from app.routes.sentiment import get_sentiment_summary

    def mock_execute_sql(query, params=None, fetch_results=False):
        return [_make_summary_row(0, 0, 0, 0)]

    with patch("app.routes.sentiment.execute_sql", side_effect=mock_execute_sql):
        result = asyncio.run(get_sentiment_summary(ticker="ZZZZ", window="30d"))

    assert result.ticker == "ZZZZ"
    assert result.totalMentions == 0
    assert result.bullishPct is None
    assert result.bearishPct is None
