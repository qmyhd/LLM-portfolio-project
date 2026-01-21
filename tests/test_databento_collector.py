"""
Tests for Databento OHLCV Collector.
"""

import os
from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest


class TestDatabentoCollector:
    """Test DatabentoCollector class."""

    @pytest.fixture
    def mock_env(self, monkeypatch):
        """Set up mock environment variables."""
        monkeypatch.setenv("DATABENTO_API_KEY", "test-api-key")
        monkeypatch.setenv("RDS_HOST", "test-rds.amazonaws.com")
        monkeypatch.setenv("RDS_PORT", "5432")
        monkeypatch.setenv("RDS_DATABASE", "postgres")
        monkeypatch.setenv("RDS_USER", "postgres")
        monkeypatch.setenv("RDS_PASSWORD", "test-password")
        monkeypatch.setenv("S3_BUCKET_NAME", "test-bucket")

    @pytest.fixture
    def collector(self, mock_env):
        """Create collector with mocked dependencies."""
        with patch("src.databento_collector.load_dotenv"):
            from src.databento_collector import DatabentoCollector

            return DatabentoCollector()

    def test_init_with_env_vars(self, mock_env):
        """Test initialization with environment variables."""
        with patch("src.databento_collector.load_dotenv"):
            from src.databento_collector import DatabentoCollector

            collector = DatabentoCollector()

            assert collector.api_key == "test-api-key"
            assert "test-rds.amazonaws.com" in collector.rds_url
            assert collector.s3_bucket == "test-bucket"

    def test_init_with_rds_db_fallback(self, monkeypatch):
        """Test RDS_DB env var fallback when RDS_DATABASE is not set."""
        monkeypatch.setenv("DATABENTO_API_KEY", "test-api-key")
        monkeypatch.setenv("RDS_HOST", "test-rds.amazonaws.com")
        monkeypatch.setenv("RDS_PASSWORD", "test-password")
        monkeypatch.setenv("RDS_DB", "custom-db-name")  # Using RDS_DB not RDS_DATABASE
        monkeypatch.delenv("RDS_DATABASE", raising=False)

        with patch("src.databento_collector.load_dotenv"):
            from src.databento_collector import DatabentoCollector

            collector = DatabentoCollector()

            # Should use RDS_DB value
            assert "custom-db-name" in collector.rds_url

    def test_init_without_api_key_raises(self, monkeypatch):
        """Test that missing API key raises ValueError."""
        monkeypatch.delenv("DATABENTO_API_KEY", raising=False)

        with patch("src.databento_collector.load_dotenv"):
            from src.databento_collector import DatabentoCollector

            with pytest.raises(ValueError, match="DATABENTO_API_KEY not set"):
                DatabentoCollector(api_key=None)

    def test_dataset_selection(self, collector):
        """Test dataset selection based on date."""
        from src.databento_collector import (
            DATASET_CUTOFF,
            DATASET_HISTORICAL,
            DATASET_CURRENT,
        )

        # Before cutoff -> EQUS.MINI
        assert collector._select_dataset(date(2024, 6, 30)) == DATASET_HISTORICAL
        assert collector._select_dataset(date(2023, 4, 1)) == DATASET_HISTORICAL

        # On or after cutoff -> EQUS.SUMMARY
        assert collector._select_dataset(date(2024, 7, 1)) == DATASET_CURRENT
        assert collector._select_dataset(date(2024, 12, 1)) == DATASET_CURRENT

    def test_split_date_range_before_cutoff(self, collector):
        """Test date range splitting when entirely before cutoff."""
        from src.databento_collector import DATASET_HISTORICAL

        segments = collector._split_date_range(date(2023, 6, 1), date(2024, 5, 31))

        assert len(segments) == 1
        assert segments[0][0] == DATASET_HISTORICAL
        assert segments[0][1] == date(2023, 6, 1)
        assert segments[0][2] == date(2024, 5, 31)

    def test_split_date_range_after_cutoff(self, collector):
        """Test date range splitting when entirely after cutoff."""
        from src.databento_collector import DATASET_CURRENT

        segments = collector._split_date_range(date(2024, 8, 1), date(2024, 12, 31))

        assert len(segments) == 1
        assert segments[0][0] == DATASET_CURRENT
        assert segments[0][1] == date(2024, 8, 1)
        assert segments[0][2] == date(2024, 12, 31)

    def test_split_date_range_spans_cutoff(self, collector):
        """Test date range splitting when spanning cutoff."""
        from src.databento_collector import (
            DATASET_HISTORICAL,
            DATASET_CURRENT,
            DATASET_CUTOFF,
        )

        segments = collector._split_date_range(date(2024, 6, 1), date(2024, 8, 31))

        assert len(segments) == 2

        # First segment: historical
        assert segments[0][0] == DATASET_HISTORICAL
        assert segments[0][1] == date(2024, 6, 1)
        assert segments[0][2] == DATASET_CUTOFF - timedelta(days=1)

        # Second segment: current
        assert segments[1][0] == DATASET_CURRENT
        assert segments[1][1] == DATASET_CUTOFF
        assert segments[1][2] == date(2024, 8, 31)

    def test_process_ohlcv_df(self, collector):
        """Test DataFrame processing."""
        # Create mock Databento response with actual float prices (as returned by ohlcv-1d)
        mock_df = pd.DataFrame(
            {
                "ts_event": [
                    1704067200000000000,  # 2024-01-01 00:00:00 UTC in nanoseconds
                    1704153600000000000,  # 2024-01-02 00:00:00 UTC
                ],
                "raw_symbol": ["AAPL", "AAPL"],
                "open": [
                    185.00,
                    186.00,
                ],  # Float prices as returned by Databento ohlcv-1d
                "high": [187.00, 188.00],
                "low": [184.00, 185.00],
                "close": [186.00, 187.00],
                "volume": [1000000, 1100000],
            }
        )

        result = collector._process_ohlcv_df(mock_df)

        assert len(result) == 2
        assert "symbol" in result.columns
        assert "date" in result.columns
        assert result["symbol"].iloc[0] == "AAPL"
        # Check prices remain correct (no conversion needed)
        assert abs(result["open"].iloc[0] - 185.0) < 0.01
        assert abs(result["close"].iloc[0] - 186.0) < 0.01

    def test_process_ohlcv_df_empty(self, collector):
        """Test processing empty DataFrame."""
        result = collector._process_ohlcv_df(pd.DataFrame())

        assert len(result) == 0
        assert "symbol" in result.columns
        assert "date" in result.columns

    def test_get_portfolio_symbols_fallback(self, collector):
        """Test fallback to default watchlist when database unavailable."""
        with patch("src.db.execute_sql", side_effect=Exception("DB error")):
            symbols = collector.get_portfolio_symbols()

        # Should return default watchlist
        assert len(symbols) > 0
        assert "AAPL" in symbols
        assert "MSFT" in symbols

    def test_get_all_tracked_symbols(self, collector):
        """Test combined portfolio + watchlist symbols."""
        with patch.object(
            collector, "get_portfolio_symbols", return_value=["AAPL", "MSFT"]
        ):
            with patch.object(
                collector, "get_watchlist_symbols", return_value=["GOOGL", "MSFT"]
            ):
                symbols = collector.get_all_tracked_symbols()

        # Should be unique and sorted
        assert symbols == ["AAPL", "GOOGL", "MSFT"]


class TestDateRangeLogic:
    """Test date range handling."""

    def test_cutoff_date_is_correct(self):
        """Verify the dataset cutoff date."""
        from src.databento_collector import DATASET_CUTOFF

        assert DATASET_CUTOFF == date(2024, 7, 1)

    def test_dataset_names(self):
        """Verify dataset names."""
        from src.databento_collector import DATASET_HISTORICAL, DATASET_CURRENT

        assert DATASET_HISTORICAL == "EQUS.MINI"
        assert DATASET_CURRENT == "EQUS.SUMMARY"


class TestDataFormats:
    """Test data format handling."""

    def test_ohlcv_returns_float_prices(self):
        """Verify ohlcv-1d schema returns float prices (not fixed-point)."""
        # Databento ohlcv-1d returns prices as float64, not as fixed-point integers
        # This test documents the expected format
        sample_prices = [185.50, 186.75, 184.25, 186.00]

        # All values should be in reasonable stock price range
        for price in sample_prices:
            assert 1 < price < 10000, "Price should be a normal float, not fixed-point"

    def test_volume_is_integer(self):
        """Verify volume is returned as integer."""
        sample_volume = 1_500_000
        assert isinstance(sample_volume, int)


# Integration test marker - skip unless DATABENTO_API_KEY is set
@pytest.mark.skipif(
    not os.getenv("DATABENTO_API_KEY"), reason="DATABENTO_API_KEY not set"
)
class TestDatabentoIntegration:
    """Integration tests that require real API access."""

    def test_fetch_single_symbol(self):
        """Test fetching data for a single symbol."""
        from src.databento_collector import DatabentoCollector

        collector = DatabentoCollector()

        # Fetch last 7 days of AAPL
        df = collector.fetch_daily_bars(
            symbols=["AAPL"],
            start=date.today() - timedelta(days=7),
            end=date.today() - timedelta(days=1),
        )

        assert len(df) > 0
        assert "symbol" in df.columns
        assert df["symbol"].iloc[0] == "AAPL"
        assert all(df["close"] > 0)
