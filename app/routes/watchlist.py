"""
Watchlist API routes.

Endpoints:
- GET /watchlist - Get current prices for watchlist tickers
- POST /watchlist/validate - Validate a ticker symbol
"""

import logging
from typing import Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel

from src.db import execute_sql
from src.market_data_service import _CRYPTO_SYMBOLS
from src.price_service import (
    get_latest_close,
    get_latest_closes_batch,
    get_previous_close,
    get_previous_closes_batch,
)

logger = logging.getLogger(__name__)
router = APIRouter()


class WatchlistItem(BaseModel):
    """Watchlist item with current price data."""

    symbol: str
    price: float
    change: float
    changePercent: float
    volume: int
    updatedAt: Optional[str] = None  # Date of the latest OHLCV record (YYYY-MM-DD)
    source: str = "databento"  # Price data source


class WatchlistResponse(BaseModel):
    """Watchlist items response."""

    items: list[WatchlistItem]


class ValidationRequest(BaseModel):
    """Ticker validation request."""

    ticker: str


class ValidationResponse(BaseModel):
    """Ticker validation response."""

    ticker: str
    valid: bool
    message: str


@router.get("", response_model=WatchlistResponse)
async def get_watchlist_prices(
    tickers: str = Query("", description="Comma-separated list of ticker symbols"),
):
    """
    Get current prices for watchlist tickers.

    Args:
        tickers: Comma-separated list of ticker symbols

    Returns:
        List of watchlist items with current price data
    """
    if not tickers:
        return WatchlistResponse(items=[])

    ticker_list = [t.strip().upper() for t in tickers.split(",") if t.strip()]

    if not ticker_list:
        return WatchlistResponse(items=[])

    # Batch fetch prices from Databento (2 queries total instead of N×2)
    prices_map = get_latest_closes_batch(ticker_list)
    prev_map = get_previous_closes_batch(ticker_list)

    # Batch fetch volume + latest date in one query
    vol_date_map = _batch_fetch_volume_and_date(ticker_list)

    # yfinance fallback for symbols not in Databento
    yf_quotes: dict[str, dict] = {}
    missing = [t for t in ticker_list if t not in prices_map]
    if missing:
        try:
            from src.market_data_service import get_realtime_quotes_batch

            yf_quotes = get_realtime_quotes_batch(missing)
        except Exception:
            pass

    items = []
    for symbol in ticker_list:
        price = prices_map.get(symbol)
        prev = prev_map.get(symbol)
        yf_q = yf_quotes.get(symbol)

        if price is None and yf_q:
            price = yf_q["price"]
            prev = yf_q.get("previousClose", price)
            source = "yfinance"
        elif price is not None:
            prev = prev or price
            source = "databento"
        else:
            continue  # No data from any source

        change = price - (prev or price)
        change_pct = (change / prev * 100) if prev and prev > 0 else 0

        vd = vol_date_map.get(symbol, {})
        items.append(
            WatchlistItem(
                symbol=symbol,
                price=round(price, 2),
                change=round(change, 2),
                changePercent=round(change_pct, 2),
                volume=int(vd.get("volume") or 0),
                updatedAt=vd.get("latest_date"),
                source=source,
            )
        )

    return WatchlistResponse(items=items)


def _batch_fetch_volume_and_date(symbols: list[str]) -> dict[str, dict]:
    """Fetch latest volume and date for *symbols* in a single query."""
    if not symbols:
        return {}
    # Exclude crypto symbols — Databento ohlcv_daily is equity-only
    equity_symbols = [s for s in symbols if s.upper().strip() not in _CRYPTO_SYMBOLS]
    if not equity_symbols:
        return {}
    try:
        rows = execute_sql(
            """
            SELECT DISTINCT ON (symbol)
                symbol,
                volume,
                date::text AS latest_date
            FROM ohlcv_daily
            WHERE symbol = ANY(:symbols)
            ORDER BY symbol, date DESC
            """,
            params={"symbols": equity_symbols},
            fetch_results=True,
        )
        result: dict[str, dict] = {}
        for row in rows or []:
            rd = dict(row._mapping) if hasattr(row, "_mapping") else dict(row)
            result[rd["symbol"]] = {
                "volume": int(rd.get("volume") or 0),
                "latest_date": rd.get("latest_date"),
            }
        return result
    except Exception as e:
        logger.warning("Batch volume/date fetch failed: %s", e)
        return {}


@router.post("/validate", response_model=ValidationResponse)
async def validate_ticker(request: ValidationRequest):
    """
    Validate a ticker symbol exists in the database.

    Args:
        request: Ticker symbol to validate

    Returns:
        Validation result with message
    """
    ticker = request.ticker.upper()

    try:
        # Check if symbol exists in symbols table
        result = execute_sql(
            """
            SELECT ticker, description
            FROM symbols
            WHERE UPPER(ticker) = :symbol
            LIMIT 1
            """,
            params={"symbol": ticker},
            fetch_results=True,
        )

        if result and len(result) > 0:
            return ValidationResponse(
                ticker=ticker,
                valid=True,
                message=f"Valid symbol: {result[0].get('description', ticker)}",
            )

        # Also check symbol_aliases table
        alias_result = execute_sql(
            """
            SELECT canonical_symbol
            FROM symbol_aliases
            WHERE UPPER(alias) = :ticker
            LIMIT 1
            """,
            params={"ticker": ticker},
            fetch_results=True,
        )

        if alias_result and len(alias_result) > 0:
            canonical = alias_result[0]["canonical_symbol"]
            return ValidationResponse(
                ticker=canonical,
                valid=True,
                message=f"Valid symbol (alias for {canonical})",
            )

        return ValidationResponse(
            ticker=ticker,
            valid=False,
            message="Symbol not found in database",
        )

    except Exception as e:
        logger.error(f"Error validating ticker {ticker}: {e}")
        return ValidationResponse(
            ticker=ticker,
            valid=False,
            message=f"Validation error: {str(e)}",
        )
