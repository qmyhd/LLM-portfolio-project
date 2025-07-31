import pandas as pd

from src.database import execute_sql


def get_recent_trades(limit: int = 50):
    """Return recent trades from the database."""
    try:
        query = "SELECT * FROM trades ORDER BY timestamp DESC LIMIT ?"
        result = execute_sql(query, (limit,), fetch_results=True)
        if result:
            # Note: We'd need to know the actual column names for the trades table
            # For now, assuming basic columns - this should be updated based on actual schema
            columns = ['id', 'symbol', 'quantity', 'price', 'action', 'timestamp']
            return pd.DataFrame(result, columns=columns)
        return pd.DataFrame()
    except Exception as e:
        print(f"Error getting recent trades: {e}")
        return pd.DataFrame()
