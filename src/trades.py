import pandas as pd
from database import get_connection


def get_recent_trades(limit: int = 50):
    """Return recent trades from the database."""
    conn = get_connection()
    try:
        query = "SELECT * FROM trades ORDER BY timestamp DESC LIMIT ?"
        return pd.read_sql_query(query, conn, params=(limit,))
    finally:
        conn.close()
