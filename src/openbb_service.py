"""
OpenBB Data Service -- OpenBB Platform SDK wrapper with TTL caching.

Provides fundamental data, earnings transcripts, SEC filings, management
data, and company news via the OpenBB Platform SDK.

All public functions return None or empty lists on failure -- they never
raise exceptions to callers.

Providers:
- FMP (Financial Modeling Prep): fundamentals, transcripts, management, news
- SEC: filings (free, no API key required)
"""

import logging
import os
import threading
from datetime import datetime
from typing import Optional

from cachetools import TTLCache

from src.retry_utils import hardened_retry

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Cache configuration (thread-safe, one per data category)
# ---------------------------------------------------------------------------
_transcript_cache = TTLCache(maxsize=100, ttl=86_400)  # 24 h
_transcript_lock = threading.Lock()

_management_cache = TTLCache(maxsize=200, ttl=86_400)  # 24 h
_management_lock = threading.Lock()

_fundamentals_cache = TTLCache(maxsize=200, ttl=3_600)  # 1 h
_fundamentals_lock = threading.Lock()

_filings_cache = TTLCache(maxsize=200, ttl=3_600)  # 1 h
_filings_lock = threading.Lock()

_news_cache = TTLCache(maxsize=200, ttl=900)  # 15 min
_news_lock = threading.Lock()

# ---------------------------------------------------------------------------
# Internal: lazy-init the OpenBB singleton
# ---------------------------------------------------------------------------
_obb_instance = None
_obb_lock = threading.Lock()


def _get_obb():
    """Lazy-initialize the OpenBB ``obb`` singleton.

    Sets the FMP API key from environment on first call.
    Returns None if openbb is not installed or config fails.
    """
    global _obb_instance
    if _obb_instance is not None:
        return _obb_instance

    with _obb_lock:
        if _obb_instance is not None:
            return _obb_instance
        try:
            from openbb import obb

            # Configure FMP API key from environment
            fmp_key = os.environ.get("FMP_API_KEY", "")
            if fmp_key:
                obb.user.credentials.fmp_api_key = fmp_key

            _obb_instance = obb
            logger.info("OpenBB Platform SDK initialized")
            return _obb_instance
        except ImportError:
            logger.warning("openbb package not installed")
            return None
        except Exception as e:
            logger.warning("OpenBB initialization failed: %s", e)
            return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_earnings_transcript(
    symbol: str, year: int | None = None, quarter: int | None = None
) -> list[dict] | None:
    """Return earnings call transcript(s) or None on failure.

    Each dict has: {date, content, quarter, year, symbol}
    """
    symbol = symbol.upper().strip()
    if year is None:
        year = datetime.now().year

    cache_key = f"{symbol}_{year}_{quarter or 'all'}"

    with _transcript_lock:
        cached = _transcript_cache.get(cache_key)
        if cached is not None:
            return cached

    try:
        result = _fetch_transcript(symbol, year, quarter)
        if result:
            with _transcript_lock:
                _transcript_cache[cache_key] = result
        return result
    except Exception as e:
        logger.warning("OpenBB transcript failed for %s: %s", symbol, e)
        return None


def get_management(symbol: str) -> list[dict] | None:
    """Return key executives list or None on failure.

    Each dict has: {name, title, pay, currency, gender, yearBorn, titleSince}
    """
    symbol = symbol.upper().strip()

    with _management_lock:
        cached = _management_cache.get(symbol)
        if cached is not None:
            return cached

    try:
        result = _fetch_management(symbol)
        if result:
            with _management_lock:
                _management_cache[symbol] = result
        return result
    except Exception as e:
        logger.warning("OpenBB management failed for %s: %s", symbol, e)
        return None


def get_fundamentals(symbol: str) -> dict | None:
    """Return fundamental metrics dict or None on failure.

    Dict has: {marketCap, peRatio, epsActual, revenuePerShare,
               debtToEquity, currentRatio, returnOnEquity, ...}
    """
    symbol = symbol.upper().strip()

    with _fundamentals_lock:
        cached = _fundamentals_cache.get(symbol)
        if cached is not None:
            return cached

    try:
        result = _fetch_fundamentals(symbol)
        if result:
            with _fundamentals_lock:
                _fundamentals_cache[symbol] = result
        return result
    except Exception as e:
        logger.warning("OpenBB fundamentals failed for %s: %s", symbol, e)
        return None


def get_filings(
    symbol: str, form_type: str | None = None, limit: int = 10
) -> list[dict] | None:
    """Return SEC filings list or None on failure.

    Each dict has: {filingDate, formType, reportUrl, description}
    Uses SEC provider (free, no API key).
    """
    symbol = symbol.upper().strip()
    cache_key = f"{symbol}_{form_type or 'all'}_{limit}"

    with _filings_lock:
        cached = _filings_cache.get(cache_key)
        if cached is not None:
            return cached

    try:
        result = _fetch_filings(symbol, form_type, limit)
        if result:
            with _filings_lock:
                _filings_cache[cache_key] = result
        return result
    except Exception as e:
        logger.warning("OpenBB filings failed for %s: %s", symbol, e)
        return None


def get_company_news(symbol: str, limit: int = 10) -> list[dict] | None:
    """Return company news list or None on failure.

    Each dict has: {date, title, text, url, source, images}
    """
    symbol = symbol.upper().strip()
    cache_key = f"{symbol}_{limit}"

    with _news_lock:
        cached = _news_cache.get(cache_key)
        if cached is not None:
            return cached

    try:
        result = _fetch_news(symbol, limit)
        if result:
            with _news_lock:
                _news_cache[cache_key] = result
        return result
    except Exception as e:
        logger.warning("OpenBB news failed for %s: %s", symbol, e)
        return None


def is_available() -> bool:
    """Check whether the openbb package is importable and configured."""
    return _get_obb() is not None


# ---------------------------------------------------------------------------
# Internal fetchers (retried, never called directly by routes)
# ---------------------------------------------------------------------------


@hardened_retry(max_retries=2, delay=1)
def _fetch_transcript(
    symbol: str, year: int, quarter: int | None
) -> list[dict] | None:
    obb = _get_obb()
    if obb is None:
        return None

    kwargs: dict = {"symbol": symbol, "year": str(year), "provider": "fmp"}
    if quarter is not None:
        kwargs["quarter"] = quarter

    response = obb.equity.fundamental.transcript(**kwargs)
    if not response or not response.results:
        return None

    transcripts = []
    for item in response.results:
        d = item.__dict__ if hasattr(item, "__dict__") else {}
        transcripts.append({
            "date": str(d.get("date", "")),
            "content": d.get("transcript", d.get("content", "")),
            "quarter": d.get("quarter"),
            "year": d.get("year", year),
            "symbol": symbol,
        })

    return transcripts if transcripts else None


@hardened_retry(max_retries=2, delay=1)
def _fetch_management(symbol: str) -> list[dict] | None:
    obb = _get_obb()
    if obb is None:
        return None

    response = obb.equity.fundamental.management(symbol=symbol, provider="fmp")
    if not response or not response.results:
        return None

    executives = []
    for item in response.results:
        d = item.__dict__ if hasattr(item, "__dict__") else {}
        executives.append({
            "name": d.get("name", ""),
            "title": d.get("title", d.get("designation", "")),
            "pay": d.get("pay"),
            "currency": d.get("currency_pay", d.get("currency", "USD")),
            "gender": d.get("gender"),
            "yearBorn": d.get("year_born", d.get("birth_year")),
            "titleSince": str(d.get("title_since", "")) if d.get("title_since") else None,
        })

    return executives if executives else None


@hardened_retry(max_retries=2, delay=1)
def _fetch_fundamentals(symbol: str) -> dict | None:
    obb = _get_obb()
    if obb is None:
        return None

    response = obb.equity.fundamental.metrics(
        symbol=symbol, provider="fmp", period="annual", limit=1
    )
    if not response or not response.results:
        return None

    # Take the most recent result
    item = response.results[0]
    d = item.__dict__ if hasattr(item, "__dict__") else {}

    return {
        "marketCap": d.get("market_cap"),
        "peRatio": d.get("pe_ratio"),
        "pegRatio": d.get("peg_ratio"),
        "epsActual": d.get("earnings_per_share") or d.get("eps"),
        "revenuePerShare": d.get("revenue_per_share"),
        "debtToEquity": d.get("debt_to_equity"),
        "currentRatio": d.get("current_ratio"),
        "returnOnEquity": d.get("return_on_equity"),
        "returnOnAssets": d.get("return_on_assets"),
        "dividendYield": d.get("dividend_yield"),
        "priceToBook": d.get("price_to_book"),
        "priceToSales": d.get("price_to_sales_ratio"),
        "bookValuePerShare": d.get("book_value_per_share"),
        "freeCashFlowPerShare": d.get("free_cash_flow_per_share"),
    }


@hardened_retry(max_retries=2, delay=1)
def _fetch_filings(
    symbol: str, form_type: str | None, limit: int
) -> list[dict] | None:
    obb = _get_obb()
    if obb is None:
        return None

    kwargs: dict = {"symbol": symbol, "provider": "sec", "limit": limit}
    if form_type:
        kwargs["form_type"] = form_type

    response = obb.equity.fundamental.filings(**kwargs)
    if not response or not response.results:
        return None

    filings = []
    for item in response.results:
        d = item.__dict__ if hasattr(item, "__dict__") else {}
        filings.append({
            "filingDate": str(d.get("filing_date", d.get("date", ""))),
            "formType": d.get("form_type", d.get("type", "")),
            "reportUrl": d.get("report_url", d.get("link", d.get("url", ""))),
            "description": d.get("description", ""),
            "acceptedDate": str(d.get("accepted_date", "")) if d.get("accepted_date") else None,
        })

    return filings if filings else None


@hardened_retry(max_retries=2, delay=1)
def _fetch_news(symbol: str, limit: int) -> list[dict] | None:
    obb = _get_obb()
    if obb is None:
        return None

    response = obb.news.company(symbols=symbol, provider="fmp", limit=limit)
    if not response or not response.results:
        return None

    articles = []
    for item in response.results:
        d = item.__dict__ if hasattr(item, "__dict__") else {}
        articles.append({
            "date": str(d.get("date", "")),
            "title": d.get("title", ""),
            "text": d.get("text", ""),
            "url": d.get("url", ""),
            "source": d.get("site", d.get("source", "")),
            "images": d.get("images") or [],
        })

    return articles if articles else None
