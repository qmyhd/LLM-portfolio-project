"""
Tests for symbol resolver and logo helper modules.
"""

import pytest
import time
from unittest.mock import patch, MagicMock


class TestSymbolResolver:
    """Tests for the symbol resolver module."""

    def test_resolve_symbol_direct_ticker(self):
        """Test that direct tickers pass through."""
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
                    ticker, _ = resolve_symbol("AAPL")
                    assert ticker == "AAPL"

    def test_resolve_symbol_from_alias_map(self):
        """Test that company names are resolved from ALIAS_MAP."""
        from src.bot.ui.symbol_resolver import resolve_symbol

        with patch(
            "src.bot.ui.symbol_resolver._get_description_from_db",
            return_value="NVIDIA Corporation",
        ):
            ticker, desc = resolve_symbol("nvidia")
            assert ticker == "NVDA"
            assert desc == "NVIDIA Corporation"

    def test_resolve_symbol_from_alias_tesla(self):
        """Test Tesla alias resolution."""
        from src.bot.ui.symbol_resolver import resolve_symbol

        with patch(
            "src.bot.ui.symbol_resolver._get_description_from_db",
            return_value="Tesla Inc",
        ):
            ticker, _ = resolve_symbol("tesla")
            assert ticker == "TSLA"

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
                    assert ticker == "MSFT"

    def test_resolve_empty_input(self):
        """Test empty input handling."""
        from src.bot.ui.symbol_resolver import resolve_symbol

        ticker, desc = resolve_symbol("")
        assert ticker == ""
        assert desc is None

    def test_get_symbol_info_returns_dict(self):
        """Test get_symbol_info returns proper dict structure."""
        from src.bot.ui.symbol_resolver import get_symbol_info

        with patch("src.db.execute_sql", return_value=None):
            info = get_symbol_info("AAPL")
            assert "ticker" in info
            assert "description" in info
            assert "logo_url" in info
            assert "exchange" in info
            assert "asset_type" in info


class TestLogoHelper:
    """Tests for the logo helper module."""

    def setup_method(self):
        """Clear logo cache before each test."""
        from src.bot.ui.logo_helper import clear_logo_cache

        clear_logo_cache()

    def test_get_logo_url_empty_symbol(self):
        """Test that empty symbol returns None."""
        from src.bot.ui.logo_helper import get_logo_url

        result = get_logo_url("")
        assert result is None

    def test_get_logo_url_with_db_cache(self):
        """Test that cached URL from database is returned."""
        from src.bot.ui.logo_helper import get_logo_url, clear_logo_cache

        clear_logo_cache()

        mock_url = "https://example.com/logo.png"
        with patch(
            "src.bot.ui.logo_helper._get_cached_logo_from_db", return_value=mock_url
        ):
            result = get_logo_url("AAPL")
            assert result == mock_url

    def test_get_logo_url_uses_memory_cache(self):
        """Test that memory cache is used for repeated calls."""
        from src.bot.ui.logo_helper import get_logo_url, _logo_cache

        _logo_cache.set("TEST", "https://cached.example.com/logo.png", provider="test")

        with patch("src.bot.ui.logo_helper._get_cached_logo_from_db") as mock_db:
            result = get_logo_url("TEST", use_cache=True)
            assert result == "https://cached.example.com/logo.png"
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
        assert stats["total"] == 0

    def test_prefetch_logos_returns_dict(self):
        """Test prefetch_logos returns a dict."""
        from src.bot.ui.logo_helper import prefetch_logos

        with patch(
            "src.bot.ui.logo_helper.get_logo_url",
            return_value="https://example.com/logo.png",
        ):
            result = prefetch_logos(["AAPL", "MSFT"])
            assert isinstance(result, dict)
            assert "AAPL" in result
            assert "MSFT" in result

    def test_ttl_cache_expiration(self):
        """Test that TTL cache entries expire correctly."""
        from src.bot.ui.logo_helper import TTLLogoCache

        test_cache = TTLLogoCache(ttl_seconds=1)
        test_cache.set("TEST", "value", provider="test")

        value, hit = test_cache.get("TEST")
        assert hit is True
        assert value == "value"

        time.sleep(1.5)

        value, hit = test_cache.get("TEST")
        assert hit is False
        assert value is None

    def test_ttl_cache_none_caching(self):
        """Test that None values are cached (negative lookups)."""
        from src.bot.ui.logo_helper import TTLLogoCache

        test_cache = TTLLogoCache(ttl_seconds=3600)
        test_cache.set("NOSYMBOL", None, provider="none")

        value, hit = test_cache.get("NOSYMBOL")
        assert hit is True
        assert value is None

    def test_get_cache_stats(self):
        """Test cache statistics reporting."""
        from src.bot.ui.logo_helper import (
            _logo_cache,
            get_cache_stats,
            clear_logo_cache,
        )

        clear_logo_cache()

        _logo_cache.set("AAPL", "https://logo.dev/aapl.png", provider="logo_dev")
        _logo_cache.set("MSFT", "https://logokit.com/msft.png", provider="logokit")
        _logo_cache.set("BADTICKER", None, provider="none")

        stats = get_cache_stats()
        assert stats["total"] == 3
        assert stats["valid"] == 2
        assert stats["failed"] == 1

    def test_fetch_from_logo_dev_success(self):
        """Test Logo.dev API success path."""
        from src.bot.ui.logo_helper import _fetch_from_logo_dev

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = MagicMock()
        mock_response.headers.get.return_value = "image/png"

        with patch("src.bot.ui.logo_helper.requests.get", return_value=mock_response):
            with patch.dict("os.environ", {"LOGO_DEV_API_KEY": "pk_test_key"}):
                url = _fetch_from_logo_dev("AAPL")
                assert url is not None
                assert "logo.dev" in url

    def test_fetch_from_logo_dev_no_api_key(self):
        """Test Logo.dev returns None without API key."""
        from src.bot.ui import logo_helper
        from src.bot.ui.logo_helper import _fetch_from_logo_dev

        # Patch module-level constant (already loaded from env at import time)
        with patch.object(logo_helper, "LOGO_DEV_API_KEY", ""):
            url = _fetch_from_logo_dev("AAPL")
            assert url is None

    def test_fetch_from_logokit_fallback(self):
        """Test Logokit fallback API."""
        from src.bot.ui.logo_helper import _fetch_from_logokit

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = MagicMock()
        mock_response.headers.get.return_value = "image/png"

        with patch("src.bot.ui.logo_helper.requests.get", return_value=mock_response):
            with patch.dict("os.environ", {"LOGOKIT_API_KEY": "pk_test_key"}):
                url = _fetch_from_logokit("AAPL")
                assert url is not None
                assert "logokit" in url
