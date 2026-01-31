"""
Price Service - Centralized OHLCV Data Access

This module is the SOLE source of truth for fetching price history and latest prices.
All price data comes from the Supabase ohlcv_daily table (Databento source).

Usage:
    from src.price_service import get_ohlcv, get_latest_close

    # Fetch OHLCV data for charting
    df = get_ohlcv("AAPL", date(2024, 1, 1), date(2024, 12, 31))

    # Get latest closing price
    price = get_latest_close("AAPL")

Environment Variables:
    DATABASE_URL   - Supabase PostgreSQL connection URL

Note:
    This module does NOT use yfinance or any external market data API.
    All data comes from Databento via the ohlcv_daily table in Supabase.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Optional

import pandas as pd

from src.db import execute_sql, healthcheck
from src.retry_utils import hardened_retry

logger = logging.getLogger(__name__)


@hardened_retry(max_retries=3, delay=1)
def get_ohlcv(
    symbol: str,
    start: date,
    end: date,
) -> pd.DataFrame:
    """
    Fetch OHLCV daily bars for a symbol within a date range.

    Data is sourced from the Supabase ohlcv_daily table (Databento).

    Args:
        symbol: Stock ticker symbol (e.g., "AAPL", "MSFT")
        start: Start date (inclusive)
        end: End date (inclusive)

    Returns:
        DataFrame with columns: Date (index), Open, High, Low, Close, Volume
        Compatible with mplfinance charting.
        Returns empty DataFrame if no data found.

    Example:
        >>> from datetime import date
        >>> df = get_ohlcv("AAPL", date(2024, 1, 1), date(2024, 12, 31))
        >>> df.head()
                      Open    High     Low   Close    Volume
        Date
        2024-01-02  185.12  186.45  184.80  185.50  45000000
    """
    symbol = symbol.upper().strip()

    try:
        rows = execute_sql(
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
            """,
            params={
                "symbol": symbol,
                "start_date": start,
                "end_date": end,
            },
            fetch_results=True,
        )

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
        volume_numeric = pd.to_numeric(df["Volume"], errors="coerce")
        df["Volume"] = pd.Series(volume_numeric).fillna(0).astype(int)

        # Drop any rows with NaN in OHLC columns
        df = df.dropna(subset=["Open", "High", "Low", "Close"])

        logger.debug(f"Fetched {len(df)} OHLCV records for {symbol}")
        return df

    except Exception as e:
        logger.error(f"Error fetching OHLCV for {symbol}: {e}")
        raise


def get_latest_closes_batch(symbols: list[str]) -> dict[str, float]:
    """
    Get the most recent closing prices for multiple symbols in a single query.

    This is much more efficient than calling get_latest_close() in a loop.

    Args:
        symbols: List of stock ticker symbols

    Returns:
        Dictionary mapping symbol to latest closing price.
        Symbols without data are omitted from the result.

    Example:
        >>> prices = get_latest_closes_batch(["AAPL", "MSFT", "GOOGL"])
        >>> print(prices)
        {"AAPL": 185.50, "MSFT": 420.25, "GOOGL": 175.30}
    """
    if not symbols:
        return {}

    # Normalize symbols
    symbols = [s.upper().strip() for s in symbols]

    try:
        # Use a subquery to get the latest date for each symbol, then join to get prices
        rows = execute_sql(
            """
            WITH latest_dates AS (
                SELECT symbol, MAX(date) as max_date
                FROM ohlcv_daily
                WHERE symbol = ANY(:symbols)
                GROUP BY symbol
            )
            SELECT o.symbol, o.close
            FROM ohlcv_daily o
            JOIN latest_dates ld ON o.symbol = ld.symbol AND o.date = ld.max_date
            """,
            params={"symbols": symbols},
            fetch_results=True,
        )

        if not rows:
            logger.debug(f"No price data found for any of {len(symbols)} symbols")
            return {}

        # Build result dictionary
        result = {}
        for row in rows:
            row_data = dict(row._mapping) if hasattr(row, "_mapping") else row
            symbol = row_data["symbol"] if isinstance(row_data, dict) else row[0]
            close = row_data["close"] if isinstance(row_data, dict) else row[1]
            if close is not None:
                result[symbol] = float(close)

        logger.debug(f"Fetched prices for {len(result)}/{len(symbols)} symbols")
        return result

    except Exception as e:
        logger.error(f"Error fetching batch prices: {e}")
        return {}


@hardened_retry(max_retries=3, delay=1)
def get_latest_close(symbol: str) -> Optional[float]:
    """
    Get the most recent closing price for a symbol.

    Data is sourced from the Supabase ohlcv_daily table (Databento).

    Args:
        symbol: Stock ticker symbol (e.g., "AAPL", "MSFT")

    Returns:
        Latest closing price as float, or None if not found.

    Example:
        >>> price = get_latest_close("AAPL")
        >>> print(f"AAPL last close: ${price:.2f}")
        AAPL last close: $185.50
    """
    symbol = symbol.upper().strip()

    try:
        rows = execute_sql(
            """
            SELECT close
            FROM ohlcv_daily
            WHERE symbol = :symbol
            ORDER BY date DESC
            LIMIT 1
            """,
            params={"symbol": symbol},
            fetch_results=True,
        )

        if not rows or rows[0][0] is None:
            logger.debug(f"No price data found for {symbol}")
            return None

        close_price = float(rows[0][0])
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
    symbol = symbol.upper().strip()
    if before_date is None:
        before_date = date.today()

    try:
        rows = execute_sql(
            """
            SELECT close
            FROM ohlcv_daily
            WHERE symbol = :symbol
              AND date < :before_date
            ORDER BY date DESC
            LIMIT 1
            """,
            params={"symbol": symbol, "before_date": before_date},
            fetch_results=True,
        )

        if not rows or rows[0][0] is None:
            logger.info(f"No previous close found for {symbol} before {before_date}")
            return None

        close_price = float(rows[0][0])
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
    if not symbols:
        return {}

    # Clean symbols
    clean_symbols = [s.upper().strip() for s in symbols]

    try:
        # Use a more efficient batch query with DISTINCT ON
        rows = execute_sql(
            """
            SELECT DISTINCT ON (symbol)
                symbol,
                close
            FROM ohlcv_daily
            WHERE symbol = ANY(:symbols)
            ORDER BY symbol, date DESC
            """,
            params={"symbols": clean_symbols},
            fetch_results=True,
        )

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
        True if Supabase is configured and reachable, False otherwise.
    """
    return healthcheck()


# Alias for backwards compatibility if needed
get_daily_ohlcv = get_ohlcv
