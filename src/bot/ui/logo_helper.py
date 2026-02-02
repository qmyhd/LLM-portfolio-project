"""
Logo Helper - Centralized logo fetching with multi-provider fallback and caching.

Provides a unified interface for fetching company logos with:
- In-memory TTL cache (configurable, default 24 hours)
- Database cache layer (symbols.logo_url)
- Logo.dev API (primary provider)
- Logokit API (fallback provider)

Environment Variables:
    LOGO_DEV_API_KEY: Publishable API key for img.logo.dev (pk_xxx format)
    LOGOKIT_API_KEY: API key for img.logokit.com
    LOGO_CACHE_TTL_SECONDS: Cache TTL in seconds (default: 86400 = 24 hours)

Usage:
    from src.bot.ui.logo_helper import get_logo_url, get_logo_image, prefetch_logos

    # Get URL for embed thumbnail (uses cache + fallback cascade)
    logo_url = get_logo_url("NVDA")

    # Get PIL Image for chart overlay
    logo_image = get_logo_image("AAPL", size=(64, 64))

    # Prefetch multiple logos for charts
    logos = prefetch_logos(["NVDA", "AAPL", "MSFT", "GOOGL"])
"""

import logging
import os
import time
from dataclasses import dataclass, field
from io import BytesIO
from typing import Dict, Optional, Tuple
from urllib.parse import quote

import requests
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────────────────

# API Keys (loaded from environment)
LOGO_DEV_API_KEY = os.getenv("LOGO_DEV_API_KEY", "")
LOGOKIT_API_KEY = os.getenv("LOGOKIT_API_KEY", "") or os.getenv("LOGO_KIT_API_KEY", "")

# API Base URLs
LOGO_DEV_BASE_URL = "https://img.logo.dev/ticker"
LOGOKIT_BASE_URL = "https://img.logokit.com/ticker"

# Request timeout in seconds
REQUEST_TIMEOUT = 5

# Cache TTL in seconds (default: 24 hours)
LOGO_CACHE_TTL_SECONDS = int(os.getenv("LOGO_CACHE_TTL_SECONDS", "86400"))


# ─────────────────────────────────────────────────────────────────────────────
# TTL Cache Implementation
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class CacheEntry:
    """Cache entry with value and timestamp for TTL expiration."""

    value: Optional[str]
    timestamp: float = field(default_factory=time.time)
    provider: Optional[str] = None  # Which provider returned this logo

    def is_expired(self, ttl_seconds: int) -> bool:
        """Check if this entry has expired based on TTL."""
        return time.time() - self.timestamp > ttl_seconds


class TTLLogoCache:
    """
    Thread-safe TTL cache for logo URLs.

    Stores logo URLs with automatic expiration. Failed lookups (None values)
    are also cached to avoid repeated slow API calls.
    """

    def __init__(self, ttl_seconds: int = LOGO_CACHE_TTL_SECONDS):
        self._cache: Dict[str, CacheEntry] = {}
        self._ttl = ttl_seconds

    def get(self, symbol: str) -> Tuple[Optional[str], bool]:
        """
        Get logo URL from cache.

        Args:
            symbol: Stock ticker symbol

        Returns:
            Tuple of (logo_url or None, hit: bool indicating if cache hit)
        """
        symbol = symbol.upper()
        entry = self._cache.get(symbol)

        if entry is None:
            return None, False  # Cache miss

        if entry.is_expired(self._ttl):
            # Remove expired entry
            del self._cache[symbol]
            logger.debug(f"Cache expired for {symbol}")
            return None, False  # Treat as miss

        logger.debug(f"Cache hit for {symbol} (provider: {entry.provider})")
        return entry.value, True  # Cache hit (value may be None for failed lookups)

    def set(
        self, symbol: str, value: Optional[str], provider: Optional[str] = None
    ) -> None:
        """
        Store logo URL in cache.

        Args:
            symbol: Stock ticker symbol
            value: Logo URL (or None for failed lookup)
            provider: Which provider returned this logo (for logging)
        """
        symbol = symbol.upper()
        self._cache[symbol] = CacheEntry(value=value, provider=provider)
        if value:
            logger.debug(f"Cached logo for {symbol} from {provider}")
        else:
            logger.debug(f"Cached failed lookup for {symbol}")

    def clear(self) -> None:
        """Clear all cache entries."""
        self._cache.clear()
        logger.info("Logo cache cleared")

    def size(self) -> int:
        """Return number of cached entries."""
        return len(self._cache)

    def get_stats(self) -> Dict:
        """Return cache statistics."""
        valid = sum(1 for e in self._cache.values() if e.value is not None)
        failed = sum(1 for e in self._cache.values() if e.value is None)
        expired = sum(1 for e in self._cache.values() if e.is_expired(self._ttl))
        return {
            "total": len(self._cache),
            "valid": valid,
            "failed": failed,
            "expired": expired,
            "ttl_seconds": self._ttl,
        }


# Global cache instance
_logo_cache = TTLLogoCache()


# ─────────────────────────────────────────────────────────────────────────────
# Database Cache Layer
# ─────────────────────────────────────────────────────────────────────────────


def _get_cached_logo_from_db(symbol: str) -> Optional[str]:
    """
    Check database symbols table for cached logo_url.

    Args:
        symbol: Stock ticker symbol

    Returns:
        Logo URL if cached and valid, None otherwise
    """
    try:
        from src.db import execute_sql

        result = execute_sql(
            "SELECT logo_url FROM symbols WHERE ticker = :symbol OR id = :symbol LIMIT 1",
            params={"symbol": symbol.upper()},
            fetch_results=True,
        )

        if result and result[0][0]:
            url = str(result[0][0]).strip()
            if url and url.startswith("http"):
                logger.debug(f"DB cache hit for {symbol}: {url[:50]}...")
                return url

    except Exception as e:
        logger.debug(f"DB cache lookup failed for {symbol}: {e}")

    return None


def _save_logo_to_db(symbol: str, logo_url: str) -> bool:
    """
    Cache logo URL in the symbols table.

    Args:
        symbol: Stock ticker symbol
        logo_url: URL to cache

    Returns:
        True if saved successfully
    """
    try:
        from src.db import execute_sql

        # Update existing symbol record
        execute_sql(
            """
            UPDATE symbols SET logo_url = :logo_url, updated_at = NOW()
            WHERE ticker = :symbol OR id = :symbol
            """,
            params={"symbol": symbol.upper(), "logo_url": logo_url},
        )
        logger.debug(f"Saved logo to DB for {symbol}")
        return True

    except Exception as e:
        logger.debug(f"Failed to cache logo in DB for {symbol}: {e}")
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Logo.dev API Integration
# ─────────────────────────────────────────────────────────────────────────────


def _fetch_from_logo_dev(symbol: str) -> Optional[str]:
    """
    Fetch logo URL from Logo.dev API.

    Uses the ticker endpoint with publishable key (pk_xxx).
    Validates response is an image before returning.

    Args:
        symbol: Stock ticker symbol

    Returns:
        Logo URL if available and valid, None otherwise
    """
    if not LOGO_DEV_API_KEY:
        logger.debug("LOGO_DEV_API_KEY not configured, skipping Logo.dev")
        return None

    try:
        # Construct Logo.dev ticker URL
        symbol_clean = quote(symbol.upper().strip())
        logo_url = f"{LOGO_DEV_BASE_URL}/{symbol_clean}?token={LOGO_DEV_API_KEY}"

        # Validate with GET stream (Logo.dev returns 404 for HEAD)
        response = requests.get(
            logo_url, timeout=REQUEST_TIMEOUT, allow_redirects=True, stream=True
        )

        if response.status_code == 200:
            content_type = response.headers.get("content-type", "")
            if "image" in content_type.lower():
                response.close()
                logger.info(f"✅ Logo.dev: Valid image for {symbol}")
                return logo_url
            else:
                logger.warning(
                    f"⚠️ Logo.dev: Non-image response for {symbol}."
                )
        else:
            logger.warning(f"⚠️ Logo.dev: HTTP {response.status_code} for {symbol}")

        response.close()
        return None

    except requests.Timeout:
        logger.warning(f"⚠️ Logo.dev: Timeout for {symbol}")
        return None
    except requests.RequestException as e:
        logger.warning(f"⚠️ Logo.dev: Request failed for {symbol}: {e}")
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Logokit API Integration (Fallback)
# ─────────────────────────────────────────────────────────────────────────────


def _fetch_from_logokit(symbol: str) -> Optional[str]:
    """
    Fetch logo URL from Logokit API (fallback provider).

    Uses ticker endpoint with fallback options for better coverage.
    Format: https://img.logokit.com/ticker/{SYMBOL}?token={KEY}&size=64&fallback=monogram-light

    Args:
        symbol: Stock ticker symbol

    Returns:
        Logo URL if available and valid, None otherwise
    """
    if not LOGOKIT_API_KEY:
        logger.debug("LOGOKIT_API_KEY not configured, skipping Logokit")
        return None

    try:
        # Construct Logokit ticker URL with fallback options
        symbol_clean = quote(symbol.upper().strip())
        logo_url = (
            f"{LOGOKIT_BASE_URL}/{symbol_clean}"
            f"?token={LOGOKIT_API_KEY}&size=64&fallback=monogram-light"
        )

        # Validate with GET stream
        response = requests.get(
            logo_url, timeout=REQUEST_TIMEOUT, allow_redirects=True, stream=True
        )

        if response.status_code == 200:
            content_type = response.headers.get("content-type", "")
            if "image" in content_type.lower():
                response.close()
                logger.info(f"✅ Logokit: Valid image for {symbol}")
                return logo_url
            else:
                logger.warning(
                    f"⚠️ Logokit: Non-image response for {symbol}"
                )
        else:
            logger.warning(f"⚠️ Logokit: HTTP {response.status_code} for {symbol}")

        response.close()
        return None

    except requests.Timeout:
        logger.warning(f"⚠️ Logokit: Timeout for {symbol}")
        return None
    except requests.RequestException as e:
        logger.warning(f"⚠️ Logokit: Request failed for {symbol}: {e}")
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────


def get_logo_url(symbol: str, use_cache: bool = True) -> Optional[str]:
    """
    Get logo URL for a stock symbol with multi-provider fallback.

    Lookup cascade (5 steps):
    1. Check in-memory TTL cache → return if found (including cached None)
    2. Check database symbols.logo_url → cache and return if valid
    3. Try Logo.dev API → save to DB, cache, and return if valid
    4. Try Logokit API (fallback) → save to DB, cache, and return if valid
    5. Cache None to avoid repeated slow calls → return None

    All results (success or failure) are cached to prevent repeated slow lookups.

    Args:
        symbol: Stock ticker symbol (e.g., "NVDA", "AAPL")
        use_cache: Whether to use cached values (default True)

    Returns:
        Logo URL string if available, None if not found or all providers failed

    Example:
        >>> url = get_logo_url("NVDA")
        >>> if url:
        ...     embed.set_thumbnail(url=url)

    Note:
        - Failed lookups are cached as None to avoid repeated API calls
        - Cache TTL is configurable via LOGO_CACHE_TTL_SECONDS (default: 24h)
        - Providers are tried in order: Logo.dev → Logokit
    """
    if not symbol:
        return None

    symbol = symbol.upper().strip()

    # ── Step 1: Check in-memory TTL cache ──────────────────────────────────
    if use_cache:
        cached_url, hit = _logo_cache.get(symbol)
        if hit:
            # Cache hit (value may be None for previously failed lookups)
            return cached_url

    # ── Step 2: Check database cache ───────────────────────────────────────
    db_url = _get_cached_logo_from_db(symbol)
    if db_url:
        _logo_cache.set(symbol, db_url, provider="database")
        return db_url

    # ── Step 3: Try Logo.dev API ───────────────────────────────────────────
    logo_url = _fetch_from_logo_dev(symbol)
    if logo_url:
        _save_logo_to_db(symbol, logo_url)
        _logo_cache.set(symbol, logo_url, provider="logo.dev")
        return logo_url

    # ── Step 4: Try Logokit API (fallback) ─────────────────────────────────
    logo_url = _fetch_from_logokit(symbol)
    if logo_url:
        _save_logo_to_db(symbol, logo_url)
        _logo_cache.set(symbol, logo_url, provider="logokit")
        return logo_url

    # ── Step 5: Cache failure and return None ──────────────────────────────
    _logo_cache.set(symbol, None, provider=None)
    logger.info(f"⚠️ No logo found for {symbol} from any provider")
    return None


def get_logo_image(
    symbol: str,
    size: Tuple[int, int] = (64, 64),
) -> Optional[BytesIO]:
    """
    Download and return logo as a BytesIO buffer for chart embedding.

    Useful for matplotlib chart overlays where you need the actual image data.
    Uses PIL for resizing and format conversion.

    Args:
        symbol: Stock ticker symbol
        size: Desired size (width, height) for resizing

    Returns:
        BytesIO buffer containing the PNG image, or None if unavailable

    Example:
        >>> from PIL import Image
        >>> buffer = get_logo_image("AAPL", size=(48, 48))
        >>> if buffer:
        ...     img = Image.open(buffer)
    """
    logo_url = get_logo_url(symbol)
    if not logo_url:
        return None

    try:
        response = requests.get(logo_url, timeout=REQUEST_TIMEOUT)

        if response.status_code != 200:
            logger.debug(
                f"Failed to download logo for {symbol}: HTTP {response.status_code}"
            )
            return None

        content_type = response.headers.get("content-type", "")
        if "image" not in content_type:
            logger.debug(f"Invalid content-type for {symbol}; expected image/*")
            return None

        # Try to resize using PIL if available
        try:
            from PIL import Image

            img = Image.open(BytesIO(response.content))

            # Convert to RGBA for transparency support
            if img.mode != "RGBA":
                img = img.convert("RGBA")

            # Resize if needed
            if img.size != size:
                img = img.resize(size, Image.Resampling.LANCZOS)

            # Save to buffer as PNG
            buffer = BytesIO()
            img.save(buffer, format="PNG")
            buffer.seek(0)
            return buffer

        except ImportError:
            # PIL not available, return raw image without resize
            logger.debug("PIL not available, returning raw image")
            buffer = BytesIO(response.content)
            buffer.seek(0)
            return buffer

    except requests.RequestException as e:
        logger.warning(f"Failed to download logo for {symbol}: {e}")
        return None
    except Exception as e:
        logger.warning(f"Error processing logo for {symbol}: {e}")
        return None


def prefetch_logos(
    symbols: list,
    max_symbols: int = 15,
) -> Dict[str, Optional[str]]:
    """
    Prefetch logos for multiple symbols.

    Useful before generating charts to warm the cache and avoid
    serial requests during chart generation.

    Args:
        symbols: List of ticker symbols to prefetch
        max_symbols: Maximum number of symbols to fetch (default 15)

    Returns:
        Dict mapping symbol → logo_url (or None if not found)

    Example:
        >>> logos = prefetch_logos(["NVDA", "AAPL", "MSFT", "GOOGL"])
        >>> for sym, url in logos.items():
        ...     print(f"{sym}: {'✓' if url else '✗'}")
    """
    results = {}
    symbols_to_fetch = [s.upper() for s in symbols[:max_symbols] if s]

    logger.info(f"Prefetching logos for {len(symbols_to_fetch)} symbols")

    for symbol in symbols_to_fetch:
        try:
            results[symbol] = get_logo_url(symbol)
        except Exception as e:
            logger.warning(f"Error prefetching logo for {symbol}: {e}")
            results[symbol] = None

    # Log summary
    found = sum(1 for v in results.values() if v)
    logger.info(f"Prefetch complete: {found}/{len(results)} logos found")

    return results


def clear_logo_cache() -> None:
    """
    Clear the in-memory logo cache.

    Useful for forcing fresh lookups after TTL changes or API key updates.
    """
    _logo_cache.clear()


def get_cache_stats() -> Dict:
    """
    Get logo cache statistics.

    Returns:
        Dict with cache stats: total, valid, failed, expired, ttl_seconds
    """
    return _logo_cache.get_stats()


# ─────────────────────────────────────────────────────────────────────────────
# Legacy Compatibility
# ─────────────────────────────────────────────────────────────────────────────

# For backward compatibility with existing code
_fetch_logo_from_api = _fetch_from_logo_dev
