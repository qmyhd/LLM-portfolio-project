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
from src.market_data_service import CRYPTO_IDENTITY, _CRYPTO_SYMBOLS, get_realtime_quotes_batch
from src.price_service import get_latest_closes_batch, get_previous_closes_batch
from src.snaptrade_collector import SnapTradeCollector

logger = logging.getLogger(__name__)
router = APIRouter()


def _resolve_tv_symbol(symbol: str, exchange_code: str | None = None) -> str:
    """Resolve a TradingView-compatible symbol string."""
    # Crypto: use canonical tv_symbol from identity dict
    identity = CRYPTO_IDENTITY.get(symbol)
    if identity:
        return identity["tv_symbol"]
    # Equity: use exchange_code if available
    if exchange_code:
        ex = exchange_code.upper()
        if ex in ("XNAS", "NASDAQ"):
            return f"NASDAQ:{symbol}"
        if ex in ("XNYS", "NYSE"):
            return f"NYSE:{symbol}"
        if ex in ("ARCX", "ARCA", "NYSEARCA"):
            return f"AMEX:{symbol}"
    return symbol


def r2(x: Any) -> float:
    """Round to 2 decimal places, coercing None → 0.0."""
    return 0.0 if x is None else round(float(x), 2)


def r4(x: Any) -> float:
    """Round to 4 decimal places, coercing None → 0.0."""
    return 0.0 if x is None else round(float(x), 4)


def r2n(x: Any) -> float | None:
    """Round to 2 decimal places, preserving None."""
    return None if x is None else round(float(x), 2)


def r4n(x: Any) -> float | None:
    """Round to 4 decimal places, preserving None."""
    return None if x is None else round(float(x), 4)


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
    assetType: str | None = None  # 'equity' | 'etf' | 'crypto' | 'option'
    tvSymbol: str | None = None  # TradingView widget symbol (e.g. "COINBASE:BTCUSD", "NASDAQ:AAPL")


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
    assetBreakdown: dict[str, float] | None = None  # {assetType: totalEquity}
    cryptoValue: float | None = None  # Total crypto equity
    cryptoPnl: float | None = None  # Total crypto unrealized P/L
    connectionStatus: str | None = None  # 'connected' | 'disconnected' | 'error' | 'deleted'


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
    asset_class: str | None = Query(
        None,
        description="Filter: 'equity' (stocks+ETFs), 'crypto', 'all', or omit for all",
    ),
    account_id: str | None = Query(
        None,
        description="Filter by account ID, or 'all' for all accounts",
    ),
):
    """
    Get portfolio summary and all positions.

    Pass ?recon=1 to include per-position debug metadata (price sources, raw values).
    Pass ?asset_class=equity for stocks/ETFs only, or ?asset_class=crypto for crypto only.
    Pass ?account_id=<id> to filter to a single account.
    """
    try:
        # Normalize 'all' to None for simpler logic
        if asset_class and asset_class.lower() == "all":
            asset_class = None
        if account_id and account_id.lower() == "all":
            account_id = None

        # Get positions from database (join symbols for asset_type + company name).
        # Exclude positions from accounts marked as 'deleted' (orphaned re-links)
        # unless a specific account_id is requested.
        pos_where = "p.quantity > 0"
        pos_params: dict[str, Any] = {}
        if account_id:
            pos_where += " AND p.account_id = :account_id"
            pos_params["account_id"] = account_id
        else:
            pos_where += (
                " AND NOT EXISTS ("
                "   SELECT 1 FROM accounts a"
                "   WHERE a.id = p.account_id"
                "   AND a.connection_status = 'deleted'"
                " )"
            )

        positions_data = execute_sql(
            f"""
            SELECT
                p.symbol,
                p.quantity,
                p.average_buy_price as average_cost,
                p.price as snaptrade_price,
                p.raw_symbol,
                p.account_id,
                p.exchange_code,
                COALESCE(s.asset_type, 'equity') as asset_type,
                s.description as company_name
            FROM positions p
            LEFT JOIN symbols s ON s.ticker = p.symbol
            WHERE {pos_where}
            ORDER BY p.symbol
            """,
            params=pos_params if pos_params else None,
            fetch_results=True,
        )

        # Get account balances (DISTINCT ON prevents double-counting from
        # multiple snapshots for the same account+currency)
        bal_where = ""
        bal_params: dict[str, Any] = {}
        if account_id:
            bal_where = "WHERE account_id = :account_id"
            bal_params["account_id"] = account_id
        else:
            # Exclude balances from deleted (orphaned) accounts
            bal_where = (
                "WHERE account_id NOT IN ("
                "  SELECT id FROM accounts WHERE connection_status = 'deleted'"
                ")"
            )

        balances_data = execute_sql(
            f"""
            SELECT
                SUM(cash) as total_cash,
                SUM(buying_power) as total_buying_power
            FROM (
                SELECT DISTINCT ON (account_id, currency_code)
                    cash, buying_power
                FROM account_balances
                {bal_where}
                ORDER BY account_id, currency_code, sync_timestamp DESC
            ) latest
            """,
            params=bal_params if bal_params else None,
            fetch_results=True,
        )

        # Extract all symbols and batch fetch prices (single query instead of N queries)
        position_rows = []
        symbols_to_fetch = []
        company_names: dict[str, str] = {}
        for row in positions_data or []:
            row_dict: dict[str, Any] = dict(row._mapping) if hasattr(row, "_mapping") else dict(row)  # type: ignore[arg-type]
            # Normalize asset_type to frontend-friendly short names
            sym = row_dict["symbol"]
            if sym in _CRYPTO_SYMBOLS:
                row_dict["asset_type"] = "crypto"
            else:
                raw_at = (row_dict.get("asset_type") or "equity").lower()
                # Map verbose DB values to concise frontend tokens
                _AT_MAP = {
                    "cryptocurrency": "crypto",
                    "common stock": "equity",
                    "american depositary receipt": "adr",
                    "structured product": "structured",
                }
                row_dict["asset_type"] = _AT_MAP.get(raw_at, raw_at)
            # Company name from the joined symbols.description
            if row_dict.get("company_name"):
                company_names[sym] = row_dict["company_name"]
            position_rows.append(row_dict)
            symbols_to_fetch.append(sym)

        # ---- Phase 1B: Batch fetch prices ----
        # CRITICAL: Split by asset type to avoid crypto/equity ticker collisions.
        # Databento ohlcv_daily has equity tickers (BTC=Grayscale, ETH=Ethan Allen)
        # that collide with crypto symbols. Never send crypto to Databento.
        crypto_syms = [s for s in symbols_to_fetch if s in _CRYPTO_SYMBOLS]
        equity_syms = [s for s in symbols_to_fetch if s not in _CRYPTO_SYMBOLS]

        # Databento ONLY for equities
        prices_map = get_latest_closes_batch(equity_syms) if equity_syms else {}
        prev_closes_map = get_previous_closes_batch(equity_syms) if equity_syms else {}

        # yfinance for ALL crypto + equity symbols Databento doesn't cover
        yf_quotes: dict[str, dict] = {}
        yf_needed = crypto_syms + [s for s in equity_syms if s not in prices_map]
        if yf_needed:
            try:
                yf_quotes = get_realtime_quotes_batch(yf_needed)
            except Exception as exc:
                logger.debug("yfinance batch quotes skipped: %s", exc)

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

            # Get current price: Databento → SnapTrade → yfinance → avg_cost → 0
            snaptrade_price = float(row_dict.get("snaptrade_price") or 0)
            databento_price = prices_map.get(symbol)
            yf_quote = yf_quotes.get(symbol)
            yf_price = yf_quote["price"] if yf_quote else None

            if databento_price:
                current_price = float(databento_price)
                price_source = "databento"
            elif snaptrade_price > 0:
                logger.info(
                    f"💱 {symbol}: Databento missing, using SnapTrade price "
                    f"${snaptrade_price:.2f} (avg_cost=${avg_cost:.2f})"
                )
                current_price = snaptrade_price
                price_source = "snaptrade"
            elif yf_price:
                current_price = float(yf_price)
                logger.info(
                    f"📊 {symbol}: Using yfinance price ${current_price:.2f}"
                )
                price_source = "yfinance"
            else:
                current_price = avg_cost or 0.0
                if current_price > 0:
                    logger.warning(
                        f"⚠️ {symbol}: No price sources, "
                        f"falling back to avg_cost=${current_price:.2f}"
                    )
                else:
                    logger.warning(
                        f"⚠️ {symbol}: No price sources and no avg_cost, "
                        f"using $0.00"
                    )
                price_source = "avgcost"

            source_counts[price_source] += 1

            # Calculate position metrics
            market_value = quantity * current_price
            cost_basis = quantity * avg_cost
            total_gain_loss = market_value - cost_basis
            total_gain_loss_pct = (
                (total_gain_loss / cost_basis * 100) if cost_basis > 0 else 0
            )

            # Day change calculation — separate logic for crypto vs equity
            is_crypto = symbol in _CRYPTO_SYMBOLS

            if is_crypto:
                # Crypto: ALWAYS use provider's 24h change (never compute from prev_close)
                if yf_quote and yf_quote.get("dayChangePct") is not None:
                    day_change_pct = yf_quote["dayChangePct"]
                    day_change = quantity * current_price * (day_change_pct / 100)
                else:
                    day_change_pct = None
                    day_change = None
                prev_close = yf_quote.get("previousClose") if yf_quote else None
                prev_close_source = "yfinance" if prev_close else None
            else:
                # Equity: compute from prev_close with guardrails
                prev_close = prev_closes_map.get(symbol)
                prev_close_source = "databento" if prev_close else None
                if not prev_close and yf_quote:
                    prev_close = yf_quote.get("previousClose")
                    if prev_close:
                        prev_close_source = "yfinance"

                if prev_close and prev_close > 0:
                    day_change_pct = ((current_price - prev_close) / prev_close) * 100
                    day_change = (current_price - prev_close) * quantity
                    # Guard: cap at 300% — treat as data error
                    if abs(day_change_pct) > 300:
                        logger.warning(
                            f"⚠️ {symbol}: day_change_pct={day_change_pct:.1f}% exceeds 300%% cap, "
                            f"nulling (current={current_price}, prev={prev_close})"
                        )
                        day_change_pct = None
                        day_change = None
                else:
                    day_change_pct = None
                    day_change = None

            positions.append(
                Position(
                    symbol=symbol,
                    accountId=str(row_dict.get("account_id") or ""),
                    quantity=quantity,
                    averageBuyPrice=r2(avg_cost),
                    currentPrice=r2(current_price),
                    equity=r2(market_value),
                    openPnl=r2(total_gain_loss),
                    openPnlPercent=r2(total_gain_loss_pct),
                    dayChange=r2n(day_change),
                    dayChangePercent=r2n(day_change_pct),
                    rawSymbol=row_dict.get("raw_symbol"),
                    companyName=company_names.get(symbol),
                    assetType=row_dict.get("asset_type", "equity"),
                    tvSymbol=_resolve_tv_symbol(symbol, row_dict.get("exchange_code")),
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
                        priceUsed=r4(current_price),
                        databentoPrice=r4n(databento_price),
                        snaptradePrice=r4(snaptrade_price) if snaptrade_price > 0 else None,
                        yfinancePrice=r4n(yf_price),
                        prevCloseSource=prev_close_source,
                        prevCloseValue=r4n(prev_close),
                    )
                )

        # ---- Phase 1C: Group positions by (symbol, assetType) ----
        # If same ticker held in multiple accounts, merge into one row
        grouped: dict[tuple[str, str | None], list[Position]] = defaultdict(list)
        for pos in positions:
            grouped[(pos.symbol, pos.assetType)].append(pos)

        merged_positions: list[Position] = []
        for (_sym, _at), group in grouped.items():
            if len(group) == 1:
                merged_positions.append(group[0])
            else:
                # Merge: sum quantities, equities, P/L; weighted avg cost
                total_qty = sum(p.quantity for p in group)
                total_eq = sum(p.equity for p in group)
                total_pnl = sum(p.openPnl for p in group)
                total_dc = sum(p.dayChange or 0 for p in group)
                total_cost_basis = sum(p.quantity * p.averageBuyPrice for p in group)
                w_avg_cost = (total_cost_basis / total_qty) if total_qty > 0 else 0
                pnl_pct = (total_pnl / total_cost_basis * 100) if total_cost_basis > 0 else 0
                first = group[0]
                dc_pct = first.dayChangePercent  # same % for same ticker
                merged_positions.append(
                    Position(
                        symbol=first.symbol,
                        accountId=",".join(p.accountId for p in group if p.accountId),
                        quantity=total_qty,
                        averageBuyPrice=r2(w_avg_cost),
                        currentPrice=first.currentPrice,
                        equity=r2(total_eq),
                        openPnl=r2(total_pnl),
                        openPnlPercent=r2(pnl_pct),
                        dayChange=r2n(total_dc) if any(p.dayChange is not None for p in group) else None,
                        dayChangePercent=dc_pct,
                        rawSymbol=first.rawSymbol,
                        companyName=first.companyName,
                        assetType=first.assetType,
                        tvSymbol=first.tvSymbol,
                    )
                )
        positions = merged_positions

        # ---- Phase 1C-filter: Apply asset_class filter if requested ----
        if asset_class:
            ac = asset_class.lower()
            # Match both "crypto" (post-override) and "cryptocurrency" (raw DB value)
            _crypto_types = {"crypto", "cryptocurrency"}
            if ac == "equity":
                positions = [p for p in positions if (p.assetType or "").lower() not in _crypto_types]
            elif ac == "crypto":
                positions = [p for p in positions if (p.assetType or "").lower() in _crypto_types]

        # Recompute totals from merged positions
        total_value = sum(p.equity for p in positions)
        total_cost = sum(p.quantity * p.averageBuyPrice for p in positions)
        total_day_change = sum(p.dayChange or 0 for p in positions)

        # total_value here is equity-only (sum of positions market values)
        total_equity = total_value

        # ---- Phase 1D: Asset breakdown ----
        asset_breakdown: dict[str, float] = defaultdict(float)
        crypto_value = 0.0
        crypto_pnl = 0.0
        for pos in positions:
            at = pos.assetType or "equity"
            asset_breakdown[at] += pos.equity
            if at.lower() in ("crypto", "cryptocurrency"):
                crypto_value += pos.equity
                crypto_pnl += pos.openPnl

        # Compute portfolio diversity for each position
        if total_equity > 0:
            for pos in positions:
                pos.portfolioDiversity = r2(pos.equity / total_equity * 100)

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
                raw_buying_power = r2(bp)

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

        # Get connection status (worst status across non-deleted accounts)
        connection_status = None
        try:
            conn_rows = execute_sql(
                "SELECT COALESCE(connection_status, 'connected') as status "
                "FROM accounts WHERE connection_status != 'deleted'",
                fetch_results=True,
            )
            if conn_rows:
                statuses = [
                    (dict(r._mapping) if hasattr(r, "_mapping") else dict(r)).get("status", "connected")
                    for r in conn_rows
                ]
                # Priority: error > disconnected > connected
                priority = {"error": 0, "disconnected": 1, "connected": 2}
                connection_status = min(statuses, key=lambda s: priority.get(s, 2))
        except Exception:
            pass  # Column may not exist yet if migration hasn't run

        summary = PortfolioSummary(
            totalValue=r2(total_portfolio_value),
            totalEquity=r2(total_equity),
            totalCost=r2(total_cost),
            unrealizedPL=r2(total_gain_loss),
            unrealizedPLPercent=r2(total_gain_loss_pct),
            dayChange=r2(total_day_change),
            dayChangePercent=r2(day_change_pct),
            cashBalance=r2(cash_for_display),
            positionsCount=len(positions),
            lastSync=last_update_str,
            source="snaptrade",
            buyingPower=raw_buying_power,
            assetBreakdown={k: r2(v) for k, v in asset_breakdown.items()} if asset_breakdown else None,
            cryptoValue=r2(crypto_value) if crypto_value > 0 else None,
            cryptoPnl=r2(crypto_pnl) if crypto_value > 0 else None,
            connectionStatus=connection_status,
        )

        recon_meta = None
        if recon:
            recon_meta = ReconMeta(
                positions=recon_positions,
                cashRaw=r2(raw_cash),
                cashForTotal=r2(cash_for_total),
                totalEquityComputed=r2(total_equity),
                totalCostComputed=r2(total_cost),
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
    accountIdUsed: str | list[str] | None
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
            AND NOT EXISTS (
                SELECT 1 FROM accounts a
                WHERE a.id = p.account_id AND a.connection_status = 'deleted'
            )
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

        # Crypto-safe price routing (same pattern as GET /portfolio)
        crypto_syms = [s for s in symbols if s in _CRYPTO_SYMBOLS]
        equity_syms = [s for s in symbols if s not in _CRYPTO_SYMBOLS]

        prices_map = get_latest_closes_batch(equity_syms) if equity_syms else {}
        prev_closes_map = get_previous_closes_batch(equity_syms) if equity_syms else {}

        yf_quotes: dict = {}
        yf_needed = crypto_syms + [s for s in equity_syms if s not in prices_map]
        if yf_needed:
            try:
                yf_quotes = get_realtime_quotes_batch(yf_needed)
            except Exception as exc:
                logger.debug("yfinance batch quotes skipped: %s", exc)

        # Build mover items with crypto-aware day change
        items: list[dict] = []

        for rd in position_rows:
            symbol = rd["symbol"]
            qty = float(rd["quantity"] or 0)
            avg_cost = float(rd["average_cost"] or 0)
            is_crypto = symbol in _CRYPTO_SYMBOLS

            # Price cascade (crypto never uses Databento)
            snaptrade_price = float(rd.get("snaptrade_price") or 0)
            databento_price = prices_map.get(symbol) if not is_crypto else None
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

            # Day change — crypto vs equity (same guards as GET /portfolio)
            day_change = None
            day_change_pct = None

            if is_crypto:
                if yf_quote and yf_quote.get("dayChangePct") is not None:
                    day_change_pct = yf_quote["dayChangePct"]
                    day_change = qty * current_price * (day_change_pct / 100)
            else:
                prev_close = prev_closes_map.get(symbol)
                if not prev_close and yf_quote:
                    prev_close = yf_quote.get("previousClose")
                if prev_close and prev_close > 0:
                    day_change_pct = ((current_price - prev_close) / prev_close) * 100
                    day_change = (current_price - prev_close) * qty
                    if abs(day_change_pct) > 300:
                        day_change_pct = None
                        day_change = None

            open_pnl_pct = ((current_price - avg_cost) / avg_cost * 100) if avg_cost > 0 else 0.0

            items.append({
                "symbol": symbol,
                "currentPrice": r2(current_price),
                "previousClose": r2n(prev_closes_map.get(symbol) or (yf_quote.get("previousClose") if yf_quote else None)),
                "dayChange": r2n(day_change),
                "dayChangePct": r2n(day_change_pct),
                "quantity": qty,
                "equity": r2(equity),
                "openPnlPct": r2(open_pnl_pct),
            })

        # Deduplicate by symbol (keep entry with highest absolute change)
        seen: dict[str, dict] = {}
        for i in items:
            sym = i["symbol"]
            if sym not in seen:
                seen[sym] = i
            else:
                existing_abs = abs(seen[sym].get("dayChangePct") or seen[sym]["openPnlPct"])
                new_abs = abs(i.get("dayChangePct") or i["openPnlPct"])
                if new_abs > existing_abs:
                    seen[sym] = i
        items = list(seen.values())

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

        # Exclude crypto symbols — Databento ohlcv_daily is equity-only
        equity_symbols = [s for s in symbols if s not in _CRYPTO_SYMBOLS]
        if not equity_symbols:
            return SparklineResponse(sparklines=[], period=period.upper())

        # Single query for equity symbols' close prices
        rows = execute_sql(
            """
            SELECT symbol, date, close
            FROM ohlcv_daily
            WHERE symbol = ANY(:symbols)
              AND date >= :start_date
              AND date <= :end_date
            ORDER BY symbol, date ASC
            """,
            params={"symbols": equity_symbols, "start_date": str(start_date), "end_date": str(end_date)},
            fetch_results=True,
        )

        # Group by symbol
        grouped: dict[str, list[tuple[str, float]]] = defaultdict(list)
        for row in rows or []:
            rd: dict[str, Any] = dict(row._mapping) if hasattr(row, "_mapping") else dict(row)
            grouped[rd["symbol"]].append((str(rd["date"]), float(rd["close"])))

        sparklines = []
        for sym in equity_symbols:
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
