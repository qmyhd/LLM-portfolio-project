"""
Price Service - Centralized OHLCV Data Access

This module is the SOLE source of truth for fetching price history and latest prices.
All price data comes from the RDS ohlcv_daily table (Databento source).

Usage:
    from src.price_service import get_ohlcv, get_latest_close

    # Fetch OHLCV data for charting
    df = get_ohlcv("AAPL", date(2024, 1, 1), date(2024, 12, 31))

    # Get latest closing price
    price = get_latest_close("AAPL")

Environment Variables:
    RDS_HOST       - RDS PostgreSQL host
    RDS_PORT       - RDS port (default: 5432)
    RDS_DATABASE   - RDS database name (also supports RDS_DB)
    RDS_USER       - RDS username (default: postgres)
    RDS_PASSWORD   - RDS password

Note:
    This module does NOT use yfinance or any external market data API.
    All data comes from Databento via the ohlcv_daily table.
"""

from __future__ import annotations

import logging
import os
from datetime import date, datetime, timedelta
from functools import lru_cache
from typing import TYPE_CHECKING, Optional

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

from src.retry_utils import hardened_retry

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine

# Load environment variables
load_dotenv()

logger = logging.getLogger(__name__)

# Module-level engine cache
_rds_engine: Optional[Engine] = None


def _build_rds_url() -> str:
    """
    Build PostgreSQL connection URL from environment variables.

    Returns:
        PostgreSQL connection URL string, or empty string if not configured.
    """
    host = os.getenv("RDS_HOST", "")
    port = os.getenv("RDS_PORT", "5432")
    # Support both RDS_DATABASE and RDS_DB for flexibility
    database = os.getenv("RDS_DATABASE") or os.getenv("RDS_DB", "postgres")
    user = os.getenv("RDS_USER", "postgres")
    password = os.getenv("RDS_PASSWORD", "")

    if not host or not password:
        logger.warning(
            "RDS configuration incomplete (RDS_HOST or RDS_PASSWORD missing)"
        )
        return ""

    return f"postgresql://{user}:{password}@{host}:{port}/{database}"


def _get_rds_engine() -> Optional[Engine]:
    """
    Get or create the RDS SQLAlchemy engine with connection pooling.

    Returns:
        SQLAlchemy Engine instance, or None if RDS is not configured.
    """
    global _rds_engine

    if _rds_engine is None:
        rds_url = _build_rds_url()
        if rds_url:
            _rds_engine = create_engine(
                rds_url,
                pool_size=5,
                max_overflow=10,
                pool_pre_ping=True,
            )
            logger.debug("RDS engine initialized")
        else:
            logger.warning("RDS not configured - price service unavailable")

    return _rds_engine


@hardened_retry(max_retries=3, delay=1)
def get_ohlcv(
    symbol: str,
    start: date,
    end: date,
) -> pd.DataFrame:
    """
    Fetch OHLCV daily bars for a symbol within a date range.

    Data is sourced from the RDS ohlcv_daily table (Databento).

    Args:
        symbol: Stock ticker symbol (e.g., "AAPL", "MSFT")
        start: Start date (inclusive)
        end: End date (inclusive)

    Returns:
        DataFrame with columns: Date (index), Open, High, Low, Close, Volume
        Compatible with mplfinance charting.
        Returns empty DataFrame if no data found or RDS not configured.

    Example:
        >>> from datetime import date
        >>> df = get_ohlcv("AAPL", date(2024, 1, 1), date(2024, 12, 31))
        >>> df.head()
                      Open    High     Low   Close    Volume
        Date
        2024-01-02  185.12  186.45  184.80  185.50  45000000
    """
    engine = _get_rds_engine()
    if engine is None:
        logger.error("RDS not configured - cannot fetch OHLCV data")
        return pd.DataFrame()

    symbol = symbol.upper().strip()

    query = text(
        """
        SELECT 
            date,
            open,
            high,
            low,
            close,
            volume
        FROM ohlcv_daily
        WHERE symbol = :symbol
          AND date >= :start_date
          AND date <= :end_date
        ORDER BY date ASC
    """
    )

    try:
        with engine.connect() as conn:
            result = conn.execute(
                query,
                {
                    "symbol": symbol,
                    "start_date": start,
                    "end_date": end,
                },
            )
            rows = result.fetchall()

        if not rows:
            logger.info(f"No OHLCV data for {symbol} from {start} to {end}")
            return pd.DataFrame()

        # Create DataFrame with proper column names for mplfinance
        df = pd.DataFrame(
            rows,
            columns=["Date", "Open", "High", "Low", "Close", "Volume"],
        )

        # Convert date to datetime and set as index
        df["Date"] = pd.to_datetime(df["Date"])
        df.set_index("Date", inplace=True)

        # Ensure numeric types
        for col in ["Open", "High", "Low", "Close"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df["Volume"] = (
            pd.to_numeric(df["Volume"], errors="coerce").fillna(0).astype(int)
        )

        # Drop any rows with NaN in OHLC columns
        df = df.dropna(subset=["Open", "High", "Low", "Close"])

        logger.debug(f"Fetched {len(df)} OHLCV records for {symbol}")
        return df

    except Exception as e:
        logger.error(f"Error fetching OHLCV for {symbol}: {e}")
        raise


@hardened_retry(max_retries=3, delay=1)
def get_latest_close(symbol: str) -> Optional[float]:
    """
    Get the most recent closing price for a symbol.

    Data is sourced from the RDS ohlcv_daily table (Databento).

    Args:
        symbol: Stock ticker symbol (e.g., "AAPL", "MSFT")

    Returns:
        Latest closing price as float, or None if not found.

    Example:
        >>> price = get_latest_close("AAPL")
        >>> print(f"AAPL last close: ${price:.2f}")
        AAPL last close: $185.50
    """
    engine = _get_rds_engine()
    if engine is None:
        logger.error("RDS not configured - cannot fetch latest close")
        return None

    symbol = symbol.upper().strip()

    query = text(
        """
        SELECT close
        FROM ohlcv_daily
        WHERE symbol = :symbol
        ORDER BY date DESC
        LIMIT 1
    """
    )

    try:
        with engine.connect() as conn:
            result = conn.execute(query, {"symbol": symbol})
            row = result.fetchone()

        if row is None:
            logger.info(f"No price data found for {symbol}")
            return None

        close_price = float(row[0])
        logger.debug(f"Latest close for {symbol}: ${close_price:.2f}")
        return close_price

    except Exception as e:
        logger.error(f"Error fetching latest close for {symbol}: {e}")
        return None


@hardened_retry(max_retries=3, delay=1)
def get_previous_close(
    symbol: str, before_date: Optional[date] = None
) -> Optional[float]:
    """
    Get the closing price before a specific date (for daily change calculations).

    Args:
        symbol: Stock ticker symbol (e.g., "AAPL", "MSFT")
        before_date: Get close before this date (defaults to today)

    Returns:
        Previous closing price as float, or None if not found.

    Example:
        >>> from datetime import date
        >>> prev = get_previous_close("AAPL", date(2024, 1, 15))
        >>> print(f"AAPL previous close: ${prev:.2f}")
    """
    engine = _get_rds_engine()
    if engine is None:
        logger.error("RDS not configured - cannot fetch previous close")
        return None

    symbol = symbol.upper().strip()
    if before_date is None:
        before_date = date.today()

    query = text(
        """
        SELECT close
        FROM ohlcv_daily
        WHERE symbol = :symbol
          AND date < :before_date
        ORDER BY date DESC
        LIMIT 1
    """
    )

    try:
        with engine.connect() as conn:
            result = conn.execute(
                query,
                {"symbol": symbol, "before_date": before_date},
            )
            row = result.fetchone()

        if row is None:
            logger.info(f"No previous close found for {symbol} before {before_date}")
            return None

        close_price = float(row[0])
        logger.debug(
            f"Previous close for {symbol} before {before_date}: ${close_price:.2f}"
        )
        return close_price

    except Exception as e:
        logger.error(f"Error fetching previous close for {symbol}: {e}")
        return None


def get_ohlcv_batch(
    symbols: list[str],
    start: date,
    end: date,
) -> dict[str, pd.DataFrame]:
    """
    Fetch OHLCV data for multiple symbols (batch operation).

    Args:
        symbols: List of ticker symbols
        start: Start date (inclusive)
        end: End date (inclusive)

    Returns:
        Dict mapping symbol -> DataFrame with OHLCV data
    """
    results = {}
    for symbol in symbols:
        try:
            df = get_ohlcv(symbol, start, end)
            if not df.empty:
                results[symbol.upper()] = df
        except Exception as e:
            logger.warning(f"Failed to fetch OHLCV for {symbol}: {e}")
    return results


def get_latest_close_batch(symbols: list[str]) -> dict[str, float]:
    """
    Get latest closing prices for multiple symbols (batch operation).

    Args:
        symbols: List of ticker symbols

    Returns:
        Dict mapping symbol -> latest close price
        (symbols with no data are omitted)
    """
    engine = _get_rds_engine()
    if engine is None:
        logger.error("RDS not configured - cannot fetch batch prices")
        return {}

    if not symbols:
        return {}

    # Clean symbols
    clean_symbols = [s.upper().strip() for s in symbols]

    # Use a more efficient batch query with DISTINCT ON
    query = text(
        """
        SELECT DISTINCT ON (symbol)
            symbol,
            close
        FROM ohlcv_daily
        WHERE symbol = ANY(:symbols)
        ORDER BY symbol, date DESC
    """
    )

    try:
        with engine.connect() as conn:
            result = conn.execute(query, {"symbols": clean_symbols})
            rows = result.fetchall()

        prices = {row[0]: float(row[1]) for row in rows if row[1] is not None}
        logger.debug(f"Fetched latest closes for {len(prices)}/{len(symbols)} symbols")
        return prices

    except Exception as e:
        logger.error(f"Error fetching batch prices: {e}")
        return {}


def is_available() -> bool:
    """
    Check if the price service is properly configured and connected.

    Returns:
        True if RDS is configured and reachable, False otherwise.
    """
    engine = _get_rds_engine()
    if engine is None:
        return False

    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception as e:
        logger.warning(f"Price service health check failed: {e}")
        return False


# Alias for backwards compatibility if needed
get_daily_ohlcv = get_ohlcv
