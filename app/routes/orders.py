"""
Orders API routes.

Endpoints:
- GET /orders - Get order history with optional filters
"""

import logging
import math
import re
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel

from src.db import execute_sql

logger = logging.getLogger(__name__)
router = APIRouter()

# UUID pattern to detect symbols that are actually UUIDs (bad data from brokerage)
_UUID_SYMBOL_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-", re.IGNORECASE)

# Trade-relevant actions (excludes DRIP, DIVIDEND, etc.)
TRADE_ACTIONS = ("BUY", "SELL", "BUY_OPEN", "SELL_CLOSE", "BUY_TO_COVER", "SELL_SHORT")


def safe_float(value: Any, default: float = 0.0) -> float:
    """Convert value to float, returning default if None or NaN."""
    if value is None:
        return default
    try:
        f = float(value)
        return default if math.isnan(f) or math.isinf(f) else f
    except (ValueError, TypeError):
        return default


def safe_float_optional(value: Any) -> Optional[float]:
    """Convert value to float, returning None if None, NaN, or invalid."""
    if value is None:
        return None
    try:
        f = float(value)
        return None if math.isnan(f) or math.isinf(f) else f
    except (ValueError, TypeError):
        return None


class Order(BaseModel):
    """Individual order record (matches api.ts Order)."""

    brokerageOrderId: str
    symbol: str
    action: str  # "BUY" or "SELL"
    orderType: str  # "market", "limit", "stop_limit"
    status: str  # "executed", "pending", "cancelled", "rejected"
    totalQuantity: float
    executionPrice: Optional[float] = None
    limitPrice: Optional[float] = None
    stopPrice: Optional[float] = None
    timeExecuted: Optional[str] = None  # ISO timestamp
    timePlaced: Optional[str] = None  # ISO timestamp
    notifiedAt: Optional[str] = None  # ISO timestamp


class OrdersResponse(BaseModel):
    """Orders list response (matches api.ts OrdersResponse)."""

    orders: list[Order]
    total: int
    hasMore: bool


@router.get("", response_model=OrdersResponse)
async def get_orders(
    limit: int = Query(50, ge=1, le=200, description="Number of orders to return"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    status: Optional[str] = Query(
        None, description="Filter by status (filled, pending, cancelled)"
    ),
    ticker: Optional[str] = Query(None, description="Filter by ticker symbol"),
    include_drip: bool = Query(False, description="Include DRIP/dividend reinvestment orders"),
):
    """
    Get order history with optional filters.

    Args:
        limit: Maximum number of orders to return (default 50, max 200)
        offset: Pagination offset
        status: Filter by order status
        ticker: Filter by ticker symbol
        include_drip: If False (default), only show trade-relevant actions (BUY/SELL/etc.)

    Returns:
        List of orders with metadata
    """
    try:
        # Build query with optional filters
        conditions: list[str] = []
        params: dict[str, Any] = {
            "limit": limit + 1,
            "offset": offset,
        }  # +1 to check hasMore

        if status:
            conditions.append("o.status = :status")
            params["status"] = status

        if ticker:
            conditions.append("UPPER(o.symbol) = UPPER(:ticker)")
            params["ticker"] = ticker

        if not include_drip:
            conditions.append("UPPER(o.action) IN (:act_0, :act_1, :act_2, :act_3, :act_4, :act_5)")
            for i, action in enumerate(TRADE_ACTIONS):
                params[f"act_{i}"] = action

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        query = f"""
            SELECT
                o.brokerage_order_id as id,
                o.symbol,
                o.action as side,
                o.order_type as type,
                o.total_quantity as quantity,
                COALESCE(o.filled_quantity, 0) as filled_quantity,
                o.limit_price as limit_price,
                o.stop_price as stop_price,
                o.execution_price as execution_price,
                o.status,
                o.time_placed as time_placed,
                o.time_executed as time_executed,
                o.notified as notified
            FROM orders o
            WHERE {where_clause}
            ORDER BY o.time_placed DESC NULLS LAST
            LIMIT :limit OFFSET :offset
        """

        orders_data = execute_sql(query, params=params, fetch_results=True)

        # Check if there are more results
        has_more = len(orders_data or []) > limit
        orders_list = (orders_data or [])[:limit]

        orders = []
        for row in orders_list:
            row_dict: dict[str, Any] = dict(row._mapping) if hasattr(row, "_mapping") else dict(row)  # type: ignore[arg-type]
            # Guard: replace UUID-like symbols with "Unknown"
            raw_symbol = row_dict["symbol"] or "UNKNOWN"
            symbol = "Unknown" if _UUID_SYMBOL_RE.match(raw_symbol) else raw_symbol
            orders.append(
                Order(
                    brokerageOrderId=str(row_dict["id"]),
                    symbol=symbol,
                    action=(row_dict["side"] or "BUY").upper(),
                    orderType=row_dict["type"] or "market",
                    status=row_dict["status"] or "unknown",
                    totalQuantity=safe_float(row_dict["quantity"]),
                    executionPrice=safe_float_optional(row_dict["execution_price"]),
                    limitPrice=safe_float_optional(row_dict["limit_price"]),
                    stopPrice=safe_float_optional(row_dict["stop_price"]),
                    timeExecuted=(
                        str(row_dict["time_executed"])
                        if row_dict["time_executed"]
                        else None
                    ),
                    timePlaced=(
                        str(row_dict["time_placed"])
                        if row_dict["time_placed"]
                        else None
                    ),
                    notifiedAt=(
                        str(row_dict["time_executed"])
                        if row_dict.get("notified")
                        else None
                    ),
                )
            )

        # Get total count for pagination
        count_query = f"""
            SELECT COUNT(*) as total
            FROM orders o
            WHERE {where_clause}
        """
        # Remove limit/offset from params for count query
        count_params = {k: v for k, v in params.items() if k not in ["limit", "offset"]}
        count_result = execute_sql(count_query, params=count_params, fetch_results=True)
        if count_result:
            count_row: dict[str, Any] = dict(count_result[0]._mapping) if hasattr(count_result[0], "_mapping") else dict(count_result[0])  # type: ignore[arg-type]
            total = int(count_row["total"])
        else:
            total = 0

        return OrdersResponse(
            orders=orders,
            total=total,
            hasMore=has_more,
        )

    except Exception as e:
        logger.error(f"Error fetching orders: {e}")
        return OrdersResponse(orders=[], total=0, hasMore=False)


@router.post("/{order_id}/notify")
async def mark_order_notified(order_id: str):
    """
    Mark an order as notified (Discord notification sent).

    Args:
        order_id: The order ID to mark as notified

    Returns:
        Updated notification status
    """
    try:
        execute_sql(
            "UPDATE orders SET notified = true WHERE brokerage_order_id = :order_id",
            params={"order_id": order_id},
        )

        return {
            "status": "success",
            "order_id": order_id,
            "notified": True,
        }
    except Exception:
        logger.exception("Error marking order notified")
        return {
            "status": "error",
            "message": "Failed to mark order as notified.",
        }
