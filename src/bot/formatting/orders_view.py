"""
Orders View Formatting Helpers

Provides deterministic formatting functions for displaying brokerage orders
in Discord embeds. All functions handle None/NaN values gracefully.

Key features:
- Safe NaN/None handling across all formatters
- Option ticker parsing (OCC format → human readable)
- UUID symbol detection (SnapTrade options use UUID symbols)
- Price-since-trade calculations
"""

import logging
import re
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple, Union

logger = logging.getLogger(__name__)

# Threshold for dividend reinvestment detection (notional value < this = likely DRIP)
DIVIDEND_REINVESTMENT_THRESHOLD = 2.00


# =============================================================================
# UUID DETECTION
# =============================================================================

# UUID regex pattern (8-4-4-4-12 format)
UUID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def is_uuid(value: Optional[str]) -> bool:
    """Check if a string is a UUID."""
    if not value:
        return False
    return bool(UUID_PATTERN.match(value.strip()))


# =============================================================================
# OPTION TICKER PARSING
# =============================================================================

# OCC option ticker format: SYMBOL + YYMMDD + C/P + 8-digit strike (strike * 1000)
# Example: "AMZN  260123C00290000" = AMZN Jan 23, 2026 $290 Call
OCC_OPTION_PATTERN = re.compile(
    r"^([A-Z]+)\s*(\d{2})(\d{2})(\d{2})([CP])(\d{8})$",
    re.IGNORECASE,
)


def parse_option_ticker(option_ticker: Optional[str]) -> Optional[Dict[str, Any]]:
    """
    Parse OCC-format option ticker into components.

    Args:
        option_ticker: OCC format like "AMZN  260123C00290000"

    Returns:
        Dict with: symbol, expiry_date, option_type, strike, display_str
        or None if not parseable

    Examples:
        >>> parse_option_ticker("AMZN  260123C00290000")
        {'symbol': 'AMZN', 'expiry': '01/23/26', 'type': 'Call', 'strike': 290.0,
         'display': 'AMZN $290C 01/23'}
    """
    if not option_ticker:
        return None

    # Clean up whitespace
    cleaned = option_ticker.strip().replace(" ", "")
    match = OCC_OPTION_PATTERN.match(cleaned)

    if not match:
        return None

    symbol = match.group(1).upper()
    year = match.group(2)  # YY
    month = match.group(3)  # MM
    day = match.group(4)  # DD
    opt_type = match.group(5).upper()  # C or P
    strike_raw = match.group(6)  # 8 digits

    # Strike is stored as strike * 1000 (to handle decimals)
    try:
        strike = int(strike_raw) / 1000
    except ValueError:
        strike = 0

    type_str = "Call" if opt_type == "C" else "Put"
    type_short = "C" if opt_type == "C" else "P"

    # Format expiry
    expiry_display = f"{month}/{day}/{year}"
    expiry_short = f"{month}/{day}"

    # Compact display: "AMZN $290C 01/23"
    if strike == int(strike):
        strike_str = f"${int(strike)}"
    else:
        strike_str = f"${strike:.2f}"

    display_str = f"{symbol} {strike_str}{type_short} {expiry_short}"

    return {
        "symbol": symbol,
        "expiry": expiry_display,
        "type": type_str,
        "type_short": type_short,
        "strike": strike,
        "display": display_str,
    }


def get_display_symbol(order: Dict[str, Any]) -> str:
    """
    Get the best display symbol for an order.

    Handles UUID symbols (uses option_ticker) and regular symbols.

    Args:
        order: Order dict with 'symbol' and optionally 'option_ticker'

    Returns:
        Human-readable symbol string
    """
    symbol = order.get("symbol") or ""
    option_ticker = order.get("option_ticker")

    # If symbol is a UUID, try to use option_ticker
    if is_uuid(symbol):
        if option_ticker:
            parsed = parse_option_ticker(option_ticker)
            if parsed:
                return parsed["display"]
            # Fallback: return cleaned option_ticker
            return option_ticker.strip()[:20]
        return "Option"

    return symbol or "N/A"


def get_underlying_symbol(order: Dict[str, Any]) -> Optional[str]:
    """
    Get the underlying symbol for an order (useful for options).

    Args:
        order: Order dict with 'symbol' and optionally 'option_ticker'

    Returns:
        Underlying ticker (e.g., "AMZN" for an AMZN option) or the symbol itself
    """
    symbol = order.get("symbol") or ""
    option_ticker = order.get("option_ticker")

    # If it's an option, extract underlying from option_ticker
    if option_ticker:
        parsed = parse_option_ticker(option_ticker)
        if parsed:
            return parsed["symbol"]

    # If symbol is a UUID, we can't determine underlying
    if is_uuid(symbol):
        return None

    return symbol or None


# =============================================================================
# NEAREST DISCORD IDEA LOOKUP
# =============================================================================


def get_nearest_idea(
    symbol: str,
    order_timestamp: Optional[Union[datetime, str]],
    window_days: int = 7,
) -> Optional[Dict[str, Any]]:
    """
    Find the nearest Discord idea for a given symbol and order timestamp.

    Queries discord_parsed_ideas joined with discord_messages to find
    the closest idea (by timestamp) within ±window_days of the order.

    Args:
        symbol: The ticker symbol to search for
        order_timestamp: The order execution/creation timestamp
        window_days: Number of days to search before/after order (default 7)

    Returns:
        Dict with keys: idea_text, confidence, time_delta_str, message_ts
        or None if no matching idea found

    Example:
        >>> get_nearest_idea("AAPL", datetime(2025, 1, 5))
        {'idea_text': 'AAPL looks bullish...', 'confidence': 0.85,
         'time_delta_str': '-2d', 'message_ts': datetime(...)}
    """
    from datetime import timedelta
    from src.db import execute_sql

    if not symbol or not order_timestamp:
        return None

    # Normalize timestamp
    if isinstance(order_timestamp, str):
        try:
            # Handle ISO format and common variations
            order_timestamp = order_timestamp.replace("Z", "+00:00")
            if "T" in order_timestamp:
                order_ts = datetime.fromisoformat(order_timestamp[:26])
            else:
                order_ts = datetime.fromisoformat(order_timestamp[:19])
        except (ValueError, TypeError):
            return None
    else:
        order_ts = order_timestamp

    # Ensure timezone-aware (PostgreSQL requires this for timestamptz)
    if order_ts.tzinfo is None:
        order_ts = order_ts.replace(tzinfo=timezone.utc)

    try:
        result = execute_sql(
            """
            SELECT
                di.idea_text,
                di.confidence,
                dm.created_at,
                EXTRACT(EPOCH FROM (dm.created_at - :order_ts)) as time_diff_seconds
            FROM discord_parsed_ideas di
            JOIN discord_messages dm ON dm.message_id = di.message_id
            WHERE di.primary_symbol = :symbol
                AND dm.created_at BETWEEN :start_ts AND :end_ts
            ORDER BY ABS(EXTRACT(EPOCH FROM (dm.created_at - :order_ts))) ASC,
                     di.confidence DESC
            LIMIT 1
            """,
            params={
                "symbol": symbol.upper(),
                "order_ts": order_ts,
                "start_ts": order_ts - timedelta(days=window_days),
                "end_ts": order_ts + timedelta(days=window_days),
            },
            fetch_results=True,
        )

        if not result or not result[0]:
            return None

        idea_text, confidence, message_ts, time_diff_seconds = result[0]

        # Format time delta for display
        time_delta_str = _format_time_delta(time_diff_seconds)

        return {
            "idea_text": idea_text,
            "confidence": float(confidence) if confidence else 0.0,
            "time_delta_str": time_delta_str,
            "message_ts": message_ts,
        }

    except Exception as e:
        logger.warning(f"Error fetching nearest idea for {symbol}: {e}")
        return None


def _format_time_delta(seconds: Optional[float]) -> str:
    """
    Format a time delta in seconds to a human-readable string.

    Args:
        seconds: Time difference in seconds (negative = before, positive = after)

    Returns:
        String like "-2d", "+5h", "-30m", "same day"
    """
    if seconds is None:
        return "?"

    try:
        seconds = float(seconds)
    except (TypeError, ValueError):
        return "?"

    abs_seconds = abs(seconds)
    sign = "-" if seconds < 0 else "+"

    if abs_seconds < 60:
        return "same time"
    elif abs_seconds < 3600:  # < 1 hour
        mins = int(abs_seconds / 60)
        return f"{sign}{mins}m"
    elif abs_seconds < 86400:  # < 1 day
        hours = int(abs_seconds / 3600)
        return f"{sign}{hours}h"
    else:
        days = int(abs_seconds / 86400)
        return f"{sign}{days}d"


def format_idea_for_embed(
    idea: Optional[Dict[str, Any]],
    max_length: int = 200,
) -> Optional[str]:
    """
    Format a nearest idea dict for embed display.

    Args:
        idea: Dict from get_nearest_idea()
        max_length: Max characters for idea text (default 200)

    Returns:
        Formatted string like '"AAPL looks bullish..." (conf 0.85, -2d)'
        or None if no idea
    """
    if not idea:
        return None

    text = idea.get("idea_text") or ""
    conf = idea.get("confidence", 0.0)
    delta = idea.get("time_delta_str", "?")

    # Truncate text if needed
    if len(text) > max_length:
        text = text[: max_length - 3].rstrip() + "..."

    # Format: "Idea text..." (conf 0.XX, ±Nd)
    return f'"{text}" (conf {conf:.2f}, {delta})'


# =============================================================================
# FORMATTING FUNCTIONS
# =============================================================================


def format_money(
    value: Optional[Union[float, int, Decimal]],
    include_sign: bool = False,
    precision: int = 2,
) -> str:
    """
    Format a monetary value with proper handling of None/NaN.

    Args:
        value: The monetary value (can be None, NaN, or any numeric)
        include_sign: If True, always prefix + for positive values
        precision: Decimal places (default 2)

    Returns:
        Formatted string like "$1,234.56" or "+$1,234.56" or "N/A"

    Examples:
        >>> format_money(1234.567)
        '$1,234.57'
        >>> format_money(None)
        'N/A'
        >>> format_money(-50.5, include_sign=True)
        '-$50.50'
    """
    if value is None:
        return "N/A"

    try:
        val = float(value)
        if val != val:  # NaN check
            return "N/A"

        # Determine sign
        if include_sign and val > 0:
            sign = "+"
        elif val < 0:
            sign = "-"
            val = abs(val)
        else:
            sign = ""

        # Format with thousands separator
        # Avoid trailing .00 for clean integers when precision allows
        if precision == 0 or (val == int(val) and precision >= 0):
            formatted = f"{val:,.0f}"
        else:
            formatted = f"{val:,.{precision}f}"

        return f"{sign}${formatted}"

    except (TypeError, ValueError):
        return "N/A"


def format_pct(
    value: Optional[Union[float, int, Decimal]],
    include_sign: bool = True,
    precision: int = 2,
) -> str:
    """
    Format a percentage value with proper handling of None/NaN.

    Args:
        value: The percentage value (can be None, NaN, or any numeric)
        include_sign: If True (default), prefix + for positive values
        precision: Decimal places (default 2)

    Returns:
        Formatted string like "+12.34%" or "-5.00%" or "N/A"

    Examples:
        >>> format_pct(12.345)
        '+12.35%'
        >>> format_pct(None)
        'N/A'
        >>> format_pct(-5.0, precision=1)
        '-5.0%'
    """
    if value is None:
        return "N/A"

    try:
        val = float(value)
        if val != val:  # NaN check
            return "N/A"

        # Determine sign
        if include_sign and val > 0:
            sign = "+"
        elif val < 0:
            sign = "-"
            val = abs(val)
        else:
            sign = ""

        return f"{sign}{val:.{precision}f}%"

    except (TypeError, ValueError):
        return "N/A"


def format_qty(value: Optional[Union[float, int, Decimal]]) -> str:
    """
    Format a quantity with intelligent decimal handling.

    Shows integer format if whole number, otherwise shows up to 6 decimals
    (common for fractional shares). Never shows scientific notation.

    Args:
        value: The quantity (can be None, NaN, or any numeric)

    Returns:
        Formatted string like "10" or "0.001228" or "N/A"

    Examples:
        >>> format_qty(10.0)
        '10'
        >>> format_qty(0.001228)
        '0.001228'
        >>> format_qty(None)
        'N/A'
    """
    if value is None:
        return "N/A"

    try:
        val = float(value)
        if val != val:  # NaN check
            return "N/A"

        # Check if effectively an integer
        if val == int(val) and abs(val) < 1_000_000_000:
            return f"{int(val):,}"

        # For fractional amounts, show up to 6 decimals but strip trailing zeros
        formatted = f"{val:.6f}".rstrip("0").rstrip(".")
        return formatted

    except (TypeError, ValueError):
        return "N/A"


def normalize_side(action: Optional[str]) -> str:
    """
    Normalize order action/side to a user-friendly display name.

    Args:
        action: The action string from the brokerage (BUY, SELL, BUY_OPEN, etc.)

    Returns:
        Normalized string like "Bought", "Sold", or "Trade"

    Examples:
        >>> normalize_side("BUY")
        'Bought'
        >>> normalize_side("SELL_CLOSE")
        'Sold'
        >>> normalize_side(None)
        'Trade'
    """
    if not action:
        return "Trade"

    action_upper = action.upper().strip()

    # Buy-side actions
    if action_upper in ("BUY", "BUY_OPEN", "BUY_TO_OPEN", "BOUGHT", "PURCHASE"):
        return "Bought"

    # Sell-side actions
    if action_upper in ("SELL", "SELL_CLOSE", "SELL_TO_CLOSE", "SOLD", "SALE"):
        return "Sold"

    # Short selling
    if action_upper in ("SHORT", "SELL_SHORT", "SELL_TO_OPEN"):
        return "Shorted"

    # Cover (buy to close short)
    if action_upper in ("COVER", "BUY_TO_CLOSE"):
        return "Covered"

    return "Trade"


def best_price(order: Dict[str, Any]) -> str:
    """
    Get the best available price for an order.

    Priority for executed orders: execution_price > limit_price
    Priority for pending orders: limit_price > stop_price > N/A

    Args:
        order: Dict with keys like 'execution_price', 'limit_price', 'stop_price', 'status'

    Returns:
        Formatted price string or "N/A"
    """
    status = (order.get("status") or "").upper()

    # For executed orders, prefer execution price
    if status in ("EXECUTED", "FILLED", "PARTIALLY_FILLED"):
        exec_price = order.get("execution_price") or order.get("exec_price")
        if exec_price is not None:
            try:
                val = float(exec_price)
                if val == val:  # Not NaN
                    return format_money(val)
            except (TypeError, ValueError):
                pass

    # Try limit price
    limit_price = order.get("limit_price")
    if limit_price is not None:
        try:
            val = float(limit_price)
            if val == val:
                return format_money(val)
        except (TypeError, ValueError):
            pass

    # Try stop price
    stop_price = order.get("stop_price")
    if stop_price is not None:
        try:
            val = float(stop_price)
            if val == val:
                return f"{format_money(val)} (stop)"
        except (TypeError, ValueError):
            pass

    return "N/A"


def safe_status(order: Dict[str, Any]) -> str:
    """
    Get a safe, normalized status string for display.

    Args:
        order: Dict with 'status' key

    Returns:
        Normalized status like "Executed", "Pending", "Canceled", etc.
    """
    status = (order.get("status") or "").upper()

    status_map = {
        "EXECUTED": "Executed",
        "FILLED": "Executed",
        "PARTIALLY_FILLED": "Partial Fill",
        "CANCELED": "Canceled",
        "CANCELLED": "Canceled",
        "OPEN": "Pending",
        "PENDING": "Pending",
        "NEW": "Pending",
        "EXPIRED": "Expired",
        "REJECTED": "Rejected",
    }

    return status_map.get(status, status.title() if status else "Unknown")


def get_order_color(action: Optional[str], status: Optional[str] = None) -> int:
    """
    Get a Discord embed color based on order action/status.

    Args:
        action: Order action (BUY, SELL, etc.)
        status: Optional status override (CANCELED, REJECTED show gray)

    Returns:
        Discord color integer
    """
    # Status overrides
    if status:
        status_upper = status.upper()
        if status_upper in ("CANCELED", "CANCELLED", "REJECTED", "EXPIRED"):
            return 0x808080  # Gray

    if not action:
        return 0x808080  # Gray

    action_upper = action.upper()

    # Green for buys
    if action_upper in ("BUY", "BUY_OPEN", "BUY_TO_OPEN", "COVER", "BUY_TO_CLOSE"):
        return 0x2ECC71  # Green

    # Red for sells/shorts
    if action_upper in ("SELL", "SELL_CLOSE", "SELL_TO_CLOSE", "SHORT", "SELL_SHORT"):
        return 0xE74C3C  # Red

    return 0x808080  # Gray default


# =============================================================================
# ORDER FORMATTER CLASS
# =============================================================================


class OrderFormatter:
    """
    Formats order data for Discord embed display.

    Handles the complete transformation from raw database order
    to a formatted embed-ready structure. Supports both equity and option orders.
    """

    def __init__(self, order: Dict[str, Any], current_price: Optional[float] = None):
        """
        Initialize with order data.

        Args:
            order: Raw order dict from database
            current_price: Optional current price for "price since trade" calculation
        """
        self.order = order
        self.current_price = current_price
        self._parsed_option = None

        # Pre-parse option if applicable
        option_ticker = order.get("option_ticker")
        if option_ticker:
            self._parsed_option = parse_option_ticker(option_ticker)

    @property
    def is_option(self) -> bool:
        """Check if this is an options order."""
        return self._parsed_option is not None or is_uuid(self.order.get("symbol"))

    @property
    def symbol(self) -> str:
        """Get the display symbol (handles UUIDs and options)."""
        return get_display_symbol(self.order)

    @property
    def underlying_symbol(self) -> Optional[str]:
        """Get the underlying ticker (for options, returns the stock symbol)."""
        return get_underlying_symbol(self.order)

    @property
    def action_display(self) -> str:
        """Get the action as display string."""
        return normalize_side(self.order.get("action"))

    @property
    def status_display(self) -> str:
        """Get the status as display string."""
        return safe_status(self.order)

    @property
    def price_display(self) -> str:
        """Get the best price display."""
        return best_price(self.order)

    @property
    def quantity_display(self) -> str:
        """Get the quantity display."""
        filled = self.order.get("filled_quantity")
        total = self.order.get("total_quantity")
        qty = filled if filled is not None else total
        return format_qty(qty)

    @property
    def notional_value(self) -> Optional[float]:
        """Calculate notional value (qty * price)."""
        try:
            filled = self.order.get("filled_quantity")
            total = self.order.get("total_quantity")
            qty = float(filled if filled is not None else total or 0)

            exec_price = self.order.get("execution_price")
            if exec_price is not None:
                return qty * float(exec_price)
            return None
        except (TypeError, ValueError):
            return None

    @property
    def notional_display(self) -> str:
        """Get notional value display."""
        return format_money(self.notional_value)

    @property
    def is_dividend_reinvestment(self) -> bool:
        """Check if this order is likely a dividend reinvestment (DRIP).

        Criteria:
        - Action is BUY
        - Notional value < DIVIDEND_REINVESTMENT_THRESHOLD ($2.00)

        These are typically automatic fractional share purchases using dividend payouts.
        """
        action = (self.order.get("action") or "").upper()
        if action not in ("BUY", "BUY_OPEN", "BOUGHT", "PURCHASE"):
            return False

        notional = self.notional_value
        if notional is None:
            return False

        return notional < DIVIDEND_REINVESTMENT_THRESHOLD

    @property
    def order_type_display(self) -> str:
        """Get the order type display."""
        ot = self.order.get("order_type") or ""
        ot_upper = ot.upper()

        type_map = {
            "MARKET": "MKT",
            "LIMIT": "LMT",
            "STOP": "STP",
            "STOP_LIMIT": "STP-LMT",
            "TRAILING_STOP": "TRAIL",
        }
        return type_map.get(ot_upper, ot.upper() or "N/A")

    @property
    def execution_price(self) -> Optional[float]:
        """Get execution price as float."""
        try:
            ep = self.order.get("execution_price")
            if ep is not None:
                return float(ep)
        except (TypeError, ValueError):
            pass
        return None

    def price_since_trade_pct(self) -> Optional[float]:
        """
        Calculate price change since trade.

        Returns:
            Percentage change (e.g., 5.25 for +5.25%), or None if not calculable
        """
        if self.current_price is None:
            return None

        exec_price = self.execution_price
        if exec_price is None or exec_price == 0:
            return None

        try:
            return ((self.current_price - exec_price) / exec_price) * 100
        except (TypeError, ValueError, ZeroDivisionError):
            return None

    def price_since_trade_display(self) -> str:
        """Get price since trade display with current price."""
        pct = self.price_since_trade_pct()
        if pct is None:
            return ""

        current_str = format_money(self.current_price)
        pct_str = format_pct(pct, include_sign=True)
        return f"Price since trade: {pct_str} (Now: {current_str})"

    @property
    def timestamp_display(self) -> str:
        """Get the most relevant timestamp for display in EST format like 'Nov 13, 2025'."""
        from zoneinfo import ZoneInfo

        # Try in order of preference
        for field in ["time_executed", "time_placed", "created_at", "sync_timestamp"]:
            ts = self.order.get(field)
            if ts:
                try:
                    if isinstance(ts, datetime):
                        dt = ts
                    elif isinstance(ts, str):
                        # Parse ISO format
                        ts_clean = ts.replace("Z", "+00:00")
                        if "T" in ts_clean:
                            dt = datetime.fromisoformat(ts_clean[:26])
                        else:
                            dt = datetime.fromisoformat(ts_clean[:19])
                    else:
                        continue

                    # Ensure timezone-aware (assume UTC if naive)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)

                    # Convert to EST
                    est = ZoneInfo("America/New_York")
                    dt_est = dt.astimezone(est)

                    # Format as "Nov 13, 2025"
                    return dt_est.strftime("%b %d, %Y")
                except Exception:
                    pass
        return "N/A"

    @property
    def order_id_short(self) -> str:
        """Get shortened brokerage order ID."""
        oid = self.order.get("brokerage_order_id") or ""
        if len(oid) > 8:
            return f"{oid[:8]}..."
        return oid or "N/A"

    @property
    def embed_color(self) -> int:
        """Get the embed color for this order."""
        return get_order_color(self.order.get("action"), self.order.get("status"))

    @property
    def order_timestamp(self) -> Optional[datetime]:
        """Get the best order timestamp for idea matching."""
        for field in ["time_executed", "time_placed", "created_at", "sync_timestamp"]:
            ts = self.order.get(field)
            if ts:
                if isinstance(ts, datetime):
                    return ts
                elif isinstance(ts, str):
                    try:
                        return datetime.fromisoformat(ts.replace("Z", "+00:00")[:26])
                    except (ValueError, TypeError):
                        continue
        return None

    def get_nearest_idea_display(
        self, max_length: int = 200
    ) -> Optional[Dict[str, Any]]:
        """
        Get the nearest Discord idea for this order, formatted for display.

        Args:
            max_length: Max characters for idea text

        Returns:
            Dict with 'text' and 'timestamp_display' keys, or None if no matching idea
        """
        # Use underlying symbol for options, regular symbol otherwise
        lookup_symbol = self.underlying_symbol or self.symbol
        if not lookup_symbol or lookup_symbol in ("N/A", "Option"):
            return None

        order_ts = self.order_timestamp
        if not order_ts:
            return None

        idea = get_nearest_idea(lookup_symbol, order_ts)
        if not idea:
            return None

        formatted_text = format_idea_for_embed(idea, max_length=max_length)
        if not formatted_text:
            return None

        # Format the idea timestamp for display (EST, like "Nov 13, 2025")
        idea_ts_display = None
        message_ts = idea.get("message_ts")
        if message_ts:
            try:
                from zoneinfo import ZoneInfo

                if isinstance(message_ts, datetime):
                    dt = message_ts
                elif isinstance(message_ts, str):
                    dt = datetime.fromisoformat(message_ts.replace("Z", "+00:00")[:26])
                else:
                    dt = None

                if dt:
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    est = ZoneInfo("America/New_York")
                    dt_est = dt.astimezone(est)
                    idea_ts_display = dt_est.strftime("%b %d, %Y")
            except Exception:
                pass

        return {
            "text": formatted_text,
            "timestamp_display": idea_ts_display,
        }

    def to_embed_dict(self, include_idea: bool = True) -> Dict[str, Any]:
        """
        Convert order to embed-ready dict structure.

        Args:
            include_idea: Whether to include nearest Discord idea (default True)

        Returns:
            Dict with title, description, color, footer, and optionally idea_field
        """
        # Title: "Bought TSLA @ $xxx.xx"
        price_str = self.price_display.replace("$", "")  # Remove $ for cleaner title
        title = f"{self.action_display} {self.symbol} @ {self.price_display}"

        # Description lines
        desc_lines = [
            f"**Status:** {self.status_display} • **Type:** {self.order_type_display}",
            f"**Qty:** {self.quantity_display} • **Notional:** {self.notional_display}",
        ]

        # Add price since trade if available
        price_since = self.price_since_trade_display()
        if price_since:
            desc_lines.append(price_since)

        # Add dividend reinvestment annotation if detected
        if self.is_dividend_reinvestment:
            desc_lines.append("\n🟡 *Potential dividend reinvestment*")

        result = {
            "title": title,
            "description": "\n".join(desc_lines),
            "color": self.embed_color,
            "footer": f"{self.timestamp_display} • ID: {self.order_id_short}",
        }

        # Add nearest idea field if requested and available
        if include_idea:
            idea_data = self.get_nearest_idea_display()
            if idea_data:
                idea_value = idea_data["text"]
                # Add idea timestamp line if available
                if idea_data.get("timestamp_display"):
                    idea_value += (
                        f"\n💡 *Idea posted on {idea_data['timestamp_display']}*"
                    )

                result["idea_field"] = {
                    "name": "💡 Nearest Discord Idea",
                    "value": idea_value,
                    "inline": False,
                }

        return result
