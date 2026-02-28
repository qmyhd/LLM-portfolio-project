#!/usr/bin/env python3
"""
Validate SnapTrade data against Robinhood CSV reports.

Supports two CSV formats:
  1. Positions snapshot — columns: Instrument/Symbol, Quantity, Average Cost
  2. Activity/transaction history — columns: Activity Date, Instrument,
     Trans Code, Quantity, Price, Amount

When a transaction-history CSV is passed to --positions, the script
automatically detects it and derives net positions from Buy/Sell rows,
then compares against the database.

Usage:
    python scripts/validate_robinhood.py --positions path/to/positions_or_activity.csv
    python scripts/validate_robinhood.py --transactions path/to/activity.csv
    python scripts/validate_robinhood.py --positions pos.csv --transactions txn.csv
"""

import argparse
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.env_bootstrap import bootstrap_env  # noqa: E402

bootstrap_env()

import pandas as pd  # noqa: E402, I001

from src.db import execute_sql  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Common Robinhood column name variants
_SYMBOL_COLS = ["instrument", "symbol", "ticker", "name"]
_QTY_COLS = ["quantity", "shares", "qty"]
_COST_COLS = ["average cost", "average_cost", "avg cost", "avg_cost", "cost basis"]

# Trans codes that change stock share positions
_BUY_CODES = {"Buy", "BCXL"}
_SELL_CODES = {"Sell", "SCXL"}
# Codes that adjust shares but aren't buy/sell (splits, mergers, spinoffs, stock dividends)
_ADJUSTMENT_CODES = {"SPL", "MRGS", "SPR", "SXCH", "SDIV"}
# Options codes (tracked separately)
_OPTIONS_CODES = {"BTO", "STC", "OEXP", "OCA"}
# Cash-only codes (no position impact)
_CASH_CODES = {"CDIV", "MDIV", "ACH", "FUTSWP", "SLIP", "DTAX", "DFEE", "AFEE", "GOLD",
               "INT", "MINT", "GDBP", "GMPC", "DCF", "MISC", "NOA", "ACATI", "RTP", "ITRF"}

# Symbol equivalences: maps all known variants to a single canonical symbol.
# Robinhood appends "Q" for bankruptcy tickers; SnapTrade keeps the original.
_SYMBOL_ALIASES = {
    "IRBTQ": "IRBT",   # iRobot — Chapter 11 bankruptcy, delisted 2024
    "TWNPQ": "TWNP",   # bankruptcy ticker suffix
}
# Build bidirectional map (both directions resolve to the same canonical)
SYMBOL_MAP: dict[str, str] = {}
for _alias, _canonical in _SYMBOL_ALIASES.items():
    SYMBOL_MAP[_alias] = _canonical
    SYMBOL_MAP[_canonical] = _canonical

# Crypto symbols — expected to be absent from Robinhood stock CSV
CRYPTO_SYMBOLS = {"BTC", "ETH", "DOGE", "SOL", "AVAX", "PEPE", "XRP", "TRUMP", "SHIB"}

# Symbols confirmed sold/transferred — positive net in CSV but absent from DB is expected.
# Prevents these from showing as MISSING_IN_DB noise in validation output.
_KNOWN_SOLD = {
    "GME",    # GameStop — sold, SnapTrade correctly shows 0
    "MLGO",   # MicroAlgo — sold/delisted
    "SIRI",   # Sirius XM — sold pre-merger Sep 2024
}


def _find_col(df: pd.DataFrame, candidates: list[str]) -> str | None:
    """Find the first matching column name (case-insensitive)."""
    lower_map = {c.lower(): c for c in df.columns}
    for candidate in candidates:
        if candidate.lower() in lower_map:
            return lower_map[candidate.lower()]
    return None


def _is_activity_csv(df: pd.DataFrame) -> bool:
    """Detect whether a CSV is a Robinhood activity/transaction export."""
    cols_lower = {c.lower() for c in df.columns}
    return "trans code" in cols_lower and "activity date" in cols_lower


def _clean_qty(val) -> float | None:
    """Parse quantity, stripping trailing 'S' (short indicator) and handling NaN."""
    if pd.isna(val):
        return None
    s = str(val).strip().rstrip("S")
    try:
        return float(s)
    except ValueError:
        return None


def _clean_amount(val) -> float | None:
    """Parse dollar amounts like '$1,525.54' or '($8.10)'."""
    if pd.isna(val):
        return None
    s = str(val).strip()
    negative = s.startswith("(") and s.endswith(")")
    s = s.strip("()$").replace(",", "")
    try:
        amt = float(s)
        return -amt if negative else amt
    except ValueError:
        return None


def _normalize_symbol(sym: str) -> str:
    """Normalize a symbol for comparison."""
    sym = sym.strip().upper()
    return SYMBOL_MAP.get(sym, sym)


def _derive_positions_from_activity(df: pd.DataFrame) -> pd.DataFrame:
    """Derive net buy/sell positions from a Robinhood activity CSV.

    Returns a DataFrame with columns: symbol, net_bought, net_sold, net_shares,
    total_cost, avg_cost_approx, first_trade, last_trade, buy_count, sell_count.
    """
    tc_col = _find_col(df, ["trans code"])
    sym_col = _find_col(df, _SYMBOL_COLS)
    qty_col = _find_col(df, _QTY_COLS)
    amount_col = _find_col(df, ["amount"])
    date_col = _find_col(df, ["activity date"])

    records = []
    for _, row in df.iterrows():
        tc = str(row.get(tc_col, "")).strip()
        sym = str(row.get(sym_col, "")).strip().upper()
        if not sym or sym == "NAN" or not tc:
            continue

        qty = _clean_qty(row.get(qty_col))
        amount = _clean_amount(row.get(amount_col))
        date = str(row.get(date_col, "")).strip() if date_col else None

        if tc in _BUY_CODES and qty is not None:
            records.append({"symbol": sym, "side": "buy", "qty": qty, "amount": amount, "date": date})
        elif tc in _SELL_CODES and qty is not None:
            records.append({"symbol": sym, "side": "sell", "qty": qty, "amount": amount, "date": date})
        elif tc in _ADJUSTMENT_CODES and qty is not None:
            records.append({"symbol": sym, "side": "adj", "qty": qty, "amount": amount, "date": date})

    if not records:
        return pd.DataFrame()

    trades = pd.DataFrame(records)
    results = []
    for sym, grp in trades.groupby("symbol"):
        buys = grp[grp["side"] == "buy"]
        sells = grp[grp["side"] == "sell"]
        adjs = grp[grp["side"] == "adj"]

        net_bought = buys["qty"].sum() if not buys.empty else 0
        net_sold = sells["qty"].sum() if not sells.empty else 0
        adj_shares = adjs["qty"].sum() if not adjs.empty else 0

        # Buy amounts are negative in Robinhood CSV (cash outflow)
        total_buy_cost = abs(buys["amount"].dropna().sum()) if not buys.empty else 0
        avg_cost = round(total_buy_cost / net_bought, 4) if net_bought > 0 else 0

        results.append({
            "symbol": _normalize_symbol(sym),
            "net_bought": round(net_bought, 6),
            "net_sold": round(net_sold, 6),
            "adj_shares": round(adj_shares, 6),
            "net_shares": round(net_bought - net_sold + adj_shares, 6),
            "total_buy_cost": round(total_buy_cost, 2),
            "avg_cost_approx": avg_cost,
            "first_trade": grp["date"].min(),
            "last_trade": grp["date"].max(),
            "buy_count": len(buys),
            "sell_count": len(sells),
        })

    return pd.DataFrame(results).sort_values("symbol").reset_index(drop=True)


def validate_positions(csv_path: str) -> dict:
    """Compare Robinhood positions against database positions.

    Auto-detects whether the CSV is a positions snapshot or activity history.
    """
    rh = pd.read_csv(csv_path, on_bad_lines="skip")
    rh.columns = [c.strip() for c in rh.columns]

    if _is_activity_csv(rh):
        return _validate_positions_from_activity(rh)

    # Original positions-snapshot logic
    sym_col = _find_col(rh, _SYMBOL_COLS)
    qty_col = _find_col(rh, _QTY_COLS)
    cost_col = _find_col(rh, _COST_COLS)

    if not sym_col:
        logger.error("Could not find symbol column in CSV. Columns: %s", list(rh.columns))
        return {"error": "No symbol column found"}

    db_rows = execute_sql(
        "SELECT symbol, quantity, average_buy_price, price FROM positions WHERE quantity > 0",
        fetch_results=True,
    )
    db = pd.DataFrame([dict(r._mapping) for r in db_rows or []])

    mismatches = []
    matched = 0

    for _, rh_row in rh.iterrows():
        symbol = str(rh_row.get(sym_col, "")).strip().upper()
        if not symbol or symbol in ("NAN", ""):
            continue

        db_match = db[db["symbol"].str.upper() == _normalize_symbol(symbol)]

        if db_match.empty:
            mismatches.append({
                "symbol": symbol,
                "issue": "MISSING_IN_DB",
                "rh_qty": float(rh_row[qty_col]) if qty_col else None,
            })
            continue

        if qty_col:
            rh_qty = float(rh_row[qty_col])
            db_qty = float(db_match.iloc[0]["quantity"])
            if abs(db_qty - rh_qty) > 0.001:
                mismatches.append({
                    "symbol": symbol,
                    "issue": "QTY_MISMATCH",
                    "rh_qty": rh_qty,
                    "db_qty": db_qty,
                    "diff": round(db_qty - rh_qty, 4),
                })
                continue

        if cost_col:
            rh_cost = float(rh_row[cost_col]) if pd.notna(rh_row[cost_col]) else None
            db_cost = (
                float(db_match.iloc[0]["average_buy_price"])
                if db_match.iloc[0]["average_buy_price"]
                else None
            )
            if rh_cost and db_cost and abs(db_cost - rh_cost) > 0.01:
                mismatches.append({
                    "symbol": symbol,
                    "issue": "COST_MISMATCH",
                    "rh_cost": rh_cost,
                    "db_cost": db_cost,
                    "diff": round(db_cost - rh_cost, 2),
                })
                continue

        matched += 1

    rh_symbols = set(rh[sym_col].dropna().str.strip().str.upper())
    for _, db_row in db.iterrows():
        if db_row["symbol"].upper() not in rh_symbols:
            mismatches.append({
                "symbol": db_row["symbol"],
                "issue": "MISSING_IN_ROBINHOOD",
                "db_qty": float(db_row["quantity"]),
            })

    return {
        "total_rh": len(rh),
        "total_db": len(db),
        "matched": matched,
        "mismatches": mismatches,
    }


def _validate_positions_from_activity(rh: pd.DataFrame) -> dict:
    """Derive positions from activity CSV and compare against DB."""
    logger.info("Detected activity/transaction CSV — deriving positions from Buy/Sell history")

    derived = _derive_positions_from_activity(rh)

    db_rows = execute_sql(
        "SELECT symbol, quantity, average_buy_price, price FROM positions WHERE quantity > 0",
        fetch_results=True,
    )
    db = pd.DataFrame([dict(r._mapping) for r in db_rows or []])

    # Also fetch all symbols ever seen in positions (including qty=0)
    all_db_rows = execute_sql(
        "SELECT DISTINCT symbol FROM positions",
        fetch_results=True,
    )
    all_db_symbols = {str(r[0]).upper() for r in (all_db_rows or [])}

    mismatches = []
    matched = 0
    rh_symbols_seen = set()

    for _, rh_row in derived.iterrows():
        symbol = rh_row["symbol"]
        rh_symbols_seen.add(symbol.upper())

        # Match by normalized symbol (handles IRBTQ↔IRBT etc.)
        db_match = db[db["symbol"].apply(lambda s: _normalize_symbol(s.upper())) == symbol.upper()]

        # Skip symbols where Robinhood shows net_shares ≈ 0 (fully sold) and DB agrees
        if abs(rh_row["net_shares"]) < 0.001:
            if db_match.empty or float(db_match.iloc[0]["quantity"]) < 0.001:
                matched += 1
                continue
            # RH says fully sold but DB still has shares
            mismatches.append({
                "symbol": symbol,
                "issue": "DB_HAS_SHARES_BUT_RH_FULLY_SOLD",
                "rh_net": rh_row["net_shares"],
                "db_qty": float(db_match.iloc[0]["quantity"]),
                "rh_bought": rh_row["net_bought"],
                "rh_sold": rh_row["net_sold"],
            })
            continue

        # RH says positive shares remain
        if db_match.empty:
            # Skip symbols confirmed sold/transferred
            if symbol.upper() in _KNOWN_SOLD:
                matched += 1
                continue
            # Check if symbol exists at all (maybe qty=0 in DB)
            if symbol.upper() in all_db_symbols:
                mismatches.append({
                    "symbol": symbol,
                    "issue": "DB_QTY_ZERO_BUT_RH_POSITIVE",
                    "rh_net": rh_row["net_shares"],
                    "rh_bought": rh_row["net_bought"],
                    "rh_sold": rh_row["net_sold"],
                    "last_trade": rh_row["last_trade"],
                })
            else:
                mismatches.append({
                    "symbol": symbol,
                    "issue": "MISSING_IN_DB",
                    "rh_net": rh_row["net_shares"],
                    "rh_bought": rh_row["net_bought"],
                    "rh_sold": rh_row["net_sold"],
                    "rh_cost": rh_row["total_buy_cost"],
                    "last_trade": rh_row["last_trade"],
                })
            continue

        matched += 1

    # Check for DB positions not in Robinhood activity
    for _, db_row in db.iterrows():
        sym = db_row["symbol"].upper()
        normalized = _normalize_symbol(sym)
        if normalized not in rh_symbols_seen:
            if sym in CRYPTO_SYMBOLS:
                # Crypto is excluded from Robinhood stock CSV — skip
                continue
            mismatches.append({
                "symbol": db_row["symbol"],
                "issue": "MISSING_IN_ROBINHOOD",
                "db_qty": float(db_row["quantity"]),
            })

    # Summary statistics
    tc_col = _find_col(rh, ["trans code"])
    trans_codes = rh[tc_col].value_counts().to_dict() if tc_col else {}

    return {
        "mode": "activity_derived",
        "total_rh_rows": len(rh),
        "total_rh_symbols": len(derived),
        "total_db_positions": len(db),
        "matched": matched,
        "mismatches": mismatches,
        "rh_trans_code_breakdown": trans_codes,
        "derived_positions": derived.to_dict("records") if not derived.empty else [],
    }


def validate_transactions(csv_path: str) -> dict:
    """Compare Robinhood transactions CSV against database activities."""
    rh = pd.read_csv(csv_path, on_bad_lines="skip")
    rh.columns = [c.strip() for c in rh.columns]

    db_rows = execute_sql(
        "SELECT id, symbol, activity_type, trade_date, amount, units FROM activities ORDER BY trade_date",
        fetch_results=True,
    )
    db = pd.DataFrame([dict(r._mapping) for r in db_rows or []])

    rh_count = len(rh)
    db_count = len(db)
    coverage = round(db_count / max(rh_count, 1) * 100, 1)

    # Count by type in DB
    type_counts = {}
    if not db.empty and "activity_type" in db.columns:
        type_counts = db["activity_type"].value_counts().to_dict()

    # Count by trans code in Robinhood
    tc_col = _find_col(rh, ["trans code"])
    rh_type_counts = rh[tc_col].value_counts().to_dict() if tc_col else {}

    # Symbol-level comparison
    sym_col = _find_col(rh, _SYMBOL_COLS)
    rh_symbols = set(rh[sym_col].dropna().str.strip().str.upper()) if sym_col else set()
    db_symbols = set(db["symbol"].dropna().str.strip().str.upper()) if not db.empty else set()

    return {
        "rh_transaction_count": rh_count,
        "db_activity_count": db_count,
        "coverage_pct": coverage,
        "db_type_breakdown": type_counts,
        "rh_type_breakdown": rh_type_counts,
        "rh_only_symbols": sorted(rh_symbols - db_symbols),
        "db_only_symbols": sorted(db_symbols - rh_symbols),
        "shared_symbols": len(rh_symbols & db_symbols),
    }


def _print_position_results(result: dict) -> None:
    """Pretty-print position validation results."""
    if "error" in result:
        print(f"Error: {result['error']}")
        return

    if result.get("mode") == "activity_derived":
        print(f"  CSV rows:              {result['total_rh_rows']}")
        print(f"  Unique RH symbols:     {result['total_rh_symbols']}")
        print(f"  DB active positions:   {result['total_db_positions']}")
        print(f"  Matched:               {result['matched']}")
        print("\n  Trans code breakdown:")
        for tc, count in sorted(result["rh_trans_code_breakdown"].items(), key=lambda x: -x[1]):
            print(f"    {tc:8s} {count:>5d}")
    else:
        print(f"  Robinhood positions: {result['total_rh']}")
        print(f"  Database positions:  {result['total_db']}")
        print(f"  Matched:             {result['matched']}")

    mismatches = result.get("mismatches", [])
    if not mismatches:
        print("\n  All positions match!")
        return

    # Group mismatches by issue type
    by_type: dict[str, list] = {}
    for m in mismatches:
        by_type.setdefault(m["issue"], []).append(m)

    print(f"\n  Discrepancies ({len(mismatches)}):")

    for issue, items in sorted(by_type.items()):
        print(f"\n  --- {issue} ({len(items)}) ---")
        for m in sorted(items, key=lambda x: x["symbol"]):
            sym = m["symbol"]
            if issue == "MISSING_IN_DB":
                extra = f"net={m.get('rh_net', m.get('rh_qty', '?'))}"
                if m.get("rh_cost"):
                    extra += f", cost=${m['rh_cost']}"
                if m.get("last_trade"):
                    extra += f", last={m['last_trade']}"
                print(f"    {sym:8s} — {extra}")
            elif issue == "MISSING_IN_ROBINHOOD":
                print(f"    {sym:8s} — DB qty={m.get('db_qty')}")
            elif issue == "QTY_MISMATCH":
                print(f"    {sym:8s} — RH={m['rh_qty']}, DB={m['db_qty']} (diff={m['diff']})")
            elif issue == "COST_MISMATCH":
                print(f"    {sym:8s} — RH=${m['rh_cost']}, DB=${m['db_cost']} (diff=${m['diff']})")
            elif issue == "DB_HAS_SHARES_BUT_RH_FULLY_SOLD":
                print(f"    {sym:8s} — DB={m['db_qty']}, RH net={m['rh_net']} (bought={m['rh_bought']}, sold={m['rh_sold']})")
            elif issue == "DB_QTY_ZERO_BUT_RH_POSITIVE":
                print(f"    {sym:8s} — RH net={m['rh_net']} (bought={m['rh_bought']}, sold={m['rh_sold']}), last={m.get('last_trade')}")
            else:
                print(f"    {sym:8s} — {m}")


def main():
    parser = argparse.ArgumentParser(description="Validate SnapTrade data against Robinhood reports")
    parser.add_argument("--positions", help="Path to Robinhood positions or activity CSV")
    parser.add_argument("--transactions", help="Path to Robinhood activity/transactions CSV")
    args = parser.parse_args()

    if not args.positions and not args.transactions:
        parser.print_help()
        print("\nError: At least one of --positions or --transactions is required.")
        sys.exit(1)

    if args.positions:
        print("\n" + "=" * 60)
        print("  POSITION VALIDATION")
        print("=" * 60)
        result = validate_positions(args.positions)
        _print_position_results(result)

    if args.transactions:
        print("\n" + "=" * 60)
        print("  TRANSACTION VALIDATION")
        print("=" * 60)
        result = validate_transactions(args.transactions)
        print(f"  Robinhood transactions: {result['rh_transaction_count']}")
        print(f"  Database activities:    {result['db_activity_count']}")
        print(f"  Coverage:               {result['coverage_pct']}%")
        if result.get("rh_type_breakdown"):
            print("\n  Robinhood trans code breakdown:")
            for atype, count in sorted(result["rh_type_breakdown"].items(), key=lambda x: -x[1]):
                print(f"    {atype:8s} {count:>5d}")
        if result.get("db_type_breakdown"):
            print("\n  DB activity type breakdown:")
            for atype, count in sorted(result["db_type_breakdown"].items(), key=lambda x: -x[1]):
                print(f"    {atype:8s} {count:>5d}")
        if result.get("rh_only_symbols"):
            print(f"\n  Symbols in RH only ({len(result['rh_only_symbols'])}):")
            for sym in result["rh_only_symbols"]:
                print(f"    {sym}")
        if result.get("db_only_symbols"):
            print(f"\n  Symbols in DB only ({len(result['db_only_symbols'])}):")
            for sym in result["db_only_symbols"]:
                print(f"    {sym}")
        print(f"\n  Shared symbols: {result['shared_symbols']}")


if __name__ == "__main__":
    main()
