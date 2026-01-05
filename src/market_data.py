"""
Market Data Query Module
========================

Consolidated module for retrieving executed orders and market data from the database.
Position queries have been moved to SnapTradeCollector for better organization.

NOTE: There is no 'trades' table. Use orders table with status='EXECUTED' instead.
"""

import pandas as pd

from src.db import execute_sql


def get_recent_executed_orders(limit: int = 50) -> pd.DataFrame:
    """Return recent executed orders from the database.

    Queries the orders table for orders with status='EXECUTED',
    sorted by time_executed descending.

    Args:
        limit: Maximum number of orders to return (default: 50)

    Returns:
        DataFrame with columns: symbol, time_executed, execution_price,
        total_quantity, action, account_id
    """
    try:
        query = """
        SELECT symbol, time_executed, execution_price, total_quantity, action, account_id
        FROM orders 
        WHERE status = 'EXECUTED' AND time_executed IS NOT NULL
        ORDER BY time_executed DESC 
        LIMIT :limit
        """
        result = execute_sql(query, {"limit": limit}, fetch_results=True)
        if result:
            columns = [
                "symbol",
                "time_executed",
                "execution_price",
                "total_quantity",
                "action",
                "account_id",
            ]
            return pd.DataFrame(result, columns=columns)
        return pd.DataFrame()
    except Exception as e:
        print(f"Error getting recent executed orders: {e}")
        return pd.DataFrame()


def get_executed_orders_for_symbol(symbol: str, limit: int = 100) -> pd.DataFrame:
    """Return executed orders for a specific symbol.

    Queries the orders table for orders matching the symbol with status='EXECUTED',
    sorted by time_executed descending.

    Args:
        symbol: Stock ticker symbol (e.g., 'AAPL')
        limit: Maximum number of orders to return (default: 100)

    Returns:
        DataFrame with columns: symbol, time_executed, execution_price,
        total_quantity, action, account_id
    """
    try:
        query = """
        SELECT symbol, time_executed, execution_price, total_quantity, action, account_id
        FROM orders 
        WHERE symbol = :symbol AND status = 'EXECUTED' AND time_executed IS NOT NULL
        ORDER BY time_executed DESC 
        LIMIT :limit
        """
        result = execute_sql(
            query, {"symbol": symbol.upper(), "limit": limit}, fetch_results=True
        )
        if result:
            columns = [
                "symbol",
                "time_executed",
                "execution_price",
                "total_quantity",
                "action",
                "account_id",
            ]
            return pd.DataFrame(result, columns=columns)
        return pd.DataFrame()
    except Exception as e:
        print(f"Error getting executed orders for {symbol}: {e}")
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
