"""
Activities API routes.

Endpoints:
- GET /activities - Get account activity history with optional filters
"""

import logging
import math
from datetime import datetime, timedelta, timezone
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


class Activity(BaseModel):
    """Individual activity record."""

    id: str
    accountId: Optional[str] = None
    activityType: Optional[str] = None
    tradeDate: Optional[str] = None
    settlementDate: Optional[str] = None
    amount: float = 0.0
    price: Optional[float] = None
    units: Optional[float] = None
    symbol: Optional[str] = None
    description: Optional[str] = None
    currency: str = "USD"
    fee: float = 0.0
    fxRate: Optional[float] = None
    institution: Optional[str] = None
    optionType: Optional[str] = None


class ActivitiesResponse(BaseModel):
    """Activities list response."""

    activities: list[Activity]
    total: int
    startDate: str
    endDate: str


@router.get("", response_model=ActivitiesResponse)
async def get_activities(
    limit: int = Query(50, ge=1, le=500, description="Number of activities to return"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    activity_type: Optional[str] = Query(
        None,
        alias="activityType",
        description="Filter by type (BUY, SELL, DIVIDEND, FEE, etc.)",
    ),
    symbol: Optional[str] = Query(None, description="Filter by ticker symbol"),
    start_date: Optional[str] = Query(
        None,
        alias="startDate",
        description="Start date (YYYY-MM-DD). Default: 90 days ago.",
    ),
    end_date: Optional[str] = Query(
        None,
        alias="endDate",
        description="End date (YYYY-MM-DD). Default: today.",
    ),
):
    """
    Get account activity history with optional filters.

    Returns dividends, trades, fees, and other account activities
    from the activities table (populated by SnapTrade sync).
    """
    try:
        # Resolve date range
        now = datetime.now(timezone.utc)
        resolved_end = end_date or now.strftime("%Y-%m-%d")
        resolved_start = start_date or (now - timedelta(days=90)).strftime("%Y-%m-%d")

        # Build dynamic filters
        conditions: list[str] = [
            "a.trade_date >= :start_date",
            "a.trade_date <= :end_date",
        ]
        params: dict[str, Any] = {
            "start_date": resolved_start,
            "end_date": resolved_end,
            "limit": limit,
            "offset": offset,
        }

        if activity_type:
            conditions.append("UPPER(a.activity_type) = UPPER(:activity_type)")
            params["activity_type"] = activity_type

        if symbol:
            conditions.append("UPPER(a.symbol) = UPPER(:symbol)")
            params["symbol"] = symbol

        where_clause = " AND ".join(conditions)

        # Count total matching rows
        count_query = f"SELECT COUNT(*) as cnt FROM activities a WHERE {where_clause}"
        count_rows = execute_sql(count_query, params=params, fetch_results=True)
        total = int(count_rows[0]["cnt"]) if count_rows else 0

        # Fetch page
        query = f"""
            SELECT
                a.id,
                a.account_id,
                a.activity_type,
                a.trade_date,
                a.settlement_date,
                a.amount,
                a.price,
                a.units,
                a.symbol,
                a.description,
                a.currency,
                a.fee,
                a.fx_rate,
                a.institution,
                a.option_type
            FROM activities a
            WHERE {where_clause}
            ORDER BY a.trade_date DESC, a.created_at DESC
            LIMIT :limit OFFSET :offset
        """
        rows = execute_sql(query, params=params, fetch_results=True) or []

        activities = []
        for row in rows:
            r = dict(row) if not isinstance(row, dict) else row
            activities.append(
                Activity(
                    id=str(r.get("id", "")),
                    accountId=r.get("account_id"),
                    activityType=r.get("activity_type"),
                    tradeDate=(str(r["trade_date"]) if r.get("trade_date") else None),
                    settlementDate=(
                        str(r["settlement_date"]) if r.get("settlement_date") else None
                    ),
                    amount=safe_float(r.get("amount")),
                    price=safe_float_optional(r.get("price")),
                    units=safe_float_optional(r.get("units")),
                    symbol=r.get("symbol"),
                    description=r.get("description"),
                    currency=r.get("currency") or "USD",
                    fee=safe_float(r.get("fee")),
                    fxRate=safe_float_optional(r.get("fx_rate")),
                    institution=r.get("institution"),
                    optionType=r.get("option_type"),
                )
            )

        return ActivitiesResponse(
            activities=activities,
            total=total,
            startDate=resolved_start,
            endDate=resolved_end,
        )

    except Exception as e:
        logger.error(f"Error fetching activities: {e}", exc_info=True)
        return ActivitiesResponse(
            activities=[],
            total=0,
            startDate=start_date or "",
            endDate=end_date or "",
        )
