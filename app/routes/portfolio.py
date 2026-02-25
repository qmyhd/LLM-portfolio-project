"""
Portfolio API routes.

Endpoints:
- GET /portfolio - Get portfolio summary with positions
- POST /portfolio/sync - Trigger SnapTrade sync
"""

import logging
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from src.db import execute_sql
from src.snaptrade_collector import SnapTradeCollector
from src.price_service import get_latest_closes_batch, get_previous_closes_batch

logger = logging.getLogger(__name__)
router = APIRouter()


# Response models (match frontend types/api.ts)
class Position(BaseModel):
    """Individual portfolio position (matches api.ts Position)."""

    symbol: str
    accountId: str
    quantity: float
    averageBuyPrice: float
    currentPrice: float
    equity: float
    openPnl: float
    openPnlPercent: float
    dayChange: Optional[float]
    dayChangePercent: Optional[float]
    rawSymbol: Optional[str]


class PortfolioSummary(BaseModel):
    """Portfolio summary metrics (matches api.ts PortfolioSummary)."""

    totalValue: float
    totalEquity: float  # Equity-only (positions market value, no cash)
    totalCost: float
    unrealizedPL: float
    unrealizedPLPercent: float
    dayChange: float
    dayChangePercent: float
    cashBalance: float
    positionsCount: int
    lastSync: str  # ISO timestamp
    source: str  # Data source: 'snaptrade' | 'cache'


class PortfolioResponse(BaseModel):
    """Full portfolio response (matches api.ts PortfolioResponse)."""

    summary: PortfolioSummary
    positions: list[Position]


@router.get("", response_model=PortfolioResponse)
async def get_portfolio():
    """
    Get portfolio summary and all positions.

    Returns:
        Portfolio summary metrics and list of positions with current prices.
    """
    try:
        # Get positions from database
        positions_data = execute_sql(
            """
            SELECT
                p.symbol,
                p.quantity,
                p.average_buy_price as average_cost,
                p.price as snaptrade_price,
                p.raw_symbol,
                p.account_id
            FROM positions p
            WHERE p.quantity > 0
            ORDER BY p.symbol
            """,
            fetch_results=True,
        )

        # Get account balances
        balances_data = execute_sql(
            """
            SELECT
                SUM(cash) as total_cash,
                SUM(buying_power) as total_buying_power
            FROM account_balances
            """,
            fetch_results=True,
        )

        # Extract all symbols and batch fetch prices (single query instead of N queries)
        position_rows = []
        symbols_to_fetch = []
        for row in positions_data or []:
            row_dict: dict[str, Any] = dict(row._mapping) if hasattr(row, "_mapping") else dict(row)  # type: ignore[arg-type]
            position_rows.append(row_dict)
            symbols_to_fetch.append(row_dict["symbol"])

        # Batch fetch all prices in ONE database query
        prices_map = (
            get_latest_closes_batch(symbols_to_fetch) if symbols_to_fetch else {}
        )
        # Batch fetch previous closes for day-change calculation
        prev_closes_map = (
            get_previous_closes_batch(symbols_to_fetch) if symbols_to_fetch else {}
        )

        # yfinance fallback for symbols Databento doesn't cover (e.g. crypto)
        yf_quotes: dict[str, dict] = {}
        databento_missing = [s for s in symbols_to_fetch if s not in prices_map]
        if databento_missing:
            try:
                from src.market_data_service import get_realtime_quotes_batch

                yf_quotes = get_realtime_quotes_batch(databento_missing)
            except Exception as exc:
                logger.debug("yfinance batch quotes skipped: %s", exc)

        positions = []
        total_value = 0.0
        total_cost = 0.0
        total_day_change = 0.0

        for row_dict in position_rows:
            symbol = row_dict["symbol"]
            quantity = float(row_dict["quantity"] or 0)
            avg_cost = float(row_dict["average_cost"] or 0)

            # Get current price: Databento → SnapTrade → yfinance → avg_cost
            snaptrade_price = float(row_dict.get("snaptrade_price") or 0)
            databento_price = prices_map.get(symbol)
            yf_quote = yf_quotes.get(symbol)

            if databento_price:
                current_price = databento_price
            elif snaptrade_price > 0:
                logger.info(
                    f"💱 {symbol}: Databento missing, using SnapTrade price "
                    f"${snaptrade_price:.2f} (avg_cost=${avg_cost:.2f})"
                )
                current_price = snaptrade_price
            elif yf_quote:
                current_price = yf_quote["price"]
                logger.info(
                    f"📊 {symbol}: Using yfinance price ${current_price:.2f}"
                )
            else:
                logger.warning(
                    f"⚠️ {symbol}: No price sources available, "
                    f"falling back to avg_cost=${avg_cost:.2f}"
                )
                current_price = avg_cost

            # Calculate position metrics
            market_value = quantity * current_price
            cost_basis = quantity * avg_cost
            total_gain_loss = market_value - cost_basis
            total_gain_loss_pct = (
                (total_gain_loss / cost_basis * 100) if cost_basis > 0 else 0
            )

            # Day change from previous close (Databento → yfinance fallback)
            prev_close = prev_closes_map.get(symbol)
            if not prev_close and yf_quote:
                prev_close = yf_quote.get("previousClose")
            if prev_close and prev_close > 0:
                day_change = (current_price - prev_close) * quantity
                day_change_pct = ((current_price - prev_close) / prev_close) * 100
            else:
                day_change = None
                day_change_pct = None

            positions.append(
                Position(
                    symbol=symbol,
                    accountId=str(row_dict.get("account_id") or ""),
                    quantity=quantity,
                    averageBuyPrice=round(avg_cost, 2),
                    currentPrice=round(current_price, 2),
                    equity=round(market_value, 2),
                    openPnl=round(total_gain_loss, 2),
                    openPnlPercent=round(total_gain_loss_pct, 2),
                    dayChange=round(day_change, 2),
                    dayChangePercent=round(day_change_pct, 2),
                    rawSymbol=row_dict.get("raw_symbol"),
                )
            )

            total_value += market_value
            total_cost += cost_basis
            total_day_change += day_change or 0.0

        # total_value here is equity-only (sum of positions market values)
        total_equity = total_value

        # Get cash and buying power
        if balances_data:
            bal_row = balances_data[0]
            bal_dict: dict[str, Any] = (
                dict(bal_row._mapping) if hasattr(bal_row, "_mapping") else dict(bal_row)  # type: ignore[arg-type]
            )
            raw_cash = float(bal_dict["total_cash"] or 0)
        else:
            raw_cash = 0.0

        # For margin accounts, cash can be negative (debit balance).
        # Only add positive cash to total portfolio value; negative cash
        # represents margin borrowing already reflected in position values.
        cash_for_display = raw_cash
        cash_for_total = max(raw_cash, 0.0)

        # Total portfolio value = equity + positive cash
        total_portfolio_value = total_value + cash_for_total

        # Reconciliation check: equity from positions should match total_equity
        if total_cost > 0 and abs(total_equity - total_value) > total_cost * 0.05:
            logger.warning(
                f"⚠️ Portfolio reconciliation: equity=${total_equity:.2f} "
                f"positions_sum=${total_value:.2f} cost=${total_cost:.2f}"
            )

        # Calculate summary metrics
        total_gain_loss = total_value - total_cost
        total_gain_loss_pct = (
            (total_gain_loss / total_cost * 100) if total_cost > 0 else 0
        )
        day_change_pct = (
            (total_day_change / (total_portfolio_value - total_day_change) * 100)
            if (total_portfolio_value - total_day_change) > 0
            else 0
        )

        # Get last update time
        last_updated = execute_sql(
            "SELECT MAX(sync_timestamp) as last_update FROM positions",
            fetch_results=True,
        )
        last_update_str = ""
        if last_updated:
            last_row = last_updated[0]
            last_dict: dict[str, Any] = (
                dict(last_row._mapping) if hasattr(last_row, "_mapping") else dict(last_row)  # type: ignore[arg-type]
            )
            if last_dict.get("last_update"):
                last_update_str = str(last_dict["last_update"])

        summary = PortfolioSummary(
            totalValue=round(total_portfolio_value, 2),
            totalEquity=round(total_equity, 2),
            totalCost=round(total_cost, 2),
            unrealizedPL=round(total_gain_loss, 2),
            unrealizedPLPercent=round(total_gain_loss_pct, 2),
            dayChange=round(total_day_change, 2),
            dayChangePercent=round(day_change_pct, 2),
            cashBalance=round(cash_for_display, 2),
            positionsCount=len(positions),
            lastSync=last_update_str,
            source="snaptrade",
        )

        return PortfolioResponse(
            summary=summary,
            positions=positions,
        )

    except Exception as e:
        logger.error(f"Error fetching portfolio: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to fetch portfolio: {str(e)}"
        )


@router.post("/sync")
async def sync_portfolio():
    """
    Trigger a SnapTrade sync to refresh portfolio data.

    Returns:
        Status of the sync operation.
    """
    try:
        collector = SnapTradeCollector()
        results = collector.collect_all_data(write_parquet=False)

        error_list = results.get("errors", []) or []
        success = bool(results.get("success"))

        return {
            "status": "success" if success else "partial",
            "message": (
                "Portfolio sync completed"
                if success
                else "Portfolio sync completed with some errors"
            ),
            "accounts": results.get("accounts", 0),
            "balances": results.get("balances", 0),
            "positions": results.get("positions", 0),
            "orders": results.get("orders", 0),
            "errorCount": len(error_list),
        }
    except Exception as e:
        logger.error(f"Error syncing portfolio: {e}")
        raise HTTPException(status_code=500, detail="Sync failed")


# ---------------------------------------------------------------------------
# Top Movers
# ---------------------------------------------------------------------------

class MoverItem(BaseModel):
    """Single mover item."""

    symbol: str
    currentPrice: float
    previousClose: Optional[float]
    dayChange: Optional[float]
    dayChangePct: Optional[float]
    quantity: float
    equity: float


class MoversResponse(BaseModel):
    """Top movers response."""

    topGainers: list[MoverItem]
    topLosers: list[MoverItem]
    source: str  # 'intraday' or 'unrealized'


@router.get("/movers", response_model=MoversResponse)
async def get_movers(
    limit: int = Query(10, ge=1, le=50),
):
    """
    Get top gainers and losers from current positions.

    Uses intraday day-change when available, falls back to unrealized P/L %.
    Only includes positions with valid price data.
    """
    try:
        positions_data = execute_sql(
            """
            SELECT p.symbol, p.quantity, p.average_buy_price as average_cost,
                   p.price as snaptrade_price
            FROM positions p
            WHERE p.quantity > 0
            ORDER BY p.symbol
            """,
            fetch_results=True,
        )

        if not positions_data:
            return MoversResponse(topGainers=[], topLosers=[], source="intraday")

        # Collect symbols and batch fetch prices
        position_rows = []
        symbols = []
        for row in positions_data:
            rd: dict = dict(row._mapping) if hasattr(row, "_mapping") else dict(row)
            position_rows.append(rd)
            symbols.append(rd["symbol"])

        prices_map = get_latest_closes_batch(symbols) if symbols else {}
        prev_closes_map = get_previous_closes_batch(symbols) if symbols else {}

        # yfinance fallback for missing symbols
        yf_quotes: dict = {}
        missing = [s for s in symbols if s not in prices_map]
        if missing:
            try:
                from src.market_data_service import get_realtime_quotes_batch

                yf_quotes = get_realtime_quotes_batch(missing)
            except Exception as exc:
                logger.debug("yfinance batch quotes skipped: %s", exc)

        # Build mover items
        items: list[dict] = []
        use_unrealized = True

        for rd in position_rows:
            symbol = rd["symbol"]
            qty = float(rd["quantity"] or 0)
            avg_cost = float(rd["average_cost"] or 0)

            # Price cascade
            snaptrade_price = float(rd.get("snaptrade_price") or 0)
            databento_price = prices_map.get(symbol)
            yf_quote = yf_quotes.get(symbol)

            if databento_price:
                current_price = databento_price
            elif snaptrade_price > 0:
                current_price = snaptrade_price
            elif yf_quote:
                current_price = yf_quote["price"]
            else:
                current_price = avg_cost

            equity = qty * current_price

            # Day change
            prev_close = prev_closes_map.get(symbol)
            if not prev_close and yf_quote:
                prev_close = yf_quote.get("previousClose")

            day_change = None
            day_change_pct = None
            if prev_close and prev_close > 0:
                day_change = (current_price - prev_close) * qty
                day_change_pct = ((current_price - prev_close) / prev_close) * 100
                use_unrealized = False

            # Unrealized P/L as fallback
            open_pnl_pct = ((current_price - avg_cost) / avg_cost * 100) if avg_cost > 0 else 0.0

            items.append({
                "symbol": symbol,
                "currentPrice": round(current_price, 2),
                "previousClose": round(prev_close, 2) if prev_close else None,
                "dayChange": round(day_change, 2) if day_change is not None else None,
                "dayChangePct": round(day_change_pct, 2) if day_change_pct is not None else None,
                "quantity": qty,
                "equity": round(equity, 2),
                "openPnlPct": round(open_pnl_pct, 2),
            })

        # Check if any items have day change data
        has_day_change = any(i["dayChangePct"] is not None for i in items)
        source = "intraday" if has_day_change else "unrealized"

        # Sort by the appropriate metric
        if has_day_change:
            with_change = [i for i in items if i["dayChangePct"] is not None]
            sorted_items = sorted(with_change, key=lambda x: x["dayChangePct"], reverse=True)
        else:
            sorted_items = sorted(items, key=lambda x: x["openPnlPct"], reverse=True)

        # Split into gainers/losers
        sort_key = "dayChangePct" if has_day_change else "openPnlPct"
        gainers = [
            MoverItem(
                symbol=i["symbol"],
                currentPrice=i["currentPrice"],
                previousClose=i["previousClose"],
                dayChange=i["dayChange"],
                dayChangePct=i.get("dayChangePct") if has_day_change else i["openPnlPct"],
                quantity=i["quantity"],
                equity=i["equity"],
            )
            for i in sorted_items
            if (i[sort_key] or 0) > 0
        ][:limit]

        losers = [
            MoverItem(
                symbol=i["symbol"],
                currentPrice=i["currentPrice"],
                previousClose=i["previousClose"],
                dayChange=i["dayChange"],
                dayChangePct=i.get("dayChangePct") if has_day_change else i["openPnlPct"],
                quantity=i["quantity"],
                equity=i["equity"],
            )
            for i in reversed(sorted_items)
            if (i[sort_key] or 0) < 0
        ][:limit]

        return MoversResponse(topGainers=gainers, topLosers=losers, source=source)

    except Exception as e:
        logger.error(f"Error fetching movers: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch movers")
