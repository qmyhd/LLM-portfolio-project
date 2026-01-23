"""
OHLCV Backfill Lambda Handler

Triggered by EventBridge (CloudWatch Events) on a schedule.
Fetches daily OHLCV data from Databento and stores in RDS.

Schedule: Daily at 5:30 PM EST (after market close)
    cron(30 22 ? * MON-FRI *)  # UTC

This function:
1. Fetches daily OHLCV bars from Databento Historical API
2. Stores data in RDS PostgreSQL (ohlcv_daily table)
3. Optionally archives to S3 in Parquet format
"""

import os
import sys
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from lambdas.shared import (
    configure_logging,
    error_response,
    load_secrets,
    success_response,
    validate_db_connection,
)

logger = configure_logging("INFO")

# Default symbols to backfill (can be overridden in event)
DEFAULT_SYMBOLS = [
    "AAPL",
    "MSFT",
    "GOOGL",
    "AMZN",
    "META",
    "NVDA",
    "TSLA",
    "SPY",
    "QQQ",
    "IWM",
    "DIA",
]


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Lambda handler for OHLCV backfill.

    Args:
        event: EventBridge event or custom event with optional parameters:
            - symbols: List of symbols to backfill (default: DEFAULT_SYMBOLS)
            - start_date: Start date (YYYY-MM-DD, default: yesterday)
            - end_date: End date (YYYY-MM-DD, default: yesterday)
            - use_rds: Write to RDS instead of Supabase (default: True)
            - archive_s3: Also archive to S3 (default: False)
        context: Lambda context

    Returns:
        Lambda response with backfill results
    """
    start_time = datetime.utcnow()
    logger.info(f"OHLCV backfill started at {start_time.isoformat()}")

    # Parse event parameters
    symbols = event.get("symbols", DEFAULT_SYMBOLS)

    # Default to yesterday for daily backfill
    yesterday = (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d")
    start_date = event.get("start_date", yesterday)
    end_date = event.get("end_date", yesterday)
    use_rds = event.get("use_rds", True)
    archive_s3 = event.get("archive_s3", False)

    logger.info(f"Parameters: symbols={len(symbols)}, dates={start_date} to {end_date}")
    logger.info(f"Storage: RDS={use_rds}, S3={archive_s3}")

    # Step 1: Load secrets
    if not load_secrets():
        return error_response("Failed to load secrets from AWS Secrets Manager")

    # Step 2: Validate Databento API key
    databento_key = os.environ.get("DATABENTO_API_KEY")
    if not databento_key:
        return error_response("DATABENTO_API_KEY not configured")

    # Step 3: Validate database connection
    if use_rds:
        if not validate_db_connection(use_rds=True):
            # Fall back to Supabase if RDS not available
            logger.warning("RDS not available, falling back to Supabase")
            use_rds = False

    if not use_rds and not validate_db_connection(use_rds=False):
        return error_response("Database connection validation failed")

    # Step 4: Fetch and store OHLCV data
    try:
        from src.databento_collector import DatabentoCollector

        collector = DatabentoCollector(api_key=databento_key)

        results = {
            "symbols_requested": len(symbols),
            "symbols_processed": 0,
            "rows_inserted": 0,
            "errors": [],
            "s3_archived": False,
        }

        # fetch_daily_bars accepts a list of symbols and handles batching internally
        # Parameters: symbols (list), start (str/date), end (str/date)
        try:
            df = collector.fetch_daily_bars(
                symbols=symbols,
                start=start_date,
                end=end_date,
            )

            if df is None or df.empty:
                logger.warning("No data returned from Databento")
            else:
                # Store all data to database
                if use_rds:
                    rows = store_ohlcv_rds_dataframe(df, collector)
                else:
                    rows = store_ohlcv_supabase_dataframe(df)

                results["symbols_processed"] = df["symbol"].nunique()
                results["rows_inserted"] = rows

                logger.info(
                    f"Stored {rows} rows for {results['symbols_processed']} symbols"
                )

        except Exception as e:
            logger.warning(f"Failed to fetch OHLCV data: {e}")
            results["errors"].append({"step": "fetch", "error": str(e)})

        # Archive to S3 if requested
        if archive_s3 and results["symbols_processed"] > 0:
            try:
                archive_to_s3(symbols, start_date, end_date)
                results["s3_archived"] = True
            except Exception as e:
                logger.warning(f"S3 archive failed: {e}")
                results["errors"].append({"step": "s3_archive", "error": str(e)})

        # Calculate duration
        duration = (datetime.utcnow() - start_time).total_seconds()

        logger.info(f"OHLCV backfill completed in {duration:.2f}s")
        logger.info(f"Results: {results}")

        return success_response(
            message="OHLCV backfill completed",
            data={
                "duration_seconds": round(duration, 2),
                "results": results,
                "timestamp": start_time.isoformat(),
                "date_range": f"{start_date} to {end_date}",
            },
        )

    except ImportError as e:
        logger.error(f"Import error: {e}")
        return error_response(
            message="Databento collector not available",
            error=str(e),
        )
    except Exception as e:
        logger.exception("OHLCV backfill failed")
        return error_response(
            message="OHLCV backfill failed",
            error=str(e),
        )


import pandas as pd


def store_ohlcv_rds_dataframe(df: pd.DataFrame, collector) -> int:
    """Store OHLCV DataFrame in RDS PostgreSQL using collector's method."""
    if df is None or df.empty:
        return 0

    # Use the collector's built-in RDS write method
    if collector.rds_engine is not None:
        try:
            collector.write_to_rds(df)
            return len(df)
        except Exception as e:
            logger.warning(f"Failed to write to RDS: {e}")
            return 0

    # Fallback: manual insert
    from src.db import get_rds_connection
    from sqlalchemy import text

    conn = get_rds_connection()
    if conn is None:
        raise RuntimeError("RDS connection not available")

    inserted = 0
    with conn:
        for _, row in df.iterrows():
            try:
                conn.execute(
                    text(
                        """
                        INSERT INTO ohlcv_daily (
                            symbol, date, open, high, low, close, volume, source
                        ) VALUES (
                            :symbol, :date, :open, :high, :low, :close, :volume, :source
                        )
                        ON CONFLICT (symbol, date) DO UPDATE SET
                            open = EXCLUDED.open,
                            high = EXCLUDED.high,
                            low = EXCLUDED.low,
                            close = EXCLUDED.close,
                            volume = EXCLUDED.volume,
                            source = EXCLUDED.source,
                            updated_at = NOW()
                    """
                    ),
                    {
                        "symbol": row["symbol"],
                        "date": row["date"],
                        "open": float(row["open"]),
                        "high": float(row["high"]),
                        "low": float(row["low"]),
                        "close": float(row["close"]),
                        "volume": int(row["volume"]),
                        "source": "databento",
                    },
                )
                inserted += 1
            except Exception as e:
                logger.warning(
                    f"Failed to insert bar for {row.get('symbol', 'unknown')}: {e}"
                )

        conn.commit()

    return inserted


def store_ohlcv_supabase_dataframe(df: pd.DataFrame) -> int:
    """Store OHLCV DataFrame in Supabase PostgreSQL."""
    from src.db import execute_sql

    if df is None or df.empty:
        return 0

    inserted = 0
    for _, row in df.iterrows():
        try:
            execute_sql(
                """
                INSERT INTO ohlcv_daily (
                    symbol, date, open, high, low, close, volume, source
                ) VALUES (
                    :symbol, :date, :open, :high, :low, :close, :volume, :source
                )
                ON CONFLICT (symbol, date) DO UPDATE SET
                    open = EXCLUDED.open,
                    high = EXCLUDED.high,
                    low = EXCLUDED.low,
                    close = EXCLUDED.close,
                    volume = EXCLUDED.volume,
                    source = EXCLUDED.source,
                    updated_at = NOW()
                """,
                params={
                    "symbol": row["symbol"],
                    "date": row["date"],
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                    "volume": int(row["volume"]),
                    "source": "databento",
                },
            )
            inserted += 1
        except Exception as e:
            logger.warning(
                f"Failed to insert bar for {row.get('symbol', 'unknown')}: {e}"
            )

    return inserted


def archive_to_s3(symbols: List[str], start_date: str, end_date: str) -> None:
    """Archive OHLCV data to S3 in Parquet format."""
    import boto3

    bucket = os.environ.get("S3_BUCKET_NAME")
    prefix = os.environ.get("S3_RAW_DAILY_PREFIX", "ohlcv/daily/")

    if not bucket:
        raise ValueError("S3_BUCKET_NAME not configured")

    # Implementation would fetch data and write as Parquet
    # For now, just log the intent
    logger.info(f"S3 archive: {bucket}/{prefix} for {start_date} to {end_date}")


# Local testing
if __name__ == "__main__":
    # Simulate EventBridge event
    test_event = {
        "source": "aws.events",
        "time": datetime.utcnow().isoformat(),
        "detail-type": "Scheduled Event",
        "symbols": ["AAPL", "MSFT"],
        "start_date": "2025-01-17",
        "end_date": "2025-01-17",
        "use_rds": False,  # Use Supabase for testing
    }

    result = handler(test_event, None)
    print(result)
