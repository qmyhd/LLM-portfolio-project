"""
Stocks API routes.

Endpoints:
- GET /stocks/{ticker} - Get stock profile with current data
- GET /stocks/{ticker}/ideas - Get trading ideas for a stock
- GET /stocks/{ticker}/ohlcv - Get OHLCV chart data

Response models match frontend TypeScript interfaces in types/api.ts.
"""

import logging
import math
import re
from datetime import date, datetime, timedelta
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Path, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from src.db import execute_sql
from src.market_data_service import _CRYPTO_SYMBOLS
from src.price_service import get_latest_close, get_ohlcv, get_previous_close

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Safe float helpers
# ---------------------------------------------------------------------------
def _safe_float(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        f = float(value)
        return default if math.isnan(f) or math.isinf(f) else f
    except (ValueError, TypeError):
        return default


def _safe_float_optional(value: Any) -> float | None:
    if value is None:
        return None
    try:
        f = float(value)
        return None if math.isnan(f) or math.isinf(f) else f
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Ticker validation helper
# ---------------------------------------------------------------------------
_TICKER_RE = re.compile(r"^[A-Z]{1,6}(\.[A-Z]+)?$")


def _validate_ticker(raw: str) -> str:
    """Normalise and validate a ticker symbol. Raises 400 on invalid input."""
    symbol = raw.strip().upper()
    if not _TICKER_RE.match(symbol):
        raise HTTPException(status_code=400, detail=f"Invalid ticker: {raw}")
    return symbol


# ---------------------------------------------------------------------------
# Stock profile models  (matches api.ts StockProfileCurrent)
# ---------------------------------------------------------------------------
class StockProfileCurrent(BaseModel):
    """Current stock profile with price data.

    Matches frontend ``types/api.ts`` StockProfileCurrent.
    Fields not yet computed are returned as ``null``.
    """

    ticker: str
    lastUpdated: str | None = None

    # Price metrics (from ohlcv_daily)
    latestClosePrice: float | None = None
    previousClosePrice: float | None = None
    dailyChangePct: float | None = None
    return1wPct: float | None = None
    return1mPct: float | None = None
    return3mPct: float | None = None
    return1yPct: float | None = None
    volatility30d: float | None = None
    volatility90d: float | None = None
    yearHigh: float | None = None
    yearLow: float | None = None
    avgVolume30d: int | None = None

    # Position metrics
    currentPositionQty: float | None = None
    currentPositionValue: float | None = None
    avgBuyPrice: float | None = None
    unrealizedPnl: float | None = None
    unrealizedPnlPct: float | None = None
    totalOrdersCount: int = 0
    buyOrdersCount: int = 0
    sellOrdersCount: int = 0
    avgOrderSize: float | None = None
    firstTradeDate: str | None = None
    lastTradeDate: str | None = None

    # Sentiment metrics
    totalMentionCount: int = 0
    mentionCount30d: int = 0
    mentionCount7d: int = 0
    avgSentimentScore: float | None = None
    bullishMentionPct: float | None = None
    bearishMentionPct: float | None = None
    neutralMentionPct: float | None = None
    firstMentionedAt: str | None = None
    lastMentionedAt: str | None = None

    # Label counts
    labelTradeExecutionCount: int = 0
    labelTradePlanCount: int = 0
    labelTechnicalAnalysisCount: int = 0
    labelOptionsCount: int = 0
    labelCatalystNewsCount: int = 0

    # Company metadata (from yfinance)
    companyName: str | None = None
    sector: str | None = None
    industry: str | None = None
    marketCap: int | None = None


# ---------------------------------------------------------------------------
# Trading idea models  (matches api.ts StockIdea / PriceLevel)
# ---------------------------------------------------------------------------
class PriceLevel(BaseModel):
    """Price level from parsed idea (matches api.ts PriceLevel)."""

    kind: str  # entry, target, stop, support, resistance
    value: float | None = None
    qualifier: str | None = None


class StockIdea(BaseModel):
    """Trading idea from Discord messages (matches api.ts StockIdea)."""

    id: int
    messageId: str
    primarySymbol: str
    symbols: list[str] = Field(default_factory=list)
    direction: str  # bullish, bearish, neutral, mixed
    action: str | None = None
    confidence: float
    labels: list[str]  # TradingLabel enum values
    levels: list[PriceLevel] = Field(default_factory=list)
    ideaText: str
    ideaSummary: str | None = None
    author: str
    sourceChannel: str
    sourceCreatedAt: str  # ISO timestamp
    parsedAt: str  # ISO timestamp


class IdeasResponse(BaseModel):
    """Ideas list response (matches api.ts IdeasResponse)."""

    ticker: str
    ideas: list[StockIdea]
    total: int


# ---------------------------------------------------------------------------
# OHLCV models  (matches api.ts OHLCVBar / ChartOrder / OHLCVSeries)
# ---------------------------------------------------------------------------
class OHLCVBar(BaseModel):
    """Single OHLCV bar (matches api.ts OHLCVBar)."""

    date: str  # YYYY-MM-DD
    open: float
    high: float
    low: float
    close: float
    volume: int


class ChartOrder(BaseModel):
    """Order for chart overlay (matches api.ts ChartOrder)."""

    date: str
    action: str  # BUY or SELL
    price: float
    quantity: float


class OHLCVSeries(BaseModel):
    """OHLCV time series data (matches api.ts OHLCVSeries)."""

    ticker: str
    period: str
    data: list[OHLCVBar]
    orders: list[ChartOrder]


# ---------------------------------------------------------------------------
# Stock activity models  (matches api.ts StockActivity)
# ---------------------------------------------------------------------------
class StockActivity(BaseModel):
    """Activity record for a specific stock."""

    id: str
    activityType: str | None = None
    tradeDate: str | None = None
    price: float | None = None
    units: float | None = None
    amount: float = 0.0
    fee: float = 0.0
    description: str | None = None


class StockActivitiesResponse(BaseModel):
    """Activities for a specific stock."""

    ticker: str
    activities: list[StockActivity]
    total: int


@router.get("/{ticker}", response_model=StockProfileCurrent)
async def get_stock_profile(
    ticker: str = Path(..., description="Stock ticker symbol"),
):
    """
    Get stock hub profile with price, position, sentiment and label metrics.

    Returns the rich ``StockProfileCurrent`` shape expected by the frontend
    stock hub page.  Fields that cannot be computed yet are returned as null.
    """
    symbol = _validate_ticker(ticker)

    try:
        # ---- 1. Current / previous close -----------------------------------
        current_price = get_latest_close(symbol)
        previous_close = get_previous_close(symbol)

        # If absolutely no data exists, 404
        if current_price is None:
            # Check if symbol exists at all
            sym_row = execute_sql(
                "SELECT 1 FROM symbols WHERE UPPER(ticker) = :s LIMIT 1",
                params={"s": symbol},
                fetch_results=True,
            )
            if not sym_row:
                raise HTTPException(
                    status_code=404, detail=f"Symbol {symbol} not found"
                )

        latest = current_price or 0.0
        prev = previous_close or latest
        daily_chg_pct = round(((latest - prev) / prev) * 100, 2) if prev else None
        # Guard: cap at 300% — treat as data error (same as portfolio endpoint)
        if daily_chg_pct is not None and abs(daily_chg_pct) > 300:
            logger.warning(
                f"⚠️ {symbol}: daily_chg_pct={daily_chg_pct:.1f}% exceeds 300%% cap, nulling"
            )
            daily_chg_pct = None

        # ---- 2. 52-week high/low & avg volume (30d) from ohlcv_daily -------
        # Databento ohlcv_daily is equity-only; skip for crypto symbols
        if symbol in _CRYPTO_SYMBOLS:
            stats_dict = {}
        else:
            stats = execute_sql(
                """
                SELECT
                    MAX(high)  AS year_high,
                    MIN(low)   AS year_low,
                    AVG(volume) FILTER (WHERE date >= CURRENT_DATE - 30)  AS avg_vol_30d
                FROM ohlcv_daily
                WHERE symbol = :s AND date >= CURRENT_DATE - 365
                """,
                params={"s": symbol},
                fetch_results=True,
            )
            stats_dict = (
                dict(stats[0]._mapping)  # type: ignore[arg-type]
                if stats and hasattr(stats[0], "_mapping")
                else {}
            )

        # ---- 3. Position metrics -------------------------------------------
        pos = execute_sql(
            """
            SELECT quantity, average_buy_price
            FROM positions WHERE symbol = :s AND quantity > 0 LIMIT 1
            """,
            params={"s": symbol},
            fetch_results=True,
        )
        pos_qty = pos_val = avg_buy = unr_pnl = unr_pnl_pct = None
        if pos:
            pd_ = dict(pos[0]._mapping) if hasattr(pos[0], "_mapping") else dict(pos[0])  # type: ignore[arg-type]
            pos_qty = float(pd_["quantity"] or 0)
            avg_buy = float(pd_["average_buy_price"] or 0)
            pos_val = round(pos_qty * latest, 2)
            cost = pos_qty * avg_buy
            unr_pnl = round(pos_val - cost, 2)
            unr_pnl_pct = round((unr_pnl / cost) * 100, 2) if cost else None

        # ---- 4. Order counts -----------------------------------------------
        ord_stats = execute_sql(
            """
            SELECT
                COUNT(*)                                  AS total,
                COUNT(*) FILTER (WHERE UPPER(action)='BUY')  AS buys,
                COUNT(*) FILTER (WHERE UPPER(action)='SELL') AS sells,
                AVG(filled_quantity)                        AS avg_size,
                MIN(time_executed)                         AS first_trade,
                MAX(time_executed)                         AS last_trade
            FROM orders
            WHERE UPPER(symbol) = :s AND status = 'filled'
            """,
            params={"s": symbol},
            fetch_results=True,
        )
        od = (
            dict(ord_stats[0]._mapping)  # type: ignore[arg-type]
            if ord_stats and hasattr(ord_stats[0], "_mapping")
            else {}
        )

        # ---- 5. Sentiment / mention metrics --------------------------------
        sent = execute_sql(
            """
            SELECT
                COUNT(*)                                                  AS total_mentions,
                COUNT(*) FILTER (WHERE dm.created_at >= NOW() - INTERVAL '30 days') AS m30d,
                COUNT(*) FILTER (WHERE dm.created_at >= NOW() - INTERVAL '7 days')  AS m7d,
                COUNT(*) FILTER (WHERE dpi.direction = 'bullish')         AS bull,
                COUNT(*) FILTER (WHERE dpi.direction = 'bearish')         AS bear,
                COUNT(*) FILTER (WHERE dpi.direction = 'neutral')         AS neut,
                MIN(dm.created_at) AS first_at,
                MAX(dm.created_at) AS last_at
            FROM discord_parsed_ideas dpi
            LEFT JOIN discord_messages dm ON dpi.message_id::text = dm.message_id
            WHERE UPPER(dpi.primary_symbol) = :s
            """,
            params={"s": symbol},
            fetch_results=True,
        )
        sd = (
            dict(sent[0]._mapping)  # type: ignore[arg-type]
            if sent and hasattr(sent[0], "_mapping")
            else {}
        )
        total_ment = int(sd.get("total_mentions") or 0)

        def _pct(n: int) -> float | None:
            return round(n / total_ment * 100, 1) if total_ment else None

        # ---- 6. Label counts -----------------------------------------------
        label_counts = execute_sql(
            """
            SELECT
                COUNT(*) FILTER (WHERE 'TRADE_EXECUTION'     = ANY(labels)) AS exec,
                COUNT(*) FILTER (WHERE 'TRADE_PLAN'           = ANY(labels)) AS plan,
                COUNT(*) FILTER (WHERE 'TECHNICAL_ANALYSIS'   = ANY(labels)) AS ta,
                COUNT(*) FILTER (WHERE 'OPTIONS'              = ANY(labels)) AS opt,
                COUNT(*) FILTER (WHERE 'CATALYST_NEWS'        = ANY(labels)) AS cat
            FROM discord_parsed_ideas
            WHERE UPPER(primary_symbol) = :s
            """,
            params={"s": symbol},
            fetch_results=True,
        )
        lc = (
            dict(label_counts[0]._mapping)  # type: ignore[arg-type]
            if label_counts and hasattr(label_counts[0], "_mapping")
            else {}
        )

        now_str = datetime.utcnow().isoformat() + "Z"

        # ---- 7. yfinance enrichment (return metrics + company info) --------
        yf_returns: dict | None = None
        yf_company: dict | None = None
        try:
            from src.market_data_service import get_company_info, get_return_metrics

            yf_returns = get_return_metrics(symbol)
            yf_company = get_company_info(symbol)
        except Exception as exc:
            logger.debug("yfinance enrichment skipped for %s: %s", symbol, exc)

        return StockProfileCurrent(
            ticker=symbol,
            lastUpdated=now_str,
            latestClosePrice=round(latest, 2) if latest else None,
            previousClosePrice=round(prev, 2) if prev else None,
            dailyChangePct=daily_chg_pct,
            # Return metrics from yfinance
            return1wPct=(yf_returns or {}).get("return1w"),
            return1mPct=(yf_returns or {}).get("return1m"),
            return3mPct=(yf_returns or {}).get("return3m"),
            return1yPct=(yf_returns or {}).get("return1y"),
            volatility30d=(yf_returns or {}).get("volatility30d"),
            volatility90d=(yf_returns or {}).get("volatility90d"),
            yearHigh=(
                float(stats_dict["year_high"]) if stats_dict.get("year_high") else None
            ),
            yearLow=(
                float(stats_dict["year_low"]) if stats_dict.get("year_low") else None
            ),
            avgVolume30d=(
                int(stats_dict["avg_vol_30d"])
                if stats_dict.get("avg_vol_30d")
                else None
            ),
            # Position
            currentPositionQty=pos_qty,
            currentPositionValue=pos_val,
            avgBuyPrice=round(avg_buy, 2) if avg_buy else None,
            unrealizedPnl=unr_pnl,
            unrealizedPnlPct=unr_pnl_pct,
            # Orders
            totalOrdersCount=int(od.get("total") or 0),
            buyOrdersCount=int(od.get("buys") or 0),
            sellOrdersCount=int(od.get("sells") or 0),
            avgOrderSize=(
                round(float(od["avg_size"]), 2) if od.get("avg_size") else None
            ),
            firstTradeDate=str(od["first_trade"]) if od.get("first_trade") else None,
            lastTradeDate=str(od["last_trade"]) if od.get("last_trade") else None,
            # Sentiment
            totalMentionCount=total_ment,
            mentionCount30d=int(sd.get("m30d") or 0),
            mentionCount7d=int(sd.get("m7d") or 0),
            bullishMentionPct=_pct(int(sd.get("bull") or 0)),
            bearishMentionPct=_pct(int(sd.get("bear") or 0)),
            neutralMentionPct=_pct(int(sd.get("neut") or 0)),
            firstMentionedAt=str(sd["first_at"]) if sd.get("first_at") else None,
            lastMentionedAt=str(sd["last_at"]) if sd.get("last_at") else None,
            # Labels
            labelTradeExecutionCount=int(lc.get("exec") or 0),
            labelTradePlanCount=int(lc.get("plan") or 0),
            labelTechnicalAnalysisCount=int(lc.get("ta") or 0),
            labelOptionsCount=int(lc.get("opt") or 0),
            labelCatalystNewsCount=int(lc.get("cat") or 0),
            # Company metadata from yfinance
            companyName=(yf_company or {}).get("name"),
            sector=(yf_company or {}).get("sector") or None,
            industry=(yf_company or {}).get("industry") or None,
            marketCap=(yf_company or {}).get("marketCap") or None,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching stock profile for {symbol}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{ticker}/ideas", response_model=IdeasResponse)
async def get_stock_ideas(
    ticker: str = Path(..., description="Stock ticker symbol"),
    direction: str | None = Query(
        None, description="Filter by direction (bullish, bearish, neutral)"
    ),
    limit: int = Query(50, ge=1, le=100, description="Number of ideas to return"),
):
    """
    Get trading ideas for a stock from Discord parsed messages.

    Returns the ``IdeasResponse`` shape matching frontend ``types/api.ts``.
    """
    symbol = _validate_ticker(ticker)

    try:
        # Build query — search both primary_symbol and symbols[] array
        conditions = ["(UPPER(dpi.primary_symbol) = :symbol OR :symbol = ANY(dpi.symbols))"]
        params: dict = {"symbol": symbol, "limit": limit}

        if direction:
            conditions.append("dpi.direction = :direction")
            params["direction"] = direction.lower()

        where_clause = " AND ".join(conditions)

        query = f"""
            SELECT
                dpi.id,
                dpi.message_id,
                dpi.primary_symbol,
                dpi.direction,
                dpi.labels,
                dpi.confidence,
                dpi.levels,
                dpi.idea_text,
                dpi.idea_summary,
                dpi.parsed_at,
                dm.author,
                dm.created_at,
                dm.channel
            FROM discord_parsed_ideas dpi
            LEFT JOIN discord_messages dm ON dpi.message_id::text = dm.message_id
            WHERE {where_clause}
            ORDER BY dm.created_at DESC NULLS LAST
            LIMIT :limit
        """

        ideas_data = execute_sql(query, params=params, fetch_results=True)

        ideas = []
        for row in ideas_data or []:
            row_dict = dict(row._mapping) if hasattr(row, "_mapping") else dict(row)

            # Build levels list (matches api.ts PriceLevel[])
            levels: list[PriceLevel] = []
            for lvl in row_dict.get("levels") or []:
                if isinstance(lvl, dict):
                    levels.append(
                        PriceLevel(
                            kind=lvl.get("kind") or "entry",
                            value=(
                                float(v)
                                if (
                                    v := lvl.get("value")
                                    or lvl.get("price")
                                    or lvl.get("high")
                                )
                                else None
                            ),
                            qualifier=lvl.get("qualifier") or lvl.get("label"),
                        )
                    )

            ideas.append(
                StockIdea(
                    id=int(row_dict["id"]),
                    messageId=str(row_dict["message_id"]),
                    primarySymbol=row_dict["primary_symbol"],
                    symbols=[row_dict["primary_symbol"]],
                    direction=row_dict.get("direction") or "neutral",
                    action=None,
                    confidence=float(row_dict.get("confidence") or 0.5),
                    labels=row_dict.get("labels") or [],
                    levels=levels,
                    ideaText=row_dict.get("idea_text") or "",
                    ideaSummary=row_dict.get("idea_summary"),
                    author=row_dict.get("author") or "",
                    sourceChannel=row_dict.get("channel") or "",
                    sourceCreatedAt=(
                        str(row_dict["created_at"])
                        if row_dict.get("created_at")
                        else ""
                    ),
                    parsedAt=(
                        str(row_dict["parsed_at"]) if row_dict.get("parsed_at") else ""
                    ),
                )
            )

        # Get total count (may be more than returned due to limit)
        count_q = """
            SELECT COUNT(*) as cnt FROM discord_parsed_ideas dpi
            WHERE (UPPER(dpi.primary_symbol) = :symbol OR :symbol = ANY(dpi.symbols))
        """
        if direction:
            count_q += " AND dpi.direction = :direction"
        count_rows = execute_sql(count_q, params=params, fetch_results=True)
        total = int(count_rows[0]["cnt"]) if count_rows else len(ideas)

        return IdeasResponse(
            ticker=symbol,
            ideas=ideas,
            total=total,
        )

    except Exception as e:
        logger.error(f"Error fetching ideas for {symbol}: {e}")
        return IdeasResponse(ticker=symbol, ideas=[], total=0)


@router.get("/{ticker}/ohlcv", response_model=OHLCVSeries)
async def get_stock_ohlcv(
    ticker: str = Path(..., description="Stock ticker symbol"),
    period: str = Query(
        "1M",
        description="Time period: 1W, 2W, 1M, 3M, 6M, 1Y, 2Y, YTD, MAX",
    ),
):
    """
    Get OHLCV chart data for a stock.

    Returns deterministic, date-ascending bars suitable for TradingView /
    lightweight-charts.  Bars always sorted oldest → newest.

    Response shape matches frontend ``types/api.ts`` ``OHLCVSeries``.
    """
    symbol = _validate_ticker(ticker)

    # Validate period
    today = date.today()
    period_upper = period.strip().upper()

    period_days = {
        "1W": 7,
        "2W": 14,
        "1M": 30,
        "3M": 90,
        "6M": 180,
        "1Y": 365,
        "2Y": 730,
        "YTD": (today - date(today.year, 1, 1)).days or 1,
        "MAX": 365 * 10,  # ~10 years
    }

    days = period_days.get(period_upper)
    if days is None:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid period '{period}'. Use: {', '.join(period_days.keys())}",
        )

    start_date = today - timedelta(days=days)

    try:
        # get_ohlcv expects date objects, returns mplfinance-compatible DataFrame
        ohlcv_df = get_ohlcv(symbol, start_date, today)

        bars: list[OHLCVBar] = []
        if ohlcv_df is not None and not ohlcv_df.empty:
            for idx, row in ohlcv_df.iterrows():
                # Index is DatetimeIndex from price_service
                bar_date = str(idx.date()) if hasattr(idx, "date") else str(idx)
                bars.append(
                    OHLCVBar(
                        date=bar_date[:10],  # Ensure YYYY-MM-DD
                        open=round(float(row.get("Open", row.get("open", 0))), 2),
                        high=round(float(row.get("High", row.get("high", 0))), 2),
                        low=round(float(row.get("Low", row.get("low", 0))), 2),
                        close=round(float(row.get("Close", row.get("close", 0))), 2),
                        volume=int(row.get("Volume", row.get("volume", 0))),
                    )
                )

        # Guarantee ascending date order
        bars.sort(key=lambda b: b.date)

        # Get orders for chart overlay
        orders_data = execute_sql(
            """
            SELECT
                DATE(time_executed) as date,
                action as side,
                execution_price as price,
                filled_quantity as quantity
            FROM orders
            WHERE UPPER(symbol) = :symbol
              AND time_executed >= :start_date
              AND status = 'filled'
            ORDER BY time_executed
            """,
            params={"symbol": symbol, "start_date": start_date.isoformat()},
            fetch_results=True,
        )

        orders: list[ChartOrder] = []
        for row in orders_data or []:
            row_dict = dict(row._mapping) if hasattr(row, "_mapping") else dict(row)  # type: ignore[arg-type]
            orders.append(
                ChartOrder(
                    date=str(row_dict["date"]),
                    action=(row_dict["side"] or "BUY").upper(),
                    price=(
                        round(float(row_dict["price"]), 2) if row_dict["price"] else 0
                    ),
                    quantity=(
                        round(float(row_dict["quantity"]), 4)
                        if row_dict["quantity"]
                        else 0
                    ),
                )
            )

        payload = OHLCVSeries(
            ticker=symbol,
            period=period_upper,
            data=bars,
            orders=orders,
        )

        # Return with Cache-Control header for frontend revalidation
        return JSONResponse(
            content=payload.model_dump(),
            headers={"Cache-Control": "public, max-age=300, stale-while-revalidate=60"},
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching OHLCV for {symbol}: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to fetch OHLCV for {symbol}"
        )


@router.get("/{ticker}/activities", response_model=StockActivitiesResponse)
async def get_stock_activities(
    ticker: str = Path(..., description="Stock ticker symbol"),
    limit: int = Query(50, ge=1, le=200, description="Number of activities"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
):
    """Get trade and dividend activity history for a specific stock."""
    clean = _validate_ticker(ticker)

    try:
        count_q = """
            SELECT COUNT(*) as cnt
            FROM activities
            WHERE UPPER(symbol) = UPPER(:ticker)
        """
        count_rows = execute_sql(count_q, params={"ticker": clean}, fetch_results=True)
        total = int(count_rows[0]["cnt"]) if count_rows else 0

        query = """
            SELECT id, activity_type, trade_date, price, units, amount, fee, description
            FROM activities
            WHERE UPPER(symbol) = UPPER(:ticker)
            ORDER BY trade_date DESC, created_at DESC
            LIMIT :limit OFFSET :offset
        """
        rows = execute_sql(
            query, params={"ticker": clean, "limit": limit, "offset": offset}, fetch_results=True
        ) or []

        activities = []
        for r in rows:
            row = dict(r._mapping) if hasattr(r, "_mapping") else dict(r)
            activities.append(
                StockActivity(
                    id=str(row.get("id", "")),
                    activityType=row.get("activity_type"),
                    tradeDate=str(row["trade_date"]) if row.get("trade_date") else None,
                    price=_safe_float_optional(row.get("price")),
                    units=_safe_float_optional(row.get("units")),
                    amount=_safe_float(row.get("amount")),
                    fee=_safe_float(row.get("fee")),
                    description=row.get("description"),
                )
            )

        return StockActivitiesResponse(ticker=clean, activities=activities, total=total)

    except Exception as e:
        logger.error(f"Error fetching activities for {clean}: {e}", exc_info=True)
        return StockActivitiesResponse(ticker=clean, activities=[], total=0)
