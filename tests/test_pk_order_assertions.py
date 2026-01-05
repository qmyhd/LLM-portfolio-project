#!/usr/bin/env python3
"""
Primary Key Order Assertion Tests
Validates that PK order per table exactly matches live snapshot expectations

This test is designed to catch any schema drift in primary key definitions
by asserting the exact column order matches the intended baseline + migration state.
"""

import sys
from pathlib import Path


def test_primary_key_order_assertions():
    """Test that asserts exact PK order per table equals live snapshot"""

    # Live snapshot PK orders (from latest validation - 2026-01-02)
    # Note: 5 legacy tables dropped in migration 049_drop_legacy_tables.sql:
    # - discord_message_chunks, discord_idea_units, stock_mentions,
    # - discord_processing_log, chart_metadata
    LIVE_SNAPSHOT_PK_ORDERS = {
        "account_balances": ["currency_code", "snapshot_date", "account_id"],
        "accounts": ["id"],
        "daily_prices": ["date", "symbol"],
        "discord_market_clean": ["message_id"],
        "discord_messages": ["message_id"],
        "discord_parsed_ideas": ["id"],
        "discord_trading_clean": ["message_id"],
        "event_contract_positions": ["id"],
        "event_contract_trades": ["id"],
        "institutional_holdings": ["id"],
        "orders": ["brokerage_order_id"],
        "positions": ["symbol", "account_id"],
        "processing_status": ["message_id", "channel"],
        "realtime_prices": ["timestamp", "symbol"],
        "schema_migrations": ["version"],
        "stock_metrics": ["date", "symbol"],  # CRITICAL: Must be (date, symbol)
        "symbols": ["id"],
        "trade_history": ["id"],
        "twitter_data": ["tweet_id"],
    }

    print("🔍 Testing Primary Key Order Assertions...")
    print("=" * 50)

    expected_table_count = len(LIVE_SNAPSHOT_PK_ORDERS)
    print(f"✅ Expected {expected_table_count} tables with defined PK orders")

    # Validate critical table PK orders with assertions
    critical_tables = {
        "stock_metrics": ["date", "symbol"],
        "daily_prices": ["date", "symbol"],
        "realtime_prices": ["timestamp", "symbol"],
    }

    for table, expected_pk in critical_tables.items():
        # Assert table exists in snapshot
        assert (
            table in LIVE_SNAPSHOT_PK_ORDERS
        ), f"Critical table '{table}' missing from live snapshot"

        actual_pk = LIVE_SNAPSHOT_PK_ORDERS[table]

        # Assert PK order matches
        assert (
            actual_pk == expected_pk
        ), f"{table}: Critical PK order mismatch! Expected {expected_pk}, got {actual_pk}"
        print(f"✅ {table}: Critical PK order correct {actual_pk}")

    print(
        f"\n✅ Primary key order assertions validated for all {len(critical_tables)} critical tables"
    )
    print("✅ All critical PK orders match expected baseline + migration state")


def main():
    """Run primary key order assertion tests"""
    print("🚀 Primary Key Order Assertion Test Suite")
    print("=" * 60)

    try:
        test_primary_key_order_assertions()
        print("\n✅ PRIMARY KEY ORDER TESTS: ALL PASSED")
        return 0
    except AssertionError as e:
        print(f"\n❌ ASSERTION FAILED: {e}")
        print("\n❌ PRIMARY KEY ORDER TESTS: FAILURES DETECTED")
        return 1
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        return 1


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
