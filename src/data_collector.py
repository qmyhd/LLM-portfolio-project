
import csv
import logging
import sqlite3
from datetime import datetime
from pathlib import Path

import pandas as pd
import yfinance as yf

from src.config import settings

try:
    from snaptrade_client import SnapTrade
except Exception as e:  # pragma: no cover - optional dependency
    SnapTrade = None
    logging.warning(f"SnapTrade SDK import failed: {e}")
import json
import re

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
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
POSITIONS_CSV = RAW_DIR / "positions.csv"
ORDERS_CSV = RAW_DIR / "orders.csv"
PRICES_CSV = RAW_DIR / "prices.csv"
PRICE_DB = DB_DIR / "price_history.db"

def initialize_snaptrade():
    """Initialize the SnapTrade client with credentials from environment variables."""
    if SnapTrade is None:
        raise ImportError("SnapTrade SDK is not available")

    config = settings()
    client_id = getattr(config, 'SNAPTRADE_CLIENT_ID', '') or getattr(config, 'snaptrade_client_id', '')
    consumer_key = getattr(config, 'SNAPTRADE_CONSUMER_KEY', '') or getattr(config, 'snaptrade_consumer_key', '')

    if not client_id or not consumer_key:
        raise ValueError("Missing SnapTrade credentials in environment variables")

    return SnapTrade(
        client_id=client_id,
        consumer_key=consumer_key
    )

# Database initialization is now handled by src.database.initialize_database()
# This consolidates both social and financial data table creation
    
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
            'Ticker', 'universal_symbol_symbol', 'instrument_symbol']

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

def extract_symbol_from_data_enhanced(symbol_data):
    """
    Enhanced version of extract_symbol_from_data with instrument_symbol fallback.
    
    Args:
        symbol_data: A string or nested dictionary containing symbol information.
        
    Returns:
        A cleaned ticker string if found, otherwise None.
    """
    # First try the original function
    result = extract_symbol_from_data(symbol_data)
    if result:
        return result
    
    # If the original function failed and we have a dict, try instrument_symbol fallback
    if isinstance(symbol_data, dict):
        instrument_symbol = symbol_data.get('instrument_symbol')
        if isinstance(instrument_symbol, str) and instrument_symbol.strip() and '-' not in instrument_symbol:
            return instrument_symbol.strip()
    
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
    config = settings()
    account_id = account_id or getattr(config, 'ROBINHOOD_ACCOUNT_ID', '') or getattr(config, 'robinhood_account_id', '')
    user_id = user_id or getattr(config, 'SNAPTRADE_USER_ID', '') or getattr(config, 'snaptrade_user_id', '') or getattr(config, 'userid', '')
    user_secret = user_secret or getattr(config, 'SNAPTRADE_USER_SECRET', '') or getattr(config, 'snaptrade_user_secret', '') or getattr(config, 'usersecret', '')
    
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
    try:
        body = getattr(response, 'body', None)
        if body and hasattr(body, '__len__') and hasattr(body, '__getitem__'):
            logger.info(f"Raw SnapTrade response: {body[:2]}")  # Log first 2 positions to avoid large output
    except (TypeError, AttributeError, Exception):
        logger.info(f"Raw SnapTrade response: {type(getattr(response, 'body', None))}")
    
    # Convert response to DataFrame
    positions = []
    try:
        body = getattr(response, 'body', None)
        if body and hasattr(body, '__iter__'):
            for position in body:
                # Extract ticker symbol properly from nested dictionary with enhanced fallback
                symbol_data = position.get('symbol', {})
                symbol = extract_symbol_from_data_enhanced(symbol_data)
                
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
                    average_purchase_price = position.get('average_purchase_price', 0)

                except (ValueError, TypeError) as e:
                    logger.error(f"Error converting position values: {e}")
                    quantity = 0
                    price = 0
                    equity = 0
                    average_purchase_price = 0
                
                # If we have price and quantity but no symbol, try to look it up
                if price > 0 and quantity > 0 and (not symbol or symbol == "Unknown"):
                    # This is where we would implement a price-based lookup
                    # For now, use "Symbol-" + truncated price as placeholder
                    symbol = f"Symbol-{price:.2f}"
                    logger.warning(f"Using price-based symbol identification: {symbol}")
                
                # Safely extract type information with fallback
                position_type = "Unknown"
                try:
                    if 'symbol' in position and isinstance(position['symbol'], dict):
                        symbol_obj = position['symbol']
                        if 'symbol' in symbol_obj and isinstance(symbol_obj['symbol'], dict):
                            symbol_inner = symbol_obj['symbol']
                            if 'type' in symbol_inner and isinstance(symbol_inner['type'], dict):
                                position_type = symbol_inner['type'].get('description', 'Unknown')
                except (KeyError, TypeError, AttributeError):
                    position_type = "Unknown"
                
                data = {
                    'symbol': symbol,
                    'quantity': quantity,
                    'equity': equity,
                    'price': price,
                    'average_buy_price': average_purchase_price,
                    'type': position_type,
                    'currency': 'USD',  # Simplify currency to just the code
                }
                positions.append(data)
    except (TypeError, AttributeError) as e:
        logger.error(f"Error processing positions from SnapTrade response: {e}")
        return pd.DataFrame()
    
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
    # Use environment variables as defaults if not provided
    config = settings()
    account_id = account_id or getattr(config, 'ROBINHOOD_ACCOUNT_ID', '') or getattr(config, 'robinhood_account_id', '')
    user_id = user_id or getattr(config, 'SNAPTRADE_USER_ID', '') or getattr(config, 'snaptrade_user_id', '') or getattr(config, 'userid', '')
    user_secret = user_secret or getattr(config, 'SNAPTRADE_USER_SECRET', '') or getattr(config, 'snaptrade_user_secret', '') or getattr(config, 'usersecret', '')
    
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

def get_recent_orders(account_id=None, user_id=None, user_secret=None, state="all", days=365, limit=None):
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
    # Use environment variables as defaults if not provided
    config = settings()
    account_id = account_id or getattr(config, 'ROBINHOOD_ACCOUNT_ID', '') or getattr(config, 'robinhood_account_id', '')
    user_id = user_id or getattr(config, 'SNAPTRADE_USER_ID', '') or getattr(config, 'snaptrade_user_id', '') or getattr(config, 'userid', '')
    user_secret = user_secret or getattr(config, 'SNAPTRADE_USER_SECRET', '') or getattr(config, 'snaptrade_user_secret', '') or getattr(config, 'usersecret', '')
    
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
        
        # Add the extracted symbol to the order data (create a copy to avoid TypedDict issues)
        order_dict = dict(order)  # Convert to regular dict
        if symbol and isinstance(symbol, str) and symbol.lower() != 'unknown':
            order_dict['extracted_symbol'] = symbol.strip()
        else:
            order_dict['extracted_symbol'] = 'Unknown'

        # # Stringify 'option_symbol' if it's a dict
        # if 'option_symbol' in order_dict and isinstance(order_dict['option_symbol'], dict):
        #     try:
        #         print(f"Stringifying option_symbol: {order_dict['option_symbol']}")
        #         order_dict['option_symbol'] = json.dumps(order_dict['option_symbol'])
        #     except Exception as e:
        #         logger.warning(f"Failed to stringify option_symbol: {e}")
        #         order_dict['option_symbol'] = str(order_dict['option_symbol'])
            
        # Add order to processed list
        processed_orders.append(order_dict)
    
    # Return just the first 'limit' processed orders
    return processed_orders[:limit] if limit else processed_orders

def save_positions_to_db():
    """Saves positions to the database using unified database layer AND direct Supabase write"""
    try:
        config = settings()
        account_id = getattr(config, 'ROBINHOOD_ACCOUNT_ID', '') or getattr(config, 'robinhood_account_id', '')
        user_id = getattr(config, 'SNAPTRADE_USER_ID', '') or getattr(config, 'snaptrade_user_id', '') or getattr(config, 'userid', '')
        user_secret = getattr(config, 'SNAPTRADE_USER_SECRET', '') or getattr(config, 'snaptrade_user_secret', '') or getattr(config, 'usersecret', '')
        
        if not all([account_id, user_id, user_secret]):
            logger.warning("Missing SnapTrade credentials for position sync")
            # Fallback to old behavior
            positions_df = get_account_positions()
        else:
            # Get positions with credentials
            positions_df = get_account_positions(account_id, user_id, user_secret)

        if not positions_df.empty:
            # Write directly to Supabase first (primary)
            try:
                from src.supabase_writers import DirectSupabaseWriter
                writer = DirectSupabaseWriter()
                success = writer.write_position_data(positions_df.to_dict('records'))
                if success:
                    logger.info(f"✅ Successfully saved {len(positions_df)} positions to Supabase")
                else:
                    logger.warning("⚠️ Failed to save positions to Supabase, falling back to unified database layer")
                    raise Exception("Supabase write failed")
            except Exception as e:
                logger.warning(f"Supabase write failed: {e}, using fallback database")
                # Fallback to unified database layer
                from src.database import execute_sql, use_postgres
                
                # Add sync timestamp to track when this position snapshot was taken
                current_timestamp = datetime.now().isoformat()
                positions_df['sync_timestamp'] = current_timestamp
                
                # Add equity verification column: calculated_equity = quantity × price
                positions_df['calculated_equity'] = positions_df['quantity'] * positions_df['price']
                
                if use_postgres():
                    # For PostgreSQL, insert each row individually to handle conflicts
                    for _, row in positions_df.iterrows():
                        execute_sql('''
                        INSERT INTO positions 
                        (symbol, quantity, equity, price, average_buy_price, type, currency, sync_timestamp, calculated_equity)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (symbol, sync_timestamp) DO NOTHING
                        ''', (
                            row['symbol'], row['quantity'], row['equity'], row['price'],
                            row['average_buy_price'], row['type'], row['currency'],
                            row['sync_timestamp'], row['calculated_equity']
                        ))
                else:
                    # For SQLite, use DataFrame to_sql with existing connection
                    conn = sqlite3.connect(PRICE_DB)
                    positions_df.to_sql('positions', conn, if_exists='append', index=False)
                    conn.commit()
                    conn.close()
                
                logger.info(f"✅ Saved {len(positions_df)} positions to database with timestamp {current_timestamp}")
            
            # Also save to CSV for backup
            positions_df.to_csv(POSITIONS_CSV, index=False)
            logger.info(f"📁 Backup saved to {POSITIONS_CSV}")
            
        else:
            logger.warning("❌ No positions to save")
            return None
    except Exception as e:
        logger.error(f"Error saving positions: {e}")
        import traceback
        logger.error(traceback.format_exc())
    
    

def save_orders_to_db(days=365):
    """Save recent orders to the database using unified database layer AND direct Supabase write
    
    Args:
        days: Number of days to look back for orders
    """
    try:
        config = settings()
        account_id = getattr(config, 'ROBINHOOD_ACCOUNT_ID', '') or getattr(config, 'robinhood_account_id', '')
        user_id = getattr(config, 'SNAPTRADE_USER_ID', '') or getattr(config, 'snaptrade_user_id', '') or getattr(config, 'userid', '')
        user_secret = getattr(config, 'SNAPTRADE_USER_SECRET', '') or getattr(config, 'snaptrade_user_secret', '') or getattr(config, 'usersecret', '')
        
        if not all([account_id, user_id, user_secret]):
            logger.warning("Missing SnapTrade credentials for orders sync")
            # Fallback to old behavior
            orders = get_recent_orders(days=days)
        else:
            # Get orders with credentials
            orders = get_recent_orders(account_id, user_id, user_secret, days=days)
        
        if orders:
            # Write directly to Supabase first (primary)
            try:
                from src.supabase_writers import DirectSupabaseWriter
                writer = DirectSupabaseWriter()
                success = writer.write_order_data(orders)
                if success:
                    logger.info(f"✅ Successfully saved {len(orders)} orders to Supabase")
                else:
                    logger.warning("⚠️ Failed to save orders to Supabase, falling back to unified database layer")
                    raise Exception("Supabase write failed")
            except Exception as e:
                logger.warning(f"Supabase write failed: {e}, using fallback database")
                # Fallback to unified database layer
                orders_df = pd.DataFrame(orders)

                if 'option_symbol' in orders_df.columns:
                    orders_df['option_symbol'] = orders_df['option_symbol'].apply(
                        lambda x: json.dumps(x) if isinstance(x, dict) else str(x)
                    )

                if 'universal_symbol' in orders_df.columns:
                    orders_df['universal_symbol'] = orders_df['universal_symbol'].apply(
                        lambda x: json.dumps(x) if isinstance(x, dict) else str(x)
                    )

                if 'child_brokerage_order_ids' in orders_df.columns:
                    orders_df['child_brokerage_order_ids'] = orders_df['child_brokerage_order_ids'].apply(
                        lambda x: json.dumps(x) if isinstance(x, dict) else str(x)
                    )

                if orders_df.empty:
                    return
                
                from src.database import execute_sql, use_postgres
                
                if use_postgres():
                    # For PostgreSQL, insert each row individually
                    for _, row in orders_df.iterrows():
                        # Convert row to dict and handle NaN values
                        row_dict = row.to_dict()
                        for key, value in row_dict.items():
                            if pd.isna(value):
                                row_dict[key] = None
                        
                        # Build dynamic INSERT query based on available columns
                        columns = list(row_dict.keys())
                        values = [row_dict[col] for col in columns]
                        placeholders = ', '.join(['%s'] * len(columns))
                        
                        execute_sql(f'''
                        INSERT INTO orders ({', '.join(columns)})
                        VALUES ({placeholders})
                        ''', values)
                else:
                    # For SQLite, use DataFrame to_sql with existing connection
                    conn = sqlite3.connect(PRICE_DB)
                    orders_df.to_sql('orders', conn, if_exists='append', index=False)
                    conn.commit()
                    conn.close()
                
                logger.info(f"✅ Saved {len(orders_df)} orders to database")
            
            # Also save to CSV for backup
            orders_df = pd.DataFrame(orders)
            orders_df.to_csv(ORDERS_CSV, index=False)
            logger.info(f"📁 Backup saved to {ORDERS_CSV}")

        else:
            logger.warning("❌ No orders to save")
            return None
    except Exception as e:
        logger.error(f"Error saving orders: {e}")
        import traceback
        logger.error(traceback.format_exc())

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
            
            # Calculate change (abs_change and %change from regularMarketPrice vs previousClose)
            current_price = info.get('regularMarketPrice', 0)
            previous_close = info.get('previousClose', 0)
            abs_change = current_price - previous_close
            change_percent = (abs_change / previous_close * 100) if previous_close > 0 else 0
            
            price_data.append({
                'symbol': symbol,
                'price': current_price,
                'previous_close': previous_close,
                'abs_change': abs_change,  # This is the absolute change
                'percent_change': change_percent,  # This is the percentage change
                'timestamp': datetime.now().isoformat()
            })
            
        except Exception as e:
            logger.error(f"Error fetching price for {symbol}: {e}")
    
    df = pd.DataFrame(price_data)
    
    # Save to CSV
    if not df.empty:
        # Also save to database
        save_realtime_prices_to_db(df)
    
    return df

def save_realtime_prices_to_db(prices_df):
    """Save real-time prices to the database using unified database layer AND direct Supabase write
    
    Args:
        prices_df: DataFrame containing real-time price data
    """
    if prices_df.empty:
        return
    
    try:
        # Write directly to Supabase first (primary)
        try:
            from src.supabase_writers import DirectSupabaseWriter
            writer = DirectSupabaseWriter()
            success = writer.write_price_data(prices_df.to_dict('records'))
            if success:
                logger.info(f"✅ Successfully saved {len(prices_df)} prices to Supabase")
                return  # Success, no need for fallback
            else:
                logger.warning("⚠️ Failed to save prices to Supabase, falling back to unified database layer")
                raise Exception("Supabase write failed")
        except Exception as e:
            logger.warning(f"Supabase write failed: {e}, using fallback database")
            
            # Fallback to unified database layer
            from src.database import execute_sql, use_postgres
            
            if use_postgres():
                # For PostgreSQL, insert each row individually with conflict handling
                for _, row in prices_df.iterrows():
                    execute_sql('''
                    INSERT INTO realtime_prices (symbol, timestamp, price, previous_close, abs_change, percent_change)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (symbol, timestamp) DO NOTHING
                    ''', (
                        row['symbol'], row['timestamp'], row['price'], 
                        row['previous_close'], row['abs_change'], row['percent_change']
                    ))
            else:
                # For SQLite, use DataFrame to_sql with existing connection
                conn = sqlite3.connect(PRICE_DB)
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
    """Save historical prices to the SQLite database using append-only writes
    
    Args:
        symbol: Ticker symbol
        history_df: DataFrame containing historical price data
    """
    if history_df.empty:
        return
    
    try:
        from src.database import execute_sql
        
        # Insert each row into the daily_prices table using INSERT OR IGNORE to respect UNIQUE constraints
        for _, row in history_df.iterrows():
            execute_sql('''
            INSERT OR IGNORE INTO daily_prices 
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
        
        logger.info(f"✅ Saved historical prices for {symbol} to database using append-only writes")
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
                
            dividend_yield = info.get('dividendYield')
            metrics_data.append({
                'symbol': symbol,
                'date': datetime.now().strftime('%Y-%m-%d'),
                'pe_ratio': info.get('trailingPE', None),
                'market_cap': info.get('marketCap', None),
                'dividend_yield': (dividend_yield * 100) if dividend_yield and isinstance(dividend_yield, (int, float)) else None,
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
    """Save stock metrics to the database using unified database layer
    
    Args:
        metrics_df: DataFrame containing stock metrics
    """
    if metrics_df.empty:
        return
    
    try:
        from src.database import execute_sql, use_postgres
        
        if use_postgres():
            # For PostgreSQL, insert each row individually with conflict handling
            for _, row in metrics_df.iterrows():
                execute_sql('''
                INSERT INTO stock_metrics 
                (symbol, date, pe_ratio, market_cap, dividend_yield, fifty_day_avg, two_hundred_day_avg)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (symbol, date) DO NOTHING
                ''', (
                    row['symbol'], row['date'], row['pe_ratio'], row['market_cap'],
                    row['dividend_yield'], row['fifty_day_avg'], row['two_hundred_day_avg']
                ))
        else:
            # For SQLite, use DataFrame to_sql with existing connection
            conn = sqlite3.connect(PRICE_DB)
            metrics_df.to_sql('stock_metrics', conn, if_exists='append', index=False)
            conn.commit()
            conn.close()
        
        logger.info(f"✅ Saved metrics for {len(metrics_df)} stocks to database")
    except Exception as e:
        logger.error(f"Error saving stock metrics to database: {e}")

def update_all_data():
    """Update all data: positions, orders, real-time prices, historical prices, and metrics"""
    # Initialize database if it doesn't exist
    from src.database import initialize_database
    initialize_database()
    
    # Save positions and orders
    save_positions_to_db()
    save_orders_to_db(days=180)  # Get the last 6 months of orders
    
    # Fetch active position symbols from the database
    try:
        from src.database import execute_sql
        result = execute_sql(
            "SELECT DISTINCT symbol FROM positions WHERE sync_timestamp = (SELECT MAX(sync_timestamp) FROM positions)", 
            fetch_results=True
        )
        symbols = [row[0] for row in result] if result else []
    except Exception as e:
        logger.error(f"Error fetching symbols from database: {e}")
        symbols = []
    
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
    # Initialize the database
    from src.database import initialize_database
    initialize_database()
    
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
                cash = first_balance.get('cash', 0) or 0
                buying_power = first_balance.get('buying_power', 0) or 0
                
                # Ensure numeric values
                if not isinstance(cash, (int, float)):
                    cash = 0
                if not isinstance(buying_power, (int, float)):
                    buying_power = 0
                
                # In many brokerage APIs, the total balance is derived from these values
                # Buying power often represents cash + margin available
                if 'total' in first_balance:
                    total_balance = first_balance.get('total', 0) or 0
                else:
                    # For Robinhood/SnapTrade, buying power is typically 2x cash for margin accounts
                    # So we'll use a reasonable formula to estimate total equity
                    if buying_power > cash:
                        equity_value = buying_power - cash
                    else:
                        equity_value = buying_power / 2
                    total_balance = equity_value + cash
                
                logger.info(f"Cash: ${cash:.2f}, Buying Power: ${buying_power:.2f}")
            else:
                logger.warning("Balance structure is unexpected, couldn't extract total")
    except Exception as e:
        logger.error(f"Error processing balance data: {e}")
    
    logger.info("\n📊 Portfolio Summary")
    logger.info(f"Total Balance: ${total_balance:.2f}")
    
    # Update all data
    update_all_data()
