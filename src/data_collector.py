import csv
import logging
import re
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from functools import wraps

import pandas as pd
import yfinance as yf

from src.message_cleaner import extract_ticker_symbols

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Define directories
BASE_DIR = Path(__file__).resolve().parent.parent
RAW_DIR = BASE_DIR / "data" / "raw"
PROCESSED_DIR = BASE_DIR / "data" / "processed"
DB_DIR = BASE_DIR / "data" / "database"

# Create directories if they don't exist
RAW_DIR.mkdir(parents=True, exist_ok=True)
PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
DB_DIR.mkdir(parents=True, exist_ok=True)

# File paths
DISCORD_CSV = RAW_DIR / "discord_msgs.csv"
PRICES_CSV = RAW_DIR / "prices.csv"
PRICE_DB = DB_DIR / "price_history.db"

# =====================================================
# Rate Limiting & Error Handling Configuration
# =====================================================
# Yahoo Finance informal limits: ~60 requests/minute, ~360/hour
RATE_LIMIT_DELAY = 1.0  # Base delay between requests (seconds)
MAX_RETRIES = 3
BACKOFF_FACTOR = 2.0  # Exponential backoff multiplier

# Valid yfinance period/interval combinations
VALID_PERIODS = ["1d", "5d", "1mo", "3mo", "6mo", "1y", "2y", "5y", "10y", "ytd", "max"]
VALID_INTERVALS = [
    "1m",
    "2m",
    "5m",
    "15m",
    "30m",
    "60m",
    "90m",
    "1h",
    "1d",
    "5d",
    "1wk",
    "1mo",
    "3mo",
]

# Interval restrictions (minute data only available for 7 days)
MINUTE_INTERVALS = ["1m", "2m", "5m", "15m", "30m", "60m", "90m", "1h"]
MINUTE_DATA_MAX_DAYS = 7

# Request tracking for rate limiting
_last_request_time = None
_request_count = 0


def rate_limit_delay():
    """Enforce rate limiting between API requests."""
    global _last_request_time, _request_count

    if _last_request_time is not None:
        elapsed = time.time() - _last_request_time
        if elapsed < RATE_LIMIT_DELAY:
            time.sleep(RATE_LIMIT_DELAY - elapsed)

    _last_request_time = time.time()
    _request_count += 1


def exponential_backoff_retry(func):
    """Decorator for exponential backoff retry on API failures."""

    @wraps(func)
    def wrapper(*args, **kwargs):
        last_exception = None
        for attempt in range(MAX_RETRIES):
            try:
                rate_limit_delay()
                return func(*args, **kwargs)
            except Exception as e:
                last_exception = e
                error_msg = str(e).lower()

                # Check for rate limit (429) errors
                if "429" in str(e) or "too many requests" in error_msg:
                    delay = RATE_LIMIT_DELAY * (BACKOFF_FACTOR**attempt) * 2
                    logger.warning(
                        f"Rate limited on {func.__name__}, waiting {delay:.1f}s (attempt {attempt + 1}/{MAX_RETRIES})"
                    )
                    time.sleep(delay)
                # Check for network/connection errors
                elif "connection" in error_msg or "timeout" in error_msg:
                    delay = RATE_LIMIT_DELAY * (BACKOFF_FACTOR**attempt)
                    logger.warning(
                        f"Network error on {func.__name__}, retrying in {delay:.1f}s (attempt {attempt + 1}/{MAX_RETRIES})"
                    )
                    time.sleep(delay)
                else:
                    # Non-retryable error
                    raise

        # All retries exhausted
        logger.error(f"All {MAX_RETRIES} retries exhausted for {func.__name__}")
        raise last_exception

    return wrapper


def validate_period_interval(period: str, interval: str) -> tuple[bool, str]:
    """Validate that period/interval combination is valid for yfinance.

    Args:
        period: Time period (e.g., "1mo", "1y")
        interval: Data interval (e.g., "1d", "1h")

    Returns:
        Tuple of (is_valid, error_message)

    Valid combinations:
    - Minute intervals (1m-1h): Only available for last 7 days
    - Daily/weekly intervals: Available for all periods
    - Monthly/quarterly intervals: Available for longer periods

    Examples:
        >>> validate_period_interval("1mo", "1d")  # ✓ Valid
        >>> validate_period_interval("1y", "1m")   # ✗ Invalid (minute data max 7 days)
        >>> validate_period_interval("1d", "1h")   # ✓ Valid
    """
    if period not in VALID_PERIODS:
        return False, f"Invalid period '{period}'. Valid: {VALID_PERIODS}"

    if interval not in VALID_INTERVALS:
        return False, f"Invalid interval '{interval}'. Valid: {VALID_INTERVALS}"

    # Check minute-level data restrictions
    if interval in MINUTE_INTERVALS:
        period_days = {
            "1d": 1,
            "5d": 5,
            "1mo": 30,
            "3mo": 90,
            "6mo": 180,
            "1y": 365,
            "2y": 730,
            "5y": 1825,
            "10y": 3650,
            "ytd": 365,
            "max": 9999,
        }
        if period_days.get(period, 30) > MINUTE_DATA_MAX_DAYS:
            return (
                False,
                f"Minute-level data (interval='{interval}') only available for last {MINUTE_DATA_MAX_DAYS} days. Use period='5d' or shorter.",
            )

    return True, ""


def get_cached_price(symbol: str) -> dict | None:
    """Get cached price from database when API fails.

    Checks in order: realtime_prices, positions.current_price, daily_prices.

    Args:
        symbol: Ticker symbol

    Returns:
        Dict with price info or None if not found
    """
    from src.db import execute_sql

    try:
        # Try realtime_prices first (most recent)
        result = execute_sql(
            """
            SELECT price, previous_close, percent_change, timestamp
            FROM realtime_prices 
            WHERE symbol = :symbol 
            ORDER BY timestamp DESC LIMIT 1
            """,
            params={"symbol": symbol},
            fetch_results=True,
        )
        if result and result[0][0]:
            return {
                "symbol": symbol,
                "price": float(result[0][0]),
                "previous_close": float(result[0][1]) if result[0][1] else None,
                "percent_change": float(result[0][2]) if result[0][2] else None,
                "source": "realtime_cache",
                "timestamp": result[0][3],
            }

        # Try positions.current_price
        result = execute_sql(
            """
            SELECT current_price, prev_price, price_updated_at
            FROM positions 
            WHERE symbol = :symbol AND current_price IS NOT NULL
            LIMIT 1
            """,
            params={"symbol": symbol},
            fetch_results=True,
        )
        if result and result[0][0]:
            current = float(result[0][0])
            prev = float(result[0][1]) if result[0][1] else current
            pct_change = ((current - prev) / prev * 100) if prev else 0
            return {
                "symbol": symbol,
                "price": current,
                "previous_close": prev,
                "percent_change": pct_change,
                "source": "position_cache",
                "timestamp": result[0][2],
            }

        # Try daily_prices (last close)
        result = execute_sql(
            """
            SELECT close, date FROM daily_prices 
            WHERE symbol = :symbol 
            ORDER BY date DESC LIMIT 1
            """,
            params={"symbol": symbol},
            fetch_results=True,
        )
        if result and result[0][0]:
            return {
                "symbol": symbol,
                "price": float(result[0][0]),
                "previous_close": float(result[0][0]),
                "percent_change": 0.0,
                "source": "daily_cache",
                "timestamp": result[0][1],
            }

    except Exception as e:
        logger.debug(f"Cache lookup failed for {symbol}: {e}")

    return None


def update_position_prices(prices_df):
    """Update positions table with current/previous prices.

    Shifts current_price to prev_price and writes new price into current_price.
    This enables quick daily-change calculations when yfinance is unavailable.

    Args:
        prices_df: DataFrame with columns [symbol, price]
    """
    if prices_df.empty:
        return

    from src.db import execute_sql

    try:
        now = datetime.now(timezone.utc)

        for _, row in prices_df.iterrows():
            symbol = row.get("symbol")
            price = row.get("price")

            if not symbol or price is None:
                continue

            # Shift current_price to prev_price and update current_price
            execute_sql(
                """
                UPDATE positions 
                SET prev_price = current_price,
                    current_price = :price,
                    price_updated_at = :updated_at
                WHERE symbol = :symbol
                """,
                params={"symbol": symbol, "price": float(price), "updated_at": now},
            )

        logger.info(f"✅ Updated position prices for {len(prices_df)} symbols")

    except Exception as e:
        logger.error(f"Error updating position prices: {e}")


def fetch_realtime_prices(symbols=None):
    """Fetch real-time prices for the given symbols or all positions

    Args:
        symbols: List of ticker symbols to fetch prices for (default: None, uses active positions)

    Returns:
        DataFrame containing real-time price data
    """
    if symbols is None:
        # Get symbols from the database positions table
        from src.db import execute_sql

        try:
            result = execute_sql(
                "SELECT DISTINCT symbol FROM positions WHERE quantity > 0",
                fetch_results=True,
            )
            symbols = [row[0] for row in result] if result else []
        except Exception as e:
            logger.error(f"Error fetching symbols from database: {e}")
            symbols = []

    # Clean up symbols to ensure they're valid ticker strings
    valid_symbols = []
    for symbol in symbols:
        if isinstance(symbol, str) and symbol.strip():
            clean_symbol = symbol.strip().upper()
            # Enhanced ticker validation - supports symbols like BRK.B, BF.B, etc.
            if re.match(r"^[A-Z]{1,6}(?:\.[A-Z]{1,2})?$", clean_symbol):
                valid_symbols.append(clean_symbol)

    if not valid_symbols:
        logger.warning("No valid symbols found for price fetching")
        return pd.DataFrame()

    logger.info(f"Fetching real-time prices for {len(valid_symbols)} symbols")

    # Use batch download for efficiency (reduces API calls)
    price_data = []
    failed_symbols = []

    try:
        # Batch download current prices with auto_adjust=False to avoid warnings
        # yf.download is more efficient than individual Ticker.history() calls
        rate_limit_delay()
        batch_data = yf.download(
            tickers=valid_symbols,
            period="1d",
            interval="1m",
            auto_adjust=False,  # CRITICAL: Explicit to avoid deprecation warning
            progress=False,
            group_by="ticker",
            threads=True,  # Parallel download
        )

        for symbol in valid_symbols:
            try:
                # Extract data for this symbol from batch result
                if len(valid_symbols) == 1:
                    symbol_data = batch_data  # Single ticker doesn't have symbol index
                else:
                    symbol_data = (
                        batch_data[symbol]
                        if symbol in batch_data.columns.get_level_values(0)
                        else None
                    )

                if (
                    symbol_data is None
                    or symbol_data.empty
                    or symbol_data["Close"].isna().all()
                ):
                    failed_symbols.append(symbol)
                    continue

                current_price = symbol_data["Close"].dropna().iloc[-1]

                # Get previous close from fast_info (more reliable)
                rate_limit_delay()
                ticker = yf.Ticker(symbol)
                fast_info = ticker.fast_info
                previous_close = (
                    getattr(fast_info, "previous_close", None) or current_price
                )

                abs_change = current_price - previous_close
                percent_change = (
                    (abs_change / previous_close * 100) if previous_close else 0
                )

                price_data.append(
                    {
                        "symbol": symbol,
                        "timestamp": datetime.now(timezone.utc),
                        "price": float(current_price),
                        "previous_close": float(previous_close),
                        "abs_change": float(abs_change),
                        "percent_change": float(percent_change),
                    }
                )

            except Exception as e:
                logger.warning(f"Error processing {symbol} from batch: {e}")
                failed_symbols.append(symbol)

    except Exception as e:
        logger.error(f"Batch download failed: {e}")
        # All symbols failed, try individual fallback
        failed_symbols = valid_symbols.copy()

    # Fallback to cached prices for failed symbols
    if failed_symbols:
        logger.info(f"Using cached prices for {len(failed_symbols)} failed symbols")
        for symbol in failed_symbols:
            cached = get_cached_price(symbol)
            if cached:
                price_data.append(
                    {
                        "symbol": symbol,
                        "timestamp": datetime.now(timezone.utc),
                        "price": cached["price"],
                        "previous_close": cached["previous_close"] or cached["price"],
                        "abs_change": cached["price"]
                        - (cached["previous_close"] or cached["price"]),
                        "percent_change": cached.get("percent_change", 0.0),
                    }
                )
                logger.debug(
                    f"Used {cached['source']} for {symbol}: ${cached['price']:.2f}"
                )
            else:
                logger.warning(f"No cached price available for {symbol}")

    df = pd.DataFrame(price_data)

    # Save to CSV
    if not df.empty:
        csv_path = (
            RAW_DIR / f"realtime_prices_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        )
        df.to_csv(csv_path, index=False)
        logger.info(f"Saved real-time prices to {csv_path}")

        # Update position prices for quick daily change access
        update_position_prices(df)

    return df

    return df


def save_realtime_prices_to_db(prices_df):
    """Save real-time prices to the database using unified database layer

    Args:
        prices_df: DataFrame containing real-time price data
    """
    if prices_df.empty:
        logger.warning("No price data to save")
        return

    try:
        from src.db import execute_sql, df_to_records
        import pandas as pd

        # Normalize timestamps to UTC timezone-aware
        prices_df_processed = prices_df.copy()
        prices_df_processed["timestamp"] = pd.to_datetime(
            prices_df_processed["timestamp"], utc=True
        )

        # Convert DataFrame to list of dicts for bulk operation
        records = df_to_records(prices_df_processed, utc_columns=["timestamp"])

        # Ensure proper data types for PostgreSQL columns
        for record in records:
            record["symbol"] = str(record["symbol"])  # TEXT column
            record["price"] = float(record["price"])  # REAL column
            record["previous_close"] = float(record["previous_close"])  # REAL column
            record["abs_change"] = float(record["abs_change"])  # REAL column
            record["percent_change"] = float(record["percent_change"])  # REAL column

        # PostgreSQL bulk upsert with ON CONFLICT using named placeholders
        # CRITICAL: PK order is (timestamp, symbol) in live DB - must match exactly
        query = """
        INSERT INTO realtime_prices (symbol, timestamp, price, previous_close, abs_change, percent_change)
        VALUES (:symbol, :timestamp, :price, :previous_close, :abs_change, :percent_change)
        ON CONFLICT (timestamp, symbol) DO UPDATE SET
        price = EXCLUDED.price,
        previous_close = EXCLUDED.previous_close,
        abs_change = EXCLUDED.abs_change,
        percent_change = EXCLUDED.percent_change
        """

        # Execute bulk operation
        execute_sql(query, records)
        logger.info(f"✅ Saved {len(records)} real-time price records to database")

    except Exception as e:
        logger.error(f"Error saving real-time prices to database: {e}")
        raise  # Re-raise the exception to ensure failures are visible


def fetch_historical_prices(symbols=None, period="1y", interval="1d"):
    """Fetch historical price data for the given symbols

    Args:
        symbols: List of ticker symbols to fetch prices for (default: None, uses active positions)
        period: Time period to fetch data for (default: "1y")
        interval: Data interval (default: "1d" for daily)

    Returns:
        Dictionary mapping symbols to their historical price DataFrames
    """
    # Validate period/interval combination
    is_valid, error_msg = validate_period_interval(period, interval)
    if not is_valid:
        logger.error(f"Invalid period/interval: {error_msg}")
        return {}

    if symbols is None:
        # Get symbols from the database positions table
        from src.db import execute_sql

        try:
            result = execute_sql(
                "SELECT DISTINCT symbol FROM positions WHERE quantity > 0",
                fetch_results=True,
            )
            symbols = [row[0] for row in result] if result else []
        except Exception as e:
            logger.error(f"Error fetching symbols from database: {e}")
            symbols = []

    # Clean up symbols to ensure they're valid ticker strings
    valid_symbols = []
    for symbol in symbols:
        if isinstance(symbol, str) and symbol.strip():
            clean_symbol = symbol.strip().upper()
            # Enhanced ticker validation - supports symbols like BRK.B, BF.B, etc.
            if re.match(r"^[A-Z]{1,6}(?:\.[A-Z]{1,2})?$", clean_symbol):
                valid_symbols.append(clean_symbol)

    if not valid_symbols:
        logger.warning("No valid symbols found for historical price fetching")
        return {}

    logger.info(
        f"Fetching historical prices for {len(valid_symbols)} symbols with {interval} interval for {period}"
    )

    price_history = {}
    failed_symbols = []

    for symbol in valid_symbols:
        try:
            rate_limit_delay()
            ticker = yf.Ticker(symbol)
            # CRITICAL: Use auto_adjust=False to avoid deprecation warning
            history = ticker.history(
                period=period, interval=interval, auto_adjust=False
            )

            if not history.empty:
                # Reset index to make Date a column
                history = history.reset_index()
                history["symbol"] = symbol
                price_history[symbol] = history

                # Save individual CSV
                csv_path = (
                    RAW_DIR
                    / f"historical_{symbol}_{period}_{interval}_{datetime.now().strftime('%Y%m%d')}.csv"
                )
                history.to_csv(csv_path, index=False)
            else:
                failed_symbols.append(symbol)

        except Exception as e:
            error_msg = str(e).lower()
            if "429" in str(e) or "too many requests" in error_msg:
                # Rate limited - apply exponential backoff
                delay = RATE_LIMIT_DELAY * BACKOFF_FACTOR * 2
                logger.warning(f"Rate limited fetching {symbol}, waiting {delay:.1f}s")
                time.sleep(delay)
                failed_symbols.append(symbol)
            else:
                logger.error(f"Error fetching historical data for {symbol}: {e}")
                failed_symbols.append(symbol)
            continue

    if failed_symbols:
        logger.warning(
            f"Failed to fetch historical data for {len(failed_symbols)} symbols: {failed_symbols[:5]}..."
        )

    logger.info(f"✅ Fetched historical prices for {len(price_history)} symbols")
    return price_history


def save_historical_prices_to_db(symbol, history_df):
    """Save historical prices to the PostgreSQL database using bulk upserts

    Args:
        symbol: Ticker symbol
        history_df: DataFrame containing historical price data
    """
    if history_df.empty:
        logger.warning(f"No historical data to save for {symbol}")
        return

    try:
        from src.db import execute_sql, df_to_records
        import pandas as pd

        # Prepare DataFrame with proper date formatting
        history_df_processed = history_df.copy()
        history_df_processed["Date"] = pd.to_datetime(
            history_df_processed["Date"]
        ).dt.strftime("%Y-%m-%d")
        history_df_processed["symbol"] = symbol  # Add symbol column

        # Convert DataFrame to list of dicts for bulk operation
        records = df_to_records(history_df_processed)

        # Ensure proper data types and field mapping for PostgreSQL columns
        processed_records = []
        for record in records:
            processed_record = {
                "symbol": str(symbol),
                "date": record["Date"],  # Already formatted as YYYY-MM-DD
                "open": (
                    float(record.get("Open", 0))
                    if record.get("Open") is not None
                    else None
                ),
                "high": (
                    float(record.get("High", 0))
                    if record.get("High") is not None
                    else None
                ),
                "low": (
                    float(record.get("Low", 0))
                    if record.get("Low") is not None
                    else None
                ),
                "close": (
                    float(record.get("Close", 0))
                    if record.get("Close") is not None
                    else None
                ),
                "volume": (
                    int(record.get("Volume", 0))
                    if record.get("Volume") is not None
                    else None
                ),
                "dividends": (
                    float(record.get("Dividends", 0))
                    if record.get("Dividends") is not None
                    else None
                ),
                "stock_splits": (
                    float(record.get("Stock Splits", 0))
                    if record.get("Stock Splits") is not None
                    else None
                ),
            }
            processed_records.append(processed_record)

        # PostgreSQL bulk upsert with ON CONFLICT using named placeholders
        # CRITICAL: PK order is (date, symbol) in live DB - must match exactly
        query = """
        INSERT INTO daily_prices (symbol, date, open, high, low, close, volume, dividends, stock_splits)
        VALUES (:symbol, :date, :open, :high, :low, :close, :volume, :dividends, :stock_splits)
        ON CONFLICT (date, symbol) DO UPDATE SET
        open = EXCLUDED.open,
        high = EXCLUDED.high,
        low = EXCLUDED.low,
        close = EXCLUDED.close,
        volume = EXCLUDED.volume,
        dividends = EXCLUDED.dividends,
        stock_splits = EXCLUDED.stock_splits
        """

        # Execute bulk operation
        execute_sql(query, processed_records)
        logger.info(
            f"✅ Saved {len(processed_records)} historical price records for {symbol}"
        )

    except Exception as e:
        logger.error(f"Error saving historical prices for {symbol}: {e}")


def fetch_stock_metrics(symbols=None):
    """Fetch fundamental metrics for stocks

    Args:
        symbols: List of ticker symbols to fetch metrics for (default: None, uses active positions)

    Returns:
        DataFrame containing stock metrics
    """
    if symbols is None:
        # Get symbols from the database positions table
        from src.db import execute_sql

        try:
            result = execute_sql(
                "SELECT DISTINCT symbol FROM positions WHERE quantity > 0",
                fetch_results=True,
            )
            symbols = [row[0] for row in result] if result else []
        except Exception as e:
            logger.error(f"Error fetching symbols from database: {e}")
            symbols = []

    # Clean up symbols to ensure they're valid ticker strings
    valid_symbols = []
    for symbol in symbols:
        if isinstance(symbol, str) and symbol.strip():
            clean_symbol = symbol.strip().upper()
            # Enhanced ticker validation - supports symbols like BRK.B, BF.B, etc.
            if re.match(r"^[A-Z]{1,6}(?:\.[A-Z]{1,2})?$", clean_symbol):
                valid_symbols.append(clean_symbol)

    if not valid_symbols:
        logger.warning("No valid symbols found for metrics fetching")
        return pd.DataFrame()

    logger.info(f"Fetching metrics for {len(valid_symbols)} symbols")

    metrics_data = []
    for symbol in valid_symbols:
        try:
            ticker = yf.Ticker(symbol)
            info = ticker.info

            metrics_data.append(
                {
                    "symbol": symbol,
                    "date": datetime.now(timezone.utc).date().isoformat(),
                    "pe_ratio": info.get("trailingPE"),
                    "market_cap": info.get("marketCap"),
                    "dividend_yield": info.get("dividendYield"),
                    "fifty_day_avg": info.get("fiftyDayAverage"),
                    "two_hundred_day_avg": info.get("twoHundredDayAverage"),
                }
            )
        except Exception as e:
            logger.error(f"Error fetching metrics for {symbol}: {e}")
            continue

    df = pd.DataFrame(metrics_data)

    # Save to database
    if not df.empty:
        save_stock_metrics_to_db(df)

    return df


def save_stock_metrics_to_db(metrics_df):
    """Save stock metrics to the database using unified database layer

    Args:
        metrics_df: DataFrame containing stock metrics
    """
    if metrics_df.empty:
        logger.warning("No metrics data to save")
        return

    try:
        from src.db import execute_sql, df_to_records

        # Convert DataFrame to list of dicts for bulk operation
        records = df_to_records(metrics_df)

        # Ensure proper data types for PostgreSQL columns
        processed_records = []
        for record in records:
            processed_record = {
                "symbol": str(record["symbol"]),
                "date": str(record["date"]),
                "pe_ratio": (
                    float(record["pe_ratio"])
                    if record["pe_ratio"] is not None
                    else None
                ),
                "market_cap": (
                    float(record["market_cap"])
                    if record["market_cap"] is not None
                    else None
                ),
                "dividend_yield": (
                    float(record["dividend_yield"])
                    if record["dividend_yield"] is not None
                    else None
                ),
                "fifty_day_avg": (
                    float(record["fifty_day_avg"])
                    if record["fifty_day_avg"] is not None
                    else None
                ),
                "two_hundred_day_avg": (
                    float(record["two_hundred_day_avg"])
                    if record["two_hundred_day_avg"] is not None
                    else None
                ),
            }
            processed_records.append(processed_record)

        # PostgreSQL bulk upsert with ON CONFLICT using named placeholders
        # CRITICAL: PK order is (date, symbol) in live DB - must match exactly
        query = """
        INSERT INTO stock_metrics (symbol, date, pe_ratio, market_cap, dividend_yield, fifty_day_avg, two_hundred_day_avg)
        VALUES (:symbol, :date, :pe_ratio, :market_cap, :dividend_yield, :fifty_day_avg, :two_hundred_day_avg)
        ON CONFLICT (date, symbol) DO UPDATE SET
        pe_ratio = EXCLUDED.pe_ratio,
        market_cap = EXCLUDED.market_cap,
        dividend_yield = EXCLUDED.dividend_yield,
        fifty_day_avg = EXCLUDED.fifty_day_avg,
        two_hundred_day_avg = EXCLUDED.two_hundred_day_avg
        """

        # Execute bulk operation
        execute_sql(query, processed_records)
        logger.info(
            f"✅ Saved {len(processed_records)} stock metrics records to database"
        )

    except Exception as e:
        logger.error(f"Error saving stock metrics to database: {e}")


def update_all_data():
    """Update all data: real-time prices, historical prices, and metrics for active positions"""
    # Initialize database if it doesn't exist (smart check to avoid conflicts)
    from src.db import initialize_database_smart

    if not initialize_database_smart():
        logger.error("❌ Database initialization failed")
        return False

    # Fetch active position symbols from the database
    try:
        from src.db import execute_sql

        result = execute_sql(
            "SELECT DISTINCT symbol FROM positions WHERE quantity > 0",
            fetch_results=True,
        )
        symbols = [row[0] for row in result] if result else []
    except Exception as e:
        logger.error(f"Error fetching symbols from database: {e}")
        symbols = []

    if symbols:
        # Fetch and save real-time prices
        logger.info("🔄 Fetching real-time prices...")
        realtime_df = fetch_realtime_prices(symbols)
        if not realtime_df.empty:
            save_realtime_prices_to_db(realtime_df)

        # Fetch and save historical prices
        logger.info("🔄 Fetching historical prices...")
        historical_data = fetch_historical_prices(symbols, period="1mo")  # Last month
        for symbol, history_df in historical_data.items():
            save_historical_prices_to_db(symbol, history_df)

        # Fetch and save stock metrics
        logger.info("🔄 Fetching stock metrics...")
        fetch_stock_metrics(symbols)

        logger.info("✅ All data updated successfully")
        return True
    else:
        logger.warning("⚠️ No active positions found - skipping market data updates")
        return True


def append_discord_message_to_csv(message_text, tickers=None, output_path=None):
    """Append a discord message to the discord_msgs.csv file

    Args:
        message_text: The content of the message
        tickers: List of ticker symbols mentioned in the message (optional)
        output_path: Path to the CSV file (default: data/raw/discord_msgs.csv)

    Returns:
        Path to the CSV file
    """
    output_path = output_path or DISCORD_CSV

    # Ensure directory exists
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # If tickers not provided, extract them from the message
    if tickers is None:
        # Use centralized ticker extraction from message_cleaner
        tickers = extract_ticker_symbols(message_text)

    timestamp = datetime.now(timezone.utc).isoformat()

    # Sanitize message text (replace newlines with spaces to avoid CSV corruption)
    sanitized_text = re.sub(r"[\r\n]+", " ", message_text)

    # Create the record
    record = {
        "message_id": f"manual-{int(datetime.now(timezone.utc).timestamp())}",
        "created_at": timestamp,
        "channel": "manual_entry",
        "author_name": "manual_user",
        "author_id": "manual_user",
        "content": sanitized_text,
        "is_reply": False,
        "reply_to_id": None,
        "mentions": "",
        "num_chars": len(message_text),
        "num_words": len(message_text.split()),
        "tickers_detected": ", ".join(tickers) if tickers else "",
        "tweet_urls": None,
        "sentiment_score": None,
    }

    # Check if file exists to determine if we need to write headers
    file_exists = output_path.exists()

    try:
        with open(output_path, "a", newline="", encoding="utf-8") as csvfile:
            fieldnames = record.keys()
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)

            # Write header if file is new
            if not file_exists:
                writer.writeheader()

            writer.writerow(record)

        logger.info(f"✅ Appended message to {output_path}")
        return output_path

    except Exception as e:
        logger.error(f"Error appending message to CSV: {e}")
        raise


# =====================================================
# Position Report & P/L Analysis
# =====================================================


def generate_position_report(account_id: str = None) -> dict:
    """Generate comprehensive position report with multi-period P/L calculations.

    Calculates realized and unrealized P/L for multiple time periods:
    - 1 month, 3 months, 6 months, 1 year, 2 years, max

    Args:
        account_id: Optional account ID to filter positions

    Returns:
        Dictionary containing:
        - positions: List of position summaries with P/L
        - realized_pnl: Dict of realized P/L by period
        - unrealized_pnl: Dict of unrealized P/L by period
        - total_value: Current portfolio value
        - period_returns: Dict of % returns by period
    """
    from src.db import execute_sql

    # Define periods for P/L calculation
    periods = {
        "1mo": timedelta(days=30),
        "3mo": timedelta(days=90),
        "6mo": timedelta(days=180),
        "1y": timedelta(days=365),
        "2y": timedelta(days=730),
        "max": timedelta(days=9999),  # All time
    }

    now = datetime.now(timezone.utc)

    # Fetch current positions
    position_query = """
        SELECT 
            p.symbol, p.quantity, p.price, p.equity, p.average_buy_price,
            p.open_pnl, p.current_price, p.prev_price, p.price_updated_at,
            a.name as account_name
        FROM positions p
        LEFT JOIN accounts a ON p.account_id = a.id
        WHERE p.quantity > 0
    """
    params = {}
    if account_id:
        position_query += " AND p.account_id = :account_id"
        params["account_id"] = account_id

    position_query += " ORDER BY p.equity DESC"

    positions = execute_sql(position_query, params=params, fetch_results=True)

    if not positions:
        return {
            "positions": [],
            "realized_pnl": {p: 0.0 for p in periods},
            "unrealized_pnl": {p: 0.0 for p in periods},
            "total_value": 0.0,
            "period_returns": {p: 0.0 for p in periods},
        }

    # Build position summaries
    position_summaries = []
    total_value = 0.0
    total_cost_basis = 0.0

    for row in positions:
        (
            symbol,
            quantity,
            price,
            equity,
            avg_buy,
            open_pnl,
            current,
            prev,
            updated_at,
            account,
        ) = row

        # Convert Decimal to float for calculations
        quantity = float(quantity) if quantity else 0.0
        price = float(price) if price else 0.0
        equity = float(equity) if equity else 0.0
        avg_buy = float(avg_buy) if avg_buy else 0.0
        open_pnl = float(open_pnl) if open_pnl else 0.0
        current = float(current) if current else None
        prev = float(prev) if prev else None

        # Use current_price if available, else price
        display_price = current or price or 0
        position_equity = equity or (
            quantity * display_price if quantity and display_price else 0
        )
        cost_basis = quantity * avg_buy
        unrealized = open_pnl or (position_equity - cost_basis if cost_basis else 0)

        # Calculate daily change from prev_price
        daily_change = 0.0
        daily_change_pct = 0.0
        if current and prev and prev > 0:
            daily_change = (current - prev) * (quantity or 0)
            daily_change_pct = ((current - prev) / prev) * 100

        position_summaries.append(
            {
                "symbol": symbol,
                "quantity": float(quantity or 0),
                "price": float(display_price),
                "equity": float(position_equity),
                "cost_basis": float(cost_basis),
                "avg_buy_price": float(avg_buy or 0),
                "unrealized_pnl": float(unrealized),
                "unrealized_pnl_pct": float(
                    (unrealized / cost_basis * 100) if cost_basis > 0 else 0
                ),
                "daily_change": float(daily_change),
                "daily_change_pct": float(daily_change_pct),
                "account": account or "Unknown",
                "last_updated": updated_at.isoformat() if updated_at else None,
            }
        )

        total_value += position_equity
        total_cost_basis += cost_basis

    # Calculate realized P/L from trade_history by period
    # trade_history uses trade_date column, not exit_date
    realized_pnl = {}
    for period_name, delta in periods.items():
        start_date = now - delta

        try:
            result = execute_sql(
                """
                SELECT COALESCE(SUM(realized_pnl), 0)
                FROM trade_history
                WHERE trade_date >= :start_date
                """,
                params={"start_date": start_date},
                fetch_results=True,
            )
            realized_pnl[period_name] = (
                float(result[0][0]) if result and result[0][0] else 0.0
            )
        except Exception as e:
            logger.warning(f"Could not fetch realized P/L for {period_name}: {e}")
            realized_pnl[period_name] = 0.0

    # Calculate unrealized P/L (current positions)
    total_unrealized = sum(p["unrealized_pnl"] for p in position_summaries)
    unrealized_pnl = {
        period: total_unrealized for period in periods
    }  # Same for all periods (current snapshot)

    # Calculate period returns as percentage
    period_returns = {}
    for period_name in periods:
        total_pnl = realized_pnl[period_name] + unrealized_pnl[period_name]
        period_returns[period_name] = (
            (total_pnl / total_cost_basis * 100) if total_cost_basis > 0 else 0.0
        )

    return {
        "positions": position_summaries,
        "realized_pnl": realized_pnl,
        "unrealized_pnl": unrealized_pnl,
        "total_value": float(total_value),
        "total_cost_basis": float(total_cost_basis),
        "period_returns": period_returns,
        "summary": {
            "total_positions": len(position_summaries),
            "total_daily_change": sum(p["daily_change"] for p in position_summaries),
            "winners": len([p for p in position_summaries if p["unrealized_pnl"] > 0]),
            "losers": len([p for p in position_summaries if p["unrealized_pnl"] < 0]),
        },
    }


def save_trade_to_history(
    symbol: str,
    trade_type: str,  # "buy" or "sell"
    quantity: float,
    price: float,
    order_id: str = None,
    cost_basis: float = None,
    account_id: str = None,
    source: str = "auto",
) -> bool:
    """Save a completed trade to trade_history for P/L tracking.

    Uses the existing trade_history table schema with columns:
    - id, symbol, account_id, trade_type, trade_date, quantity, execution_price,
    - total_value, cost_basis, realized_pnl, realized_pnl_pct, position_qty_before,
    - position_qty_after, holding_pct, portfolio_weight, brokerage_order_id, source

    Args:
        symbol: Ticker symbol
        trade_type: "buy" or "sell"
        quantity: Number of shares
        price: Execution price
        order_id: Optional brokerage order ID (for dedup)
        cost_basis: Cost basis for P/L calculation (for sells)
        account_id: Account ID
        source: Data source identifier

    Returns:
        True if saved successfully
    """
    from src.db import execute_sql

    try:
        now = datetime.now(timezone.utc)

        # Calculate trade value
        total_value = quantity * price

        # Calculate P/L for sells
        realized_pnl = None
        realized_pnl_pct = None

        if trade_type.lower() == "sell" and cost_basis and cost_basis > 0:
            realized_pnl = total_value - cost_basis
            realized_pnl_pct = (realized_pnl / cost_basis) * 100

        # Get current portfolio value for weight calculation
        total_query = (
            "SELECT COALESCE(SUM(equity), 0) FROM positions WHERE quantity > 0"
        )
        result = execute_sql(total_query, fetch_results=True)
        portfolio_value = float(result[0][0]) if result and result[0][0] else 0

        portfolio_weight = (
            (total_value / portfolio_value * 100) if portfolio_value > 0 else 0
        )

        # Get current position quantity for position tracking
        pos_result = execute_sql(
            "SELECT COALESCE(quantity, 0) FROM positions WHERE symbol = :symbol LIMIT 1",
            params={"symbol": symbol},
            fetch_results=True,
        )
        position_qty_before = (
            float(pos_result[0][0]) if pos_result and pos_result[0] else 0
        )

        if trade_type.lower() == "buy":
            position_qty_after = position_qty_before + quantity
        else:
            position_qty_after = position_qty_before - quantity

        # Upsert trade record using actual table columns
        query = """
        INSERT INTO trade_history (
            symbol, account_id, trade_type, trade_date, quantity, execution_price,
            total_value, cost_basis, realized_pnl, realized_pnl_pct,
            position_qty_before, position_qty_after, portfolio_weight,
            brokerage_order_id, source, created_at
        ) VALUES (
            :symbol, :account_id, :trade_type, :trade_date, :quantity, :execution_price,
            :total_value, :cost_basis, :realized_pnl, :realized_pnl_pct,
            :position_qty_before, :position_qty_after, :portfolio_weight,
            :order_id, :source, :created_at
        )
        ON CONFLICT (brokerage_order_id) DO UPDATE SET
            execution_price = EXCLUDED.execution_price,
            total_value = EXCLUDED.total_value,
            realized_pnl = EXCLUDED.realized_pnl,
            realized_pnl_pct = EXCLUDED.realized_pnl_pct,
            updated_at = NOW()
        """

        params = {
            "symbol": symbol,
            "account_id": account_id,
            "trade_type": trade_type.lower(),
            "trade_date": now,
            "quantity": float(quantity),
            "execution_price": float(price),
            "total_value": float(total_value),
            "cost_basis": float(cost_basis) if cost_basis else None,
            "realized_pnl": realized_pnl,
            "realized_pnl_pct": realized_pnl_pct,
            "position_qty_before": position_qty_before,
            "position_qty_after": position_qty_after,
            "portfolio_weight": portfolio_weight,
            "order_id": order_id,
            "source": source,
            "created_at": now,
        }

        execute_sql(query, params=params)
        logger.info(
            f"✅ Saved {trade_type} trade for {symbol}: {quantity} @ ${price:.2f}"
        )
        return True

    except Exception as e:
        logger.error(f"Error saving trade to history: {e}")
        return False


# Example usage when running this file directly
if __name__ == "__main__":
    # Initialize the database (smart initialization to avoid conflicts)
    from src.db import initialize_database_smart

    if initialize_database_smart():
        # Update all market data for active positions
        if update_all_data():
            logger.info("✅ Data collection completed successfully")
        else:
            logger.error("❌ Data collection failed")
    else:
        logger.error("❌ Database initialization failed")
