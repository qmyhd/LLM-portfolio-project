import csv
import logging
import re
import sqlite3
from datetime import datetime
from pathlib import Path

import pandas as pd
import yfinance as yf

from src.config import settings
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


def fetch_realtime_prices(symbols=None):
    """Fetch real-time prices for the given symbols or all positions

    Args:
        symbols: List of ticker symbols to fetch prices for (default: None, uses active positions)

    Returns:
        DataFrame containing real-time price data
    """
    if symbols is None:
        # Get symbols from the database positions table
        from src.database import execute_sql

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
            if re.match(r"^[A-Z]{1,5}$", clean_symbol):  # Basic ticker validation
                valid_symbols.append(clean_symbol)

    if not valid_symbols:
        logger.warning("No valid symbols found for price fetching")
        return pd.DataFrame()

    logger.info(f"Fetching real-time prices for {len(valid_symbols)} symbols")

    # Use yfinance to get current prices
    price_data = []
    for symbol in valid_symbols:
        try:
            ticker = yf.Ticker(symbol)
            info = ticker.history(period="1d", interval="1m")

            if not info.empty:
                current_price = info["Close"].iloc[-1]
                previous_close = ticker.info.get("previousClose", current_price)
                abs_change = current_price - previous_close
                percent_change = (
                    (abs_change / previous_close * 100) if previous_close else 0
                )

                price_data.append(
                    {
                        "symbol": symbol,
                        "timestamp": datetime.now().isoformat(),
                        "price": current_price,
                        "previous_close": previous_close,
                        "abs_change": abs_change,
                        "percent_change": percent_change,
                    }
                )
        except Exception as e:
            logger.error(f"Error fetching price for {symbol}: {e}")
            continue

    df = pd.DataFrame(price_data)

    # Save to CSV
    if not df.empty:
        csv_path = (
            RAW_DIR / f"realtime_prices_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        )
        df.to_csv(csv_path, index=False)
        logger.info(f"Saved real-time prices to {csv_path}")

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
        from src.database import execute_sql, use_postgres

        for _, row in prices_df.iterrows():
            if use_postgres():
                query = """
                INSERT INTO realtime_prices (symbol, timestamp, price, previous_close, abs_change, percent_change)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (symbol, timestamp) DO UPDATE SET
                price = EXCLUDED.price,
                previous_close = EXCLUDED.previous_close,
                abs_change = EXCLUDED.abs_change,
                percent_change = EXCLUDED.percent_change
                """
                params = (
                    row["symbol"],
                    row["timestamp"],
                    row["price"],
                    row["previous_close"],
                    row["abs_change"],
                    row["percent_change"],
                )
            else:
                # SQLite version
                query = """
                INSERT OR REPLACE INTO realtime_prices 
                (symbol, timestamp, price, previous_close, abs_change, percent_change)
                VALUES (?, ?, ?, ?, ?, ?)
                """
                params = (
                    row["symbol"],
                    row["timestamp"],
                    row["price"],
                    row["previous_close"],
                    row["abs_change"],
                    row["percent_change"],
                )

            execute_sql(query, params)

        logger.info(f"✅ Saved {len(prices_df)} real-time price records to database")

    except Exception as e:
        logger.error(f"Error saving real-time prices to database: {e}")


def fetch_historical_prices(symbols=None, period="1y", interval="1d"):
    """Fetch historical price data for the given symbols

    Args:
        symbols: List of ticker symbols to fetch prices for (default: None, uses active positions)
        period: Time period to fetch data for (default: "1y")
        interval: Data interval (default: "1d" for daily)

    Returns:
        Dictionary mapping symbols to their historical price DataFrames
    """
    if symbols is None:
        # Get symbols from the database positions table
        from src.database import execute_sql

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
            if re.match(r"^[A-Z]{1,5}$", clean_symbol):  # Basic ticker validation
                valid_symbols.append(clean_symbol)

    if not valid_symbols:
        logger.warning("No valid symbols found for historical price fetching")
        return {}

    logger.info(
        f"Fetching historical prices for {len(valid_symbols)} symbols with {interval} interval for {period}"
    )

    price_history = {}
    for symbol in valid_symbols:
        try:
            ticker = yf.Ticker(symbol)
            history = ticker.history(period=period, interval=interval)

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

        except Exception as e:
            logger.error(f"Error fetching historical data for {symbol}: {e}")
            continue

    logger.info(f"✅ Fetched historical prices for {len(price_history)} symbols")
    return price_history


def save_historical_prices_to_db(symbol, history_df):
    """Save historical prices to the SQLite database using append-only writes

    Args:
        symbol: Ticker symbol
        history_df: DataFrame containing historical price data
    """
    if history_df.empty:
        logger.warning(f"No historical data to save for {symbol}")
        return

    try:
        from src.database import execute_sql, use_postgres

        for _, row in history_df.iterrows():
            date_str = (
                row["Date"].strftime("%Y-%m-%d")
                if hasattr(row["Date"], "strftime")
                else str(row["Date"])
            )

            if use_postgres():
                query = """
                INSERT INTO daily_prices (symbol, date, open, high, low, close, volume, dividends, stock_splits)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (symbol, date) DO UPDATE SET
                open = EXCLUDED.open,
                high = EXCLUDED.high,
                low = EXCLUDED.low,
                close = EXCLUDED.close,
                volume = EXCLUDED.volume,
                dividends = EXCLUDED.dividends,
                stock_splits = EXCLUDED.stock_splits
                """
                params = (
                    symbol,
                    date_str,
                    row.get("Open"),
                    row.get("High"),
                    row.get("Low"),
                    row.get("Close"),
                    row.get("Volume", 0),
                    row.get("Dividends", 0),
                    row.get("Stock Splits", 0),
                )
            else:
                # SQLite version
                query = """
                INSERT OR REPLACE INTO daily_prices 
                (symbol, date, open, high, low, close, volume, dividends, stock_splits)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """
                params = (
                    symbol,
                    date_str,
                    row.get("Open"),
                    row.get("High"),
                    row.get("Low"),
                    row.get("Close"),
                    row.get("Volume", 0),
                    row.get("Dividends", 0),
                    row.get("Stock Splits", 0),
                )

            execute_sql(query, params)

        logger.info(f"✅ Saved {len(history_df)} historical price records for {symbol}")

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
        from src.database import execute_sql

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
            if re.match(r"^[A-Z]{1,5}$", clean_symbol):  # Basic ticker validation
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
                    "date": datetime.now().date().isoformat(),
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
        from src.database import execute_sql, use_postgres

        for _, row in metrics_df.iterrows():
            if use_postgres():
                query = """
                INSERT INTO stock_metrics (symbol, date, pe_ratio, market_cap, dividend_yield, fifty_day_avg, two_hundred_day_avg)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (symbol, date) DO UPDATE SET
                pe_ratio = EXCLUDED.pe_ratio,
                market_cap = EXCLUDED.market_cap,
                dividend_yield = EXCLUDED.dividend_yield,
                fifty_day_avg = EXCLUDED.fifty_day_avg,
                two_hundred_day_avg = EXCLUDED.two_hundred_day_avg
                """
                params = (
                    row["symbol"],
                    row["date"],
                    row["pe_ratio"],
                    row["market_cap"],
                    row["dividend_yield"],
                    row["fifty_day_avg"],
                    row["two_hundred_day_avg"],
                )
            else:
                # SQLite version
                query = """
                INSERT OR REPLACE INTO stock_metrics 
                (symbol, date, pe_ratio, market_cap, dividend_yield, fifty_day_avg, two_hundred_day_avg)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """
                params = (
                    row["symbol"],
                    row["date"],
                    row["pe_ratio"],
                    row["market_cap"],
                    row["dividend_yield"],
                    row["fifty_day_avg"],
                    row["two_hundred_day_avg"],
                )

            execute_sql(query, params)

        logger.info(f"✅ Saved {len(metrics_df)} stock metrics records to database")

    except Exception as e:
        logger.error(f"Error saving stock metrics to database: {e}")


def update_all_data():
    """Update all data: real-time prices, historical prices, and metrics for active positions"""
    # Initialize database if it doesn't exist
    from src.database import initialize_database

    initialize_database()

    # Fetch active position symbols from the database
    try:
        from src.database import execute_sql

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

    timestamp = datetime.now().isoformat()

    # Sanitize message text (replace newlines with spaces to avoid CSV corruption)
    sanitized_text = re.sub(r"[\r\n]+", " ", message_text)

    # Create the record
    record = {
        "message_id": f"manual-{int(datetime.now().timestamp())}",
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


# Example usage when running this file directly
if __name__ == "__main__":
    # Initialize the database
    from src.database import initialize_database

    initialize_database()

    # Update all market data for active positions
    update_all_data()

    logger.info("✅ Data collection completed successfully")
