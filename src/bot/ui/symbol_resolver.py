"""
Symbol Resolver - Maps company names and aliases to stock tickers.

Provides unified lookup for resolving user input (company names, partial matches,
or tickers) to canonical stock symbols.

Uses multiple sources:
1. ALIAS_MAP from preclean.py (hardcoded common names)
2. Database symbols table (ticker and description search)
3. Database positions table (for held symbols)
"""

import logging
from typing import Optional, Tuple, List

logger = logging.getLogger(__name__)


def resolve_symbol(user_input: str) -> Tuple[str, Optional[str]]:
    """
    Resolve user input to a stock ticker symbol.

    Handles:
    - Direct ticker input: "NVDA" -> ("NVDA", "NVIDIA Corp")
    - Company name: "nvidia" -> ("NVDA", "NVIDIA Corp")
    - Alias/subsidiary: "waymo" -> ("GOOGL", "Alphabet Inc.")
    - Partial match: "apple" -> ("AAPL", "Apple Inc.")

    Args:
        user_input: Raw user input (ticker or company name)

    Returns:
        Tuple of (resolved_ticker, company_description)
        If not found, returns (original_input.upper(), None)

    Example:
        >>> resolve_symbol("nvidia")
        ('NVDA', 'NVIDIA Corporation')
        >>> resolve_symbol("AAPL")
        ('AAPL', 'Apple Inc.')
        >>> resolve_symbol("waymo")
        ('GOOGL', 'Alphabet Inc. Class A')
    """
    if not user_input:
        return ("", None)

    user_input = user_input.strip()
    user_upper = user_input.upper()
    user_lower = user_input.lower()

    # 1. Check ALIAS_MAP first (fast, in-memory)
    try:
        from src.nlp.preclean import ALIAS_MAP

        if user_lower in ALIAS_MAP:
            ticker = ALIAS_MAP[user_lower]
            description = _get_description_from_db(ticker)
            return (ticker, description)
    except ImportError:
        pass

    # 2. Check if it's already a valid ticker in our database
    description = _get_description_from_db(user_upper)
    if description:
        return (user_upper, description)

    # 3. Search symbols table by description (fuzzy match)
    match = _search_symbols_by_description(user_input)
    if match:
        return match

    # 4. Check positions table (user might have a position in this)
    pos_match = _search_positions_by_symbol(user_upper)
    if pos_match:
        return pos_match

    # 5. Return as-is (uppercase), no description found
    return (user_upper, None)


def _get_description_from_db(ticker: str) -> Optional[str]:
    """Get company description from symbols table."""
    try:
        from src.db import execute_sql

        result = execute_sql(
            """
            SELECT description FROM symbols 
            WHERE ticker = :ticker OR id = :ticker 
            LIMIT 1
            """,
            params={"ticker": ticker},
            fetch_results=True,
        )
        if result and result[0][0]:
            return str(result[0][0])
    except Exception:
        pass
    return None


def _search_symbols_by_description(
    search_term: str,
) -> Optional[Tuple[str, Optional[str]]]:
    """
    Search symbols table by description (case-insensitive LIKE).

    Returns first match as (ticker, description).
    """
    try:
        from src.db import execute_sql

        result = execute_sql(
            """
            SELECT ticker, description FROM symbols 
            WHERE LOWER(description) LIKE :pattern 
            LIMIT 1
            """,
            params={"pattern": f"%{search_term.lower()}%"},
            fetch_results=True,
        )
        if result and result[0][0]:
            return (str(result[0][0]), str(result[0][1]) if result[0][1] else None)
    except Exception:
        pass
    return None


def _search_positions_by_symbol(ticker: str) -> Optional[Tuple[str, Optional[str]]]:
    """
    Check positions table for matching symbol.

    Useful when symbol isn't in symbols table but user holds it.
    """
    try:
        from src.db import execute_sql

        result = execute_sql(
            """
            SELECT symbol, symbol_description FROM positions 
            WHERE symbol = :ticker 
            LIMIT 1
            """,
            params={"ticker": ticker},
            fetch_results=True,
        )
        if result and result[0][0]:
            return (str(result[0][0]), str(result[0][1]) if result[0][1] else None)
    except Exception:
        pass
    return None


def get_symbol_info(ticker: str) -> dict:
    """
    Get comprehensive symbol information from database.

    Args:
        ticker: Stock ticker symbol

    Returns:
        Dict with keys: ticker, description, logo_url, exchange, asset_type
    """
    info = {
        "ticker": ticker.upper(),
        "description": None,
        "logo_url": None,
        "exchange": None,
        "asset_type": None,
    }

    try:
        from src.db import execute_sql

        result = execute_sql(
            """
            SELECT ticker, description, logo_url, exchange_name, asset_type 
            FROM symbols 
            WHERE ticker = :ticker OR id = :ticker 
            LIMIT 1
            """,
            params={"ticker": ticker.upper()},
            fetch_results=True,
        )
        if result:
            row = result[0]
            info["ticker"] = row[0] or ticker.upper()
            info["description"] = row[1]
            info["logo_url"] = row[2]
            info["exchange"] = row[3]
            info["asset_type"] = row[4]

    except Exception as e:
        logger.debug(f"Failed to get symbol info for {ticker}: {e}")

    return info


def search_symbols(query: str, limit: int = 10) -> List[dict]:
    """
    Search for symbols matching a query.

    Searches both ticker and description.

    Args:
        query: Search query
        limit: Max results (default 10)

    Returns:
        List of dicts with ticker, description, logo_url
    """
    results = []

    try:
        from src.db import execute_sql

        db_result = execute_sql(
            """
            SELECT ticker, description, logo_url 
            FROM symbols 
            WHERE ticker LIKE :pattern OR LOWER(description) LIKE :pattern_lower
            ORDER BY 
                CASE WHEN ticker = :exact THEN 0 ELSE 1 END,
                ticker
            LIMIT :limit
            """,
            params={
                "pattern": f"{query.upper()}%",
                "pattern_lower": f"%{query.lower()}%",
                "exact": query.upper(),
                "limit": limit,
            },
            fetch_results=True,
        )

        for row in db_result or []:
            results.append(
                {
                    "ticker": row[0],
                    "description": row[1],
                    "logo_url": row[2],
                }
            )

    except Exception as e:
        logger.debug(f"Symbol search failed: {e}")

    return results
