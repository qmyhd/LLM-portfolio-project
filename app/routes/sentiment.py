"""
Sentiment API routes.

Endpoints:
- GET /sentiment/summary?ticker=NVDA&window=30d - Sentiment summary for a ticker
- GET /sentiment/messages?ticker=NVDA&limit=20&cursor=0 - Paginated messages mentioning a ticker
"""

import logging
from datetime import UTC
from typing import Any, Optional

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
    bullishPct: float | None = None
    bearishPct: float | None = None
    neutralPct: float | None = None
    firstMentionedAt: str | None = None
    lastMentionedAt: str | None = None


class MessageItem(BaseModel):
    """A single Discord message mentioning a ticker."""

    id: int
    messageId: str
    ticker: str
    direction: str
    ideaText: str
    author: str
    channel: str
    createdAt: str | None = None
    labels: list[str]


class MessagesResponse(BaseModel):
    """Paginated messages response."""

    ticker: str
    messages: list[MessageItem]
    total: int


class FeedLevel(BaseModel):
    """One price level extracted by the NLP parser (entry, target, stop, etc.)."""

    kind: str | None = None  # entry | target | stop | support | resistance | ...
    value: float | None = None
    low: float | None = None
    high: float | None = None
    qualifier: str | None = None  # 'above', 'around', etc.


class FeedItem(BaseModel):
    """One recent feed item — either an NLP-parsed idea or a raw Discord
    message with auto-extracted tickers + vader sentiment.

    `source` distinguishes the two:
    - 'parsed': came from discord_parsed_ideas, has direction/labels/levels
    - 'raw'   : came from discord_messages, has vader sentimentScore + tickers
    """

    id: str  # int for parsed, message_id for raw — both string-safe
    source: str  # 'parsed' | 'raw'
    messageId: str
    ticker: str | None = None
    tickers: list[str] = []  # all tickers detected (raw msgs may mention several)
    direction: str  # bullish | bearish | neutral | mixed
    ideaText: str
    author: str
    channel: str
    channelType: str | None = None  # trading | market | general
    createdAt: str | None = None
    labels: list[str] = []
    confidence: float | None = None
    sentimentScore: float | None = None  # vader, -1..+1
    # Trade-actionable fields (parsed only)
    action: str | None = None  # buy | sell | trim | add | watch | hold | ...
    instrument: str | None = None  # equity | option | crypto | ...
    levels: list[FeedLevel] = []


class FeedResponse(BaseModel):
    """Recent feed across all tickers and channels."""

    items: list[FeedItem]
    trendingTickers: list[str]  # unique tickers in the feed, ordered by recency
    parsedCount: int  # how many items came from discord_parsed_ideas
    rawCount: int  # how many items came from discord_messages directly
    nextCursor: int | None = None


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

        def pct(n: int) -> float | None:
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
        raise HTTPException(status_code=500, detail=str(e)) from e


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
        raise HTTPException(status_code=500, detail=str(e)) from e


def _parsed_direction(value: Any) -> str:
    """Normalize parser's direction value to the front-end's vocabulary."""
    if not value:
        return "neutral"
    v = str(value).lower()
    if v in ("bullish", "bearish", "neutral", "mixed"):
        return v
    return "neutral"


def _sentiment_to_direction(score: Any) -> str:
    """Translate a vader compound score to a direction chip color.

    Mirrors the same thresholds the multi-agent sentiment analyzer uses:
    > 0.2 → bullish, < -0.2 → bearish, else neutral.
    """
    if score is None:
        return "neutral"
    try:
        s = float(score)
    except (TypeError, ValueError):
        return "neutral"
    if s > 0.2:
        return "bullish"
    if s < -0.2:
        return "bearish"
    return "neutral"


def _parse_tickers_field(raw: Any) -> list[str]:
    """`discord_messages.tickers_detected` is a comma-separated text column.
    Split, uppercase, dedupe while preserving order."""
    if not raw:
        return []
    if isinstance(raw, list):
        items = [str(t).strip().upper() for t in raw if str(t).strip()]
    else:
        items = [t.strip().upper() for t in str(raw).split(",") if t.strip()]
    # Dedupe preserving order
    seen: set[str] = set()
    out: list[str] = []
    for t in items:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


@router.get("/feed", response_model=FeedResponse)
async def get_sentiment_feed(
    limit: int = Query(40, ge=1, le=200, description="Max items to return"),
    days: int = Query(30, ge=1, le=365, description="Lookback window in days"),
    channel_type: str | None = Query(
        None,
        description=(
            "Filter by channel type: 'trading', 'market', 'general', or omit for all. "
            "Matches the type tag assigned at ingest time."
        ),
    ),
    source: str | None = Query(
        None,
        description=(
            "Restrict to 'parsed' (NLP-extracted ideas only) or 'raw' "
            "(direct Discord messages only). Default is both, merged."
        ),
    ),
):
    """Recent feed of Discord activity — parsed ideas + raw messages, merged.

    Powers the research home page. The previous version only surfaced
    ``discord_parsed_ideas`` rows, which meant any message stuck in
    ``parse_status='pending'`` (the common case until the NLP batch runs)
    didn't appear at all. This version walks ``discord_messages``
    directly, LEFT JOINs to its parsed counterpart, and shows the parsed
    fields when available and the raw vader sentiment + extracted tickers
    when not.

    Filters:
    - ``channel_type``: 'trading' for trading-picks, 'market' for market-news
    - ``source``: 'parsed' to see only LLM-parsed entries, 'raw' for the rest
    """
    # Normalize filter args
    ct = (channel_type or "").strip().lower() or None
    src = (source or "").strip().lower() or None
    if src not in (None, "parsed", "raw"):
        src = None

    where_clauses = [
        "dm.created_at > NOW() - (:days || ' days')::INTERVAL",
        "dm.content IS NOT NULL",
        "dm.content != ''",
        # Drop bot announcements and slash commands — they're never useful here
        "COALESCE(dm.is_bot, false) = false",
        "COALESCE(dm.is_command, false) = false",
        # Drop messages the prefilter explicitly marked as noise
        "COALESCE(dm.parse_status, 'pending') NOT IN ('noise', 'skipped')",
    ]
    params: dict[str, Any] = {"days": str(days), "limit": limit}

    if ct:
        where_clauses.append("LOWER(COALESCE(dm.channel_type, '')) = :ct")
        params["ct"] = ct

    if src == "parsed":
        where_clauses.append("dpi.id IS NOT NULL")
    elif src == "raw":
        where_clauses.append("dpi.id IS NULL")

    where_sql = "\n          AND ".join(where_clauses)

    try:
        rows = execute_sql(
            f"""
            SELECT
                dm.message_id,
                dm.author,
                dm.channel,
                dm.channel_type,
                dm.content,
                dm.tickers_detected,
                dm.sentiment_score,
                dm.created_at,
                dpi.id              AS parsed_id,
                dpi.primary_symbol  AS parsed_primary_symbol,
                dpi.symbols         AS parsed_symbols,
                dpi.direction       AS parsed_direction,
                dpi.action          AS parsed_action,
                dpi.instrument      AS parsed_instrument,
                dpi.confidence      AS parsed_confidence,
                dpi.idea_text       AS parsed_idea_text,
                dpi.labels          AS parsed_labels,
                dpi.levels          AS parsed_levels
            FROM discord_messages dm
            LEFT JOIN discord_parsed_ideas dpi
              ON dpi.message_id::text = dm.message_id
             AND dpi.is_noise IS NOT TRUE
            WHERE {where_sql}
            ORDER BY dm.created_at DESC NULLS LAST
            LIMIT :limit
            """,
            params=params,
            fetch_results=True,
        ) or []

        items: list[FeedItem] = []
        seen_tickers: list[str] = []
        parsed_count = 0
        raw_count = 0

        for r in rows:
            d = dict(r._mapping) if hasattr(r, "_mapping") else dict(r)
            is_parsed = d.get("parsed_id") is not None

            # Decide ticker(s) for this item: prefer parsed primary_symbol,
            # fall back to first extracted ticker from raw.
            raw_tickers = _parse_tickers_field(d.get("tickers_detected"))
            parsed_symbols = d.get("parsed_symbols") or []
            primary = d.get("parsed_primary_symbol")
            if primary:
                primary = str(primary).upper()
            elif raw_tickers:
                primary = raw_tickers[0]
            else:
                primary = None

            # All tickers for this item (used for trending strip)
            tickers = []
            if parsed_symbols:
                tickers = [str(s).upper() for s in parsed_symbols if s]
            elif raw_tickers:
                tickers = raw_tickers

            for t in tickers:
                if t not in seen_tickers:
                    seen_tickers.append(t)

            # Direction: parser's call if available, else vader-derived
            if is_parsed:
                direction = _parsed_direction(d.get("parsed_direction"))
            else:
                direction = _sentiment_to_direction(d.get("sentiment_score"))

            # Body text: prefer parser's idea_text (cleaner), else raw content
            idea_text = (d.get("parsed_idea_text") or d.get("content") or "").strip()
            # Trim very long raw messages for the card view; full content is
            # still on the stock-detail Raw tab.
            if not is_parsed and len(idea_text) > 600:
                idea_text = idea_text[:600].rsplit(" ", 1)[0] + "…"

            # Levels: parser returns JSONB list-of-dicts; normalize to FeedLevel
            levels: list[FeedLevel] = []
            raw_levels = d.get("parsed_levels")
            if raw_levels:
                try:
                    if isinstance(raw_levels, str):
                        import json as _json
                        raw_levels = _json.loads(raw_levels)
                    for lvl in raw_levels or []:
                        if not isinstance(lvl, dict):
                            continue
                        levels.append(FeedLevel(
                            kind=lvl.get("kind"),
                            value=_safe_float(lvl.get("value")),
                            low=_safe_float(lvl.get("low")),
                            high=_safe_float(lvl.get("high")),
                            qualifier=lvl.get("qualifier"),
                        ))
                except Exception:
                    pass  # Bad JSON in levels → just skip

            if is_parsed:
                parsed_count += 1
            else:
                raw_count += 1

            items.append(
                FeedItem(
                    id=str(d.get("parsed_id") or d["message_id"]),
                    source="parsed" if is_parsed else "raw",
                    messageId=str(d["message_id"]),
                    ticker=primary,
                    tickers=tickers[:5],  # cap to avoid bloating the response
                    direction=direction,
                    ideaText=idea_text,
                    author=d.get("author") or "",
                    channel=d.get("channel") or "",
                    channelType=d.get("channel_type"),
                    createdAt=str(d["created_at"]) if d.get("created_at") else None,
                    labels=list(d.get("parsed_labels") or []),
                    confidence=(
                        float(d["parsed_confidence"])
                        if d.get("parsed_confidence") is not None
                        else None
                    ),
                    sentimentScore=(
                        float(d["sentiment_score"])
                        if d.get("sentiment_score") is not None
                        else None
                    ),
                    action=d.get("parsed_action"),
                    instrument=d.get("parsed_instrument"),
                    levels=levels,
                )
            )

        return FeedResponse(
            items=items,
            trendingTickers=seen_tickers[:12],
            parsedCount=parsed_count,
            rawCount=raw_count,
        )

    except Exception as e:
        logger.error(f"Error fetching sentiment feed: {e}", exc_info=True)
        return FeedResponse(items=[], trendingTickers=[], parsedCount=0, rawCount=0)


def _safe_float(v: Any) -> float | None:
    """Convert numeric-ish to float, returning None on bad input."""
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# =============================================================================
# Admin: pipeline status + reparse
# =============================================================================


class PipelineStatus(BaseModel):
    """Snapshot of where Discord messages sit in the NLP pipeline."""

    pending: int
    ok: int
    error: int
    skipped: int
    noise: int
    parsedIdeas: int  # rows in discord_parsed_ideas
    lastMessageAt: str | None = None
    lastParsedAt: str | None = None
    backlogDays: float | None = None  # age of oldest pending message in days


class ReparseRequest(BaseModel):
    """Reparse-request body.

    `messageIds` resets specific messages to ``parse_status='pending'``.
    `resetStatuses` (alternative) resets all messages currently in the
    listed statuses (e.g. ``['skipped', 'noise']``) so the next batch
    picks them up. Provide one or the other; if both are present
    ``messageIds`` wins.
    """

    messageIds: list[str] | None = None
    resetStatuses: list[str] | None = None
    sinceDays: int | None = None  # only reset messages newer than N days


class ReparseResponse(BaseModel):
    reset: int  # how many discord_messages rows were flipped to 'pending'
    deletedParsedIdeas: int  # how many discord_parsed_ideas rows were dropped
    note: str  # what to do next (e.g. "next nightly batch will pick these up")


@router.get("/status", response_model=PipelineStatus)
async def get_sentiment_status():
    """Pipeline status snapshot — backlog counts and last-activity times.

    Useful for the admin UI / health checks: confirms the NLP batch is
    running and surfaces unparsed backlog before it gets bad.
    """
    try:
        rows = execute_sql(
            """
            SELECT
                COUNT(*) FILTER (WHERE parse_status = 'pending')                 AS pending,
                COUNT(*) FILTER (WHERE parse_status = 'ok')                      AS ok,
                COUNT(*) FILTER (WHERE parse_status = 'error')                   AS errored,
                COUNT(*) FILTER (WHERE parse_status = 'skipped')                 AS skipped,
                COUNT(*) FILTER (WHERE parse_status = 'noise')                   AS noise,
                MAX(created_at)                                                  AS last_msg_at,
                MIN(created_at) FILTER (WHERE parse_status = 'pending')          AS oldest_pending_at
            FROM discord_messages
            """,
            fetch_results=True,
        ) or []
        d = dict(rows[0]._mapping) if rows and hasattr(rows[0], "_mapping") else (dict(rows[0]) if rows else {})

        parsed_rows = execute_sql(
            "SELECT COUNT(*) AS n, MAX(created_at) AS last_at FROM discord_parsed_ideas",
            fetch_results=True,
        ) or []
        pd = (
            dict(parsed_rows[0]._mapping)
            if parsed_rows and hasattr(parsed_rows[0], "_mapping")
            else (dict(parsed_rows[0]) if parsed_rows else {})
        )

        oldest = d.get("oldest_pending_at")
        backlog_days: float | None = None
        if oldest is not None:
            from datetime import datetime, timezone
            try:
                ts = oldest if hasattr(oldest, "tzinfo") else datetime.fromisoformat(str(oldest))
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=UTC)
                backlog_days = round((datetime.now(UTC) - ts).total_seconds() / 86400, 2)
            except Exception:
                backlog_days = None

        return PipelineStatus(
            pending=int(d.get("pending") or 0),
            ok=int(d.get("ok") or 0),
            error=int(d.get("errored") or 0),
            skipped=int(d.get("skipped") or 0),
            noise=int(d.get("noise") or 0),
            parsedIdeas=int(pd.get("n") or 0),
            lastMessageAt=str(d["last_msg_at"]) if d.get("last_msg_at") else None,
            lastParsedAt=str(pd["last_at"]) if pd.get("last_at") else None,
            backlogDays=backlog_days,
        )
    except Exception as e:
        logger.error(f"Error fetching sentiment status: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e)) from e


_RESETTABLE_STATUSES = frozenset({"ok", "error", "skipped", "noise", "pending"})


@router.post("/reparse", response_model=ReparseResponse)
async def reparse_messages(req: ReparseRequest):
    """Flag messages back to ``parse_status='pending'`` so the next NLP
    batch re-processes them. This endpoint does NOT run the parser
    in-band — it just resets state. The nightly batch (or
    ``scripts/nlp/parse_messages.py``) picks them up on the next run.

    Two modes, in priority order:

    1. ``messageIds=['123', '456']`` — explicit, surgical. Drops any
       existing ``discord_parsed_ideas`` rows for those messages and
       sets them to pending.
    2. ``resetStatuses=['skipped', 'noise']`` — bulk. Resets every
       message currently in one of the named statuses. Optionally
       limited with ``sinceDays``.

    Always returns the counts so the caller knows what was actually
    affected (e.g., a typo'd messageId yields ``reset=0``).
    """
    # Mode 1 — explicit message IDs
    if req.messageIds:
        ids = [str(m).strip() for m in req.messageIds if str(m).strip()]
        if not ids:
            return ReparseResponse(reset=0, deletedParsedIdeas=0, note="no message ids provided")
        # Drop any parsed ideas for these messages so the reparse starts clean
        del_rows = execute_sql(
            "DELETE FROM discord_parsed_ideas WHERE message_id::text = ANY(:ids) RETURNING id",
            params={"ids": ids},
            fetch_results=True,
        ) or []
        upd_rows = execute_sql(
            """
            UPDATE discord_messages
               SET parse_status = 'pending',
                   error_reason = NULL
             WHERE message_id = ANY(:ids)
            RETURNING message_id
            """,
            params={"ids": ids},
            fetch_results=True,
        ) or []
        return ReparseResponse(
            reset=len(upd_rows),
            deletedParsedIdeas=len(del_rows),
            note="Marked as pending — next NLP batch will reparse.",
        )

    # Mode 2 — by status
    statuses = [str(s).strip().lower() for s in (req.resetStatuses or []) if str(s).strip()]
    statuses = [s for s in statuses if s in _RESETTABLE_STATUSES]
    if not statuses:
        raise HTTPException(
            status_code=400,
            detail=(
                "Provide either messageIds=[...] or resetStatuses=[...] (one of "
                f"{sorted(_RESETTABLE_STATUSES)})"
            ),
        )

    params: dict[str, Any] = {"statuses": statuses}
    where_extra = ""
    if req.sinceDays is not None and req.sinceDays > 0:
        where_extra = " AND created_at > NOW() - (:days || ' days')::INTERVAL"
        params["days"] = str(req.sinceDays)

    # Drop parsed ideas only for the messages we're about to reset
    del_rows = execute_sql(
        f"""
        DELETE FROM discord_parsed_ideas
        WHERE message_id::text IN (
            SELECT message_id FROM discord_messages
             WHERE parse_status = ANY(:statuses){where_extra}
        )
        RETURNING id
        """,
        params=params,
        fetch_results=True,
    ) or []

    upd_rows = execute_sql(
        f"""
        UPDATE discord_messages
           SET parse_status = 'pending',
               error_reason = NULL
         WHERE parse_status = ANY(:statuses){where_extra}
        RETURNING message_id
        """,
        params=params,
        fetch_results=True,
    ) or []

    return ReparseResponse(
        reset=len(upd_rows),
        deletedParsedIdeas=len(del_rows),
        note=(
            f"Reset {len(upd_rows)} message(s) in status {statuses} to pending. "
            "Next NLP batch will reparse."
        ),
    )
