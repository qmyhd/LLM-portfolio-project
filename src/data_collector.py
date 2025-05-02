import os
import pandas as pd
import yfinance as yf
from pprint import pprint
import csv
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from dotenv import load_dotenv
from snaptrade_client import SnapTrade
import logging
import json
import re

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

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
POSITIONS_CSV = RAW_DIR / "positions.csv"
ORDERS_CSV = RAW_DIR / "orders.csv"
PRICES_CSV = RAW_DIR / "prices.csv"
PRICE_DB = DB_DIR / "price_history.db"

# SnapTrade credentials
client_id = os.getenv("SNAPTRADE_CLIENT_ID")
consumer_key = os.getenv("SNAPTRADE_CONSUMER_KEY")
user_id = os.getenv("SNAPTRADE_USER_ID") or os.getenv("userId")
user_secret = os.getenv("SNAPTRADE_USER_SECRET") or os.getenv("userSecret")
account_id = os.getenv("ROBINHOOD_ACCOUNT_ID")

def initialize_snaptrade():
    """Initialize the SnapTrade client with credentials from environment variables"""
    client_id = os.getenv("SNAPTRADE_CLIENT_ID")
    consumer_key = os.getenv("SNAPTRADE_CONSUMER_KEY")
    
    if not client_id or not consumer_key:
        raise ValueError("Missing SnapTrade credentials in environment variables")
    
    return SnapTrade(
        client_id=client_id,
        consumer_key=consumer_key
    )

def initialize_price_database():
    """Initialize the SQLite database for storing price history
    
    Creates tables for daily prices and real-time prices if they don't exist
    """
    conn = sqlite3.connect(PRICE_DB)
    cursor = conn.cursor()
    
    # Create daily price history table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS daily_prices (
        id INTEGER PRIMARY KEY,
        symbol TEXT NOT NULL,
        date TEXT NOT NULL,
        open REAL,
        high REAL,
        low REAL,
        close REAL,
        volume INTEGER,
        dividends REAL,
        stock_splits REAL,
        UNIQUE(symbol, date)
    )
    ''')
    
    # Create real-time price table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS realtime_prices (
        id INTEGER PRIMARY KEY,
        symbol TEXT NOT NULL,
        timestamp TEXT NOT NULL,
        price REAL,
        previous_close REAL,
        change REAL,
        change_percent REAL,
        UNIQUE(symbol, timestamp)
    )
    ''')
    
    # Create table for stock metrics
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS stock_metrics (
        id INTEGER PRIMARY KEY,
        symbol TEXT NOT NULL,
        date TEXT NOT NULL,
        pe_ratio REAL,
        market_cap REAL,
        dividend_yield REAL,
        fifty_day_avg REAL,
        two_hundred_day_avg REAL,
        UNIQUE(symbol, date)
    )
    ''')
    
    conn.commit()
    conn.close()
    logger.info("✅ Price database initialized")
    
def extract_symbol_from_data(symbol_data):
    """
    Return a clean ticker string from the messy SnapTrade payload.
    Walks nested dicts until it finds something that looks like “MSFT”.

    Args:
        symbol_data: A string or nested dictionary containing symbol information.

    Returns:
        A cleaned ticker string if found, otherwise None.

    Example:
        Input: {"raw_symbol": "MSFT", "id": "12345"}
        Output: "MSFT"
    """
    # already a string ➜ done
    if isinstance(symbol_data, str):
        return symbol_data.strip()

    if not isinstance(symbol_data, dict):
        return None

    # search priority (don’t touch 'id' until last)
    KEYS = ['raw_symbol', 'symbol', 'SYMBOL', 'ticker',
            'Ticker', 'universal_symbol_symbol']

    def _search(d: dict):
        # 1️⃣  look at the preferred keys
        for k in KEYS:
            if k in d:
                v = d[k]
                if isinstance(v, str) and v.strip():
                    return v.strip()
                if isinstance(v, dict):
                    found = _search(v)
                    if found:
                        return found
        # 2️⃣  scan any other nested dicts
        for v in d.values():
            if isinstance(v, dict):
                found = _search(v)
                if found:
                    return found
        return None

    res = _search(symbol_data)
    if res:
        return res

    # last-ditch: short “id” values that *look* like tickers, not UUIDs
    id_val = symbol_data.get('id')
    if isinstance(id_val, str) and '-' not in id_val and len(id_val) <= 5:
        return id_val.strip()

    return None

def get_account_positions(account_id=None, user_id=None, user_secret=None):
    """Get positions for a specific account using SnapTrade
    
    Args:
        account_id: The Robinhood account ID to fetch positions for
        user_id: The SnapTrade user ID 
        user_secret: The SnapTrade user secret
        
    Returns:
        DataFrame containing position data
    """
    # Use environment variables as defaults if not provided
    account_id = account_id or os.getenv("ROBINHOOD_ACCOUNT_ID")
    user_id = user_id or os.getenv("SNAPTRADE_USER_ID") or os.getenv("userId")
    user_secret = user_secret or os.getenv("SNAPTRADE_USER_SECRET") or os.getenv("userSecret")
    
    if not all([account_id, user_id, user_secret]):
        raise ValueError("Missing required parameters: account_id, user_id, or user_secret")
    
    snaptrade = initialize_snaptrade()
    
    response = snaptrade.account_information.get_user_account_positions(
        account_id=account_id,
        user_id=user_id,
        user_secret=user_secret
    )
    
    if not response.body:
        logger.warning("No positions found")
        return pd.DataFrame()
    
    # Log raw response data for debugging
    logger.info(f"Raw SnapTrade response: {response.body[:2]}")  # Log first 2 positions to avoid large output
    
    # Convert response to DataFrame
    positions = []
    for position in response.body:
        # Extract ticker symbol properly from nested dictionary
        symbol_data = position.get('symbol', {})
        symbol = extract_symbol_from_data(symbol_data)
        
        # If we couldn't extract a valid symbol, try to identify it from other data
        if not symbol:
            # Try to extract from security_type or other fields
            symbol = position.get('symbol_id') or position.get('id') or "Unknown"
            logger.warning(f"Using fallback symbol identification: {symbol}")
        
        # Calculate values correctly - ensure they're floating point numbers
        try:
            quantity = float(position.get('units', 0) or 0)
            price = float(position.get('price', 0) or 0)
            equity = quantity * price
            
            # Calculate average buy price safely
            book_value = float(position.get('book_value', 0) or 0)
            avg_buy_price = book_value / quantity if quantity and quantity != 0 else 0
        except (ValueError, TypeError) as e:
            logger.error(f"Error converting position values: {e}")
            quantity = 0
            price = 0
            equity = 0
            avg_buy_price = 0
        
        # If we have price and quantity but no symbol, try to look it up
        if price > 0 and quantity > 0 and (not symbol or symbol == "Unknown"):
            # This is where we would implement a price-based lookup
            # For now, use "Symbol-" + truncated price as placeholder
            symbol = f"Symbol-{price:.2f}"
            logger.warning(f"Using price-based symbol identification: {symbol}")
        
        data = {
            'symbol': symbol,
            'quantity': quantity,
            'equity': equity,
            'price': price,
            'average_buy_price': avg_buy_price,
            'security_type': position.get('security_type', 'Unknown'),
            'currency': 'USD',  # Simplify currency to just the code
        }
        positions.append(data)
    
    # Create DataFrame and sort by equity (descending)
    positions_df = pd.DataFrame(positions)
    if not positions_df.empty and 'equity' in positions_df.columns:
        positions_df = positions_df.sort_values('equity', ascending=False)
    
    # Log summary of positions for debugging
    if not positions_df.empty:
        logger.info(f"Extracted {len(positions_df)} positions, top symbols: {positions_df['symbol'].head(5).tolist()}")
        logger.info(f"Total equity value: ${positions_df['equity'].sum():.2f}")
    
    return positions_df

def get_account_balance(account_id=None, user_id=None, user_secret=None):
    """Get account balance using SnapTrade
    
    Args:
        account_id: The Robinhood account ID
        user_id: The SnapTrade user ID
        user_secret: The SnapTrade user secret
        
    Returns:
        Dictionary containing account balance information
    """
    account_id = account_id or os.getenv("ROBINHOOD_ACCOUNT_ID")
    user_id = user_id or os.getenv("SNAPTRADE_USER_ID") or os.getenv("userId")
    user_secret = user_secret or os.getenv("SNAPTRADE_USER_SECRET") or os.getenv("userSecret")
    
    if not all([account_id, user_id, user_secret]):
        raise ValueError("Missing required parameters: account_id, user_id, or user_secret")
    
    snaptrade = initialize_snaptrade()
    
    response = snaptrade.account_information.get_user_account_balance(
        account_id=account_id,
        user_id=user_id,
        user_secret=user_secret
    )
    
    if not response.body:
        logger.warning("No balance information found")
        return {}
    
    return response.body

def get_recent_orders(account_id=None, user_id=None, user_secret=None, state="all", days=30, limit=20):
    """Get recent orders using SnapTrade
    
    Args:
        account_id: The Robinhood account ID
        user_id: The SnapTrade user ID
        user_secret: The SnapTrade user secret
        state: Order state to filter by ('all', 'open', 'executed')
        days: Number of days to look back for orders
        limit: Maximum number of orders to return
        
    Returns:
        List containing order information
    """
    account_id = account_id or os.getenv("ROBINHOOD_ACCOUNT_ID")
    user_id = user_id or os.getenv("SNAPTRADE_USER_ID") or os.getenv("userId")
    user_secret = user_secret or os.getenv("SNAPTRADE_USER_SECRET") or os.getenv("userSecret")
    
    if not all([account_id, user_id, user_secret]):
        raise ValueError("Missing required parameters: account_id, user_id, or user_secret")
    
    snaptrade = initialize_snaptrade()
    
    response = snaptrade.account_information.get_user_account_orders(
        account_id=account_id,
        user_id=user_id,
        user_secret=user_secret,
        state=state,
        days=days
    )
    
    if not response.body:
        logger.warning("No orders found")
        return []
    
    # Process the orders to extract ticker symbols properly
    processed_orders = []
    for order in response.body:
        # Extract symbol from nested structure if needed
        symbol = None
        symbol_data = order.get('symbol', {})
        
        if isinstance(symbol_data, dict):
            # Try to get the symbol directly from the nested dictionary
            symbol = symbol_data.get('symbol')
            
            # If not found, try other possible keys
            if not symbol:
                symbol = (symbol_data.get('SYMBOL') or 
                         symbol_data.get('RAW_SYMBOL') or 
                         symbol_data.get('raw_symbol'))
                
            # If still not found, look for id or description as fallback
            if not symbol:
                symbol = (symbol_data.get('id') or 
                         symbol_data.get('description') or
                         symbol_data.get('ticker'))
        elif isinstance(symbol_data, str):
            symbol = symbol_data
        
        # Add the extracted symbol to the order data
        if symbol and isinstance(symbol, str) and symbol.lower() != 'unknown':
            order['extracted_symbol'] = symbol.strip()
        else:
            order['extracted_symbol'] = 'Unknown'
            
        # Add order to processed list
        processed_orders.append(order)
    
    # Return just the first 'limit' processed orders
    return processed_orders[:limit] if limit else processed_orders

def save_positions_to_csv(output_path=None):
    """Get positions and save to CSV
    
    Args:
        output_path: Path to save the CSV file (default: data/raw/positions.csv)
    
    Returns:
        Path to the saved CSV file
    """
    output_path = output_path or POSITIONS_CSV
    
    # Ensure directory exists
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    positions_df = get_account_positions()
    
    if not positions_df.empty:
        positions_df.to_csv(output_path, index=False)
        logger.info(f"✅ Saved {len(positions_df)} positions to {output_path}")
        return output_path
    else:
        logger.warning("❌ No positions to save")
        return None

def save_orders_to_csv(output_path=None, days=30):
    """Get recent orders and save to CSV
    
    Args:
        output_path: Path to save the CSV file (default: data/raw/orders.csv)
        days: Number of days to look back for orders
    
    Returns:
        Path to the saved CSV file
    """
    output_path = output_path or ORDERS_CSV
    
    # Ensure directory exists
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    orders = get_recent_orders(days=days)
    
    if orders:
        # Convert to DataFrame - this will include our extracted_symbol field
        orders_df = pd.DataFrame(orders)
        
        # If the dataframe has nested dictionaries in any columns, flatten them
        # This is particularly important for symbol column which might be a dictionary
        for col in orders_df.columns:
            if orders_df[col].apply(lambda x: isinstance(x, dict)).any():
                # For dictionary columns, extract key values and create new columns
                for key in set().union(*[d.keys() for d in orders_df[col] if isinstance(d, dict)]):
                    orders_df[f"{col}_{key}"] = orders_df[col].apply(
                        lambda x: x.get(key) if isinstance(x, dict) else None
                    )
                
                # Drop the original dictionary column if we created new columns from it
                if any(col + '_' in c for c in orders_df.columns):
                    orders_df = orders_df.drop(columns=[col])
        
        # Make sure we use the extracted symbol field that we added
        if 'extracted_symbol' in orders_df.columns:
            # Rename it to be clearer
            orders_df = orders_df.rename(columns={'extracted_symbol': 'symbol'})
        
        # Save to CSV
        orders_df.to_csv(output_path, index=False)
        logger.info(f"✅ Saved {len(orders_df)} orders to {output_path}")
        return output_path
    else:
        logger.warning("❌ No orders to save")
        return None

def fetch_realtime_prices(symbols=None):
    """Fetch real-time prices for the given symbols or all positions
    
    Args:
        symbols: List of ticker symbols to fetch prices for (default: None, uses active positions)
        
    Returns:
        DataFrame containing real-time price data
    """
    if symbols is None:
        # Get symbols from positions if not provided
        positions_df = get_account_positions()
        if positions_df.empty:
            logger.warning("No positions found and no symbols provided")
            return pd.DataFrame()
        symbols = positions_df['symbol'].tolist()
    
    # Clean up symbols to ensure they're valid ticker strings
    valid_symbols = []
    for symbol in symbols:
        # Handle dictionary objects (nested symbol representation)
        if isinstance(symbol, dict):
            # Try to extract symbol from dictionary
            ticker_symbol = symbol.get('SYMBOL') or symbol.get('symbol') or symbol.get('RAW_SYMBOL') or symbol.get('raw_symbol')
            if ticker_symbol and isinstance(ticker_symbol, str) and ticker_symbol.lower() != 'unknown' and ticker_symbol.strip():
                valid_symbols.append(ticker_symbol)
                continue
            else:
                logger.warning(f"Skipping dictionary-type symbol with invalid or missing ticker: {symbol}")
                continue
                
        # Handle string symbols
        if isinstance(symbol, str):
            # Skip empty strings, "UNKNOWN", or strings that look like JSON objects
            if not symbol.strip() or symbol.lower() == 'unknown' or symbol.startswith('{'):
                logger.warning(f"Skipping invalid symbol: {symbol}")
                continue
            valid_symbols.append(symbol)
        else:
            logger.warning(f"Skipping non-string, non-dict symbol of type {type(symbol)}: {symbol}")
    
    if not valid_symbols:
        logger.warning("No valid symbols to fetch prices for")
        return pd.DataFrame()
    
    logger.info(f"Fetching real-time prices for {len(valid_symbols)} symbols")
    
    # Use yfinance to get current prices
    price_data = []
    for symbol in valid_symbols:
        try:
            ticker = yf.Ticker(symbol)
            # Get the latest price information
            info = ticker.info
            
            # Skip if we didn't get any information
            if not info:
                logger.warning(f"No info data found for symbol: {symbol}")
                continue
                
            previous_close = info.get('previousClose', 0)
            current_price = info.get('regularMarketPrice', 0)
            
            # Calculate change
            change = current_price - previous_close
            change_percent = (change / previous_close * 100) if previous_close > 0 else 0
            
            price_data.append({
                'symbol': symbol,
                'price': current_price,
                'previous_close': previous_close,
                'change': change,
                'change_percent': change_percent,
                'timestamp': datetime.now().isoformat()
            })
            
        except Exception as e:
            logger.error(f"Error fetching price for {symbol}: {e}")
    
    df = pd.DataFrame(price_data)
    
    # Save to CSV
    if not df.empty:
        df.to_csv(PRICES_CSV, index=False)
        logger.info(f"✅ Saved real-time prices to {PRICES_CSV}")
        
        # Also save to database
        save_realtime_prices_to_db(df)
    
    return df

def save_realtime_prices_to_db(prices_df):
    """Save real-time prices to the SQLite database
    
    Args:
        prices_df: DataFrame containing real-time price data
    """
    if prices_df.empty:
        return
    
    try:
        conn = sqlite3.connect(PRICE_DB)
        
        # Insert into realtime_prices table
        prices_df.to_sql('realtime_prices', conn, if_exists='append', index=False)
        
        conn.commit()
        conn.close()
        logger.info(f"✅ Saved {len(prices_df)} real-time prices to database")
    except Exception as e:
        logger.error(f"Error saving prices to database: {e}")

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
        # Get symbols from positions if not provided
        positions_df = get_account_positions()
        if positions_df.empty:
            logger.warning("No positions found and no symbols provided")
            return {}
        symbols = positions_df['symbol'].tolist()
    
    # Clean up symbols to ensure they're valid ticker strings
    valid_symbols = []
    for symbol in symbols:
        # Handle dictionary objects (nested symbol representation)
        if isinstance(symbol, dict):
            # Try to extract symbol from dictionary
            ticker_symbol = symbol.get('SYMBOL') or symbol.get('symbol') or symbol.get('RAW_SYMBOL') or symbol.get('raw_symbol')
            if ticker_symbol and isinstance(ticker_symbol, str) and ticker_symbol.lower() != 'unknown' and ticker_symbol.strip():
                valid_symbols.append(ticker_symbol)
                continue
            else:
                logger.warning(f"Skipping dictionary-type symbol with invalid or missing ticker: {symbol}")
                continue
                
        # Handle string symbols
        if isinstance(symbol, str):
            # Skip empty strings, "UNKNOWN", or strings that look like JSON objects
            if not symbol.strip() or symbol.lower() == 'unknown' or symbol.startswith('{'):
                logger.warning(f"Skipping invalid symbol: {symbol}")
                continue
            valid_symbols.append(symbol)
        else:
            logger.warning(f"Skipping non-string, non-dict symbol of type {type(symbol)}: {symbol}")
    
    if not valid_symbols:
        logger.warning("No valid symbols to fetch historical prices for")
        return {}
    
    logger.info(f"Fetching historical prices for {len(valid_symbols)} symbols with {interval} interval for {period}")
    
    price_history = {}
    for symbol in valid_symbols:
        try:
            ticker = yf.Ticker(symbol)
            history = ticker.history(period=period, interval=interval)
            
            # Skip if history is empty
            if history.empty:
                logger.warning(f"No history data found for symbol: {symbol}")
                continue
            
            # Reset index to move Date from index to column
            history = history.reset_index()
            
            # Ensure Date column contains datetime objects before using .dt accessor
            if 'Date' in history.columns and pd.api.types.is_datetime64_any_dtype(history['Date']):
                history['Date'] = history['Date'].dt.strftime('%Y-%m-%d')
            else:
                logger.warning(f"Date column missing or not datetime for {symbol}")
                # Convert Date to string if it exists but isn't a datetime
                if 'Date' in history.columns:
                    history['Date'] = history['Date'].astype(str)
            
            price_history[symbol] = history
            
            # Save to database
            save_historical_prices_to_db(symbol, history)
            
        except Exception as e:
            logger.error(f"Error fetching historical prices for {symbol}: {e}")
    
    return price_history

def save_historical_prices_to_db(symbol, history_df):
    """Save historical prices to the SQLite database
    
    Args:
        symbol: Ticker symbol
        history_df: DataFrame containing historical price data
    """
    if history_df.empty:
        return
    
    try:
        conn = sqlite3.connect(PRICE_DB)
        cursor = conn.cursor()
        
        # Insert each row into the daily_prices table
        for _, row in history_df.iterrows():
            cursor.execute('''
            INSERT OR REPLACE INTO daily_prices 
            (symbol, date, open, high, low, close, volume, dividends, stock_splits)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                symbol,
                row['Date'],
                row['Open'],
                row['High'],
                row['Low'],
                row['Close'],
                row['Volume'],
                row['Dividends'],
                row['Stock Splits']
            ))
        
        conn.commit()
        conn.close()
        logger.info(f"✅ Saved historical prices for {symbol} to database")
    except Exception as e:
        logger.error(f"Error saving historical prices to database for {symbol}: {e}")

def fetch_stock_metrics(symbols=None):
    """Fetch fundamental metrics for stocks
    
    Args:
        symbols: List of ticker symbols to fetch metrics for (default: None, uses active positions)
        
    Returns:
        DataFrame containing stock metrics
    """
    if symbols is None:
        # Get symbols from positions if not provided
        positions_df = get_account_positions()
        if positions_df.empty:
            logger.warning("No positions found and no symbols provided")
            return pd.DataFrame()
        symbols = positions_df['symbol'].tolist()
    
    # Clean up symbols to ensure they're valid ticker strings
    valid_symbols = []
    for symbol in symbols:
        # Handle dictionary objects (nested symbol representation)
        if isinstance(symbol, dict):
            # Try to extract symbol from dictionary
            ticker_symbol = symbol.get('SYMBOL') or symbol.get('symbol') or symbol.get('RAW_SYMBOL') or symbol.get('raw_symbol')
            if ticker_symbol and isinstance(ticker_symbol, str) and ticker_symbol.lower() != 'unknown' and ticker_symbol.strip():
                valid_symbols.append(ticker_symbol)
                continue
            else:
                logger.warning(f"Skipping dictionary-type symbol with invalid or missing ticker: {symbol}")
                continue
                
        # Handle string symbols
        if isinstance(symbol, str):
            # Skip empty strings, "UNKNOWN", or strings that look like JSON objects
            if not symbol.strip() or symbol.lower() == 'unknown' or symbol.startswith('{'):
                logger.warning(f"Skipping invalid symbol: {symbol}")
                continue
            valid_symbols.append(symbol)
        else:
            logger.warning(f"Skipping non-string, non-dict symbol of type {type(symbol)}: {symbol}")
    
    if not valid_symbols:
        logger.warning("No valid symbols to fetch metrics for")
        return pd.DataFrame()
    
    logger.info(f"Fetching metrics for {len(valid_symbols)} symbols")
    
    metrics_data = []
    for symbol in valid_symbols:
        try:
            ticker = yf.Ticker(symbol)
            info = ticker.info
            
            # Skip if we didn't get any information
            if not info:
                logger.warning(f"No info data found for symbol: {symbol}")
                continue
                
            metrics_data.append({
                'symbol': symbol,
                'date': datetime.now().strftime('%Y-%m-%d'),
                'pe_ratio': info.get('trailingPE', None),
                'market_cap': info.get('marketCap', None),
                'dividend_yield': info.get('dividendYield', None) * 100 if info.get('dividendYield') else None,
                'fifty_day_avg': info.get('fiftyDayAverage', None),
                'two_hundred_day_avg': info.get('twoHundredDayAverage', None)
            })
            
        except Exception as e:
            logger.error(f"Error fetching metrics for {symbol}: {e}")
    
    df = pd.DataFrame(metrics_data)
    
    # Save to database
    if not df.empty:
        save_stock_metrics_to_db(df)
    
    return df

def save_stock_metrics_to_db(metrics_df):
    """Save stock metrics to the SQLite database
    
    Args:
        metrics_df: DataFrame containing stock metrics
    """
    if metrics_df.empty:
        return
    
    try:
        conn = sqlite3.connect(PRICE_DB)
        
        # Insert into stock_metrics table
        metrics_df.to_sql('stock_metrics', conn, if_exists='append', index=False)
        
        conn.commit()
        conn.close()
        logger.info(f"✅ Saved metrics for {len(metrics_df)} stocks to database")
    except Exception as e:
        logger.error(f"Error saving stock metrics to database: {e}")

def update_all_data():
    """Update all data: positions, orders, real-time prices, historical prices, and metrics"""
    # Initialize database if it doesn't exist
    initialize_price_database()
    
    # Save positions and orders
    positions_path = save_positions_to_csv()
    save_orders_to_csv(days=180)  # Get the last 6 months of orders
    
    # Fetch active position symbols
    positions_df = pd.read_csv(positions_path) if positions_path else pd.DataFrame()
    symbols = positions_df['symbol'].tolist() if not positions_df.empty else []
    
    if symbols:
        # Fetch and save real-time prices
        fetch_realtime_prices(symbols)
        
        # Fetch and save historical prices for the last month with daily interval
        fetch_historical_prices(symbols, period="1mo", interval="1d")
        
        # Fetch and save stock metrics
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
        tickers = extract_ticker_symbols(message_text)
    
    # Create a timestamp
    timestamp = datetime.now().isoformat()
    
    # Sanitize message text (replace newlines with spaces to avoid CSV corruption)
    sanitized_text = re.sub(r'[\r\n]+', ' ', message_text)
    
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
        "sentiment_score": None
    }
    
    # Check if file exists to determine if we need to write headers
    file_exists = output_path.exists()
    
    try:
        with open(output_path, mode="a", encoding="utf-8", newline='') as f:
            writer = csv.DictWriter(f, fieldnames=record.keys())
            if not file_exists:
                writer.writeheader()
            writer.writerow(record)
        
        logger.info(f"✅ Appended message with {len(tickers) if tickers else 0} tickers to {output_path}")
        return output_path
    except Exception as e:
        logger.error(f"❌ Error appending message to CSV: {e}")
        return None

def extract_ticker_symbols(text):
    """Extract ticker symbols from text, matching $TICKER format anywhere in the text
    
    Args:
        text: The text to extract ticker symbols from
        
    Returns:
        List of unique ticker symbols
    """
    if not text:
        return []
    
    # Find all instances of $TICKER anywhere in text using finditer for better position tracking
    matches = list(re.finditer(r'\$[A-Z]{1,6}\b', text))
    
    # Extract unique tickers while preserving order
    unique_tickers = []
    for match in matches:
        ticker = match.group(0)
        if ticker not in unique_tickers:
            unique_tickers.append(ticker)
            
    return unique_tickers

# Example usage when running this file directly
if __name__ == "__main__":
    # Initialize the price database
    initialize_price_database()
    
    # Get account summary for display
    balance = get_account_balance()
    
    # Debug logging to see the actual structure of the balance object
    logger.info(f"Balance object type: {type(balance)}")
    logger.info(f"Balance content: {balance}")
    
    # Handle balance data which may be a list instead of a dictionary
    total_balance = 0
    try:
        if isinstance(balance, dict):
            total_balance = balance.get('total', {}).get('amount', 0)
        elif isinstance(balance, list) and balance:
            # If it's a list, try to extract balance from the first item
            first_balance = balance[0]
            if isinstance(first_balance, dict):
                # Calculate total from available fields
                cash = first_balance.get('cash', 0)
                buying_power = first_balance.get('buying_power', 0)
                
                # In many brokerage APIs, the total balance is derived from these values
                # Buying power often represents cash + margin available
                if 'total' in first_balance:
                    total_balance = first_balance.get('total', 0)
                else:
                    # For Robinhood/SnapTrade, buying power is typically 2x cash for margin accounts
                    # So we'll use a reasonable formula to estimate total equity
                    equity_value = buying_power - cash if buying_power > cash else buying_power/2
                    total_balance = equity_value + cash
                
                logger.info(f"Cash: ${cash:.2f}, Buying Power: ${buying_power:.2f}")
            else:
                logger.warning("Balance structure is unexpected, couldn't extract total")
    except Exception as e:
        logger.error(f"Error processing balance data: {e}")
    
    logger.info(f"\n📊 Portfolio Summary")
    logger.info(f"Total Balance: ${total_balance:.2f}")
    
    # Update all data
    update_all_data()