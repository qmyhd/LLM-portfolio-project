"""
Databento OHLCV Data Collector

Fetches daily OHLCV bars from Databento Historical API.
Handles dataset switching: EQUS.MINI (pre-2024-07-01), EQUS.SUMMARY (current).

All data is stored in Supabase PostgreSQL (ohlcv_daily table) via upsert
keyed on (symbol, date).

Environment Variables:
    DATABENTO_API_KEY   - Required. Databento API key.
    DATABASE_URL        - Supabase PostgreSQL connection URL.
    REQUIRE_DATABENTO   - If '1' pipeline aborts on failure. Default '1' (critical).
"""

from __future__ import annotations

import logging
import os
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING

import pandas as pd
from dotenv import load_dotenv

from src.db import execute_sql
from src.retry_utils import hardened_retry

if TYPE_CHECKING:
    pass

# Load environment variables
load_dotenv()

logger = logging.getLogger(__name__)

# Pipeline resiliency: when True (default), Databento failures are fatal
REQUIRE_DATABENTO = os.environ.get("REQUIRE_DATABENTO", "1") == "1"

# Dataset cutoff date: EQUS.MINI ends 2024-06-30, EQUS.SUMMARY starts 2024-07-01
DATASET_CUTOFF = date(2024, 7, 1)
DATASET_HISTORICAL = "EQUS.MINI"
DATASET_CURRENT = "EQUS.SUMMARY"


class DatabentoCollector:
    """Collect OHLCV daily bars from Databento Historical API."""

    def __init__(
        self,
        api_key: str | None = None,
    ):
        """
        Initialize the collector.

        Args:
            api_key: Databento API key (defaults to DATABENTO_API_KEY env var)
        """
        self.api_key = api_key or os.getenv("DATABENTO_API_KEY")
        if not self.api_key:
            raise ValueError("DATABENTO_API_KEY not set")

        # Lazy-loaded Databento client
        self._db_client = None

    @property
    def db_client(self):
        """Lazy-load Databento client."""
        if self._db_client is None:
            try:
                import databento as db

                self._db_client = db.Historical(self.api_key)
            except ImportError:
                raise ImportError(
                    "databento package not installed. Run: pip install databento"
                )
        return self._db_client

    def get_portfolio_symbols(self) -> list[str]:
        """
        Get unique symbols from portfolio positions.

        Falls back to a default watchlist if database is unavailable.
        """
        try:
            from src.db import execute_sql

            # Get symbols from positions table
            result = execute_sql(
                "SELECT DISTINCT symbol FROM positions WHERE symbol IS NOT NULL",
                fetch_results=True,
            )

            if result:
                symbols = [row[0] for row in result if row[0]]
                logger.info(f"Retrieved {len(symbols)} symbols from portfolio")
                return sorted(set(symbols))
        except Exception as e:
            logger.warning(f"Could not fetch portfolio symbols: {e}")

        # Fallback watchlist
        default_symbols = ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA"]
        logger.info(f"Using default watchlist: {default_symbols}")
        return default_symbols

    def get_watchlist_symbols(self) -> list[str]:
        """
        Get additional symbols from watchlist.

        Can be extended to read from a config file or database table.
        """
        # TODO: Implement watchlist table or config file
        return []

    def get_all_tracked_symbols(self) -> list[str]:
        """Get combined portfolio + watchlist symbols."""
        portfolio = set(self.get_portfolio_symbols())
        watchlist = set(self.get_watchlist_symbols())
        return sorted(portfolio | watchlist)

    def _select_dataset(self, query_date: date) -> str:
        """
        Select appropriate Databento dataset based on date.

        Args:
            query_date: The date being queried

        Returns:
            Dataset name (EQUS.MINI or EQUS.SUMMARY)
        """
        if query_date < DATASET_CUTOFF:
            return DATASET_HISTORICAL
        return DATASET_CURRENT

    def _split_date_range(self, start: date, end: date) -> list[tuple[str, date, date]]:
        """
        Split date range into segments by dataset.

        Args:
            start: Start date (inclusive)
            end: End date (inclusive)

        Returns:
            List of (dataset, start, end) tuples
        """
        segments = []

        # If entirely before cutoff
        if end < DATASET_CUTOFF:
            segments.append((DATASET_HISTORICAL, start, end))
        # If entirely after cutoff
        elif start >= DATASET_CUTOFF:
            segments.append((DATASET_CURRENT, start, end))
        # Spans cutoff - split into two segments
        else:
            segments.append(
                (DATASET_HISTORICAL, start, DATASET_CUTOFF - timedelta(days=1))
            )
            segments.append((DATASET_CURRENT, DATASET_CUTOFF, end))

        return segments

    def _parse_available_end_from_error(self, error_msg: str) -> date | None:
        """
        Parse the available end date from Databento 422 error message.

        Error format contains something like:
        "data_end_after_available_end: ... available end is 2026-02-01T..."

        Args:
            error_msg: Error message from Databento

        Returns:
            Parsed date or None if parsing fails
        """
        import re

        # Try to extract ISO timestamp from error message
        # Look for patterns like "2026-02-01T" or "available end is 2026-02-01"
        patterns = [
            r"available[_ ]end[_ ]is[_ ](\d{4}-\d{2}-\d{2})",
            r"(\d{4}-\d{2}-\d{2})T\d{2}:\d{2}:\d{2}",
        ]

        for pattern in patterns:
            match = re.search(pattern, error_msg)
            if match:
                try:
                    return datetime.strptime(match.group(1), "%Y-%m-%d").date()
                except ValueError:
                    continue

        return None

    @hardened_retry(max_retries=3, delay=2)
    def _fetch_segment(
        self,
        dataset: str,
        symbols: list[str],
        start: date,
        end: date,
        _retry_with_clamped_end: bool = False,
    ) -> pd.DataFrame:
        """
        Fetch OHLCV data for a single dataset segment.

        Handles Databento 422 "data_end_after_available_end" errors by clamping
        the end date to the available data range and retrying once.

        Args:
            dataset: Databento dataset name
            symbols: List of ticker symbols
            start: Start date (inclusive)
            end: End date (inclusive)
            _retry_with_clamped_end: Internal flag to prevent infinite retry

        Returns:
            DataFrame with OHLCV data
        """
        logger.info(f"Fetching {dataset}: {len(symbols)} symbols from {start} to {end}")

        try:
            # Fetch data from Databento
            data = self.db_client.timeseries.get_range(
                dataset=dataset,
                schema="ohlcv-1d",
                symbols=symbols,
                start=start.isoformat(),
                end=(end + timedelta(days=1)).isoformat(),  # Databento end is exclusive
                stype_in="raw_symbol",
            )

            # Convert to DataFrame
            df = data.to_df()

            if df.empty:
                logger.warning(f"No data returned for {dataset} segment")
                return pd.DataFrame()

            # Process the DataFrame
            return self._process_ohlcv_df(df)

        except Exception as e:
            error_msg = str(e).lower()

            # Handle Databento 422: data_end_after_available_end
            # This happens when requesting data beyond what's available
            if (
                "data_end_after_available_end" in error_msg
                and not _retry_with_clamped_end
            ):
                logger.warning(
                    f"End date {end} is after available data, attempting to clamp..."
                )

                # Try to parse the available end date from the error message
                available_end = self._parse_available_end_from_error(str(e))

                if available_end:
                    # Clamp end date to available_end - 1 day (for safety)
                    clamped_end = available_end - timedelta(days=1)
                    logger.info(f"Clamping end date from {end} to {clamped_end}")

                    if clamped_end >= start:
                        # Retry with clamped end date (no retry decorator on this call)
                        return self._fetch_segment_inner(
                            dataset, symbols, start, clamped_end
                        )
                    else:
                        logger.warning(
                            f"Clamped end {clamped_end} is before start {start}, skipping segment"
                        )
                        return pd.DataFrame()
                else:
                    # Fall back to yesterday UTC as the end date
                    yesterday = date.today() - timedelta(days=1)
                    if yesterday >= start and yesterday < end:
                        logger.info(
                            f"Could not parse available end, falling back to yesterday: {yesterday}"
                        )
                        return self._fetch_segment_inner(
                            dataset, symbols, start, yesterday
                        )
                    else:
                        logger.error(f"Cannot clamp date range, original error: {e}")
                        return pd.DataFrame()

            logger.error(f"Error fetching {dataset}: {e}")
            raise

    def _fetch_segment_inner(
        self,
        dataset: str,
        symbols: list[str],
        start: date,
        end: date,
    ) -> pd.DataFrame:
        """
        Inner fetch method without retry decorator, used for clamped retries.

        Args:
            dataset: Databento dataset name
            symbols: List of ticker symbols
            start: Start date (inclusive)
            end: End date (inclusive)

        Returns:
            DataFrame with OHLCV data
        """
        logger.info(
            f"Retrying {dataset}: {len(symbols)} symbols from {start} to {end} (clamped)"
        )

        try:
            data = self.db_client.timeseries.get_range(
                dataset=dataset,
                schema="ohlcv-1d",
                symbols=symbols,
                start=start.isoformat(),
                end=(end + timedelta(days=1)).isoformat(),
                stype_in="raw_symbol",
            )

            df = data.to_df()

            if df.empty:
                logger.warning(f"No data returned for {dataset} segment (clamped)")
                return pd.DataFrame()

            return self._process_ohlcv_df(df)

        except Exception as e:
            logger.error(f"Error fetching {dataset} (clamped retry): {e}")
            return pd.DataFrame()

    def _process_ohlcv_df(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Process raw Databento DataFrame into our schema.

        Args:
            df: Raw DataFrame from Databento

        Returns:
            Processed DataFrame matching ohlcv_daily schema
        """
        if df.empty:
            return pd.DataFrame(
                columns=["symbol", "date", "open", "high", "low", "close", "volume"]
            )

        # Reset index if ts_event is the index
        if df.index.name == "ts_event":
            df = df.reset_index()

        # Price columns are already float64 in Databento ohlcv-1d schema
        # No conversion needed - values come as regular prices (e.g., 233.53)
        price_cols = ["open", "high", "low", "close"]
        for col in price_cols:
            if col in df.columns:
                df[col] = df[col].astype(float)

        # Extract date from timestamp (convert to Eastern Time)
        if "ts_event" in df.columns:
            # Databento timestamps are in nanoseconds UTC
            df["date"] = pd.to_datetime(df["ts_event"], unit="ns", utc=True)
            df["date"] = df["date"].dt.tz_convert("America/New_York").dt.date  # type: ignore[union-attr]

        # Get symbol from raw_symbol or symbol column
        if "raw_symbol" in df.columns:
            df["symbol"] = df["raw_symbol"]
        elif "symbol" not in df.columns:
            raise ValueError("No symbol column found in Databento response")

        # Select and order columns
        result = df[["symbol", "date", "open", "high", "low", "close", "volume"]].copy()

        # Remove any duplicates (keep last)
        result = result.drop_duplicates(subset=["symbol", "date"], keep="last")

        logger.info(f"Processed {len(result)} OHLCV records")
        return result

    def fetch_daily_bars(
        self,
        symbols: list[str] | None = None,
        start: str | date | None = None,
        end: str | date | None = None,
    ) -> pd.DataFrame:
        """
        Fetch daily OHLCV bars for given symbols and date range.

        Automatically handles dataset switching at the cutoff date.

        Args:
            symbols: List of ticker symbols (defaults to portfolio symbols)
            start: Start date (defaults to 1 year ago)
            end: End date (defaults to today)

        Returns:
            DataFrame with columns: symbol, date, open, high, low, close, volume
        """
        # Default to portfolio symbols
        if symbols is None:
            symbols = self.get_all_tracked_symbols()

        if not symbols:
            logger.warning("No symbols to fetch")
            return pd.DataFrame()

        # Parse dates
        if start is None:
            start_date = date.today() - timedelta(days=365)
        elif isinstance(start, str):
            start_date = datetime.strptime(start, "%Y-%m-%d").date()
        else:
            start_date = start

        if end is None:
            end_date = date.today() - timedelta(days=1)  # Yesterday
        elif isinstance(end, str):
            end_date = datetime.strptime(end, "%Y-%m-%d").date()
        else:
            end_date = end

        logger.info(
            f"Fetching OHLCV for {len(symbols)} symbols: {start_date} to {end_date}"
        )

        # Split into dataset segments
        segments = self._split_date_range(start_date, end_date)

        # Fetch each segment
        dfs = []
        for dataset, seg_start, seg_end in segments:
            df = self._fetch_segment(dataset, symbols, seg_start, seg_end)
            if not df.empty:
                dfs.append(df)

        if not dfs:
            logger.warning("No data fetched from any segment")
            return pd.DataFrame()

        # Combine all segments
        result = pd.concat(dfs, ignore_index=True)
        result = result.drop_duplicates(subset=["symbol", "date"], keep="last")
        result = result.sort_values(["symbol", "date"]).reset_index(drop=True)

        logger.info(f"Total fetched: {len(result)} OHLCV records")
        return result

    def save_to_supabase(self, df: pd.DataFrame) -> int:
        """
        Save OHLCV data to Supabase PostgreSQL with upsert keyed on (symbol, date).

        Args:
            df: DataFrame with OHLCV data

        Returns:
            Number of rows upserted
        """
        if df.empty:
            logger.warning("No data to save to Supabase")
            return 0

        # Batch upsert for better performance
        rows_affected = 0
        errors = 0
        for _, row in df.iterrows():
            try:
                execute_sql(
                    """
                    INSERT INTO ohlcv_daily (symbol, date, open, high, low, close, volume, source)
                    VALUES (:symbol, :date, :open, :high, :low, :close, :volume, 'databento')
                    ON CONFLICT (symbol, date)
                    DO UPDATE SET
                        open = EXCLUDED.open,
                        high = EXCLUDED.high,
                        low = EXCLUDED.low,
                        close = EXCLUDED.close,
                        volume = EXCLUDED.volume,
                        source = EXCLUDED.source,
                        updated_at = now()
                    """,
                    params={
                        "symbol": row["symbol"],
                        "date": row["date"],
                        "open": float(row["open"]) if pd.notna(row["open"]) else None,
                        "high": float(row["high"]) if pd.notna(row["high"]) else None,
                        "low": float(row["low"]) if pd.notna(row["low"]) else None,
                        "close": (
                            float(row["close"]) if pd.notna(row["close"]) else None
                        ),
                        "volume": (
                            int(row["volume"]) if pd.notna(row["volume"]) else None
                        ),
                    },
                    fetch_results=False,
                )
                rows_affected += 1
            except Exception as e:
                errors += 1
                logger.warning(
                    f"Error upserting row for {row['symbol']} on {row['date']}: {e}"
                )

        logger.info(f"Saved {rows_affected} rows to Supabase ({errors} errors)")
        return rows_affected

    def run_backfill(
        self,
        start: str | date,
        end: str | date,
        symbols: list[str] | None = None,
    ) -> dict:
        """
        Run a full backfill for the given date range.

        Respects REQUIRE_DATABENTO env var: if '1' and fetch fails, raises.

        Args:
            start: Start date
            end: End date
            symbols: Optional list of symbols (defaults to portfolio)

        Returns:
            Dict with operation results
        """
        logger.info(f"Starting backfill: {start} to {end}")

        results = {
            "fetched_rows": 0,
            "supabase_rows": 0,
            "success": True,
        }

        try:
            # Fetch data
            df = self.fetch_daily_bars(symbols=symbols, start=start, end=end)
            results["fetched_rows"] = len(df)

            if df.empty:
                logger.warning("No data fetched, nothing to save")
                return results

            # Save to Supabase
            results["supabase_rows"] = self.save_to_supabase(df)

        except Exception as e:
            logger.error(f"Backfill failed: {e}")
            results["success"] = False

            if REQUIRE_DATABENTO:
                raise RuntimeError(
                    f"Databento backfill failed and REQUIRE_DATABENTO=1: {e}"
                ) from e
            else:
                logger.warning("⚠️ Databento failed (REQUIRE_DATABENTO=0, continuing)")

        logger.info(f"Backfill complete: {results}")
        return results

    def get_symbols_missing_ohlcv(self, lookback_days: int = 30) -> list[str]:
        """
        Get portfolio symbols that have no OHLCV data in the given lookback period.

        Useful for auto-backfilling when new symbols are added to positions.

        Args:
            lookback_days: Days to look back for existing data

        Returns:
            List of symbols with no recent OHLCV data
        """
        try:
            cutoff = (date.today() - timedelta(days=lookback_days)).isoformat()
            result = execute_sql(
                """
                SELECT DISTINCT p.symbol
                FROM positions p
                WHERE p.symbol IS NOT NULL
                  AND p.symbol NOT IN (
                    SELECT DISTINCT symbol FROM ohlcv_daily WHERE date >= :cutoff
                  )
                ORDER BY p.symbol
                """,
                params={"cutoff": cutoff},
                fetch_results=True,
            )
            symbols = [row[0] for row in result] if result else []
            if symbols:
                logger.info(f"Found {len(symbols)} symbols missing OHLCV: {symbols}")
            return symbols
        except Exception as e:
            logger.warning(f"Could not check for missing OHLCV symbols: {e}")
            return []

    def run_daily_update(
        self,
        lookback_days: int = 5,
        symbols: list[str] | None = None,
    ) -> dict:
        """
        Run daily incremental update.

        Fetches recent data with a small lookback to catch any missed days.

        Args:
            lookback_days: Number of days to look back
            symbols: Optional list of symbols (defaults to portfolio)

        Returns:
            Dict with operation results
        """
        end_date = date.today() - timedelta(days=1)  # Yesterday
        start_date = end_date - timedelta(days=lookback_days)

        logger.info(f"Running daily update: {start_date} to {end_date}")

        return self.run_backfill(
            start=start_date,
            end=end_date,
            symbols=symbols,
        )


# Convenience functions for CLI usage
def main():
    """Main entry point for testing."""
    logging.basicConfig(level=logging.INFO)

    collector = DatabentoCollector()
    symbols = collector.get_all_tracked_symbols()
    print(f"Tracked symbols: {symbols}")

    # Test fetch (last 7 days)
    df = collector.fetch_daily_bars(
        symbols=symbols[:3],  # Limit for testing
        start=date.today() - timedelta(days=7),
        end=date.today() - timedelta(days=1),
    )
    print(f"\nFetched {len(df)} rows:")
    print(df.head(10))


if __name__ == "__main__":
    main()
