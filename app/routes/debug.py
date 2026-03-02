"""
Debug API routes -- symbol trace and data lineage audit.

These endpoints are DISABLED by default and require DEBUG_ENDPOINTS=1 env var.
When enabled, they require the same API key auth as other endpoints.
"""

import logging
from typing import Any, Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel

from src.db import execute_sql
from src.market_data_service import (
    CRYPTO_IDENTITY,
    _CRYPTO_SYMBOLS,
    get_realtime_quotes_batch,
)
from src.price_service import get_latest_closes_batch

logger = logging.getLogger(__name__)
router = APIRouter()


class PriceResolution(BaseModel):
    databento_hit: bool
    databento_price: Optional[float] = None
    yfinance_symbol: Optional[str] = None
    yfinance_price: Optional[float] = None
    snaptrade_price: Optional[float] = None
    selected_source: str
    selected_price: float


class SymbolTraceResponse(BaseModel):
    symbol: str
    is_crypto: bool
    canonical_quote_symbol: Optional[str] = None
    tv_symbol: Optional[str] = None
    positions: list[dict[str, Any]]
    symbols_row: Optional[dict[str, Any]] = None
    recent_activities: list[dict[str, Any]]
    recent_orders: list[dict[str, Any]]
    price_resolution: PriceResolution


def _serialize_row(d: dict) -> dict:
    """Convert non-JSON-serializable values in a dict."""
    for k, v in d.items():
        if hasattr(v, "isoformat"):
            d[k] = v.isoformat()
        elif v is not None and not isinstance(v, (str, int, float, bool, list)):
            d[k] = str(v)
    return d


@router.get("/symbol-trace", response_model=SymbolTraceResponse)
async def symbol_trace(
    symbol: str = Query(..., description="Ticker symbol to trace"),
    account_id: Optional[str] = Query(None, description="Filter to specific account"),
):
    """Trace a symbol through the entire data pipeline for debugging."""
    symbol = symbol.upper().strip()
    is_crypto = symbol in _CRYPTO_SYMBOLS
    identity = CRYPTO_IDENTITY.get(symbol)

    # 1. Positions rows
    pos_query = "SELECT * FROM positions WHERE UPPER(symbol) = UPPER(:symbol)"
    pos_params: dict = {"symbol": symbol}
    if account_id:
        pos_query += " AND account_id = :account_id"
        pos_params["account_id"] = account_id
    positions_data = execute_sql(pos_query, params=pos_params, fetch_results=True)
    positions = [_serialize_row(dict(r._mapping)) for r in (positions_data or [])]

    # 2. Symbols table row
    sym_data = execute_sql(
        "SELECT * FROM symbols WHERE UPPER(ticker) = UPPER(:symbol) LIMIT 1",
        params={"symbol": symbol},
        fetch_results=True,
    )
    symbols_row = _serialize_row(dict(sym_data[0]._mapping)) if sym_data else None

    # 3. Recent activities
    act_data = execute_sql(
        "SELECT id, activity_type, trade_date, amount, price, units, symbol "
        "FROM activities WHERE UPPER(symbol) = UPPER(:symbol) "
        "ORDER BY trade_date DESC LIMIT 5",
        params={"symbol": symbol},
        fetch_results=True,
    )
    activities = [_serialize_row(dict(r._mapping)) for r in (act_data or [])]

    # 4. Recent orders
    ord_data = execute_sql(
        "SELECT brokerage_order_id, symbol, action, status, execution_price "
        "FROM orders WHERE UPPER(symbol) = UPPER(:symbol) "
        "ORDER BY time_placed DESC LIMIT 5",
        params={"symbol": symbol},
        fetch_results=True,
    )
    orders = [_serialize_row(dict(r._mapping)) for r in (ord_data or [])]

    # 5. Price resolution trace
    snaptrade_price = float(positions[0].get("price", 0)) if positions else 0.0

    # Check Databento (only for equity -- crypto should get nothing)
    if is_crypto:
        databento_price = None
    else:
        databento_map = get_latest_closes_batch([symbol])
        databento_price = databento_map.get(symbol)

    # Check yfinance
    yf_symbol = identity["quote_symbol"] if identity else symbol
    yf_map = get_realtime_quotes_batch([symbol])
    yf_price = yf_map[symbol]["price"] if symbol in yf_map else None

    # Determine selected source (same cascade as GET /portfolio)
    if not is_crypto and databento_price:
        selected_source = "databento"
        selected_price = float(databento_price)
    elif snaptrade_price > 0:
        selected_source = "snaptrade"
        selected_price = snaptrade_price
    elif yf_price:
        selected_source = "yfinance"
        selected_price = float(yf_price)
    else:
        selected_source = "none"
        selected_price = 0.0

    return SymbolTraceResponse(
        symbol=symbol,
        is_crypto=is_crypto,
        canonical_quote_symbol=identity["quote_symbol"] if identity else None,
        tv_symbol=identity["tv_symbol"] if identity else None,
        positions=positions,
        symbols_row=symbols_row,
        recent_activities=activities,
        recent_orders=orders,
        price_resolution=PriceResolution(
            databento_hit=databento_price is not None,
            databento_price=float(databento_price) if databento_price else None,
            yfinance_symbol=yf_symbol if is_crypto else None,
            yfinance_price=float(yf_price) if yf_price else None,
            snaptrade_price=snaptrade_price if snaptrade_price > 0 else None,
            selected_source=selected_source,
            selected_price=selected_price,
        ),
    )
