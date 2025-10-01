#!/usr/bin/env python3
"""
Simple Schema Compliance Test
Tests primary key order compliance against expected baseline + migration state

Usage: python scripts/test_pk_compliance.py
"""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

try:
    from db import execute_sql
except ImportError as e:
    print(f"❌ Cannot import database modules: {e}")
    print(f"Current working directory: {Path.cwd()}")
    print(f"Script location: {Path(__file__).parent}")
    sys.exit(1)

# Expected Primary Key Orders (from baseline + migrations analysis)
EXPECTED_PRIMARY_KEYS = {
    "accounts": ["id"],
    "account_balances": ["account_id", "currency_code", "snapshot_date"],
    "positions": ["symbol", "account_id"],
    "orders": ["brokerage_order_id"],
    "symbols": ["id"],
    "daily_prices": ["symbol", "date"],
    "realtime_prices": ["symbol", "timestamp"],
    "stock_metrics": [
        "date",
        "symbol",
    ],  # CRITICAL: Should be (date, symbol) per baseline + migration 015
    "discord_messages": ["message_id"],
    "discord_market_clean": ["message_id"],
    "discord_trading_clean": ["message_id"],
    "discord_processing_log": ["message_id", "channel"],
    "processing_status": ["message_id"],
    "twitter_data": ["tweet_id"],
    "chart_metadata": ["symbol", "period", "interval", "theme"],
    "schema_migrations": ["version"],
}


def test_primary_key_compliance():
    """Test that all primary key orders match expected baseline + migrations"""
    print("🔍 Testing Primary Key Compliance...")
    print("=" * 50)

    # Query to get actual PK column order
    query = """
    SELECT 
        tc.table_name,
        array_agg(kcu.column_name ORDER BY kcu.ordinal_position) as pk_columns
    FROM information_schema.table_constraints tc
    JOIN information_schema.key_column_usage kcu 
        ON tc.constraint_name = kcu.constraint_name
        AND tc.table_schema = kcu.table_schema
    WHERE tc.constraint_type = 'PRIMARY KEY' 
        AND tc.table_schema = 'public'
        AND tc.table_name NOT LIKE '%backup%'
    GROUP BY tc.table_name
    ORDER BY tc.table_name;
    """

    try:
        results = execute_sql(query, fetch_results=True)
        if not results:
            print("❌ No primary key data returned from database")
            return False

        # Convert results to dict
        live_pks = {}
        for row in results:
            if hasattr(row, "_asdict"):
                # Named tuple
                row_dict = row._asdict()
            elif isinstance(row, dict):
                row_dict = row
            else:
                # SQLAlchemy Row object - convert to dict
                row_dict = {col: getattr(row, col) for col in row.keys()}

            table_name = row_dict["table_name"]
            pk_columns = row_dict["pk_columns"]
            live_pks[table_name] = pk_columns

        print(f"✅ Found primary keys for {len(live_pks)} tables")

        # Test compliance
        errors = []
        for table, expected_pk in EXPECTED_PRIMARY_KEYS.items():
            if table not in live_pks:
                errors.append(f"❌ Table {table} missing primary key")
                continue

            live_pk = live_pks[table]
            if live_pk != expected_pk:
                errors.append(
                    f"❌ PK drift in {table}: expected {expected_pk}, got {live_pk}"
                )
            else:
                print(f"✅ {table}: PK order correct {live_pk}")

        # Check for unexpected tables
        unexpected_tables = set(live_pks.keys()) - set(EXPECTED_PRIMARY_KEYS.keys())
        if unexpected_tables:
            for table in unexpected_tables:
                print(f"⚠️  Unexpected table: {table} (PK: {live_pks[table]})")

        if errors:
            print("\n" + "=" * 50)
            print("❌ PRIMARY KEY COMPLIANCE FAILURES:")
            for error in errors:
                print(f"   {error}")
            return False
        else:
            print("\n✅ ALL PRIMARY KEYS COMPLY WITH BASELINE + MIGRATIONS")
            return True

    except Exception as e:
        print(f"❌ Database query failed: {e}")
        return False


def test_schema_design_rationale_removed():
    """Test that schema_design_rationale view has been removed"""
    print("\n🔍 Testing Schema Design Rationale View Removal...")

    query = """
    SELECT COUNT(*) as view_count
    FROM information_schema.views 
    WHERE table_schema = 'public' 
    AND table_name = 'schema_design_rationale';
    """

    try:
        results = execute_sql(query, fetch_results=True)

        # Simple approach - assume results is iterable and get first value
        count = 0
        try:
            if results:
                # Try to iterate over results
                for row in results:
                    if isinstance(row, dict):
                        count = row.get("view_count", 0)
                    elif hasattr(row, "_asdict"):
                        count = row._asdict().get("view_count", 0)
                    elif hasattr(row, "keys"):
                        # SQLAlchemy Row - get first column
                        count = row[0] if len(row.keys()) > 0 else 0
                    elif isinstance(row, (list, tuple)):
                        count = row[0] if len(row) > 0 else 0
                    break  # Just need first row
        except:
            count = 1  # Assume view exists if we can't determine

        if count == 0:
            print("✅ schema_design_rationale view successfully removed")
            return True
        else:
            print(f"❌ schema_design_rationale view still exists (count: {count})")
            print("   Run migration 018 to remove it")
            return False

    except Exception as e:
        print(f"❌ View check query failed: {e}")
        return False


def main():
    """Run all compliance tests"""
    print("🚀 Schema Compliance Test Suite")
    print("=" * 60)

    # Test 1: Primary Key Compliance
    pk_compliance = test_primary_key_compliance()

    # Test 2: Schema Design Rationale Removal
    view_compliance = test_schema_design_rationale_removed()

    # Overall result
    print("\n" + "=" * 60)
    if pk_compliance and view_compliance:
        print("🎉 ALL SCHEMA COMPLIANCE TESTS PASSED")
        print(
            "✅ Database schema fully complies with baseline + migration expectations"
        )
        return 0
    else:
        print("❌ SCHEMA COMPLIANCE FAILURES DETECTED")
        if not view_compliance:
            print("💡 Run migration 018 to fix drift issues")
        return 1


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
