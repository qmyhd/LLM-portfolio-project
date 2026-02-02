"""
Portfolio API routes.

Endpoints:
- GET /portfolio - Get portfolio summary with positions
- POST /portfolio/sync - Trigger SnapTrade sync
"""

import logging
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from src.db import execute_sql
from src.snaptrade_collector import SnapTradeCollector
from src.price_service import get_latest_closes_batch

logger = logging.getLogger(__name__)
router = APIRouter()


# Response models
class Position(BaseModel):
    """Individual portfolio position."""

    symbol: str
    quantity: float
    avgCost: float
    currentPrice: float
    marketValue: float
    dayChange: float
    dayChangePercent: float
    totalGainLoss: float
    totalGainLossPercent: float
    portfolioWeight: float


class PortfolioSummary(BaseModel):
    """Portfolio summary metrics."""

    totalValue: float
    dayChange: float
    dayChangePercent: float
    totalGainLoss: float
    totalGainLossPercent: float
    cash: float
    buyingPower: float
    positionCount: int


class PortfolioResponse(BaseModel):
    """Full portfolio response."""

    summary: PortfolioSummary
    positions: list[Position]
    lastUpdated: str


@router.get("", response_model=PortfolioResponse)
async def get_portfolio():
    """
    Get portfolio summary and all positions.

    Returns:
        Portfolio summary metrics and list of positions with current prices.
    """
    try:
        # Get positions from database
        positions_data = execute_sql(
            """
            SELECT
                p.symbol,
                p.quantity,
                p.average_buy_price as average_cost,
                p.raw_symbol,
                p.account_id
            FROM positions p
            WHERE p.quantity > 0
            ORDER BY p.symbol
            """,
            fetch_results=True,
        )

        # Get account balances
        balances_data = execute_sql(
            """
            SELECT
                SUM(cash) as total_cash,
                SUM(buying_power) as total_buying_power
            FROM account_balances
            """,
            fetch_results=True,
        )

        # Extract all symbols and batch fetch prices (single query instead of N queries)
        position_rows = []
        symbols_to_fetch = []
        for row in positions_data or []:
            row_dict: dict[str, Any] = dict(row._mapping) if hasattr(row, "_mapping") else dict(row)  # type: ignore[arg-type]
            position_rows.append(row_dict)
            symbols_to_fetch.append(row_dict["symbol"])

        # Batch fetch all prices in ONE database query
        prices_map = get_latest_closes_batch(symbols_to_fetch) if symbols_to_fetch else {}

        positions = []
        total_value = 0.0
        total_cost = 0.0
        total_day_change = 0.0

        for row_dict in position_rows:
            symbol = row_dict["symbol"]
            quantity = float(row_dict["quantity"] or 0)
            avg_cost = float(row_dict["average_cost"] or 0)

            # Get current price from batch-fetched prices, fallback to avg_cost
            current_price = prices_map.get(symbol, avg_cost)

            # Calculate position metrics
            market_value = quantity * current_price
            cost_basis = quantity * avg_cost
            total_gain_loss = market_value - cost_basis
            total_gain_loss_pct = (
                (total_gain_loss / cost_basis * 100) if cost_basis > 0 else 0
            )

            # Day change (simplified - would need previous close)
            day_change = 0.0  # TODO: Calculate from previous close
            day_change_pct = 0.0

            positions.append(
                Position(
                    symbol=symbol,
                    quantity=quantity,
                    avgCost=round(avg_cost, 2),
                    currentPrice=round(current_price, 2),
                    marketValue=round(market_value, 2),
                    dayChange=round(day_change, 2),
                    dayChangePercent=round(day_change_pct, 2),
                    totalGainLoss=round(total_gain_loss, 2),
                    totalGainLossPercent=round(total_gain_loss_pct, 2),
                    portfolioWeight=0.0,  # Calculated below
                )
            )

            total_value += market_value
            total_cost += cost_basis
            total_day_change += day_change

        # Get cash and buying power
        if balances_data:
            bal_row = balances_data[0]
            bal_dict: dict[str, Any] = (
                dict(bal_row._mapping) if hasattr(bal_row, "_mapping") else dict(bal_row)  # type: ignore[arg-type]
            )
            cash = float(bal_dict["total_cash"] or 0)
            buying_power = float(bal_dict["total_buying_power"] or 0)
        else:
            cash = 0
            buying_power = 0

        # Add cash to total value
        total_portfolio_value = total_value + cash

        # Calculate portfolio weights
        for pos in positions:
            pos.portfolioWeight = round(
                (
                    (pos.marketValue / total_portfolio_value * 100)
                    if total_portfolio_value > 0
                    else 0
                ),
                2,
            )

        # Calculate summary metrics
        total_gain_loss = total_value - total_cost
        total_gain_loss_pct = (
            (total_gain_loss / total_cost * 100) if total_cost > 0 else 0
        )
        day_change_pct = (
            (total_day_change / (total_portfolio_value - total_day_change) * 100)
            if (total_portfolio_value - total_day_change) > 0
            else 0
        )

        summary = PortfolioSummary(
            totalValue=round(total_portfolio_value, 2),
            dayChange=round(total_day_change, 2),
            dayChangePercent=round(day_change_pct, 2),
            totalGainLoss=round(total_gain_loss, 2),
            totalGainLossPercent=round(total_gain_loss_pct, 2),
            cash=round(cash, 2),
            buyingPower=round(buying_power, 2),
            positionCount=len(positions),
        )

        # Get last update time
        last_updated = execute_sql(
            "SELECT MAX(sync_timestamp) as last_update FROM positions",
            fetch_results=True,
        )
        last_update_str = ""
        if last_updated:
            last_row = last_updated[0]
            last_dict: dict[str, Any] = (
                dict(last_row._mapping) if hasattr(last_row, "_mapping") else dict(last_row)  # type: ignore[arg-type]
            )
            if last_dict.get("last_update"):
                last_update_str = str(last_dict["last_update"])

        return PortfolioResponse(
            summary=summary,
            positions=positions,
            lastUpdated=last_update_str,
        )

    except Exception as e:
        logger.error(f"Error fetching portfolio: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to fetch portfolio: {str(e)}"
        )


@router.post("/sync")
async def sync_portfolio():
    """
    Trigger a SnapTrade sync to refresh portfolio data.

    Returns:
        Status of the sync operation.
    """
    try:
        collector = SnapTradeCollector()
        results = collector.collect_all_data(write_parquet=False)

        error_list = results.get("errors", []) or []
        success = bool(results.get("success"))

        return {
            "status": "success" if success else "partial",
            "message": "Portfolio sync completed"
            if success
            else "Portfolio sync completed with some errors",
            "accounts": results.get("accounts", 0),
            "balances": results.get("balances", 0),
            "positions": results.get("positions", 0),
            "orders": results.get("orders", 0),
            "errorCount": len(error_list),
        }
    except Exception as e:
        logger.error(f"Error syncing portfolio: {e}")
        raise HTTPException(status_code=500, detail="Sync failed")
