"""
Sentiment API routes.

Endpoints:
- GET /sentiment/summary?ticker=NVDA&window=30d - Sentiment summary for a ticker
- GET /sentiment/messages?ticker=NVDA&limit=20&cursor=0 - Paginated messages mentioning a ticker
"""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from src.db import execute_sql

logger = logging.getLogger(__name__)
router = APIRouter()

_WINDOW_DAYS = {"7d": 7, "30d": 30, "90d": 90, "1y": 365}


class SentimentSummary(BaseModel):
    """Sentiment summary for a ticker over a time window."""

    ticker: str
    window: str
    totalMentions: int
    bullishPct: Optional[float] = None
    bearishPct: Optional[float] = None
    neutralPct: Optional[float] = None
    firstMentionedAt: Optional[str] = None
    lastMentionedAt: Optional[str] = None


class MessageItem(BaseModel):
    """A single Discord message mentioning a ticker."""

    id: int
    messageId: str
    ticker: str
    direction: str
    ideaText: str
    author: str
    channel: str
    createdAt: Optional[str] = None
    labels: list[str]


class MessagesResponse(BaseModel):
    """Paginated messages response."""

    ticker: str
    messages: list[MessageItem]
    total: int
    nextCursor: Optional[int] = None


@router.get("/summary", response_model=SentimentSummary)
async def get_sentiment_summary(
    ticker: str = Query(..., description="Stock ticker symbol"),
    window: str = Query("30d", description="Time window: 7d, 30d, 90d, 1y"),
):
    """
    Get sentiment summary for a ticker within a time window.

    Returns aggregated bullish/bearish/neutral mention counts and percentages.
    Window applies to the message creation date.
    """
    symbol = ticker.strip().upper()
    days = _WINDOW_DAYS.get(window.lower())
    if days is None:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid window '{window}'. Use: {', '.join(_WINDOW_DAYS.keys())}",
        )

    try:
        rows = execute_sql(
            """
            SELECT
                COUNT(*)                                               AS total,
                COUNT(*) FILTER (WHERE dpi.direction = 'bullish')     AS bull,
                COUNT(*) FILTER (WHERE dpi.direction = 'bearish')     AS bear,
                COUNT(*) FILTER (WHERE dpi.direction = 'neutral')     AS neut,
                MIN(dm.created_at)                                    AS first_at,
                MAX(dm.created_at)                                    AS last_at
            FROM discord_parsed_ideas dpi
            LEFT JOIN discord_messages dm ON dpi.message_id::text = dm.message_id
            WHERE UPPER(dpi.primary_symbol) = :symbol
              AND (
                  dm.created_at IS NULL
                  OR dm.created_at >= NOW() - (:days || ' days')::interval
              )
            """,
            params={"symbol": symbol, "days": days},
            fetch_results=True,
        )

        row = (
            dict(rows[0]._mapping)
            if rows and hasattr(rows[0], "_mapping")
            else (dict(rows[0]) if rows else {})
        )
        total = int(row.get("total") or 0)

        def pct(n: int) -> Optional[float]:
            return round(n / total * 100, 1) if total else None

        return SentimentSummary(
            ticker=symbol,
            window=window.lower(),
            totalMentions=total,
            bullishPct=pct(int(row.get("bull") or 0)),
            bearishPct=pct(int(row.get("bear") or 0)),
            neutralPct=pct(int(row.get("neut") or 0)),
            firstMentionedAt=str(row["first_at"]) if row.get("first_at") else None,
            lastMentionedAt=str(row["last_at"]) if row.get("last_at") else None,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching sentiment summary for {symbol}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/messages", response_model=MessagesResponse)
async def get_sentiment_messages(
    ticker: str = Query(..., description="Stock ticker symbol"),
    limit: int = Query(20, ge=1, le=100, description="Max messages to return"),
    cursor: int = Query(0, ge=0, description="Pagination offset"),
):
    """
    Get paginated Discord messages mentioning a ticker.

    Uses integer cursor (offset) pagination. Pass nextCursor from the previous
    response to get the next page.
    """
    symbol = ticker.strip().upper()

    try:
        rows = execute_sql(
            """
            SELECT
                dpi.id,
                dpi.message_id,
                dpi.primary_symbol,
                dpi.direction,
                dpi.idea_text,
                dpi.labels,
                dm.author,
                dm.channel,
                dm.created_at
            FROM discord_parsed_ideas dpi
            LEFT JOIN discord_messages dm ON dpi.message_id::text = dm.message_id
            WHERE UPPER(dpi.primary_symbol) = :symbol
            ORDER BY dm.created_at DESC NULLS LAST
            LIMIT :limit OFFSET :offset
            """,
            params={"symbol": symbol, "limit": limit, "offset": cursor},
            fetch_results=True,
        )

        count_rows = execute_sql(
            "SELECT COUNT(*) AS total FROM discord_parsed_ideas WHERE UPPER(primary_symbol) = :symbol",
            params={"symbol": symbol},
            fetch_results=True,
        )
        total = 0
        if count_rows:
            cr = (
                dict(count_rows[0]._mapping)
                if hasattr(count_rows[0], "_mapping")
                else dict(count_rows[0])
            )
            total = int(cr.get("total") or 0)

        messages = []
        for row in rows or []:
            d = dict(row._mapping) if hasattr(row, "_mapping") else dict(row)
            messages.append(
                MessageItem(
                    id=int(d["id"]),
                    messageId=str(d["message_id"]),
                    ticker=d.get("primary_symbol") or symbol,
                    direction=d.get("direction") or "neutral",
                    ideaText=d.get("idea_text") or "",
                    author=d.get("author") or "",
                    channel=d.get("channel") or "",
                    createdAt=str(d["created_at"]) if d.get("created_at") else None,
                    labels=d.get("labels") or [],
                )
            )

        next_cursor = cursor + limit if (cursor + limit) < total else None

        return MessagesResponse(
            ticker=symbol,
            messages=messages,
            total=total,
            nextCursor=next_cursor,
        )

    except Exception as e:
        logger.error(f"Error fetching messages for {symbol}: {e}")
        raise HTTPException(status_code=500, detail=str(e))
