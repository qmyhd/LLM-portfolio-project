"""Quick smoke-test script: check ohlcv_daily contents."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.env_bootstrap import bootstrap_env  # noqa: E402

bootstrap_env()

from src.db import execute_sql  # noqa: E402


def main():
    rows = execute_sql(
        """
        SELECT symbol, MIN(date) AS mn, MAX(date) AS mx, COUNT(*) AS cnt
        FROM ohlcv_daily
        GROUP BY symbol
        ORDER BY cnt DESC
        LIMIT 20
        """,
        fetch_results=True,
    )

    if not rows:
        print("⚠️  ohlcv_daily is EMPTY — no bars to chart!")
        return

    print(f"{'symbol':<10} {'min_date':<12} {'max_date':<12} {'count':>6}")
    print("-" * 44)
    for row in rows:
        d = dict(row._mapping)
        print(f"{d['symbol']:<10} {str(d['mn']):<12} {str(d['mx']):<12} {d['cnt']:>6}")


def verify_tables_indexes():
    """Check that key tables and indexes exist in Supabase."""
    print("\n=== TABLE CHECK ===")
    tables = execute_sql(
        """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'public'
        ORDER BY table_name
        """,
        fetch_results=True,
    )
    table_names = [dict(r._mapping)["table_name"] for r in tables]
    print(f"Found {len(table_names)} public tables:")
    for t in table_names:
        print(f"  - {t}")

    # Check key tables we care about
    required = [
        "ohlcv_daily",
        "positions",
        "orders",
        "accounts",
        "account_balances",
        "discord_messages",
        "discord_parsed_ideas",
        "discord_trading_clean",
        "discord_market_clean",
        "twitter_data",
        "stock_profile_current",
        "stock_profile_history",
        "processing_status",
        "schema_migrations",
        "symbols",
        "symbol_aliases",
        "institutional_holdings",
    ]
    missing = [t for t in required if t not in table_names]
    if missing:
        print(f"\n⚠️  MISSING tables: {missing}")
    else:
        print(f"\n✅ All {len(required)} required tables present")

    print("\n=== INDEX CHECK (ohlcv_daily) ===")
    indexes = execute_sql(
        """
        SELECT indexname, indexdef
        FROM pg_indexes
        WHERE tablename = 'ohlcv_daily'
        ORDER BY indexname
        """,
        fetch_results=True,
    )
    if not indexes:
        print("⚠️  No indexes found for ohlcv_daily")
    else:
        for idx in indexes:
            d = dict(idx._mapping)
            print(f"  {d['indexname']}")
            print(f"    {d['indexdef']}")

    print("\n=== RLS POLICIES (ohlcv_daily) ===")
    rls = execute_sql(
        """
        SELECT polname, polcmd, polroles::text
        FROM pg_policy
        WHERE polrelid = 'ohlcv_daily'::regclass
        ORDER BY polname
        """,
        fetch_results=True,
    )
    if not rls:
        print("  No RLS policies (using service role key bypasses RLS)")
    else:
        for p in rls:
            d = dict(p._mapping)
            print(f"  {d['polname']} ({d['polcmd']})")

    print("\n=== TOTAL ROW COUNTS ===")
    count_sql = """
        SELECT 'ohlcv_daily' AS tbl, COUNT(*) AS cnt FROM ohlcv_daily
        UNION ALL SELECT 'positions', COUNT(*) FROM positions
        UNION ALL SELECT 'orders', COUNT(*) FROM orders
        UNION ALL SELECT 'discord_messages', COUNT(*) FROM discord_messages
        UNION ALL SELECT 'discord_parsed_ideas', COUNT(*) FROM discord_parsed_ideas
        ORDER BY tbl
    """
    counts = execute_sql(count_sql, fetch_results=True)
    for c in counts:
        d = dict(c._mapping)
        print(f"  {d['tbl']:<25} {d['cnt']:>8} rows")


if __name__ == "__main__":
    main()
    verify_tables_indexes()
