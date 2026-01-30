"""
Stocks API routes.

Endpoints:
- GET /stocks/{ticker} - Get stock profile with current data
- GET /stocks/{ticker}/ideas - Get trading ideas for a stock
- GET /stocks/{ticker}/ohlcv - Get OHLCV chart data
"""

import logging
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, HTTPException, Path, Query
from pydantic import BaseModel

from src.db import execute_sql
from src.price_service import get_ohlcv, get_latest_close, get_previous_close

logger = logging.getLogger(__name__)
router = APIRouter()


# Stock profile models
class StockProfileCurrent(BaseModel):
    """Current stock profile with price data."""

    symbol: str
    name: str
    sector: Optional[str]
    exchange: Optional[str]
    currentPrice: float
    previousClose: float
    dayChange: float
    dayChangePercent: float
    volume: int
    avgVolume: Optional[int]
    marketCap: Optional[float]
    high52Week: Optional[float]
    low52Week: Optional[float]


# Trading idea models
class PriceLevel(BaseModel):
    """Price level with optional label."""

    price: float
    label: Optional[str]


class StockIdea(BaseModel):
    """Trading idea from Discord messages."""

    id: int
    messageId: str
    symbol: str
    direction: str  # "bullish", "bearish", "neutral"
    labels: list[str]
    confidence: float
    entryLevels: list[PriceLevel]
    targetLevels: list[PriceLevel]
    stopLevels: list[PriceLevel]
    rawText: str
    author: Optional[str]
    createdAt: str
    channelType: Optional[str]


class IdeasResponse(BaseModel):
    """Ideas list response."""

    ideas: list[StockIdea]
    total: int


# OHLCV models
class OHLCVBar(BaseModel):
    """Single OHLCV bar."""

    date: str
    open: float
    high: float
    low: float
    close: float
    volume: int


class ChartOrder(BaseModel):
    """Order for chart overlay."""

    date: str
    side: str
    price: float
    quantity: float


class OHLCVSeries(BaseModel):
    """OHLCV time series data."""

    symbol: str
    period: str
    bars: list[OHLCVBar]
    orders: list[ChartOrder]


@router.get("/{ticker}", response_model=StockProfileCurrent)
async def get_stock_profile(
    ticker: str = Path(..., description="Stock ticker symbol"),
):
    """
    Get stock profile with current price data.

    Args:
        ticker: Stock ticker symbol (e.g., AAPL, MSFT)

    Returns:
        Stock profile with current price and change metrics
    """
    symbol = ticker.upper()

    try:
        # Get symbol info from database
        symbol_data = execute_sql(
            """
            SELECT symbol, name, exchange
            FROM symbols
            WHERE UPPER(symbol) = :symbol
            """,
            params={"symbol": symbol},
            fetch_results=True,
        )

        if not symbol_data:
            raise HTTPException(status_code=404, detail=f"Symbol {symbol} not found")

        symbol_info = symbol_data[0]

        # Get current and previous close from OHLCV
        current_price = get_latest_close(symbol) or 0.0
        previous_close = get_previous_close(symbol) or current_price

        # Calculate day change
        day_change = current_price - previous_close
        day_change_pct = (
            (day_change / previous_close * 100) if previous_close > 0 else 0
        )

        # Get volume from latest OHLCV bar
        today = datetime.now().date()
        week_ago = today - timedelta(days=7)
        ohlcv_df = get_ohlcv(symbol, week_ago.isoformat(), today.isoformat())

        volume = 0
        if ohlcv_df is not None and not ohlcv_df.empty:
            volume = int(ohlcv_df.iloc[-1].get("volume", 0))

        return StockProfileCurrent(
            symbol=symbol,
            name=symbol_info.get("name", symbol),
            sector=None,  # Would need sector data
            exchange=symbol_info.get("exchange"),
            currentPrice=round(current_price, 2),
            previousClose=round(previous_close, 2),
            dayChange=round(day_change, 2),
            dayChangePercent=round(day_change_pct, 2),
            volume=volume,
            avgVolume=None,
            marketCap=None,
            high52Week=None,
            low52Week=None,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching stock profile for {symbol}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{ticker}/ideas", response_model=IdeasResponse)
async def get_stock_ideas(
    ticker: str = Path(..., description="Stock ticker symbol"),
    direction: Optional[str] = Query(
        None, description="Filter by direction (bullish, bearish, neutral)"
    ),
    limit: int = Query(50, ge=1, le=100, description="Number of ideas to return"),
):
    """
    Get trading ideas for a stock from Discord parsed messages.

    Args:
        ticker: Stock ticker symbol
        direction: Optional filter for idea direction
        limit: Maximum number of ideas to return

    Returns:
        List of trading ideas with levels and metadata
    """
    symbol = ticker.upper()

    try:
        # Build query
        conditions = ["UPPER(dpi.primary_symbol) = :symbol"]
        params = {"symbol": symbol, "limit": limit}

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
                dpi.entry_levels,
                dpi.target_levels,
                dpi.stop_levels,
                dpi.raw_chunk,
                dm.author_name,
                dm.created_at,
                dm.channel_type
            FROM discord_parsed_ideas dpi
            LEFT JOIN discord_messages dm ON dpi.message_id = dm.message_id
            WHERE {where_clause}
            ORDER BY dm.created_at DESC
            LIMIT :limit
        """

        ideas_data = execute_sql(query, params=params, fetch_results=True)

        ideas = []
        for row in ideas_data or []:
            # Parse levels from JSON arrays
            entry_levels = []
            target_levels = []
            stop_levels = []

            if row.get("entry_levels"):
                for level in row["entry_levels"]:
                    if isinstance(level, dict):
                        entry_levels.append(
                            PriceLevel(
                                price=level.get("price", 0),
                                label=level.get("label"),
                            )
                        )
                    elif isinstance(level, (int, float)):
                        entry_levels.append(PriceLevel(price=float(level), label=None))

            if row.get("target_levels"):
                for level in row["target_levels"]:
                    if isinstance(level, dict):
                        target_levels.append(
                            PriceLevel(
                                price=level.get("price", 0),
                                label=level.get("label"),
                            )
                        )
                    elif isinstance(level, (int, float)):
                        target_levels.append(PriceLevel(price=float(level), label=None))

            if row.get("stop_levels"):
                for level in row["stop_levels"]:
                    if isinstance(level, dict):
                        stop_levels.append(
                            PriceLevel(
                                price=level.get("price", 0),
                                label=level.get("label"),
                            )
                        )
                    elif isinstance(level, (int, float)):
                        stop_levels.append(PriceLevel(price=float(level), label=None))

            ideas.append(
                StockIdea(
                    id=row["id"],
                    messageId=str(row["message_id"]),
                    symbol=row["primary_symbol"],
                    direction=row.get("direction", "neutral"),
                    labels=row.get("labels", []) or [],
                    confidence=float(row.get("confidence", 0.5)),
                    entryLevels=entry_levels,
                    targetLevels=target_levels,
                    stopLevels=stop_levels,
                    rawText=row.get("raw_chunk", ""),
                    author=row.get("author_name"),
                    createdAt=str(row["created_at"]) if row.get("created_at") else "",
                    channelType=row.get("channel_type"),
                )
            )

        return IdeasResponse(
            ideas=ideas,
            total=len(ideas),
        )

    except Exception as e:
        logger.error(f"Error fetching ideas for {symbol}: {e}")
        return IdeasResponse(ideas=[], total=0)


@router.get("/{ticker}/ohlcv", response_model=OHLCVSeries)
async def get_stock_ohlcv(
    ticker: str = Path(..., description="Stock ticker symbol"),
    period: str = Query("1M", description="Time period (1W, 1M, 3M, 6M, 1Y, YTD)"),
):
    """
    Get OHLCV chart data for a stock.

    Args:
        ticker: Stock ticker symbol
        period: Time period for the chart

    Returns:
        OHLCV bars and order overlays for charting
    """
    symbol = ticker.upper()

    try:
        # Calculate date range based on period
        today = datetime.now().date()

        period_days = {
            "1W": 7,
            "1M": 30,
            "3M": 90,
            "6M": 180,
            "1Y": 365,
            "YTD": (today - datetime(today.year, 1, 1).date()).days,
        }

        days = period_days.get(period.upper(), 30)
        start_date = today - timedelta(days=days)

        # Get OHLCV data from price service
        ohlcv_df = get_ohlcv(symbol, start_date.isoformat(), today.isoformat())

        bars = []
        if ohlcv_df is not None and not ohlcv_df.empty:
            for idx, row in ohlcv_df.iterrows():
                bars.append(
                    OHLCVBar(
                        date=(
                            str(idx)
                            if hasattr(idx, "__str__")
                            else str(row.get("date", ""))
                        ),
                        open=round(float(row.get("open", 0)), 2),
                        high=round(float(row.get("high", 0)), 2),
                        low=round(float(row.get("low", 0)), 2),
                        close=round(float(row.get("close", 0)), 2),
                        volume=int(row.get("volume", 0)),
                    )
                )

        # Get orders for chart overlay
        orders_data = execute_sql(
            """
            SELECT
                DATE(filled_at) as date,
                side,
                filled_price as price,
                filled_quantity as quantity
            FROM orders
            WHERE UPPER(symbol) = :symbol
              AND filled_at >= :start_date
              AND status = 'filled'
            ORDER BY filled_at
            """,
            params={"symbol": symbol, "start_date": start_date.isoformat()},
            fetch_results=True,
        )

        orders = []
        for row in orders_data or []:
            orders.append(
                ChartOrder(
                    date=str(row["date"]),
                    side=row["side"],
                    price=float(row["price"]) if row["price"] else 0,
                    quantity=float(row["quantity"]) if row["quantity"] else 0,
                )
            )

        return OHLCVSeries(
            symbol=symbol,
            period=period.upper(),
            bars=bars,
            orders=orders,
        )

    except Exception as e:
        logger.error(f"Error fetching OHLCV for {symbol}: {e}")
        return OHLCVSeries(symbol=symbol, period=period, bars=[], orders=[])
