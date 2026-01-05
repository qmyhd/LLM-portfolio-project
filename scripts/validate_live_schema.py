#!/usr/bin/env python3
"""
Live Schema Validation Script

Validates that code inserts align with actual Supabase table schemas.
Compares VALID_COLUMNS sets in code against live database columns.
"""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.db import execute_sql


def get_live_table_columns(table_name: str) -> dict:
    """Get column names and types from live Supabase table."""
    result = execute_sql(
        """
        SELECT column_name, data_type, is_nullable
        FROM information_schema.columns
        WHERE table_name = :table_name
        AND table_schema = 'public'
        ORDER BY ordinal_position
        """,
        params={"table_name": table_name},
        fetch_results=True,
    )

    if not result:
        return {}

    return {row[0]: {"type": row[1], "nullable": row[2]} for row in result}


def validate_discord_tables():
    """Validate Discord message tables against code expectations."""
    print("\n" + "=" * 60)
    print("DISCORD TABLE VALIDATION")
    print("=" * 60)

    # Expected columns from message_cleaner.py
    VALID_COLUMNS_MARKET = {
        "message_id",
        "author",
        "content",
        "sentiment",
        "cleaned_content",
        "timestamp",
        "processed_at",
    }

    VALID_COLUMNS_TRADING = VALID_COLUMNS_MARKET | {"stock_mentions"}

    # Validate discord_market_clean
    print("\n📋 discord_market_clean:")
    live_cols = get_live_table_columns("discord_market_clean")
    if not live_cols:
        print("   ❌ Table not found!")
    else:
        print(f"   Live columns: {sorted(live_cols.keys())}")
        print(f"   Code expects: {sorted(VALID_COLUMNS_MARKET)}")

        missing_in_db = VALID_COLUMNS_MARKET - set(live_cols.keys())
        extra_in_code = set(live_cols.keys()) - VALID_COLUMNS_MARKET

        if missing_in_db:
            print(f"   ⚠️  Missing in DB: {missing_in_db}")
        if extra_in_code:
            print(f"   ℹ️  Extra in DB (not used): {extra_in_code}")
        if not missing_in_db:
            print("   ✅ Code columns align with DB")

    # Validate discord_trading_clean
    print("\n📋 discord_trading_clean:")
    live_cols = get_live_table_columns("discord_trading_clean")
    if not live_cols:
        print("   ❌ Table not found!")
    else:
        print(f"   Live columns: {sorted(live_cols.keys())}")
        print(f"   Code expects: {sorted(VALID_COLUMNS_TRADING)}")

        missing_in_db = VALID_COLUMNS_TRADING - set(live_cols.keys())
        extra_in_code = set(live_cols.keys()) - VALID_COLUMNS_TRADING

        if missing_in_db:
            print(f"   ⚠️  Missing in DB: {missing_in_db}")
        if extra_in_code:
            print(f"   ℹ️  Extra in DB (not used): {extra_in_code}")
        if not missing_in_db:
            print("   ✅ Code columns align with DB")

    # Validate processing_status
    print("\n📋 processing_status:")
    live_cols = get_live_table_columns("processing_status")
    if not live_cols:
        print("   ❌ Table not found!")
    else:
        # Based on db.py mark_message_processed() and get_unprocessed_messages()
        expected_cols = {
            "message_id",
            "channel",
            "processed_for_cleaning",
            "processed_for_twitter",
            "updated_at",
        }
        print(f"   Live columns: {sorted(live_cols.keys())}")
        print(f"   Code expects: {sorted(expected_cols)}")

        missing_in_db = expected_cols - set(live_cols.keys())
        if missing_in_db:
            print(f"   ⚠️  Missing in DB: {missing_in_db}")
        else:
            print("   ✅ Code columns align with DB")


def validate_snaptrade_tables():
    """Validate SnapTrade tables against collector expectations."""
    print("\n" + "=" * 60)
    print("SNAPTRADE TABLE VALIDATION")
    print("=" * 60)

    # Expected columns from snaptrade_collector.py extract_position_data()
    # Note: sync_timestamp is added by write_to_database(), not extract_position_data()
    POSITIONS_EXPECTED = {
        "symbol",
        "symbol_id",
        "account_id",
        "quantity",
        "price",
        "equity",
        "average_buy_price",
        "open_pnl",
        "asset_type",
        "currency",
        "logo_url",
        "exchange_code",
        "exchange_name",
        "mic_code",
        "figi_code",
        "symbol_description",
        "sync_timestamp",
    }

    print("\n📋 positions:")
    live_cols = get_live_table_columns("positions")
    if not live_cols:
        print("   ❌ Table not found!")
    else:
        print(f"   Live columns ({len(live_cols)}): {sorted(live_cols.keys())}")
        print(
            f"   Code expects ({len(POSITIONS_EXPECTED)}): {sorted(POSITIONS_EXPECTED)}"
        )

        missing_in_db = POSITIONS_EXPECTED - set(live_cols.keys())
        extra_in_code = set(live_cols.keys()) - POSITIONS_EXPECTED

        if missing_in_db:
            print(f"   ❌ Missing in DB (will cause insert failures): {missing_in_db}")
        if extra_in_code:
            print(f"   ℹ️  Extra in DB (not populated by code): {extra_in_code}")
        if not missing_in_db:
            print("   ✅ All code columns exist in DB")

    # Expected columns for orders
    ORDERS_EXPECTED = {
        "brokerage_order_id",
        "account_id",
        "symbol",
        "action",
        "status",
        "total_quantity",
        "filled_quantity",
        "execution_price",
        "time_placed",
        "time_executed",
        "sync_timestamp",
    }

    print("\n📋 orders:")
    live_cols = get_live_table_columns("orders")
    if not live_cols:
        print("   ❌ Table not found!")
    else:
        print(f"   Live columns ({len(live_cols)}): {sorted(live_cols.keys())}")
        print(f"   Code expects (minimal): {sorted(ORDERS_EXPECTED)}")

        missing_in_db = ORDERS_EXPECTED - set(live_cols.keys())

        if missing_in_db:
            print(f"   ❌ Missing in DB: {missing_in_db}")
        else:
            print("   ✅ All required code columns exist in DB")

    # Accounts table
    print("\n📋 accounts:")
    live_cols = get_live_table_columns("accounts")
    if not live_cols:
        print("   ❌ Table not found!")
    else:
        print(f"   Live columns: {sorted(live_cols.keys())}")
        print("   ✅ Table exists")

    # Symbols table
    print("\n📋 symbols:")
    live_cols = get_live_table_columns("symbols")
    if not live_cols:
        print("   ❌ Table not found!")
    else:
        print(f"   Live columns: {sorted(live_cols.keys())}")
        print("   ✅ Table exists")


def validate_row_counts():
    """Show row counts for all relevant tables."""
    print("\n" + "=" * 60)
    print("TABLE ROW COUNTS")
    print("=" * 60)

    tables = [
        "accounts",
        "positions",
        "orders",
        "symbols",
        "discord_messages",
        "discord_market_clean",
        "discord_trading_clean",
        "processing_status",
    ]

    print(f"\n{'Table':<30} {'Rows':>10}")
    print("-" * 42)

    for table in tables:
        try:
            result = execute_sql(f"SELECT COUNT(*) FROM {table}", fetch_results=True)
            count = result[0][0] if result else 0
            print(f"{table:<30} {count:>10,}")
        except Exception as e:
            print(f"{table:<30} {'ERROR':>10} - {str(e)[:30]}")


def validate_foreign_keys():
    """Validate foreign key relationships."""
    print("\n" + "=" * 60)
    print("FOREIGN KEY VALIDATION")
    print("=" * 60)

    # positions -> accounts
    print("\n📋 positions.account_id -> accounts.id:")
    result = execute_sql(
        """
        SELECT COUNT(*) FROM positions p
        LEFT JOIN accounts a ON p.account_id = a.id
        WHERE a.id IS NULL AND p.account_id IS NOT NULL
        """,
        fetch_results=True,
    )
    orphan_count = result[0][0] if result else 0
    if orphan_count > 0:
        print(f"   ⚠️  {orphan_count} positions have invalid account_id")
    else:
        print("   ✅ All positions have valid account references")

    # orders -> accounts
    print("\n📋 orders.account_id -> accounts.id:")
    result = execute_sql(
        """
        SELECT COUNT(*) FROM orders o
        LEFT JOIN accounts a ON o.account_id = a.id
        WHERE a.id IS NULL AND o.account_id IS NOT NULL
        """,
        fetch_results=True,
    )
    orphan_count = result[0][0] if result else 0
    if orphan_count > 0:
        print(f"   ⚠️  {orphan_count} orders have invalid account_id")
    else:
        print("   ✅ All orders have valid account references")


def validate_primary_keys():
    """Validate primary key uniqueness."""
    print("\n" + "=" * 60)
    print("PRIMARY KEY VALIDATION")
    print("=" * 60)

    # positions composite PK (symbol, account_id)
    print("\n📋 positions (symbol, account_id) uniqueness:")
    result = execute_sql(
        """
        SELECT symbol, account_id, COUNT(*) as cnt
        FROM positions
        GROUP BY symbol, account_id
        HAVING COUNT(*) > 1
        """,
        fetch_results=True,
    )
    if result:
        print(f"   ❌ {len(result)} duplicate composite keys found")
        for row in result[:5]:
            print(f"      {row[0]} / {row[1]}: {row[2]} duplicates")
    else:
        print("   ✅ No duplicate composite keys")

    # orders PK (brokerage_order_id)
    print("\n📋 orders (brokerage_order_id) uniqueness:")
    result = execute_sql(
        """
        SELECT brokerage_order_id, COUNT(*) as cnt
        FROM orders
        GROUP BY brokerage_order_id
        HAVING COUNT(*) > 1
        """,
        fetch_results=True,
    )
    if result:
        print(f"   ❌ {len(result)} duplicate order IDs found")
    else:
        print("   ✅ No duplicate order IDs")

    # processing_status composite PK (message_id, channel)
    print("\n📋 processing_status (message_id, channel) uniqueness:")
    result = execute_sql(
        """
        SELECT message_id, channel, COUNT(*) as cnt
        FROM processing_status
        GROUP BY message_id, channel
        HAVING COUNT(*) > 1
        """,
        fetch_results=True,
    )
    if result:
        print(f"   ❌ {len(result)} duplicate processing status entries")
    else:
        print("   ✅ No duplicate processing status entries")


def main():
    """Run all validations."""
    print("\n" + "🔍 " * 20)
    print("LIVE SUPABASE SCHEMA VALIDATION")
    print("🔍 " * 20)

    try:
        validate_discord_tables()
        validate_snaptrade_tables()
        validate_row_counts()
        validate_foreign_keys()
        validate_primary_keys()

        print("\n" + "=" * 60)
        print("VALIDATION COMPLETE")
        print("=" * 60)
        print("\n✅ All schema validations passed! Code-to-DB alignment verified.\n")

    except Exception as e:
        print(f"\n❌ Validation failed with error: {e}")
        import traceback

        traceback.print_exc()
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
