"""
Databento OHLCV Data Collector

Fetches daily OHLCV bars from Databento Historical API.
Handles dataset switching: EQUS.MINI (pre-2024-07-01), EQUS.SUMMARY (current).

Environment Variables:
    DATABENTO_API_KEY   - Required. Databento API key.
    RDS_HOST            - RDS PostgreSQL host.
    RDS_PORT            - RDS port (default: 5432).
    RDS_DATABASE/RDS_DB - RDS database name (default: postgres).
    RDS_USER            - RDS username (default: postgres).
    RDS_PASSWORD        - RDS password.
    S3_BUCKET_NAME      - S3 bucket for Parquet archive.
    S3_RAW_DAILY_PREFIX - S3 key prefix (default: ohlcv/daily).
"""

from __future__ import annotations

import logging
import os
from datetime import date, datetime, timedelta
from decimal import Decimal
from io import BytesIO
from typing import TYPE_CHECKING

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

from src.retry_utils import hardened_retry

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine

# Load environment variables
load_dotenv()

logger = logging.getLogger(__name__)

# Dataset cutoff date: EQUS.MINI ends 2024-06-30, EQUS.SUMMARY starts 2024-07-01
DATASET_CUTOFF = date(2024, 7, 1)
DATASET_HISTORICAL = "EQUS.MINI"
DATASET_CURRENT = "EQUS.SUMMARY"


class DatabentoCollector:
    """Collect OHLCV daily bars from Databento Historical API."""

    def __init__(
        self,
        api_key: str | None = None,
        rds_url: str | None = None,
        s3_bucket: str | None = None,
        supabase_url: str | None = None,
    ):
        """
        Initialize the collector.

        Args:
            api_key: Databento API key (defaults to DATABENTO_API_KEY env var)
            rds_url: PostgreSQL RDS connection URL (defaults to RDS_* env vars)
            s3_bucket: S3 bucket name (defaults to S3_BUCKET_NAME env var)
            supabase_url: Optional Supabase connection URL for syncing
        """
        self.api_key = api_key or os.getenv("DATABENTO_API_KEY")
        if not self.api_key:
            raise ValueError("DATABENTO_API_KEY not set")

        # Build RDS connection URL from components if not provided
        self.rds_url = rds_url or self._build_rds_url()
        self.s3_bucket = s3_bucket or os.getenv("S3_BUCKET_NAME", "qqq-llm-raw-history")
        self.supabase_url = supabase_url

        # Lazy-loaded clients
        self._db_client = None
        self._rds_engine: Engine | None = None
        self._s3_client = None

    def _build_rds_url(self) -> str:
        """Build PostgreSQL connection URL from environment variables."""
        host = os.getenv("RDS_HOST", "")
        port = os.getenv("RDS_PORT", "5432")
        # Support both RDS_DATABASE and RDS_DB for flexibility
        database = os.getenv("RDS_DATABASE") or os.getenv("RDS_DB", "postgres")
        user = os.getenv("RDS_USER", "postgres")
        password = os.getenv("RDS_PASSWORD", "")

        if not host or not password:
            logger.warning("RDS configuration incomplete, RDS storage will be disabled")
            return ""

        return f"postgresql://{user}:{password}@{host}:{port}/{database}"

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

    @property
    def rds_engine(self) -> Engine | None:
        """Lazy-load RDS SQLAlchemy engine."""
        if self._rds_engine is None and self.rds_url:
            self._rds_engine = create_engine(
                self.rds_url,
                pool_size=5,
                max_overflow=10,
                pool_pre_ping=True,
            )
        return self._rds_engine

    @property
    def s3_client(self):
        """Lazy-load S3 client."""
        if self._s3_client is None:
            try:
                import boto3  # type: ignore[import-untyped]

                self._s3_client = boto3.client("s3")
            except ImportError:
                raise ImportError("boto3 package not installed. Run: pip install boto3")
        return self._s3_client

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

    @hardened_retry(max_retries=3, delay=2)
    def _fetch_segment(
        self,
        dataset: str,
        symbols: list[str],
        start: date,
        end: date,
    ) -> pd.DataFrame:
        """
        Fetch OHLCV data for a single dataset segment.

        Args:
            dataset: Databento dataset name
            symbols: List of ticker symbols
            start: Start date (inclusive)
            end: End date (inclusive)

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
            logger.error(f"Error fetching {dataset}: {e}")
            raise

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

    def save_to_rds(self, df: pd.DataFrame) -> int:
        """
        Save OHLCV data to RDS PostgreSQL with upsert.

        Args:
            df: DataFrame with OHLCV data

        Returns:
            Number of rows upserted
        """
        if df.empty:
            logger.warning("No data to save to RDS")
            return 0

        if not self.rds_engine:
            logger.warning("RDS not configured, skipping RDS save")
            return 0

        # Ensure table exists
        self._ensure_rds_table()

        # Upsert data
        rows_affected = 0
        with self.rds_engine.connect() as conn:
            for _, row in df.iterrows():
                result = conn.execute(
                    text(
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
                            updated_at = now()
                    """
                    ),
                    {
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
                )
                rows_affected += result.rowcount
            conn.commit()

        logger.info(f"Saved {rows_affected} rows to RDS")
        return rows_affected

    def _ensure_rds_table(self) -> None:
        """Ensure ohlcv_daily table exists in RDS."""
        if not self.rds_engine:
            return

        create_table_sql = """
            CREATE TABLE IF NOT EXISTS ohlcv_daily (
                symbol TEXT NOT NULL,
                date DATE NOT NULL,
                open NUMERIC(18,6),
                high NUMERIC(18,6),
                low NUMERIC(18,6),
                close NUMERIC(18,6),
                volume BIGINT,
                created_at TIMESTAMPTZ DEFAULT now(),
                updated_at TIMESTAMPTZ DEFAULT now(),
                source TEXT DEFAULT 'databento',
                PRIMARY KEY (symbol, date)
            );
            
            CREATE INDEX IF NOT EXISTS idx_ohlcv_daily_symbol ON ohlcv_daily(symbol);
            CREATE INDEX IF NOT EXISTS idx_ohlcv_daily_date ON ohlcv_daily(date DESC);
            CREATE INDEX IF NOT EXISTS idx_ohlcv_daily_symbol_date ON ohlcv_daily(symbol, date DESC);
        """

        with self.rds_engine.connect() as conn:
            conn.execute(text(create_table_sql))
            conn.commit()

        logger.debug("Ensured ohlcv_daily table exists in RDS")

    def save_to_s3(
        self,
        df: pd.DataFrame,
        partition_date: date | None = None,
        prefix: str | None = None,
    ) -> str | None:
        """
        Save OHLCV data to S3 as Parquet.

        Args:
            df: DataFrame with OHLCV data
            partition_date: Date for partitioning (defaults to max date in df)
            prefix: S3 key prefix

        Returns:
            S3 key of saved file, or None if failed
        """
        if df.empty:
            logger.warning("No data to save to S3")
            return None

        if not self.s3_bucket:
            logger.warning("S3 bucket not configured, skipping S3 save")
            return None

        # Use env var or default for prefix
        if prefix is None:
            prefix = os.getenv("S3_RAW_DAILY_PREFIX", "ohlcv/daily").rstrip("/")

        # Determine partition date
        if partition_date is None:
            partition_date = df["date"].max()
            if isinstance(partition_date, pd.Timestamp):
                partition_date = partition_date.date()

        # Build S3 key with date partitioning
        assert partition_date is not None  # Ensured above
        year = partition_date.year
        month = f"{partition_date.month:02d}"
        day = f"{partition_date.day:02d}"
        key = f"{prefix}/year={year}/month={month}/day={day}/ohlcv.parquet"

        try:
            # Convert to Parquet in memory
            buffer = BytesIO()
            df.to_parquet(buffer, index=False, engine="pyarrow")
            buffer.seek(0)

            # Upload to S3
            self.s3_client.put_object(
                Bucket=self.s3_bucket,
                Key=key,
                Body=buffer.getvalue(),
            )

            logger.info(f"Saved {len(df)} rows to s3://{self.s3_bucket}/{key}")
            return key

        except Exception as e:
            logger.error(f"Failed to save to S3: {e}")
            return None

    def save_to_supabase(self, df: pd.DataFrame) -> int:
        """
        Sync OHLCV data to Supabase (optional).

        Uses the project's standard database connection.

        Args:
            df: DataFrame with OHLCV data

        Returns:
            Number of rows synced
        """
        if df.empty:
            return 0

        try:
            from src.db import execute_sql

            rows_affected = 0
            for _, row in df.iterrows():
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
                )
                rows_affected += 1

            logger.info(f"Synced {rows_affected} rows to Supabase")
            return rows_affected

        except Exception as e:
            logger.error(f"Failed to sync to Supabase: {e}")
            return 0

    def run_backfill(
        self,
        start: str | date,
        end: str | date,
        symbols: list[str] | None = None,
        save_rds: bool = True,
        save_s3: bool = True,
        save_supabase: bool = False,
    ) -> dict:
        """
        Run a full backfill for the given date range.

        Args:
            start: Start date
            end: End date
            symbols: Optional list of symbols (defaults to portfolio)
            save_rds: Whether to save to RDS
            save_s3: Whether to save to S3
            save_supabase: Whether to sync to Supabase

        Returns:
            Dict with operation results
        """
        logger.info(f"Starting backfill: {start} to {end}")

        # Fetch data
        df = self.fetch_daily_bars(symbols=symbols, start=start, end=end)

        results = {
            "fetched_rows": len(df),
            "rds_rows": 0,
            "s3_key": None,
            "supabase_rows": 0,
        }

        if df.empty:
            logger.warning("No data fetched, nothing to save")
            return results

        # Save to targets
        if save_rds:
            results["rds_rows"] = self.save_to_rds(df)

        if save_s3:
            results["s3_key"] = self.save_to_s3(df)

        if save_supabase:
            results["supabase_rows"] = self.save_to_supabase(df)

        logger.info(f"Backfill complete: {results}")
        return results

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
            save_rds=True,
            save_s3=True,
            save_supabase=True,  # Sync to Supabase for daily updates
        )

    def prune_rds_data(self, keep_days: int = 365) -> int:
        """
        Prune old data from RDS to maintain rolling window.

        Args:
            keep_days: Number of days of data to keep

        Returns:
            Number of rows deleted
        """
        if not self.rds_engine:
            logger.warning("RDS not configured")
            return 0

        cutoff_date = date.today() - timedelta(days=keep_days)

        with self.rds_engine.connect() as conn:
            result = conn.execute(
                text("DELETE FROM ohlcv_daily WHERE date < :cutoff"),
                {"cutoff": cutoff_date},
            )
            conn.commit()
            deleted = result.rowcount

        logger.info(f"Pruned {deleted} rows older than {cutoff_date}")
        return deleted


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
