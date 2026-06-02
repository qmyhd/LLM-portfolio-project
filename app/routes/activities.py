"""
Activities API routes.

Endpoints:
- GET /activities - Get account activity history with optional filters
"""

import logging
import math
from datetime import UTC, datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel

from src.bucket import BucketQuery, validate_bucket
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


def safe_float_optional(value: Any) -> float | None:
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
    accountId: str | None = None
    activityType: str | None = None
    tradeDate: str | None = None
    settlementDate: str | None = None
    amount: float = 0.0
    price: float | None = None
    units: float | None = None
    symbol: str | None = None
    description: str | None = None
    currency: str = "USD"
    fee: float = 0.0
    fxRate: float | None = None
    institution: str | None = None
    optionType: str | None = None


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
    activity_type: str | None = Query(
        None,
        alias="activityType",
        description="Filter by type (BUY, SELL, DIVIDEND, FEE, etc.)",
    ),
    symbol: str | None = Query(None, description="Filter by ticker symbol"),
    start_date: str | None = Query(
        None,
        alias="startDate",
        description="Start date (YYYY-MM-DD). Default: 90 days ago.",
    ),
    end_date: str | None = Query(
        None,
        alias="endDate",
        description="End date (YYYY-MM-DD). Default: today.",
    ),
    bucket: str | None = BucketQuery,
):
    """
    Get account activity history with optional filters.

    Returns dividends, trades, fees, and other account activities
    from the activities table (populated by SnapTrade sync).

    Pass ``?bucket=<name>`` to restrict to a single strategy bucket
    (long_term, swing, day, retirement, other).
    """
    try:
        bucket = validate_bucket(bucket)

        # Resolve date range
        now = datetime.now(UTC)
        resolved_end = end_date or now.strftime("%Y-%m-%d")
        resolved_start = start_date or (now - timedelta(days=90)).strftime("%Y-%m-%d")

        # Build dynamic filters. JOIN accounts so we can filter by bucket
        # and exclude activities from deleted (orphaned) accounts.
        conditions: list[str] = [
            "a.trade_date >= :start_date",
            "a.trade_date <= :end_date",
            "COALESCE(acc.connection_status, 'connected') != 'deleted'",
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

        if bucket:
            conditions.append("acc.bucket = :bucket")
            params["bucket"] = bucket

        where_clause = " AND ".join(conditions)

        # Count total matching rows — same JOIN + filter as page query.
        # LEFT JOIN so legacy rows with orphan account_id still surface when
        # no bucket filter is set (matches the pre-bucket behavior).
        count_query = (
            f"SELECT COUNT(*) as cnt FROM activities a "
            f"LEFT JOIN accounts acc ON acc.id = a.account_id "
            f"WHERE {where_clause}"
        )
        # The count query doesn't reference limit/offset; strip them so any
        # strict driver doesn't complain about unused bind params.
        count_params = {k: v for k, v in params.items() if k not in ("limit", "offset")}
        count_rows = execute_sql(count_query, params=count_params, fetch_results=True)
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
            LEFT JOIN accounts acc ON acc.id = a.account_id
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
