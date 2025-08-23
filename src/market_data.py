"""
Market Data Query Module
========================

Consolidated module for retrieving portfolio positions, trades, and market data
from the database. Combines functionality from portfolio.py and trades.py.
"""

import pandas as pd

from src.database import execute_sql


def get_positions() -> pd.DataFrame:
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
            columns = [
                "symbol",
                "quantity",
                "equity",
                "price",
                "average_buy_price",
                "type",
                "currency",
                "sync_timestamp",
                "calculated_equity",
            ]
            return pd.DataFrame(result, columns=columns)
        return pd.DataFrame()
    except Exception as e:
        print(f"Error getting positions: {e}")
        return pd.DataFrame()


def get_position(symbol: str) -> pd.DataFrame:
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
            columns = [
                "symbol",
                "quantity",
                "equity",
                "price",
                "average_buy_price",
                "type",
                "currency",
                "sync_timestamp",
                "calculated_equity",
            ]
            return pd.DataFrame(result, columns=columns)
        return pd.DataFrame()
    except Exception as e:
        print(f"Error getting position for {symbol}: {e}")
        return pd.DataFrame()


def get_recent_trades(limit: int = 50) -> pd.DataFrame:
    """Return recent trades from the database."""
    try:
        query = "SELECT * FROM trades ORDER BY timestamp DESC LIMIT ?"
        result = execute_sql(query, (limit,), fetch_results=True)
        if result:
            # Note: Column names should match actual trades table schema
            columns = ["id", "symbol", "quantity", "price", "action", "timestamp"]
            return pd.DataFrame(result, columns=columns)
        return pd.DataFrame()
    except Exception as e:
        print(f"Error getting recent trades: {e}")
        return pd.DataFrame()


def get_trades_for_symbol(symbol: str, limit: int = 100) -> pd.DataFrame:
    """Return trades for a specific symbol."""
    try:
        query = """
        SELECT * FROM trades 
        WHERE symbol = ? 
        ORDER BY timestamp DESC 
        LIMIT ?
        """
        result = execute_sql(query, (symbol, limit), fetch_results=True)
        if result:
            columns = ["id", "symbol", "quantity", "price", "action", "timestamp"]
            return pd.DataFrame(result, columns=columns)
        return pd.DataFrame()
    except Exception as e:
        print(f"Error getting trades for {symbol}: {e}")
        return pd.DataFrame()


def get_portfolio_summary() -> dict:
    """Return a summary of the current portfolio."""
    try:
        positions = get_positions()
        if positions.empty:
            return {"total_equity": 0, "position_count": 0, "top_holdings": []}

        total_equity = positions["equity"].sum() if "equity" in positions.columns else 0
        position_count = len(positions)
        top_holdings = (
            positions.head(5)[["symbol", "equity"]].to_dict("records")
            if "symbol" in positions.columns
            else []
        )

        return {
            "total_equity": total_equity,
            "position_count": position_count,
            "top_holdings": top_holdings,
        }
    except Exception as e:
        print(f"Error getting portfolio summary: {e}")
        return {"total_equity": 0, "position_count": 0, "top_holdings": []}
