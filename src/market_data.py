"""
Market Data Query Module
========================

Consolidated module for retrieving trades and market data from the database.
Position queries have been moved to SnapTradeCollector for better organization.
"""

import pandas as pd

from src.db import execute_sql


# Deprecated functions removed - use SnapTradeCollector.get_stored_positions() and get_stored_position() instead


def get_recent_trades(limit: int = 50) -> pd.DataFrame:
    """Return recent trades from the database."""
    try:
        query = "SELECT * FROM trades ORDER BY timestamp DESC LIMIT :limit"
        result = execute_sql(query, {"limit": limit}, fetch_results=True)
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
        WHERE symbol = :symbol 
        ORDER BY timestamp DESC 
        LIMIT :limit
        """
        result = execute_sql(
            query, {"symbol": symbol, "limit": limit}, fetch_results=True
        )
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
        from src.snaptrade_collector import SnapTradeCollector

        collector = SnapTradeCollector()
        positions = collector.get_stored_positions()

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
