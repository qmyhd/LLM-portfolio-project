"""
Tests for symbol resolver and logo helper modules.
"""

import unittest
from unittest.mock import patch, MagicMock


class TestSymbolResolver(unittest.TestCase):
    """Tests for the symbol resolver module."""

    def test_resolve_symbol_direct_ticker(self):
        """Test that direct tickers pass through."""
        from src.bot.ui.symbol_resolver import resolve_symbol

        # Mock database to return no description
        with patch(
            "src.bot.ui.symbol_resolver._get_description_from_db", return_value=None
        ):
            with patch(
                "src.bot.ui.symbol_resolver._search_symbols_by_description",
                return_value=None,
            ):
                with patch(
                    "src.bot.ui.symbol_resolver._search_positions_by_symbol",
                    return_value=None,
                ):
                    ticker, desc = resolve_symbol("AAPL")
                    self.assertEqual(ticker, "AAPL")

    def test_resolve_symbol_from_alias_map(self):
        """Test that company names are resolved from ALIAS_MAP."""
        from src.bot.ui.symbol_resolver import resolve_symbol

        with patch(
            "src.bot.ui.symbol_resolver._get_description_from_db",
            return_value="NVIDIA Corporation",
        ):
            ticker, desc = resolve_symbol("nvidia")
            self.assertEqual(ticker, "NVDA")
            self.assertEqual(desc, "NVIDIA Corporation")

    def test_resolve_symbol_from_alias_tesla(self):
        """Test Tesla alias resolution."""
        from src.bot.ui.symbol_resolver import resolve_symbol

        with patch(
            "src.bot.ui.symbol_resolver._get_description_from_db",
            return_value="Tesla Inc",
        ):
            ticker, desc = resolve_symbol("tesla")
            self.assertEqual(ticker, "TSLA")

    def test_resolve_symbol_uppercase_handling(self):
        """Test that lowercase input becomes uppercase."""
        from src.bot.ui.symbol_resolver import resolve_symbol

        with patch(
            "src.bot.ui.symbol_resolver._get_description_from_db", return_value=None
        ):
            with patch(
                "src.bot.ui.symbol_resolver._search_symbols_by_description",
                return_value=None,
            ):
                with patch(
                    "src.bot.ui.symbol_resolver._search_positions_by_symbol",
                    return_value=None,
                ):
                    ticker, _ = resolve_symbol("msft")
                    # Either resolves via ALIAS_MAP to MSFT or uppercases to MSFT
                    self.assertEqual(ticker, "MSFT")

    def test_resolve_empty_input(self):
        """Test empty input handling."""
        from src.bot.ui.symbol_resolver import resolve_symbol

        ticker, desc = resolve_symbol("")
        self.assertEqual(ticker, "")
        self.assertIsNone(desc)

    def test_get_symbol_info_returns_dict(self):
        """Test get_symbol_info returns proper dict structure."""
        from src.bot.ui.symbol_resolver import get_symbol_info

        with patch("src.db.execute_sql", return_value=None):
            info = get_symbol_info("AAPL")
            self.assertIn("ticker", info)
            self.assertIn("description", info)
            self.assertIn("logo_url", info)
            self.assertIn("exchange", info)
            self.assertIn("asset_type", info)


class TestLogoHelper(unittest.TestCase):
    """Tests for the logo helper module."""

    def setUp(self):
        """Clear logo cache before each test."""
        from src.bot.ui.logo_helper import clear_logo_cache

        clear_logo_cache()

    def test_get_logo_url_empty_symbol(self):
        """Test that empty symbol returns None."""
        from src.bot.ui.logo_helper import get_logo_url

        result = get_logo_url("")
        self.assertIsNone(result)

    def test_get_logo_url_with_db_cache(self):
        """Test that cached URL from database is returned."""
        from src.bot.ui.logo_helper import get_logo_url, clear_logo_cache

        # Clear cache
        clear_logo_cache()

        # Mock database returning a cached URL
        mock_url = "https://example.com/logo.png"
        with patch(
            "src.bot.ui.logo_helper._get_cached_logo_from_db", return_value=mock_url
        ):
            result = get_logo_url("AAPL")
            self.assertEqual(result, mock_url)

    def test_get_logo_url_uses_memory_cache(self):
        """Test that memory cache is used for repeated calls."""
        from src.bot.ui.logo_helper import get_logo_url, _logo_cache

        # Pre-populate cache with a CacheEntry
        _logo_cache.set("TEST", "https://cached.example.com/logo.png", provider="test")

        # Should not hit database
        with patch("src.bot.ui.logo_helper._get_cached_logo_from_db") as mock_db:
            result = get_logo_url("TEST", use_cache=True)
            self.assertEqual(result, "https://cached.example.com/logo.png")
            mock_db.assert_not_called()

    def test_clear_logo_cache(self):
        """Test cache clearing."""
        from src.bot.ui.logo_helper import (
            clear_logo_cache,
            _logo_cache,
            get_cache_stats,
        )

        _logo_cache.set("TEST", "something", provider="test")
        clear_logo_cache()

        stats = get_cache_stats()
        self.assertEqual(stats["total"], 0)

    def test_prefetch_logos_returns_dict(self):
        """Test prefetch_logos returns a dict."""
        from src.bot.ui.logo_helper import prefetch_logos

        with patch(
            "src.bot.ui.logo_helper.get_logo_url",
            return_value="https://example.com/logo.png",
        ):
            result = prefetch_logos(["AAPL", "MSFT"])
            self.assertIsInstance(result, dict)
            self.assertIn("AAPL", result)
            self.assertIn("MSFT", result)

    def test_ttl_cache_expiration(self):
        """Test that TTL cache entries expire correctly."""
        import time
        from src.bot.ui.logo_helper import TTLLogoCache

        # Create cache with 1 second TTL for testing
        test_cache = TTLLogoCache(ttl_seconds=1)
        test_cache.set("TEST", "value", provider="test")

        # Should be valid immediately - get() returns (value, hit)
        value, hit = test_cache.get("TEST")
        self.assertTrue(hit)
        self.assertEqual(value, "value")

        # Wait for expiration
        time.sleep(1.5)

        # Should be None after TTL
        value, hit = test_cache.get("TEST")
        self.assertFalse(hit)
        self.assertIsNone(value)

    def test_ttl_cache_none_caching(self):
        """Test that None values are cached (negative lookups)."""
        from src.bot.ui.logo_helper import TTLLogoCache

        test_cache = TTLLogoCache(ttl_seconds=3600)
        test_cache.set("NOSYMBOL", None, provider="none")

        # get() returns tuple (value, hit)
        value, hit = test_cache.get("NOSYMBOL")
        self.assertTrue(hit)  # Cache hit
        self.assertIsNone(value)  # But value is None

    def test_get_cache_stats(self):
        """Test cache statistics reporting."""
        from src.bot.ui.logo_helper import (
            _logo_cache,
            get_cache_stats,
            clear_logo_cache,
        )

        clear_logo_cache()

        # Add some entries
        _logo_cache.set("AAPL", "https://logo.dev/aapl.png", provider="logo_dev")
        _logo_cache.set("MSFT", "https://logokit.com/msft.png", provider="logokit")
        _logo_cache.set("BADTICKER", None, provider="none")

        stats = get_cache_stats()
        self.assertEqual(stats["total"], 3)
        self.assertEqual(stats["valid"], 2)  # AAPL and MSFT have valid URLs
        self.assertEqual(stats["failed"], 1)  # BADTICKER is None

    def test_fetch_from_logo_dev_success(self):
        """Test Logo.dev API success path."""
        from src.bot.ui.logo_helper import _fetch_from_logo_dev

        # Mock successful Logo.dev response with proper headers.get() behavior
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = MagicMock()
        mock_response.headers.get.return_value = "image/png"

        with patch("src.bot.ui.logo_helper.requests.get", return_value=mock_response):
            with patch.dict("os.environ", {"LOGO_DEV_API_KEY": "pk_test_key"}):
                url = _fetch_from_logo_dev("AAPL")
                self.assertIsNotNone(url)
                assert url is not None  # Type narrowing for mypy/pylance
                self.assertIn("logo.dev", url)

    def test_fetch_from_logo_dev_no_api_key(self):
        """Test Logo.dev returns None without API key."""
        from src.bot.ui.logo_helper import _fetch_from_logo_dev

        with patch.dict("os.environ", {"LOGO_DEV_API_KEY": ""}, clear=True):
            url = _fetch_from_logo_dev("AAPL")
            self.assertIsNone(url)

    def test_fetch_from_logokit_fallback(self):
        """Test Logokit fallback API."""
        from src.bot.ui.logo_helper import _fetch_from_logokit

        # Mock successful Logokit response with proper headers.get() behavior
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = MagicMock()
        mock_response.headers.get.return_value = "image/png"

        with patch("src.bot.ui.logo_helper.requests.get", return_value=mock_response):
            with patch.dict("os.environ", {"LOGOKIT_API_KEY": "pk_test_key"}):
                url = _fetch_from_logokit("AAPL")
                self.assertIsNotNone(url)
                assert url is not None  # Type narrowing for mypy/pylance
                self.assertIn("logokit", url)


class TestAliasMapIntegration(unittest.TestCase):
    """Test that ALIAS_MAP is correctly used for symbol resolution."""

    def test_common_aliases_exist(self):
        """Test that common company aliases are in ALIAS_MAP."""
        from src.nlp.preclean import ALIAS_MAP

        # Check key aliases exist
        self.assertEqual(ALIAS_MAP.get("nvidia"), "NVDA")
        self.assertEqual(ALIAS_MAP.get("tesla"), "TSLA")
        self.assertEqual(ALIAS_MAP.get("apple"), "AAPL")
        self.assertEqual(ALIAS_MAP.get("microsoft"), "MSFT")
        self.assertEqual(ALIAS_MAP.get("google"), "GOOGL")
        self.assertEqual(ALIAS_MAP.get("amazon"), "AMZN")

    def test_subsidiary_aliases(self):
        """Test subsidiary aliases resolve correctly."""
        from src.nlp.preclean import ALIAS_MAP

        # Subsidiaries should map to parent
        self.assertEqual(ALIAS_MAP.get("waymo"), "GOOGL")
        self.assertEqual(ALIAS_MAP.get("youtube"), "GOOGL")
        self.assertEqual(ALIAS_MAP.get("instagram"), "META")
        self.assertEqual(ALIAS_MAP.get("whatsapp"), "META")

    def test_lowercase_ticker_aliases(self):
        """Test that lowercase tickers are in ALIAS_MAP."""
        from src.nlp.preclean import ALIAS_MAP

        # Common lowercase ticker usage
        self.assertEqual(ALIAS_MAP.get("nvda"), "NVDA")
        self.assertEqual(ALIAS_MAP.get("aapl"), "AAPL")
        self.assertEqual(ALIAS_MAP.get("msft"), "MSFT")


if __name__ == "__main__":
    unittest.main()
