"""
Unit tests for SnapTradeCollector.resolve_account_id.

Covers:
- Explicit account_id passthrough
- Configured ROBINHOOD_ACCOUNT_ID validated against API
- Invalid config ID → deterministic auto-select (highest equity)
- Multiple accounts → highest equity wins (with alphabetical tiebreaker)
- API 401 → ConnectionError ("relink required")
- API 404/1011 → structured error
- Empty accounts → ValueError
- Caching of resolved account ID
- collect_all_data integration (accountIdUsed + authError)
"""

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest


def _make_collector(config_account_id: str = ""):
    """Build a SnapTradeCollector with mocked client + config."""
    with patch("src.snaptrade_collector.settings") as mock_settings:
        cfg = MagicMock()
        cfg.ROBINHOOD_ACCOUNT_ID = config_account_id
        cfg.robinhood_account_id = config_account_id
        cfg.SNAPTRADE_CLIENT_ID = "test-client"
        cfg.snaptrade_client_id = "test-client"
        cfg.SNAPTRADE_CONSUMER_KEY = "test-key"
        cfg.snaptrade_consumer_key = "test-key"
        cfg.SNAPTRADE_USER_ID = "test-user"
        cfg.snaptrade_user_id = "test-user"
        cfg.userid = "test-user"
        cfg.SNAPTRADE_USER_SECRET = "test-secret"
        cfg.snaptrade_user_secret = "test-secret"
        cfg.usersecret = "test-secret"
        cfg.SNAPTRADE_CLIENT_SECRET = ""
        cfg.snaptrade_client_secret = ""
        mock_settings.return_value = cfg

        from src.snaptrade_collector import SnapTradeCollector

        with patch.object(SnapTradeCollector, "_initialize_client"):
            collector = SnapTradeCollector()
            collector.client = MagicMock()
            collector._resolved_account_id = None
            return collector


def _accounts_df(accounts: list[dict]) -> pd.DataFrame:
    """Build a mock accounts DataFrame matching get_accounts() output."""
    return pd.DataFrame(accounts)


# -----------------------------------------------------------------------
# 1. Explicit account_id passthrough
# -----------------------------------------------------------------------

class TestExplicitAccountId:
    def test_explicit_id_returned_directly(self):
        collector = _make_collector(config_account_id="configured-123")
        result = collector.resolve_account_id(account_id="explicit-456")
        assert result == "explicit-456"

    def test_explicit_id_skips_api_call(self):
        collector = _make_collector()
        with patch.object(collector, "get_accounts") as mock_get:
            result = collector.resolve_account_id(account_id="explicit-789")
            mock_get.assert_not_called()
            assert result == "explicit-789"


# -----------------------------------------------------------------------
# 2. Configured ID validated against API
# -----------------------------------------------------------------------

class TestConfiguredAccountId:
    def test_valid_configured_id(self):
        collector = _make_collector(config_account_id="acc-A")
        df = _accounts_df([
            {"id": "acc-A", "total_equity": 50000, "institution_name": "Robinhood"},
            {"id": "acc-B", "total_equity": 100000, "institution_name": "Fidelity"},
        ])
        with patch.object(collector, "get_accounts", return_value=df):
            result = collector.resolve_account_id()
            # Should use configured ID even though acc-B has higher equity
            assert result == "acc-A"

    def test_invalid_configured_id_falls_to_discovery(self):
        collector = _make_collector(config_account_id="nonexistent-999")
        df = _accounts_df([
            {"id": "acc-X", "total_equity": 10000, "institution_name": "Schwab"},
            {"id": "acc-Y", "total_equity": 90000, "institution_name": "Fidelity"},
        ])
        with patch.object(collector, "get_accounts", return_value=df):
            result = collector.resolve_account_id()
            # Should auto-select by highest equity → acc-Y
            assert result == "acc-Y"


# -----------------------------------------------------------------------
# 3. Deterministic selection: highest equity wins
# -----------------------------------------------------------------------

class TestDeterministicSelection:
    def test_highest_equity_selected(self):
        collector = _make_collector(config_account_id="")
        df = _accounts_df([
            {"id": "acc-1", "total_equity": 5000, "institution_name": "Broker A"},
            {"id": "acc-2", "total_equity": 150000, "institution_name": "Broker B"},
            {"id": "acc-3", "total_equity": 25000, "institution_name": "Broker C"},
        ])
        with patch.object(collector, "get_accounts", return_value=df):
            result = collector.resolve_account_id()
            assert result == "acc-2"

    def test_equity_tiebreaker_alphabetical_id(self):
        collector = _make_collector(config_account_id="")
        df = _accounts_df([
            {"id": "z-account", "total_equity": 50000, "institution_name": "Broker Z"},
            {"id": "a-account", "total_equity": 50000, "institution_name": "Broker A"},
        ])
        with patch.object(collector, "get_accounts", return_value=df):
            result = collector.resolve_account_id()
            # Same equity → alphabetical by id → "a-account"
            assert result == "a-account"

    def test_null_equity_treated_as_zero(self):
        collector = _make_collector(config_account_id="")
        df = _accounts_df([
            {"id": "acc-null", "total_equity": None, "institution_name": "Broker X"},
            {"id": "acc-small", "total_equity": 100, "institution_name": "Broker Y"},
        ])
        with patch.object(collector, "get_accounts", return_value=df):
            result = collector.resolve_account_id()
            # acc-null equity → 0, so acc-small (100) wins
            assert result == "acc-small"

    def test_single_account_auto_selected(self):
        collector = _make_collector(config_account_id="")
        df = _accounts_df([
            {"id": "only-account", "total_equity": 42000, "institution_name": "Solo"},
        ])
        with patch.object(collector, "get_accounts", return_value=df):
            result = collector.resolve_account_id()
            assert result == "only-account"


# -----------------------------------------------------------------------
# 4. API 401 → ConnectionError ("relink required")
# -----------------------------------------------------------------------

class TestAuthErrors:
    def test_401_raises_connection_error(self):
        collector = _make_collector(config_account_id="")
        with patch.object(
            collector, "get_accounts",
            side_effect=Exception("HTTP 401 Unauthorized"),
        ):
            with pytest.raises(ConnectionError, match="re-link brokerage"):
                collector.resolve_account_id()

    def test_1076_raises_connection_error(self):
        collector = _make_collector(config_account_id="")
        with patch.object(
            collector, "get_accounts",
            side_effect=Exception("Error code 1076: invalid user credentials"),
        ):
            with pytest.raises(ConnectionError, match="re-link brokerage"):
                collector.resolve_account_id()

    def test_401_with_configured_id_still_raises(self):
        """Auth errors should NOT silently fall back to configured ID."""
        collector = _make_collector(config_account_id="configured-id")
        with patch.object(
            collector, "get_accounts",
            side_effect=Exception("401 unauthorized"),
        ):
            with pytest.raises(ConnectionError, match="re-link brokerage"):
                collector.resolve_account_id()


# -----------------------------------------------------------------------
# 5. API errors (non-auth) → ValueError / fallback
# -----------------------------------------------------------------------

class TestApiErrors:
    def test_non_auth_error_with_configured_id_uses_fallback(self):
        collector = _make_collector(config_account_id="fallback-id")
        with patch.object(
            collector, "get_accounts",
            side_effect=Exception("HTTP 500 Internal Server Error"),
        ):
            result = collector.resolve_account_id()
            assert result == "fallback-id"

    def test_non_auth_error_without_configured_id_raises(self):
        collector = _make_collector(config_account_id="")
        with patch.object(
            collector, "get_accounts",
            side_effect=Exception("HTTP 500 Internal Server Error"),
        ):
            with pytest.raises(ValueError, match="cannot fetch accounts"):
                collector.resolve_account_id()

    def test_empty_accounts_with_no_config_raises(self):
        collector = _make_collector(config_account_id="")
        with patch.object(collector, "get_accounts", return_value=pd.DataFrame()):
            with pytest.raises(ValueError, match="No accounts found"):
                collector.resolve_account_id()


# -----------------------------------------------------------------------
# 6. Caching
# -----------------------------------------------------------------------

class TestCaching:
    def test_resolved_id_is_cached(self):
        collector = _make_collector(config_account_id="")
        df = _accounts_df([
            {"id": "cached-account", "total_equity": 10000, "institution_name": "Broker"},
        ])
        with patch.object(collector, "get_accounts", return_value=df) as mock_get:
            first = collector.resolve_account_id()
            second = collector.resolve_account_id()
            assert first == second == "cached-account"
            # get_accounts called only once (second call uses cache)
            mock_get.assert_called_once()


# -----------------------------------------------------------------------
# 7. collect_all_data integration: accountIdUsed + authError
# -----------------------------------------------------------------------

class TestCollectAllDataIntegration:
    def test_auth_error_surfaces_in_results(self):
        collector = _make_collector(config_account_id="")
        # get_accounts is called twice: once in collect_all_data for initial fetch,
        # once inside resolve_account_id. Mock both.
        call_count = 0

        def _side_effect():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # First call in collect_all_data: returns empty accounts
                return pd.DataFrame()
            # Second call in resolve_account_id: auth error
            raise Exception("401 unauthorized")

        with patch.object(collector, "get_accounts", side_effect=_side_effect):
            results = collector.collect_all_data(write_parquet=False)
            assert results["authError"] is True
            assert results["success"] is False
            assert any("re-link" in e for e in results["errors"])

    def test_successful_sync_includes_account_id_used(self):
        collector = _make_collector(config_account_id="my-account")
        accounts_df = _accounts_df([
            {"id": "my-account", "total_equity": 50000, "institution_name": "Test"},
        ])

        with patch.object(collector, "get_accounts", return_value=accounts_df), \
             patch.object(collector, "write_to_database"), \
             patch.object(collector, "get_balances", return_value=pd.DataFrame()), \
             patch.object(collector, "get_positions", return_value=pd.DataFrame()), \
             patch.object(collector, "get_orders", return_value=pd.DataFrame()), \
             patch.object(collector, "get_activities", return_value=pd.DataFrame()):
            results = collector.collect_all_data(write_parquet=False)
            assert results["accountIdUsed"] == "my-account"
            assert results["authError"] is False
            assert results["success"] is True
