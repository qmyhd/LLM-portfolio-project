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
from src.price_service import get_latest_close, get_previous_close

logger = logging.getLogger(__name__)
router = APIRouter()


class WatchlistItem(BaseModel):
    """Watchlist item with current price data."""

    symbol: str
    price: float
    change: float
    changePercent: float
    volume: int


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

    items = []

    for symbol in ticker_list:
        try:
            # Get current and previous close
            current_price = get_latest_close(symbol)

            if current_price is None:
                continue

            previous_close = get_previous_close(symbol) or current_price

            # Calculate change
            change = current_price - previous_close
            change_pct = (change / previous_close * 100) if previous_close > 0 else 0

            # Volume would need OHLCV lookup - simplified here
            volume = 0

            items.append(
                WatchlistItem(
                    symbol=symbol,
                    price=round(current_price, 2),
                    change=round(change, 2),
                    changePercent=round(change_pct, 2),
                    volume=volume,
                )
            )

        except Exception as e:
            logger.warning(f"Error fetching watchlist data for {symbol}: {e}")
            continue

    return WatchlistResponse(items=items)


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
            SELECT symbol, name
            FROM symbols
            WHERE UPPER(symbol) = :symbol
            LIMIT 1
            """,
            params={"symbol": ticker},
            fetch_results=True,
        )

        if result and len(result) > 0:
            return ValidationResponse(
                ticker=ticker,
                valid=True,
                message=f"Valid symbol: {result[0].get('name', ticker)}",
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
