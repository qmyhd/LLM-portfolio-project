"""
Tests for market_data_service.py — yfinance wrapper.

All tests mock yfinance to avoid network calls.
"""

import threading
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clear_caches():
    """Clear all TTL caches between tests to avoid cross-test pollution."""
    from src.market_data_service import (
        _company_cache,
        _company_lock,
        _quote_cache,
        _quote_lock,
        _returns_cache,
        _returns_lock,
        _search_cache,
        _search_lock,
    )
    with _company_lock:
        _company_cache.clear()
    with _quote_lock:
        _quote_cache.clear()
    with _returns_lock:
        _returns_cache.clear()
    with _search_lock:
        _search_cache.clear()


@pytest.fixture(autouse=True)
def clear_caches():
    _clear_caches()
    yield
    _clear_caches()


# ---------------------------------------------------------------------------
# get_company_info
# ---------------------------------------------------------------------------

class TestGetCompanyInfo:

    @patch("src.market_data_service.yf", create=True)
    def test_returns_company_data(self, mock_yf):
        mock_ticker = MagicMock()
        mock_ticker.info = {
            "shortName": "Apple Inc.",
            "sector": "Technology",
            "industry": "Consumer Electronics",
            "marketCap": 3_000_000_000_000,
            "regularMarketPrice": 185.50,
        }
        mock_yf.Ticker.return_value = mock_ticker

        # Patch at the import site used inside the function
        with patch("src.market_data_service._fetch_company_info") as mock_fetch:
            mock_fetch.return_value = {
                "name": "Apple Inc.",
                "sector": "Technology",
                "industry": "Consumer Electronics",
                "marketCap": 3_000_000_000_000,
            }
            from src.market_data_service import get_company_info

            result = get_company_info("AAPL")

        assert result is not None
        assert result["name"] == "Apple Inc."
        assert result["sector"] == "Technology"

    def test_returns_none_on_exception(self):
        with patch("src.market_data_service._fetch_company_info", side_effect=Exception("boom")):
            from src.market_data_service import get_company_info

            result = get_company_info("INVALID")
        assert result is None


# ---------------------------------------------------------------------------
# get_realtime_quote
# ---------------------------------------------------------------------------

class TestGetRealtimeQuote:

    def test_calculates_day_change(self):
        with patch("src.market_data_service._fetch_realtime_quote") as mock_fetch:
            mock_fetch.return_value = {
                "price": 185.50,
                "previousClose": 183.00,
                "dayChange": 2.50,
                "dayChangePct": 1.3661,
            }
            from src.market_data_service import get_realtime_quote

            result = get_realtime_quote("AAPL")

        assert result is not None
        assert result["price"] == 185.50
        assert result["previousClose"] == 183.00
        assert result["dayChange"] == 2.50
        assert abs(result["dayChangePct"] - 1.37) < 0.1

    def test_returns_none_on_failure(self):
        with patch("src.market_data_service._fetch_realtime_quote", side_effect=Exception("net err")):
            from src.market_data_service import get_realtime_quote

            result = get_realtime_quote("AAPL")
        assert result is None


# ---------------------------------------------------------------------------
# get_realtime_quotes_batch
# ---------------------------------------------------------------------------

class TestGetRealtimeQuotesBatch:

    def test_empty_list(self):
        from src.market_data_service import get_realtime_quotes_batch

        assert get_realtime_quotes_batch([]) == {}

    def test_returns_batch_results(self):
        with patch("src.market_data_service._fetch_quotes_batch") as mock_batch:
            mock_batch.return_value = {
                "AAPL": {"price": 185.0, "previousClose": 183.0, "dayChange": 2.0, "dayChangePct": 1.09},
                "MSFT": {"price": 420.0, "previousClose": 418.0, "dayChange": 2.0, "dayChangePct": 0.48},
            }
            from src.market_data_service import get_realtime_quotes_batch

            result = get_realtime_quotes_batch(["AAPL", "MSFT"])

        assert "AAPL" in result
        assert "MSFT" in result
        assert result["AAPL"]["price"] == 185.0

    def test_falls_back_to_individual_on_batch_failure(self):
        with (
            patch("src.market_data_service._fetch_quotes_batch", side_effect=Exception("batch fail")),
            patch("src.market_data_service._fetch_realtime_quote") as mock_single,
        ):
            mock_single.return_value = {
                "price": 185.0,
                "previousClose": 183.0,
                "dayChange": 2.0,
                "dayChangePct": 1.09,
            }
            from src.market_data_service import get_realtime_quotes_batch

            result = get_realtime_quotes_batch(["AAPL"])

        assert "AAPL" in result


# ---------------------------------------------------------------------------
# get_return_metrics
# ---------------------------------------------------------------------------

class TestGetReturnMetrics:

    def test_returns_metrics(self):
        with patch("src.market_data_service._fetch_return_metrics") as mock_fetch:
            mock_fetch.return_value = {
                "return1w": 2.5,
                "return1m": 5.1,
                "return3m": 12.3,
                "return1y": 35.7,
                "volatility30d": 22.4,
                "volatility90d": 20.1,
            }
            from src.market_data_service import get_return_metrics

            result = get_return_metrics("AAPL")

        assert result is not None
        assert result["return1w"] == 2.5
        assert result["volatility30d"] == 22.4

    def test_returns_none_on_failure(self):
        with patch("src.market_data_service._fetch_return_metrics", side_effect=Exception("err")):
            from src.market_data_service import get_return_metrics

            result = get_return_metrics("AAPL")
        assert result is None


# ---------------------------------------------------------------------------
# search_symbols
# ---------------------------------------------------------------------------

class TestSearchSymbols:

    def test_returns_results(self):
        with patch("src.market_data_service._fetch_search_results") as mock_fetch:
            mock_fetch.return_value = [
                {"symbol": "AAPL", "name": "Apple Inc.", "type": "stock"},
                {"symbol": "AAPLX", "name": "Something Else", "type": "stock"},
            ]
            from src.market_data_service import search_symbols

            result = search_symbols("AAPL")

        assert len(result) == 2
        assert result[0]["symbol"] == "AAPL"

    def test_empty_query(self):
        from src.market_data_service import search_symbols

        assert search_symbols("") == []
        assert search_symbols("  ") == []

    def test_returns_empty_on_failure(self):
        with patch("src.market_data_service._fetch_search_results", side_effect=Exception("err")):
            from src.market_data_service import search_symbols

            result = search_symbols("test")
        assert result == []


# ---------------------------------------------------------------------------
# Caching behaviour
# ---------------------------------------------------------------------------

class TestCaching:

    def test_second_call_uses_cache(self):
        call_count = 0

        def counting_fetch(symbol):
            nonlocal call_count
            call_count += 1
            return {"name": "Test", "sector": "", "industry": "", "marketCap": 0}

        with patch("src.market_data_service._fetch_company_info", side_effect=counting_fetch):
            from src.market_data_service import get_company_info

            get_company_info("AAPL")
            get_company_info("AAPL")

        assert call_count == 1  # Second call served from cache


# ---------------------------------------------------------------------------
# Crypto symbol normalisation
# ---------------------------------------------------------------------------

class TestCryptoNormalisation:

    def test_crypto_gets_usd_suffix(self):
        from src.market_data_service import _yf_symbol

        assert _yf_symbol("XRP") == "XRP-USD"
        assert _yf_symbol("BTC") == "BTC-USD"
        assert _yf_symbol("AAPL") == "AAPL"


# ---------------------------------------------------------------------------
# is_available
# ---------------------------------------------------------------------------

class TestIsAvailable:

    def test_true_when_importable(self):
        from src.market_data_service import is_available

        assert is_available() is True
