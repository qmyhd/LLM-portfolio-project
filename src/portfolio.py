import pandas as pd

from src.database import execute_sql


def get_positions():
    """Return all portfolio positions as a DataFrame from the latest sync."""
    try:
        # Get positions from the most recent sync timestamp
        query = """
        SELECT symbol, quantity, equity, price, average_buy_price, type, currency, sync_timestamp, calculated_equity 
        FROM positions 
        WHERE sync_timestamp = (SELECT MAX(sync_timestamp) FROM positions)
        ORDER BY equity DESC
        """
        result = execute_sql(query, fetch_results=True)
        if result:
            columns = ['symbol', 'quantity', 'equity', 'price', 'average_buy_price', 'type', 'currency', 'sync_timestamp', 'calculated_equity']
            return pd.DataFrame(result, columns=columns)
        return pd.DataFrame()
    except Exception as e:
        print(f"Error getting positions: {e}")
        return pd.DataFrame()


def get_position(symbol: str):
    """Return the most recent position for the given symbol."""
    try:
        # Get the most recent position for this symbol
        query = """
        SELECT symbol, quantity, equity, price, average_buy_price, type, currency, sync_timestamp, calculated_equity 
        FROM positions 
        WHERE symbol = ? AND sync_timestamp = (SELECT MAX(sync_timestamp) FROM positions WHERE symbol = ?)
        """
        result = execute_sql(query, (symbol, symbol), fetch_results=True)
        if result:
            columns = ['symbol', 'quantity', 'equity', 'price', 'average_buy_price', 'type', 'currency', 'sync_timestamp', 'calculated_equity']
            df = pd.DataFrame(result, columns=columns)
            return df.iloc[0] if not df.empty else None
        return None
    except Exception as e:
        print(f"Error getting position for {symbol}: {e}")
        return None
