"""Per-(symbol, bucket) actual-trade track record.

Reuses the trade-assembly helpers in app.routes.trades (merge/dedup +
historical-basis walk) and adds aggregate metrics (win rate, avg hold,
realized return, current position). Bucket is attributed via the live
accounts.bucket join; orphan account_ids fold into 'other' via COALESCE.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.routes.trades import _compute_historical_basis, _merge_and_dedup, _row_to_dict
from src.db import execute_sql

_HIST_LIMIT = 5000


def _parse_dt(v: Any) -> datetime | None:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None


def compute_stock_track_record(symbol: str, bucket: str | None) -> dict[str, Any]:
    """Aggregate realized-trade metrics for one symbol, optionally bucket-scoped.

    `bucket` must already be validated (output of validate_bucket) or None.
    """
    sym = symbol.strip().upper()
    # COALESCE keeps orphan account_id rows under 'other'; bucket_filter_sql's
    # plain clause would exclude them. We inline the COALESCE form here.
    if bucket:
        bclause = " AND COALESCE(acc.bucket, 'other') = :bucket "
        bparams = {"bucket": bucket}
    else:
        bclause, bparams = "", {}

    activities = execute_sql(
        f"""
        SELECT a.id, a.symbol, UPPER(a.activity_type) AS side, a.price, a.units,
               COALESCE(a.amount, 0) AS amount, COALESCE(a.fee, 0) AS fee,
               a.trade_date AS executed_at, a.description
        FROM activities a
        LEFT JOIN accounts acc ON acc.id = a.account_id
        WHERE UPPER(a.symbol) = :symbol
          AND COALESCE(acc.connection_status, 'connected') != 'deleted'
          {bclause}
        ORDER BY a.trade_date DESC
        LIMIT :lim
        """,
        params={"symbol": sym, "lim": _HIST_LIMIT, **bparams},
        fetch_results=True,
    ) or []
    orders = execute_sql(
        f"""
        SELECT o.brokerage_order_id AS id, o.symbol, UPPER(o.action) AS side,
               o.execution_price AS price, o.filled_quantity AS units,
               COALESCE(o.execution_price * o.filled_quantity, 0) AS amount,
               0 AS fee, o.time_executed AS executed_at, NULL AS description
        FROM orders o
        LEFT JOIN accounts acc ON acc.id = o.account_id
        WHERE UPPER(o.symbol) = :symbol
          AND o.status IN ('EXECUTED', 'FILLED') AND o.time_executed IS NOT NULL
          AND COALESCE(acc.connection_status, 'connected') != 'deleted'
          {bclause}
        ORDER BY o.time_executed DESC
        LIMIT :lim
        """,
        params={"symbol": sym, "lim": _HIST_LIMIT, **bparams},
        fetch_results=True,
    ) or []

    acts = [{**_row_to_dict(r), "source": "activity"} for r in activities]
    ords = [{**_row_to_dict(r), "source": "order"} for r in orders]
    merged = _merge_and_dedup(acts, ords)
    _compute_historical_basis(merged)

    # Aggregate realized P/L over SELLs that have a basis.
    realized_pcts: list[float] = []
    wins = 0
    holds: list[int] = []
    buy_dates = sorted(
        d for d in (
            _parse_dt(t.get("executed_at"))
            for t in merged
            if (t.get("side") or "").upper() == "BUY"
        ) if d
    )
    first_buy = buy_dates[0] if buy_dates else None

    for t in merged:
        side = (t.get("side") or "").upper()
        basis = t.get("basis_at_trade")
        price = t.get("price")
        if side == "SELL" and basis and price and basis > 0:
            ratio = price / basis
            if 0.1 <= ratio <= 10:  # same split guardrail as _enrich_trade
                pct = (price - basis) / basis * 100
                realized_pcts.append(pct)
                if pct >= 0:
                    wins += 1
                sell_dt = _parse_dt(t.get("executed_at"))
                if sell_dt and first_buy:
                    holds.append((sell_dt - first_buy).days)

    dates = [d for d in (_parse_dt(t.get("executed_at")) for t in merged) if d]
    realized_pnl_pct = round(sum(realized_pcts) / len(realized_pcts), 2) if realized_pcts else 0.0
    win_rate = round(wins / len(realized_pcts) * 100, 1) if realized_pcts else 0.0

    # Current position (bucket-scoped), for currentQty + weight.
    pos = execute_sql(
        f"""
        SELECT SUM(p.quantity) AS qty,
               SUM(p.quantity * COALESCE(p.current_price, p.price)) AS value
        FROM positions p
        LEFT JOIN accounts acc ON acc.id = p.account_id
        WHERE UPPER(p.symbol) = :symbol AND p.quantity > 0
          AND COALESCE(acc.connection_status, 'connected') != 'deleted'
          {bclause}
        """,
        params={"symbol": sym, **bparams},
        fetch_results=True,
    ) or []
    total = execute_sql(
        f"""
        SELECT SUM(p.quantity * COALESCE(p.current_price, p.price)) AS total
        FROM positions p
        LEFT JOIN accounts acc ON acc.id = p.account_id
        WHERE p.quantity > 0
          AND COALESCE(acc.connection_status, 'connected') != 'deleted'
          {bclause}
        """,
        params=bparams or None,
        fetch_results=True,
    ) or []

    pos_d = _row_to_dict(pos[0]) if pos else {}
    cur_qty = float(pos_d.get("qty") or 0)
    cur_value = float(pos_d.get("value") or 0)
    total_value = float(_row_to_dict(total[0]).get("total") or 0) if total else 0.0
    weight = round(cur_value / total_value * 100, 2) if total_value > 0 else 0.0

    return {
        "symbol": sym,
        "bucket": bucket or "all",
        "tradeCount": len(merged),
        "realizedPnlPct": realized_pnl_pct,
        "winRate": win_rate,
        "avgHoldDays": round(sum(holds) / len(holds)) if holds else 0,
        "best": round(max(realized_pcts), 2) if realized_pcts else 0.0,
        "worst": round(min(realized_pcts), 2) if realized_pcts else 0.0,
        "currentQty": cur_qty,
        "currentWeightPct": weight,
        "firstTradeDate": min(dates).isoformat() if dates else None,
        "lastTradeDate": max(dates).isoformat() if dates else None,
    }
