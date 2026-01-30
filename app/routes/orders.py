"""
Orders API routes.

Endpoints:
- GET /orders - Get order history with optional filters
"""

import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel

from src.db import execute_sql

logger = logging.getLogger(__name__)
router = APIRouter()


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
    notified: bool  # Whether Discord notification was sent


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
    notified: Optional[bool] = Query(None, description="Filter by notification status"),
):
    """
    Get order history with optional filters.

    Args:
        limit: Maximum number of orders to return (default 50, max 200)
        offset: Pagination offset
        status: Filter by order status
        ticker: Filter by ticker symbol
        notified: Filter by notification status

    Returns:
        List of orders with metadata
    """
    try:
        # Build query with optional filters
        conditions = []
        params = {"limit": limit + 1, "offset": offset}  # +1 to check hasMore

        if status:
            conditions.append("o.status = :status")
            params["status"] = status

        if ticker:
            conditions.append("UPPER(o.symbol) = UPPER(:ticker)")
            params["ticker"] = ticker

        if notified is not None:
            conditions.append("o.notified = :notified")
            params["notified"] = notified

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        query = f"""
            SELECT
                o.order_id as id,
                o.symbol,
                o.side,
                o.order_type as type,
                o.quantity,
                COALESCE(o.filled_quantity, 0) as filled_quantity,
                o.limit_price as price,
                o.filled_price,
                o.status,
                o.created_at,
                o.filled_at,
                COALESCE(o.notified, false) as notified
            FROM orders o
            WHERE {where_clause}
            ORDER BY o.created_at DESC
            LIMIT :limit OFFSET :offset
        """

        orders_data = execute_sql(query, params=params, fetch_results=True)

        # Check if there are more results
        has_more = len(orders_data or []) > limit
        orders_list = (orders_data or [])[:limit]

        orders = []
        for row in orders_list:
            orders.append(
                Order(
                    id=str(row["id"]),
                    symbol=row["symbol"] or "UNKNOWN",
                    side=row["side"] or "buy",
                    type=row["type"] or "market",
                    quantity=float(row["quantity"] or 0),
                    filledQuantity=float(row["filled_quantity"] or 0),
                    price=float(row["price"]) if row["price"] else None,
                    filledPrice=(
                        float(row["filled_price"]) if row["filled_price"] else None
                    ),
                    status=row["status"] or "unknown",
                    createdAt=str(row["created_at"]) if row["created_at"] else "",
                    filledAt=str(row["filled_at"]) if row["filled_at"] else None,
                    notified=bool(row["notified"]),
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
        total = int(count_result[0]["total"]) if count_result else 0

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
