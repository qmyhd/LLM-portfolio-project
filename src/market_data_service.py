"""
Market Data Service — yfinance wrapper with TTL caching.

Provides supplementary market data as a FALLBACK to Databento/SnapTrade.
All public functions return None or empty dicts on failure — they never raise
exceptions to callers.

This module is NOT the primary price source.  ``src/price_service.py``
(Databento via ``ohlcv_daily``) remains the source of truth for OHLCV data.
"""

import logging
import threading
from typing import Optional

from cachetools import TTLCache

from src.retry_utils import hardened_retry

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Cache configuration  (thread-safe, one per data category)
# ---------------------------------------------------------------------------
_company_cache = TTLCache(maxsize=500, ttl=86_400)  # 24 h
_company_lock = threading.Lock()

_quote_cache = TTLCache(maxsize=500, ttl=300)  # 5 min
_quote_lock = threading.Lock()

_returns_cache = TTLCache(maxsize=500, ttl=3_600)  # 1 h
_returns_lock = threading.Lock()

_search_cache = TTLCache(maxsize=200, ttl=3_600)  # 1 h
_search_lock = threading.Lock()

# Known crypto tickers that need -USD suffix for yfinance
_CRYPTO_SYMBOLS = frozenset(
    {"XRP", "BTC", "ETH", "SOL", "ADA", "DOGE", "AVAX", "LINK", "DOT", "MATIC", "SHIB",
     "PEPE", "TRUMP"}
)

# Canonical identity for each crypto asset — single source of truth
# quote_symbol: yfinance-compatible symbol for price fetching
# tv_symbol: TradingView widget symbol (EXCHANGE:PAIR format)
CRYPTO_IDENTITY: dict[str, dict[str, str]] = {
    "BTC":   {"quote_symbol": "BTC-USD",   "tv_symbol": "COINBASE:BTCUSD"},
    "ETH":   {"quote_symbol": "ETH-USD",   "tv_symbol": "COINBASE:ETHUSD"},
    "SOL":   {"quote_symbol": "SOL-USD",   "tv_symbol": "COINBASE:SOLUSD"},
    "XRP":   {"quote_symbol": "XRP-USD",   "tv_symbol": "COINBASE:XRPUSD"},
    "ADA":   {"quote_symbol": "ADA-USD",   "tv_symbol": "COINBASE:ADAUSD"},
    "DOGE":  {"quote_symbol": "DOGE-USD",  "tv_symbol": "COINBASE:DOGEUSD"},
    "AVAX":  {"quote_symbol": "AVAX-USD",  "tv_symbol": "COINBASE:AVAXUSD"},
    "LINK":  {"quote_symbol": "LINK-USD",  "tv_symbol": "COINBASE:LINKUSD"},
    "DOT":   {"quote_symbol": "DOT-USD",   "tv_symbol": "COINBASE:DOTUSD"},
    "MATIC": {"quote_symbol": "MATIC-USD", "tv_symbol": "COINBASE:MATICUSD"},
    "SHIB":  {"quote_symbol": "SHIB-USD",  "tv_symbol": "COINBASE:SHIBUSD"},
    "PEPE":  {"quote_symbol": "PEPE-USD",  "tv_symbol": "CRYPTO:PEPEUSD"},
    "TRUMP": {"quote_symbol": "TRUMP-USD", "tv_symbol": "CRYPTO:TRUMPUSD"},
}


def _yf_symbol(symbol: str) -> str:
    """Normalise a portfolio symbol into a yfinance-compatible symbol."""
    identity = CRYPTO_IDENTITY.get(symbol)
    if identity:
        return identity["quote_symbol"]
    return symbol


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_company_info(symbol: str) -> Optional[dict]:
    """Return ``{name, sector, industry, marketCap}`` or *None* on failure."""
    symbol = symbol.upper().strip()

    with _company_lock:
        cached = _company_cache.get(symbol)
        if cached is not None:
            return cached

    try:
        result = _fetch_company_info(symbol)
        if result:
            with _company_lock:
                _company_cache[symbol] = result
        return result
    except Exception as e:
        logger.warning("yfinance company info failed for %s: %s", symbol, e)
        return None


def get_realtime_quote(symbol: str) -> Optional[dict]:
    """Return ``{price, previousClose, dayChange, dayChangePct}`` or *None*."""
    symbol = symbol.upper().strip()

    with _quote_lock:
        cached = _quote_cache.get(symbol)
        if cached is not None:
            return cached

    try:
        result = _fetch_realtime_quote(symbol)
        if result:
            with _quote_lock:
                _quote_cache[symbol] = result
        return result
    except Exception as e:
        logger.warning("yfinance quote failed for %s: %s", symbol, e)
        return None


def get_realtime_quotes_batch(symbols: list[str]) -> dict[str, dict]:
    """Batch-fetch quotes.  Uses ``yf.Tickers()`` for efficiency.

    Returns a dict mapping *original* symbol → quote dict.
    Symbols that fail are silently omitted.
    """
    if not symbols:
        return {}

    symbols = [s.upper().strip() for s in symbols]

    # Separate cache hits from misses
    results: dict[str, dict] = {}
    cache_misses: list[str] = []

    with _quote_lock:
        for sym in symbols:
            cached = _quote_cache.get(sym)
            if cached is not None:
                results[sym] = cached
            else:
                cache_misses.append(sym)

    if not cache_misses:
        return results

    # Batch fetch the misses
    try:
        batch = _fetch_quotes_batch(cache_misses)
        with _quote_lock:
            for sym, quote in batch.items():
                _quote_cache[sym] = quote
                results[sym] = quote
    except Exception as e:
        logger.warning("yfinance batch quote failed: %s", e)
        # Fall back to individual fetches
        for sym in cache_misses:
            quote = get_realtime_quote(sym)
            if quote:
                results[sym] = quote

    return results


def get_return_metrics(symbol: str) -> Optional[dict]:
    """Return ``{return1w, return1m, return3m, return1y, volatility30d, volatility90d}`` or *None*."""
    symbol = symbol.upper().strip()

    with _returns_lock:
        cached = _returns_cache.get(symbol)
        if cached is not None:
            return cached

    try:
        result = _fetch_return_metrics(symbol)
        if result:
            with _returns_lock:
                _returns_cache[symbol] = result
        return result
    except Exception as e:
        logger.warning("yfinance return metrics failed for %s: %s", symbol, e)
        return None


def search_symbols(query: str) -> list[dict]:
    """Search for symbols.  Returns ``[{symbol, name, type}]`` or ``[]``."""
    query = query.strip()
    if not query:
        return []

    cache_key = query.lower()

    with _search_lock:
        cached = _search_cache.get(cache_key)
        if cached is not None:
            return cached

    try:
        result = _fetch_search_results(query)
        with _search_lock:
            _search_cache[cache_key] = result
        return result
    except Exception as e:
        logger.warning("yfinance search failed for '%s': %s", query, e)
        return []


def is_available() -> bool:
    """Quick check whether the ``yfinance`` package is importable."""
    try:
        import yfinance as _yf  # noqa: F401
        return True
    except ImportError:
        return False


# ---------------------------------------------------------------------------
# Internal fetchers (retried, never called directly by routes)
# ---------------------------------------------------------------------------


@hardened_retry(max_retries=2, delay=1)
def _fetch_company_info(symbol: str) -> Optional[dict]:
    import yfinance as yf

    ticker = yf.Ticker(_yf_symbol(symbol))
    info = ticker.info or {}

    # yfinance returns a near-empty dict for invalid symbols
    if not info.get("regularMarketPrice") and not info.get("currentPrice"):
        return None

    return {
        "name": info.get("shortName") or info.get("longName") or symbol,
        "sector": info.get("sector") or "",
        "industry": info.get("industry") or "",
        "marketCap": info.get("marketCap") or 0,
    }


@hardened_retry(max_retries=2, delay=1)
def _fetch_realtime_quote(symbol: str) -> Optional[dict]:
    import yfinance as yf

    ticker = yf.Ticker(_yf_symbol(symbol))
    info = ticker.info or {}

    price = info.get("regularMarketPrice") or info.get("currentPrice")
    prev_close = info.get("regularMarketPreviousClose") or info.get("previousClose")

    if price is None:
        return None

    day_change = (price - prev_close) if prev_close else 0.0
    day_change_pct = ((day_change / prev_close) * 100) if prev_close else 0.0

    return {
        "price": float(price),
        "previousClose": float(prev_close) if prev_close else float(price),
        "dayChange": round(day_change, 4),
        "dayChangePct": round(day_change_pct, 4),
    }


@hardened_retry(max_retries=2, delay=1)
def _fetch_quotes_batch(symbols: list[str]) -> dict[str, dict]:
    import yfinance as yf

    yf_syms = [_yf_symbol(s) for s in symbols]
    tickers = yf.Tickers(" ".join(yf_syms))

    # Build a reverse map: yfinance symbol → original symbol
    yf_to_orig = {_yf_symbol(s): s for s in symbols}

    results: dict[str, dict] = {}
    for yf_sym in yf_syms:
        try:
            info = tickers.tickers[yf_sym].info or {}
            price = info.get("regularMarketPrice") or info.get("currentPrice")
            prev_close = info.get("regularMarketPreviousClose") or info.get("previousClose")

            if price is None:
                continue

            day_change = (price - prev_close) if prev_close else 0.0
            day_change_pct = ((day_change / prev_close) * 100) if prev_close else 0.0

            orig = yf_to_orig.get(yf_sym, yf_sym)
            results[orig] = {
                "price": float(price),
                "previousClose": float(prev_close) if prev_close else float(price),
                "dayChange": round(day_change, 4),
                "dayChangePct": round(day_change_pct, 4),
            }
        except Exception as exc:
            logger.debug("yfinance batch: skipping %s: %s", yf_sym, exc)

    return results


@hardened_retry(max_retries=2, delay=1)
def _fetch_return_metrics(symbol: str) -> Optional[dict]:
    import numpy as np
    import yfinance as yf

    ticker = yf.Ticker(_yf_symbol(symbol))
    hist = ticker.history(period="1y", interval="1d")

    if hist is None or hist.empty or len(hist) < 5:
        return None

    closes = hist["Close"]
    current = float(closes.iloc[-1])

    def _return_pct(days_back: int) -> Optional[float]:
        if len(closes) > days_back:
            old_price = float(closes.iloc[-days_back - 1])
            if old_price > 0:
                return round(((current - old_price) / old_price) * 100, 2)
        return None

    def _volatility(days: int) -> Optional[float]:
        if len(closes) > days:
            recent = closes.iloc[-days:]
            daily_returns = recent.pct_change().dropna()
            if len(daily_returns) > 1:
                return round(float(daily_returns.std() * np.sqrt(252) * 100), 2)
        return None

    return {
        "return1w": _return_pct(5),
        "return1m": _return_pct(21),
        "return3m": _return_pct(63),
        "return1y": _return_pct(252),
        "volatility30d": _volatility(30),
        "volatility90d": _volatility(90),
    }


@hardened_retry(max_retries=2, delay=1)
def _fetch_search_results(query: str) -> list[dict]:
    import yfinance as yf

    search = yf.Search(query)
    results: list[dict] = []

    for item in getattr(search, "quotes", []) or []:
        symbol = item.get("symbol", "")
        if not symbol:
            continue

        quote_type = (item.get("quoteType") or "").lower()
        if quote_type == "etf":
            item_type = "etf"
        elif quote_type == "cryptocurrency":
            item_type = "crypto"
        else:
            item_type = "stock"

        results.append(
            {
                "symbol": symbol,
                "name": item.get("shortname") or item.get("longname") or symbol,
                "type": item_type,
            }
        )

    return results[:20]
