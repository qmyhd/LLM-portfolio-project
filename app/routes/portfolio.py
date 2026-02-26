"""
Portfolio API routes.

Endpoints:
- GET /portfolio - Get portfolio summary with positions
- POST /portfolio/sync - Trigger SnapTrade sync
- GET /portfolio/sparklines - Batch sparkline close prices for held symbols
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from src.db import execute_sql
from src.price_service import get_latest_closes_batch, get_previous_closes_batch
from src.snaptrade_collector import SnapTradeCollector

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
    dayChange: float | None
    dayChangePercent: float | None
    rawSymbol: str | None
    # Robinhood-style fields (optional, non-breaking)
    portfolioDiversity: float | None = None  # equity / totalEquity * 100
    companyName: str | None = None


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
    buyingPower: float | None = None  # From account_balances.buying_power


class ReconPositionMeta(BaseModel):
    """Debug metadata for a single position — only returned when ?recon=1."""

    symbol: str
    priceSource: str  # "databento" | "snaptrade" | "yfinance" | "avgcost"
    priceUsed: float
    databentoPrice: float | None = None
    snaptradePrice: float | None = None
    yfinancePrice: float | None = None
    prevCloseSource: str | None = None
    prevCloseValue: float | None = None


class ReconMeta(BaseModel):
    """Portfolio-level debug metadata — only returned when ?recon=1."""

    positions: list[ReconPositionMeta]
    cashRaw: float
    cashForTotal: float
    totalEquityComputed: float
    totalCostComputed: float
    priceSourceBreakdown: dict[str, int]


class PortfolioResponse(BaseModel):
    """Full portfolio response (matches api.ts PortfolioResponse)."""

    summary: PortfolioSummary
    positions: list[Position]
    recon: ReconMeta | None = None  # Only populated when ?recon=1


@router.get("", response_model=PortfolioResponse)
async def get_portfolio(
    recon: bool = Query(False, description="Include debug metadata for reconciliation"),
):
    """
    Get portfolio summary and all positions.

    Pass ?recon=1 to include per-position debug metadata (price sources, raw values).
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

        # Batch fetch company names from stock_profile_current
        company_names: dict[str, str] = {}
        if symbols_to_fetch:
            name_rows = execute_sql(
                """
                SELECT symbol, "companyName"
                FROM stock_profile_current
                WHERE symbol = ANY(:symbols)
                """,
                params={"symbols": symbols_to_fetch},
                fetch_results=True,
            )
            for nr in name_rows or []:
                nr_dict: dict[str, Any] = dict(nr._mapping) if hasattr(nr, "_mapping") else dict(nr)  # type: ignore[arg-type]
                if nr_dict.get("companyName"):
                    company_names[nr_dict["symbol"]] = nr_dict["companyName"]

        positions = []
        total_value = 0.0
        total_cost = 0.0
        total_day_change = 0.0
        # Recon tracking
        recon_positions: list[ReconPositionMeta] = []
        source_counts: dict[str, int] = defaultdict(int)

        for row_dict in position_rows:
            symbol = row_dict["symbol"]
            quantity = float(row_dict["quantity"] or 0)
            avg_cost = float(row_dict["average_cost"] or 0)

            # Get current price: Databento → SnapTrade → yfinance → avg_cost
            snaptrade_price = float(row_dict.get("snaptrade_price") or 0)
            databento_price = prices_map.get(symbol)
            yf_quote = yf_quotes.get(symbol)
            yf_price = yf_quote["price"] if yf_quote else None

            if databento_price:
                current_price = databento_price
                price_source = "databento"
            elif snaptrade_price > 0:
                logger.info(
                    f"💱 {symbol}: Databento missing, using SnapTrade price "
                    f"${snaptrade_price:.2f} (avg_cost=${avg_cost:.2f})"
                )
                current_price = snaptrade_price
                price_source = "snaptrade"
            elif yf_price:
                current_price = yf_price
                logger.info(
                    f"📊 {symbol}: Using yfinance price ${current_price:.2f}"
                )
                price_source = "yfinance"
            else:
                logger.warning(
                    f"⚠️ {symbol}: No price sources available, "
                    f"falling back to avg_cost=${avg_cost:.2f}"
                )
                current_price = avg_cost
                price_source = "avgcost"

            source_counts[price_source] += 1

            # Calculate position metrics
            market_value = quantity * current_price
            cost_basis = quantity * avg_cost
            total_gain_loss = market_value - cost_basis
            total_gain_loss_pct = (
                (total_gain_loss / cost_basis * 100) if cost_basis > 0 else 0
            )

            # Day change from previous close (Databento → yfinance fallback)
            prev_close = prev_closes_map.get(symbol)
            prev_close_source = "databento" if prev_close else None
            if not prev_close and yf_quote:
                prev_close = yf_quote.get("previousClose")
                if prev_close:
                    prev_close_source = "yfinance"
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
                    dayChange=round(day_change, 2) if day_change is not None else None,
                    dayChangePercent=round(day_change_pct, 2) if day_change_pct is not None else None,
                    rawSymbol=row_dict.get("raw_symbol"),
                    companyName=company_names.get(symbol),
                )
            )

            total_value += market_value
            total_cost += cost_basis
            total_day_change += day_change or 0.0

            if recon:
                recon_positions.append(
                    ReconPositionMeta(
                        symbol=symbol,
                        priceSource=price_source,
                        priceUsed=round(current_price, 4),
                        databentoPrice=round(databento_price, 4) if databento_price else None,
                        snaptradePrice=round(snaptrade_price, 4) if snaptrade_price > 0 else None,
                        yfinancePrice=round(yf_price, 4) if yf_price else None,
                        prevCloseSource=prev_close_source,
                        prevCloseValue=round(prev_close, 4) if prev_close else None,
                    )
                )

        # total_value here is equity-only (sum of positions market values)
        total_equity = total_value

        # Compute portfolio diversity for each position
        if total_equity > 0:
            for pos in positions:
                pos.portfolioDiversity = round(pos.equity / total_equity * 100, 2)

        # Get cash and buying power
        raw_cash = 0.0
        raw_buying_power: float | None = None
        if balances_data:
            bal_row = balances_data[0]
            bal_dict: dict[str, Any] = (
                dict(bal_row._mapping) if hasattr(bal_row, "_mapping") else dict(bal_row)  # type: ignore[arg-type]
            )
            raw_cash = float(bal_dict["total_cash"] or 0)
            bp = bal_dict.get("total_buying_power")
            if bp is not None:
                raw_buying_power = round(float(bp), 2)

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
            buyingPower=raw_buying_power,
        )

        recon_meta = None
        if recon:
            recon_meta = ReconMeta(
                positions=recon_positions,
                cashRaw=round(raw_cash, 2),
                cashForTotal=round(cash_for_total, 2),
                totalEquityComputed=round(total_equity, 2),
                totalCostComputed=round(total_cost, 2),
                priceSourceBreakdown=dict(source_counts),
            )

        return PortfolioResponse(
            summary=summary,
            positions=positions,
            recon=recon_meta,
        )

    except Exception as e:
        logger.error(f"Error fetching portfolio: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to fetch portfolio: {str(e)}"
        ) from e


class SyncResult(BaseModel):
    """Stable sync response model — always returned with HTTP 200."""

    status: str  # 'success' | 'partial' | 'error'
    message: str
    accounts: int
    balances: int
    positions: int
    orders: int
    activities: int
    errorCount: int
    errors: list[str]
    accountIdUsed: str | None
    authError: bool


@router.post("/sync", response_model=SyncResult)
async def sync_portfolio():
    """
    Trigger a SnapTrade sync to refresh portfolio data.

    Always returns HTTP 200 with a stable SyncResult shape.
    status='error' indicates the sync failed but the response is still valid JSON.
    Only truly fatal server crashes (unhandled exceptions) produce HTTP 500.
    """
    try:
        collector = SnapTradeCollector()
        results = collector.collect_all_data(write_parquet=False)

        error_list = results.get("errors", []) or []
        success = bool(results.get("success"))
        auth_error = bool(results.get("authError"))

        if auth_error:
            status = "error"
            message = "Brokerage authentication failed — please re-link your account"
        elif success:
            status = "success"
            message = "Portfolio sync completed"
        else:
            status = "partial"
            message = "Portfolio sync completed with some errors"

        return SyncResult(
            status=status,
            message=message,
            accounts=results.get("accounts", 0),
            balances=results.get("balances", 0),
            positions=results.get("positions", 0),
            orders=results.get("orders", 0),
            activities=results.get("activities", 0),
            errorCount=len(error_list),
            errors=[str(e) for e in error_list[:10]],
            accountIdUsed=results.get("accountIdUsed"),
            authError=auth_error,
        )
    except Exception as e:
        logger.error(f"Error syncing portfolio: {e}")
        # Even fatal errors return 200 with a stable shape so the UI always gets parseable JSON
        return SyncResult(
            status="error",
            message=f"Sync failed: {str(e)}",
            accounts=0,
            balances=0,
            positions=0,
            orders=0,
            activities=0,
            errorCount=1,
            errors=[str(e)],
            accountIdUsed=None,
            authError=False,
        )


# ---------------------------------------------------------------------------
# Top Movers
# ---------------------------------------------------------------------------

class MoverItem(BaseModel):
    """Single mover item.

    dayChangePct: intraday price change % (null when no prev close available).
    openPnlPct: unrealized P/L % from cost basis (always present when cost > 0).
    """

    symbol: str
    currentPrice: float
    previousClose: float | None
    dayChange: float | None
    dayChangePct: float | None  # null = no intraday data
    openPnlPct: float  # always present (0.0 if no cost basis)
    quantity: float
    equity: float


class MoversResponse(BaseModel):
    """Top movers response.

    source: 'intraday' when ranking used dayChangePct, 'unrealized' when using openPnlPct.
    The frontend should display the metric matching source and label accordingly.
    """

    topGainers: list[MoverItem]
    topLosers: list[MoverItem]
    source: str  # 'intraday' | 'unrealized'


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

        def _to_mover(i: dict) -> MoverItem:
            return MoverItem(
                symbol=i["symbol"],
                currentPrice=i["currentPrice"],
                previousClose=i["previousClose"],
                dayChange=i["dayChange"],
                dayChangePct=i.get("dayChangePct"),
                openPnlPct=i["openPnlPct"],
                quantity=i["quantity"],
                equity=i["equity"],
            )

        gainers = [
            _to_mover(i) for i in sorted_items if (i[sort_key] or 0) > 0
        ][:limit]

        losers = [
            _to_mover(i) for i in reversed(sorted_items) if (i[sort_key] or 0) < 0
        ][:limit]

        return MoversResponse(topGainers=gainers, topLosers=losers, source=source)

    except Exception as e:
        logger.error(f"Error fetching movers: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch movers") from e


# ---------------------------------------------------------------------------
# Sparklines — batch close prices for held symbols
# ---------------------------------------------------------------------------

PERIOD_DAYS = {"1W": 7, "1M": 30, "3M": 90}


class SparklineData(BaseModel):
    """Close-price array for a single symbol, suitable for sparkline rendering."""

    symbol: str
    closes: list[float]
    dates: list[str]


class SparklineResponse(BaseModel):
    """Batch sparkline data for all held symbols."""

    sparklines: list[SparklineData]
    period: str


@router.get("/sparklines", response_model=SparklineResponse)
async def get_sparklines(
    period: str = Query("1M", description="Period: 1W, 1M, or 3M"),
):
    """
    Get close-price arrays for all held symbols, suitable for sparkline charts.

    Uses ohlcv_daily data (Databento). Symbols without OHLCV data return empty arrays.
    """
    days = PERIOD_DAYS.get(period.upper(), 30)
    end_date = date.today()
    start_date = end_date - timedelta(days=days)

    try:
        # Get held symbols
        held = execute_sql(
            "SELECT DISTINCT symbol FROM positions WHERE quantity > 0",
            fetch_results=True,
        )
        symbols = [
            (dict(r._mapping) if hasattr(r, "_mapping") else dict(r))["symbol"]
            for r in (held or [])
        ]

        if not symbols:
            return SparklineResponse(sparklines=[], period=period.upper())

        # Single query for all symbols' close prices
        rows = execute_sql(
            """
            SELECT symbol, date, close
            FROM ohlcv_daily
            WHERE symbol = ANY(:symbols)
              AND date >= :start_date
              AND date <= :end_date
            ORDER BY symbol, date ASC
            """,
            params={"symbols": symbols, "start_date": str(start_date), "end_date": str(end_date)},
            fetch_results=True,
        )

        # Group by symbol
        grouped: dict[str, list[tuple[str, float]]] = defaultdict(list)
        for row in rows or []:
            rd: dict[str, Any] = dict(row._mapping) if hasattr(row, "_mapping") else dict(row)
            grouped[rd["symbol"]].append((str(rd["date"]), float(rd["close"])))

        sparklines = []
        for sym in symbols:
            entries = grouped.get(sym, [])
            sparklines.append(
                SparklineData(
                    symbol=sym,
                    closes=[e[1] for e in entries],
                    dates=[e[0] for e in entries],
                )
            )

        return SparklineResponse(sparklines=sparklines, period=period.upper())

    except Exception as e:
        logger.error(f"Error fetching sparklines: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch sparklines") from e
