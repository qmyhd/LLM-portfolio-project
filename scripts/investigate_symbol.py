#!/usr/bin/env python3
"""
Symbol Investigation Tool — prints activity history, net units, and
cross-table presence for a given ticker.

Usage:
    python scripts/investigate_symbol.py --symbol AAPL
    python scripts/investigate_symbol.py --symbol AAPL --account c4caf1cc-...
    python scripts/investigate_symbol.py --symbol AAPL --limit 20
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow running from repo root
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.env_bootstrap import bootstrap_env  # noqa: E402

bootstrap_env()

from src.db import execute_sql  # noqa: E402


def _row_to_dict(row) -> dict:
    """Convert a SQLAlchemy Row to a plain dict."""
    if hasattr(row, "_mapping"):
        return dict(row._mapping)
    return dict(row)


def investigate(symbol: str, account_id: str | None = None, limit: int = 10) -> None:
    sym = symbol.upper().strip()
    acct_filter = ""
    params: dict = {"sym": sym}
    if account_id:
        acct_filter = " AND account_id = :acct"
        params["acct"] = account_id

    # ---- 1. Activities (last N) ---------------------------------------------
    print("=" * 70)
    print(f"  Symbol Investigation: {sym}")
    if account_id:
        print(f"  Account filter: {account_id[:12]}...")
    print("=" * 70)

    activities = execute_sql(
        f"""
        SELECT trade_date, activity_type, units, amount, price, description, account_id
        FROM activities
        WHERE symbol = :sym {acct_filter}
        ORDER BY trade_date DESC
        LIMIT :lim
        """,
        {**params, "lim": limit},
        fetch_results=True,
    )

    print(f"\n  Last {limit} activities:")
    if not activities:
        print("    (none found)")
    else:
        print(
            f"    {'Date':12s}  {'Type':10s}  {'Units':>10s}  "
            f"{'Amount':>12s}  {'Price':>10s}  Description"
        )
        print("    " + "-" * 80)
        for row in activities:
            d = _row_to_dict(row)
            trade_date = str(d.get("trade_date") or "")[:10]
            act_type = str(d.get("activity_type") or "")[:10]
            units = d.get("units")
            amount = d.get("amount")
            price = d.get("price")
            desc = str(d.get("description") or "")[:40]
            print(
                f"    {trade_date:12s}  {act_type:10s}  "
                f"{_fmt_num(units):>10s}  {_fmt_money(amount):>12s}  "
                f"{_fmt_money(price):>10s}  {desc}"
            )

    # ---- 2. Net units from activities ---------------------------------------
    net_rows = execute_sql(
        f"""
        SELECT
            COALESCE(SUM(units), 0) as net_units,
            MAX(trade_date) as last_trade,
            COUNT(*) as activity_count
        FROM activities
        WHERE symbol = :sym {acct_filter}
        """,
        params,
        fetch_results=True,
    )
    if net_rows:
        nd = _row_to_dict(net_rows[0])
        print(f"\n  Net units (from activities): {_fmt_num(nd.get('net_units'))}")
        print(f"  Last trade date:             {nd.get('last_trade') or '(none)'}")
        print(f"  Total activity count:        {nd.get('activity_count', 0)}")

    # ---- 3. Positions table -------------------------------------------------
    pos_rows = execute_sql(
        f"""
        SELECT symbol, quantity, average_buy_price, price, equity, open_pnl,
               account_id, sync_timestamp
        FROM positions
        WHERE symbol = :sym {acct_filter}
        """,
        params,
        fetch_results=True,
    )

    print(f"\n  Positions table ({len(pos_rows or [])} rows):")
    if not pos_rows:
        print("    (not found)")
    else:
        for row in pos_rows:
            pd = _row_to_dict(row)
            qty = float(pd.get("quantity") or 0)
            avg = float(pd.get("average_buy_price") or 0)
            price = float(pd.get("price") or 0)
            equity = float(pd.get("equity") or 0)
            pnl = float(pd.get("open_pnl") or 0)
            acct = str(pd.get("account_id") or "")[:12]
            synced = str(pd.get("sync_timestamp") or "")[:19]
            status = "ACTIVE" if qty > 0 else "ZEROED"
            print(
                f"    [{status}] qty={qty:,.4f}  avg=${avg:,.2f}  "
                f"price=${price:,.2f}  equity=${equity:,.2f}  "
                f"pnl=${pnl:,.2f}  acct={acct}...  sync={synced}"
            )

    # ---- 4. Orders table ----------------------------------------------------
    order_rows = execute_sql(
        f"""
        SELECT brokerage_order_id, action, order_type, status,
               filled_quantity, execution_price, time_placed, account_id
        FROM orders
        WHERE symbol = :sym {acct_filter}
        ORDER BY time_placed DESC
        LIMIT :lim
        """,
        {**params, "lim": limit},
        fetch_results=True,
    )

    print(f"\n  Orders table (last {limit}, {len(order_rows or [])} returned):")
    if not order_rows:
        print("    (none found)")
    else:
        print(
            f"    {'Date':12s}  {'Action':8s}  {'Type':8s}  "
            f"{'Status':10s}  {'Filled':>8s}  {'Price':>10s}"
        )
        print("    " + "-" * 70)
        for row in order_rows:
            od = _row_to_dict(row)
            print(
                f"    {str(od.get('time_placed') or '')[:10]:12s}  "
                f"{str(od.get('action') or ''):8s}  "
                f"{str(od.get('order_type') or ''):8s}  "
                f"{str(od.get('status') or ''):10s}  "
                f"{_fmt_num(od.get('filled_quantity')):>8s}  "
                f"{_fmt_money(od.get('execution_price')):>10s}"
            )

    # ---- 5. Summary ---------------------------------------------------------
    has_active_pos = any(
        float(_row_to_dict(r).get("quantity") or 0) > 0 for r in (pos_rows or [])
    )
    print("\n  " + "-" * 40)
    print(f"  Currently held (positions qty > 0): {has_active_pos}")
    print(f"  Has order history:                  {bool(order_rows)}")
    print(f"  Has activity history:               {bool(activities)}")
    print("=" * 70)


def _fmt_num(val) -> str:
    if val is None:
        return "-"
    return f"{float(val):,.4f}"


def _fmt_money(val) -> str:
    if val is None:
        return "-"
    return f"${float(val):,.2f}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Investigate a symbol across DB tables")
    parser.add_argument("--symbol", "-s", required=True, help="Ticker symbol (e.g. AAPL)")
    parser.add_argument("--account", "-a", default=None, help="Filter by account ID")
    parser.add_argument("--limit", "-n", type=int, default=10, help="Max rows per section")
    args = parser.parse_args()

    investigate(args.symbol, args.account, args.limit)


if __name__ == "__main__":
    main()
