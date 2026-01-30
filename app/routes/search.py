"""
Search API routes.

Endpoints:
- GET /search - Search for stocks/tickers by symbol or name
"""

import logging
from typing import Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel

from src.db import execute_sql

logger = logging.getLogger(__name__)
router = APIRouter()


class SearchResult(BaseModel):
    """Individual search result."""

    symbol: str
    name: str
    sector: Optional[str]
    type: str  # "stock" or "etf"


class SearchResponse(BaseModel):
    """Search results response."""

    results: list[SearchResult]
    query: str
    total: int


@router.get("", response_model=SearchResponse)
async def search_symbols(
    q: str = Query(..., min_length=1, description="Search query"),
    limit: int = Query(10, ge=1, le=50, description="Maximum results"),
):
    """
    Search for stocks/tickers by symbol or name.

    Args:
        q: Search query (matches symbol prefix or name contains)
        limit: Maximum number of results to return

    Returns:
        List of matching symbols with metadata
    """
    query_upper = q.upper()

    try:
        # Search symbols table
        # Match symbol prefix OR name contains
        results_data = execute_sql(
            """
            SELECT DISTINCT
                symbol,
                name,
                exchange
            FROM symbols
            WHERE UPPER(symbol) LIKE :prefix
               OR UPPER(name) LIKE :contains
            ORDER BY
                CASE WHEN UPPER(symbol) = :exact THEN 0
                     WHEN UPPER(symbol) LIKE :prefix THEN 1
                     ELSE 2
                END,
                symbol
            LIMIT :limit
            """,
            params={
                "prefix": f"{query_upper}%",
                "contains": f"%{query_upper}%",
                "exact": query_upper,
                "limit": limit,
            },
            fetch_results=True,
        )

        results = []
        for row in results_data or []:
            symbol = row["symbol"]

            # Determine type (ETF or stock based on common patterns)
            is_etf = symbol in [
                "SPY",
                "QQQ",
                "IWM",
                "DIA",
                "VTI",
                "VOO",
                "VXX",
                "UVXY",
                "SQQQ",
                "TQQQ",
            ]

            results.append(
                SearchResult(
                    symbol=symbol,
                    name=row.get("name", symbol),
                    sector=None,  # Would need sector data in symbols table
                    type="etf" if is_etf else "stock",
                )
            )

        return SearchResponse(
            results=results,
            query=q,
            total=len(results),
        )

    except Exception as e:
        logger.error(f"Error searching symbols: {e}")
        return SearchResponse(results=[], query=q, total=0)
