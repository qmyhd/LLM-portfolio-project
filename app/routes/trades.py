"""
Trades API routes.

Endpoints:
- GET /stocks/{ticker}/trades - Per-stock trade history merging orders + activities with P/L enrichment
- GET /trades/recent - Dashboard recent trades across all stocks

Merges data from both the `activities` and `orders` tables, deduplicating
rows that appear in both (preferring activities because they contain fee data).
Enriches each trade with current position metrics for P/L calculation.
"""

import logging
import math
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Path, Query
from pydantic import BaseModel, Field

from src.db import execute_sql

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Safe float helpers
# ---------------------------------------------------------------------------
def _safe_float(value: Any, default: float = 0.0) -> float:
    """Convert value to float, returning default if None or NaN."""
    if value is None:
        return default
    try:
        f = float(value)
        return default if math.isnan(f) or math.isinf(f) else f
    except (ValueError, TypeError):
        return default


def _safe_float_optional(value: Any) -> float | None:
    """Convert value to float, returning None if None, NaN, or invalid."""
    if value is None:
        return None
    try:
        f = float(value)
        return None if math.isnan(f) or math.isinf(f) else f
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------
class EnrichedTrade(BaseModel):
    """Single trade record merged from activities + orders with P/L enrichment."""

    id: str
    symbol: str
    type: str  # BUY, SELL, DIVIDEND, etc. (maps from DB side/action)
    price: float | None = None
    units: float | None = None
    amount: float = 0.0
    fee: float = 0.0
    tradeDate: str | None = None  # ISO timestamp
    source: str  # "activity" or "order"
    description: str | None = None

    # Position enrichment
    currentPrice: float | None = None
    avgCost: float | None = None
    totalShares: float | None = None
    marketValue: float | None = None
    portfolioPct: float | None = None

    # P/L enrichment
    realizedPnl: float | None = None  # For SELL: (salePrice - avgCost) * units
    realizedPnlPct: float | None = None  # For SELL: percentage gain/loss
    unrealizedPnl: float | None = None  # For BUY: (currentPrice - avgCost) * units
    unrealizedPnlPct: float | None = None  # For BUY: percentage gain/loss


class TradesResponse(BaseModel):
    """Response for per-stock trade history."""

    ticker: str
    trades: list[EnrichedTrade] = Field(default_factory=list)
    total: int = 0


class RecentTradesResponse(BaseModel):
    """Response for dashboard recent trades across all stocks."""

    trades: list[EnrichedTrade] = Field(default_factory=list)
    total: int = 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _row_to_dict(row: Any) -> dict:
    """Convert a SQLAlchemy row to a dictionary."""
    if hasattr(row, "_mapping"):
        return dict(row._mapping)
    return dict(row)


def _round_minute(dt_str: str | None) -> str | None:
    """Round a datetime string to the nearest minute for dedup matching."""
    if not dt_str:
        return None
    try:
        # Handle various timestamp formats
        raw = str(dt_str).replace("T", " ").split("+")[0].split(".")[0]
        # Return truncated to minute precision: "YYYY-MM-DD HH:MM"
        return raw[:16]
    except Exception:
        return None


def _dedup_key(symbol: str, executed_at: str | None, amount: float) -> str:
    """Generate a deduplication key from symbol + minute-rounded time + rounded amount."""
    minute = _round_minute(executed_at) or "none"
    rounded_amount = round(amount, 2)
    return f"{symbol.upper()}|{minute}|{rounded_amount}"


def _build_position_map(rows: list) -> dict[str, dict]:
    """
    Build aggregated position data per symbol across accounts.

    Returns: {symbol: {quantity, avg_cost, current_price, market_value}}
    Weighted average cost is computed when symbol is held in multiple accounts.
    """
    symbol_data: dict[str, dict] = {}

    for row in rows:
        rd = _row_to_dict(row)
        sym = rd["symbol"]
        qty = _safe_float(rd.get("quantity"))
        avg_cost = _safe_float(rd.get("average_buy_price"))
        current_price = _safe_float(rd.get("current_price") or rd.get("price"))

        if sym not in symbol_data:
            symbol_data[sym] = {
                "quantity": qty,
                "total_cost_basis": qty * avg_cost,
                "current_price": current_price,
            }
        else:
            existing = symbol_data[sym]
            existing["quantity"] += qty
            existing["total_cost_basis"] += qty * avg_cost
            # Use latest non-zero current_price
            if current_price > 0:
                existing["current_price"] = current_price

    # Compute weighted avg cost and market value
    result: dict[str, dict] = {}
    for sym, data in symbol_data.items():
        qty = data["quantity"]
        avg_cost = (data["total_cost_basis"] / qty) if qty > 0 else 0.0
        cp = data["current_price"]
        result[sym] = {
            "quantity": qty,
            "avg_cost": round(avg_cost, 4),
            "current_price": round(cp, 4),
            "market_value": round(qty * cp, 2),
        }

    return result


def _compute_total_portfolio_value(position_map: dict[str, dict]) -> float:
    """Sum market values across all symbols."""
    return sum(p["market_value"] for p in position_map.values())


def _enrich_trade(
    trade: dict,
    position_map: dict[str, dict],
    total_portfolio_value: float,
) -> EnrichedTrade:
    """Enrich a raw trade dict with position + P/L data."""
    symbol = trade["symbol"]
    pos = position_map.get(symbol.upper(), {})

    current_price = _safe_float_optional(pos.get("current_price")) if pos else None
    avg_cost = _safe_float_optional(pos.get("avg_cost")) if pos else None
    total_shares = _safe_float_optional(pos.get("quantity")) if pos else None
    market_value = _safe_float_optional(pos.get("market_value")) if pos else None

    portfolio_pct = None
    if market_value and total_portfolio_value > 0:
        portfolio_pct = round(market_value / total_portfolio_value * 100, 2)

    # P/L calculation
    realized_pnl = None
    realized_pnl_pct = None
    unrealized_pnl = None
    unrealized_pnl_pct = None
    side = (trade.get("side") or "").upper()
    trade_price = _safe_float_optional(trade.get("price"))
    trade_units = _safe_float_optional(trade.get("units"))

    if side == "SELL" and trade_price is not None and trade_units is not None and avg_cost:
        realized_pnl = round((trade_price - avg_cost) * abs(trade_units), 2)
        if avg_cost > 0:
            realized_pnl_pct = round((trade_price - avg_cost) / avg_cost * 100, 2)
    elif side == "BUY" and trade_units is not None and avg_cost and current_price:
        unrealized_pnl = round((current_price - avg_cost) * abs(trade_units), 2)
        if avg_cost > 0:
            unrealized_pnl_pct = round((current_price - avg_cost) / avg_cost * 100, 2)

    return EnrichedTrade(
        id=trade["id"],
        symbol=symbol,
        type=side or trade.get("side", "UNKNOWN"),
        price=_safe_float_optional(trade.get("price")),
        units=_safe_float_optional(trade.get("units")),
        amount=_safe_float(trade.get("amount")),
        fee=_safe_float(trade.get("fee")),
        tradeDate=str(trade["executed_at"]) if trade.get("executed_at") else None,
        source=trade.get("source", "unknown"),
        description=trade.get("description"),
        currentPrice=round(current_price, 2) if current_price else None,
        avgCost=round(avg_cost, 2) if avg_cost else None,
        totalShares=round(total_shares, 4) if total_shares else None,
        marketValue=round(market_value, 2) if market_value else None,
        portfolioPct=portfolio_pct,
        realizedPnl=realized_pnl,
        realizedPnlPct=realized_pnl_pct,
        unrealizedPnl=unrealized_pnl,
        unrealizedPnlPct=unrealized_pnl_pct,
    )


def _merge_and_dedup(
    activities: list[dict],
    orders: list[dict],
) -> list[dict]:
    """
    Merge activities + orders, deduplicate by (symbol, minute, amount).

    When a trade appears in both sources, prefer the activity row (has fee data).
    """
    seen: dict[str, dict] = {}

    # Activities first — they take priority
    for act in activities:
        key = _dedup_key(
            act["symbol"],
            act.get("executed_at"),
            act.get("amount", 0),
        )
        seen[key] = act

    # Orders — only add if no matching activity
    for order in orders:
        key = _dedup_key(
            order["symbol"],
            order.get("executed_at"),
            order.get("amount", 0),
        )
        if key not in seen:
            seen[key] = order

    # Sort by executed_at descending (most recent first)
    merged = list(seen.values())
    merged.sort(
        key=lambda t: t.get("executed_at") or "",
        reverse=True,
    )
    return merged


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/stocks/{ticker}/trades", response_model=TradesResponse)
async def get_stock_trades(
    ticker: str = Path(..., description="Stock ticker symbol"),
    limit: int = Query(50, ge=1, le=200, description="Number of trades to return"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
):
    """
    Get per-stock trade history merging orders + activities with P/L enrichment.

    Merges from both `activities` and `orders` tables, deduplicates rows
    that appear in both (preferring activities for fee data), and enriches
    each trade with current position metrics and P/L calculations.
    """
    symbol = ticker.strip().upper()

    try:
        # 1. Fetch activities for this symbol (exclude deleted accounts)
        activities_rows = execute_sql(
            """
            SELECT
                a.id,
                a.symbol,
                UPPER(a.activity_type) AS side,
                a.price,
                a.units,
                COALESCE(a.amount, 0) AS amount,
                COALESCE(a.fee, 0) AS fee,
                a.trade_date AS executed_at,
                a.description
            FROM activities a
            JOIN accounts acc ON acc.id = a.account_id
            WHERE UPPER(a.symbol) = :symbol
              AND COALESCE(acc.connection_status, 'connected') != 'deleted'
            ORDER BY a.trade_date DESC
            LIMIT :fetch_limit
            """,
            params={"symbol": symbol, "fetch_limit": limit + offset + 100},
            fetch_results=True,
        ) or []

        activities = []
        for row in activities_rows:
            rd = _row_to_dict(row)
            rd["source"] = "activity"
            activities.append(rd)

        # 2. Fetch orders for this symbol (exclude deleted accounts)
        orders_rows = execute_sql(
            """
            SELECT
                o.brokerage_order_id AS id,
                o.symbol,
                UPPER(o.action) AS side,
                o.execution_price AS price,
                o.filled_quantity AS units,
                COALESCE(o.execution_price * o.filled_quantity, 0) AS amount,
                0 AS fee,
                o.time_executed AS executed_at,
                NULL AS description
            FROM orders o
            JOIN accounts acc ON acc.id = o.account_id
            WHERE UPPER(o.symbol) = :symbol
              AND o.status IN ('EXECUTED', 'FILLED')
              AND o.time_executed IS NOT NULL
              AND COALESCE(acc.connection_status, 'connected') != 'deleted'
            ORDER BY o.time_executed DESC
            LIMIT :fetch_limit
            """,
            params={"symbol": symbol, "fetch_limit": limit + offset + 100},
            fetch_results=True,
        ) or []

        orders = []
        for row in orders_rows:
            rd = _row_to_dict(row)
            rd["source"] = "order"
            orders.append(rd)

        # 3. Merge and deduplicate
        merged = _merge_and_dedup(activities, orders)
        total = len(merged)

        # 4. Apply pagination
        page = merged[offset: offset + limit]

        # 5. Fetch position data for enrichment
        position_rows = execute_sql(
            """
            SELECT p.symbol, p.quantity, p.average_buy_price,
                   COALESCE(p.current_price, p.price) AS current_price
            FROM positions p
            JOIN accounts acc ON acc.id = p.account_id
            WHERE UPPER(p.symbol) = :symbol
              AND p.quantity > 0
              AND COALESCE(acc.connection_status, 'connected') != 'deleted'
            """,
            params={"symbol": symbol},
            fetch_results=True,
        ) or []

        position_map = _build_position_map(position_rows)

        # Get total portfolio value for portfolioPct
        all_positions = execute_sql(
            """
            SELECT p.symbol, p.quantity, p.average_buy_price,
                   COALESCE(p.current_price, p.price) AS current_price
            FROM positions p
            JOIN accounts acc ON acc.id = p.account_id
            WHERE p.quantity > 0
              AND COALESCE(acc.connection_status, 'connected') != 'deleted'
            """,
            fetch_results=True,
        ) or []

        all_position_map = _build_position_map(all_positions)
        total_portfolio_value = _compute_total_portfolio_value(all_position_map)

        # 6. Enrich trades
        enriched = [
            _enrich_trade(t, position_map, total_portfolio_value)
            for t in page
        ]

        return TradesResponse(ticker=symbol, trades=enriched, total=total)

    except Exception as e:
        logger.error(f"Error fetching trades for {symbol}: {e}", exc_info=True)
        return TradesResponse(ticker=symbol, trades=[], total=0)


@router.get("/trades/recent", response_model=RecentTradesResponse)
async def get_recent_trades(
    limit: int = Query(20, ge=1, le=100, description="Number of recent trades"),
    days: int = Query(30, ge=1, le=365, description="Lookback window in days"),
):
    """
    Get recent trades across all stocks for the dashboard.

    Merges activities + orders from the lookback window, deduplicates,
    and enriches with position data.
    """
    try:
        cutoff = (datetime.now(UTC) - timedelta(days=days)).strftime("%Y-%m-%d")

        # 1. Fetch recent activities (exclude deleted accounts)
        activities_rows = execute_sql(
            """
            SELECT
                a.id,
                a.symbol,
                UPPER(a.activity_type) AS side,
                a.price,
                a.units,
                COALESCE(a.amount, 0) AS amount,
                COALESCE(a.fee, 0) AS fee,
                a.trade_date AS executed_at,
                a.description
            FROM activities a
            JOIN accounts acc ON acc.id = a.account_id
            WHERE a.trade_date >= :cutoff
              AND a.symbol IS NOT NULL
              AND UPPER(a.activity_type) IN ('BUY', 'SELL')
              AND COALESCE(acc.connection_status, 'connected') != 'deleted'
            ORDER BY a.trade_date DESC
            LIMIT :fetch_limit
            """,
            params={"cutoff": cutoff, "fetch_limit": limit + 100},
            fetch_results=True,
        ) or []

        activities = []
        for row in activities_rows:
            rd = _row_to_dict(row)
            rd["source"] = "activity"
            activities.append(rd)

        # 2. Fetch recent orders (exclude deleted accounts)
        orders_rows = execute_sql(
            """
            SELECT
                o.brokerage_order_id AS id,
                o.symbol,
                UPPER(o.action) AS side,
                o.execution_price AS price,
                o.filled_quantity AS units,
                COALESCE(o.execution_price * o.filled_quantity, 0) AS amount,
                0 AS fee,
                o.time_executed AS executed_at,
                NULL AS description
            FROM orders o
            JOIN accounts acc ON acc.id = o.account_id
            WHERE o.time_executed >= :cutoff
              AND o.status IN ('EXECUTED', 'FILLED')
              AND o.time_executed IS NOT NULL
              AND UPPER(o.action) IN ('BUY', 'SELL')
              AND COALESCE(acc.connection_status, 'connected') != 'deleted'
            ORDER BY o.time_executed DESC
            LIMIT :fetch_limit
            """,
            params={"cutoff": cutoff, "fetch_limit": limit + 100},
            fetch_results=True,
        ) or []

        orders = []
        for row in orders_rows:
            rd = _row_to_dict(row)
            rd["source"] = "order"
            orders.append(rd)

        # 3. Merge and deduplicate
        merged = _merge_and_dedup(activities, orders)

        # 4. Trim to limit
        page = merged[:limit]
        total = len(merged)

        # 5. Fetch all position data for enrichment
        position_rows = execute_sql(
            """
            SELECT p.symbol, p.quantity, p.average_buy_price,
                   COALESCE(p.current_price, p.price) AS current_price
            FROM positions p
            JOIN accounts acc ON acc.id = p.account_id
            WHERE p.quantity > 0
              AND COALESCE(acc.connection_status, 'connected') != 'deleted'
            """,
            fetch_results=True,
        ) or []

        position_map = _build_position_map(position_rows)
        total_portfolio_value = _compute_total_portfolio_value(position_map)

        # 6. Enrich trades
        enriched = [
            _enrich_trade(t, position_map, total_portfolio_value)
            for t in page
        ]

        return RecentTradesResponse(trades=enriched, total=total)

    except Exception as e:
        logger.error(f"Error fetching recent trades: {e}", exc_info=True)
        return RecentTradesResponse(trades=[], total=0)
