import pandas as pd
from database import get_connection


def get_positions():
    """Return all portfolio positions as a DataFrame."""
    conn = get_connection()
    try:
        return pd.read_sql_query("SELECT * FROM positions ORDER BY equity DESC", conn)
    finally:
        conn.close()


def get_position(symbol: str):
    """Return a single position for the given symbol."""
    conn = get_connection()
    try:
        df = pd.read_sql_query("SELECT * FROM positions WHERE symbol = ?", conn, params=(symbol,))
        return df.iloc[0] if not df.empty else None
    finally:
        conn.close()
