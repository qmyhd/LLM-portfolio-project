"""
Orders API routes.

Endpoints:
- GET /orders - Get order history with optional filters
"""

import logging
import math
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel

from src.db import execute_sql

logger = logging.getLogger(__name__)
router = APIRouter()


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
    """Individual order record."""

    id: str
    symbol: str
    side: str  # "buy" or "sell"
    type: str  # "market", "limit", etc.
    quantity: float
    filledQuantity: float
    price: Optional[float]
    filledPrice: Optional[float]
    status: str  # "filled", "pending", "cancelled", etc.
    createdAt: str
    filledAt: Optional[str]


class OrdersResponse(BaseModel):
    """Orders list response."""

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
):
    """
    Get order history with optional filters.

    Args:
        limit: Maximum number of orders to return (default 50, max 200)
        offset: Pagination offset
        status: Filter by order status
        ticker: Filter by ticker symbol

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

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        query = f"""
            SELECT
                o.brokerage_order_id as id,
                o.symbol,
                o.action as side,
                o.order_type as type,
                o.total_quantity as quantity,
                COALESCE(o.filled_quantity, 0) as filled_quantity,
                o.limit_price as price,
                o.execution_price as filled_price,
                o.status,
                o.time_placed as created_at,
                o.time_executed as filled_at
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
            orders.append(
                Order(
                    id=str(row_dict["id"]),
                    symbol=row_dict["symbol"] or "UNKNOWN",
                    side=row_dict["side"] or "buy",
                    type=row_dict["type"] or "market",
                    quantity=safe_float(row_dict["quantity"]),
                    filledQuantity=safe_float(row_dict["filled_quantity"]),
                    price=safe_float_optional(row_dict["price"]),
                    filledPrice=safe_float_optional(row_dict["filled_price"]),
                    status=row_dict["status"] or "unknown",
                    createdAt=(
                        str(row_dict["created_at"]) if row_dict["created_at"] else ""
                    ),
                    filledAt=(
                        str(row_dict["filled_at"]) if row_dict["filled_at"] else None
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
            "UPDATE orders SET notified = true WHERE order_id = :order_id",
            params={"order_id": order_id},
        )

        return {
            "status": "success",
            "order_id": order_id,
            "notified": True,
        }
    except Exception as e:
        logger.error(f"Error marking order notified: {e}")
        return {"status": "error", "message": str(e)}
