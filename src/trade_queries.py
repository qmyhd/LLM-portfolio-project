"""
Shared trade query functions.

Extracted from bot/commands/chart.py to resolve layering violations.
Both chart.py (bot layer) and position_analysis.py (core layer) import from here.
"""

import logging
from datetime import datetime

import pandas as pd

from src.db import execute_sql

logger = logging.getLogger(__name__)


def query_trade_data(
    symbol: str, start_date: datetime, end_date: datetime, min_trade: float = 0.0
):
    """Query trade data within a timeframe.

    Args:
        symbol: Stock ticker symbol
        start_date: Start date for trade query
        end_date: End date for trade query
        min_trade: Minimum trade size threshold

    Returns:
        DataFrame containing trade data or empty DataFrame
    """
    try:
        query = """
        SELECT
            symbol,
            action,
            time_executed as execution_date,
            execution_price,
            total_quantity,
            (execution_price * total_quantity) as trade_value
        FROM orders
        WHERE symbol = :symbol
        AND time_executed BETWEEN :start_date AND :end_date
        AND status = 'executed'
        AND (execution_price * total_quantity) >= :min_trade
        ORDER BY time_executed ASC
        """

        start_str = start_date.strftime("%Y-%m-%d")
        end_str = end_date.strftime("%Y-%m-%d")

        result = execute_sql(
            query,
            {
                "symbol": symbol,
                "start_date": start_str,
                "end_date": end_str,
                "min_trade": min_trade,
            },
            fetch_results=True,
        )

        columns = [
            "symbol",
            "action",
            "execution_date",
            "execution_price",
            "total_quantity",
            "trade_value",
        ]

        if result:
            df = pd.DataFrame(result, columns=columns)
            if not df.empty and "execution_date" in df.columns:
                df["execution_date"] = pd.to_datetime(df["execution_date"])
        else:
            df = pd.DataFrame(columns=columns)
            df["execution_date"] = pd.to_datetime(df["execution_date"])

        return df

    except Exception as e:
        logger.error(f"Error querying trade data: {e}")
        return pd.DataFrame()
