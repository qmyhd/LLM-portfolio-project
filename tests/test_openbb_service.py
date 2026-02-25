"""
Tests for openbb_service.py -- OpenBB Platform SDK wrapper.

All tests mock the OpenBB SDK to avoid network calls and API key requirements.
"""

from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clear_caches():
    """Clear all TTL caches between tests."""
    from src.openbb_service import (
        _filings_cache,
        _filings_lock,
        _fundamentals_cache,
        _fundamentals_lock,
        _management_cache,
        _management_lock,
        _news_cache,
        _news_lock,
        _transcript_cache,
        _transcript_lock,
    )
    for cache, lock in [
        (_transcript_cache, _transcript_lock),
        (_management_cache, _management_lock),
        (_fundamentals_cache, _fundamentals_lock),
        (_filings_cache, _filings_lock),
        (_news_cache, _news_lock),
    ]:
        with lock:
            cache.clear()


def _reset_obb_singleton():
    """Reset the lazy-initialized obb singleton."""
    import src.openbb_service as mod
    mod._obb_instance = None


@pytest.fixture(autouse=True)
def clear_state():
    _clear_caches()
    _reset_obb_singleton()
    yield
    _clear_caches()
    _reset_obb_singleton()


# ---------------------------------------------------------------------------
# get_earnings_transcript
# ---------------------------------------------------------------------------

class TestGetEarningsTranscript:

    def test_returns_transcript_data(self):
        with patch("src.openbb_service._fetch_transcript") as mock_fetch:
            mock_fetch.return_value = [
                {
                    "date": "2024-01-25",
                    "content": "Good morning everyone...",
                    "quarter": 1,
                    "year": 2024,
                    "symbol": "AAPL",
                }
            ]
            from src.openbb_service import get_earnings_transcript
            result = get_earnings_transcript("AAPL", year=2024, quarter=1)

        assert result is not None
        assert len(result) == 1
        assert result[0]["symbol"] == "AAPL"
        assert "Good morning" in result[0]["content"]

    def test_returns_none_on_failure(self):
        with patch("src.openbb_service._fetch_transcript", side_effect=Exception("api error")):
            from src.openbb_service import get_earnings_transcript
            result = get_earnings_transcript("INVALID")
        assert result is None

    def test_returns_none_when_fetch_returns_none(self):
        with patch("src.openbb_service._fetch_transcript", return_value=None):
            from src.openbb_service import get_earnings_transcript
            result = get_earnings_transcript("AAPL", year=2024)
        assert result is None


# ---------------------------------------------------------------------------
# get_management
# ---------------------------------------------------------------------------

class TestGetManagement:

    def test_returns_executives(self):
        with patch("src.openbb_service._fetch_management") as mock_fetch:
            mock_fetch.return_value = [
                {
                    "name": "Tim Cook", "title": "CEO", "pay": 3000000,
                    "currency": "USD", "gender": "Male", "yearBorn": 1960,
                    "titleSince": "2011",
                },
            ]
            from src.openbb_service import get_management
            result = get_management("AAPL")

        assert result is not None
        assert result[0]["name"] == "Tim Cook"
        assert result[0]["title"] == "CEO"

    def test_returns_none_on_failure(self):
        with patch("src.openbb_service._fetch_management", side_effect=Exception("err")):
            from src.openbb_service import get_management
            result = get_management("AAPL")
        assert result is None


# ---------------------------------------------------------------------------
# get_fundamentals
# ---------------------------------------------------------------------------

class TestGetFundamentals:

    def test_returns_metrics(self):
        with patch("src.openbb_service._fetch_fundamentals") as mock_fetch:
            mock_fetch.return_value = {
                "marketCap": 3_000_000_000_000,
                "peRatio": 30.5,
                "epsActual": 6.42,
                "debtToEquity": 1.87,
                "returnOnEquity": 0.147,
                "currentRatio": 0.99,
            }
            from src.openbb_service import get_fundamentals
            result = get_fundamentals("AAPL")

        assert result is not None
        assert result["peRatio"] == 30.5
        assert result["marketCap"] == 3_000_000_000_000

    def test_returns_none_on_failure(self):
        with patch("src.openbb_service._fetch_fundamentals", side_effect=Exception("err")):
            from src.openbb_service import get_fundamentals
            result = get_fundamentals("AAPL")
        assert result is None


# ---------------------------------------------------------------------------
# get_filings
# ---------------------------------------------------------------------------

class TestGetFilings:

    def test_returns_filings_list(self):
        with patch("src.openbb_service._fetch_filings") as mock_fetch:
            mock_fetch.return_value = [
                {
                    "filingDate": "2024-10-26", "formType": "10-K",
                    "reportUrl": "https://sec.gov/...", "description": "Annual Report",
                },
            ]
            from src.openbb_service import get_filings
            result = get_filings("AAPL", form_type="10-K", limit=5)

        assert result is not None
        assert result[0]["formType"] == "10-K"

    def test_returns_none_on_failure(self):
        with patch("src.openbb_service._fetch_filings", side_effect=Exception("err")):
            from src.openbb_service import get_filings
            result = get_filings("AAPL")
        assert result is None


# ---------------------------------------------------------------------------
# get_company_news
# ---------------------------------------------------------------------------

class TestGetCompanyNews:

    def test_returns_articles(self):
        with patch("src.openbb_service._fetch_news") as mock_fetch:
            mock_fetch.return_value = [
                {
                    "date": "2024-02-08", "title": "Apple Announces...",
                    "text": "Apple Inc. today...", "url": "https://...",
                    "source": "Reuters", "images": [],
                },
            ]
            from src.openbb_service import get_company_news
            result = get_company_news("AAPL", limit=5)

        assert result is not None
        assert result[0]["title"] == "Apple Announces..."

    def test_returns_none_on_failure(self):
        with patch("src.openbb_service._fetch_news", side_effect=Exception("err")):
            from src.openbb_service import get_company_news
            result = get_company_news("AAPL")
        assert result is None


# ---------------------------------------------------------------------------
# Caching behaviour
# ---------------------------------------------------------------------------

class TestCaching:

    def test_second_call_uses_cache(self):
        call_count = 0

        def counting_fetch(symbol):
            nonlocal call_count
            call_count += 1
            return [{"name": "Test CEO", "title": "CEO", "pay": None,
                     "currency": "USD", "gender": None, "yearBorn": None,
                     "titleSince": None}]

        with patch("src.openbb_service._fetch_management", side_effect=counting_fetch):
            from src.openbb_service import get_management
            get_management("AAPL")
            get_management("AAPL")

        assert call_count == 1  # Second call served from cache

    def test_different_symbols_not_cached(self):
        call_count = 0

        def counting_fetch(symbol):
            nonlocal call_count
            call_count += 1
            return [{"name": f"CEO of {symbol}", "title": "CEO", "pay": None,
                     "currency": "USD", "gender": None, "yearBorn": None,
                     "titleSince": None}]

        with patch("src.openbb_service._fetch_management", side_effect=counting_fetch):
            from src.openbb_service import get_management
            get_management("AAPL")
            get_management("MSFT")

        assert call_count == 2  # Different symbols → separate cache entries


# ---------------------------------------------------------------------------
# is_available
# ---------------------------------------------------------------------------

class TestIsAvailable:

    def test_returns_false_when_not_installed(self):
        with patch("src.openbb_service._get_obb", return_value=None):
            from src.openbb_service import is_available
            assert is_available() is False

    def test_returns_true_when_installed(self):
        with patch("src.openbb_service._get_obb", return_value=object()):
            from src.openbb_service import is_available
            assert is_available() is True
