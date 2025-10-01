#!/usr/bin/env python3
"""
Test script to validate timestamp field migration.
Runs before and after the migration to ensure data integrity.
"""
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd

# Add the src directory to the path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from src.db import get_sync_engine
from sqlalchemy import text

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def test_timestamp_field_queries():
    """Test queries that would break with text timestamps."""
    engine = get_sync_engine()

    test_queries = [
        {
            "name": "positions_sync_timestamp_max",
            "query": "SELECT MAX(sync_timestamp) as latest_sync FROM positions WHERE sync_timestamp IS NOT NULL",
            "description": "Find latest position sync timestamp",
        },
        {
            "name": "accounts_sync_ordering",
            "query": "SELECT id, sync_timestamp FROM accounts ORDER BY sync_timestamp DESC LIMIT 5",
            "description": "Order accounts by sync timestamp (desc)",
        },
        {
            "name": "daily_prices_date_range",
            "query": "SELECT symbol, date FROM daily_prices WHERE date >= '2024-01-01' ORDER BY date DESC LIMIT 10",
            "description": "Get recent daily prices with date filtering",
        },
        {
            "name": "realtime_prices_timestamp_filtering",
            "query": "SELECT symbol, timestamp, price FROM realtime_prices WHERE timestamp >= NOW() - INTERVAL '1 day' ORDER BY timestamp DESC LIMIT 10",
            "description": "Get realtime prices from last day",
        },
        {
            "name": "account_balances_snapshot_grouping",
            "query": "SELECT snapshot_date, COUNT(*) as balance_count FROM account_balances GROUP BY snapshot_date ORDER BY snapshot_date DESC LIMIT 10",
            "description": "Group account balances by snapshot date",
        },
        {
            "name": "twitter_data_date_comparison",
            "query": "SELECT message_id, discord_date, tweet_date FROM twitter_data WHERE discord_date > tweet_date LIMIT 5",
            "description": "Compare Discord and tweet dates",
        },
    ]

    results = {}

    with engine.connect() as conn:
        for test in test_queries:
            try:
                logger.info(f"Running test: {test['name']}")
                result = conn.execute(text(test["query"]))
                rows = result.fetchall()
                results[test["name"]] = {
                    "success": True,
                    "row_count": len(rows),
                    "sample_rows": [dict(row._mapping) for row in rows[:3]],
                    "description": test["description"],
                }
                logger.info(f"  ✅ Success: {len(rows)} rows returned")
            except Exception as e:
                results[test["name"]] = {
                    "success": False,
                    "error": str(e),
                    "description": test["description"],
                }
                logger.error(f"  ❌ Failed: {e}")

    return results


def check_data_types():
    """Check the data types of timestamp columns."""
    engine = get_sync_engine()

    timestamp_columns = [
        ("positions", "sync_timestamp"),
        ("accounts", "sync_timestamp"),
        ("accounts", "last_successful_sync"),
        ("account_balances", "sync_timestamp"),
        ("account_balances", "snapshot_date"),
        ("daily_prices", "date"),
        ("realtime_prices", "timestamp"),
        ("stock_metrics", "date"),
        ("discord_processing_log", "processed_date"),
        ("twitter_data", "discord_date"),
        ("twitter_data", "tweet_date"),
        ("twitter_data", "discord_sent_date"),
        ("twitter_data", "tweet_created_date"),
    ]

    type_results = {}

    with engine.connect() as conn:
        for table, column in timestamp_columns:
            try:
                query = text(
                    """
                    SELECT data_type, is_nullable
                    FROM information_schema.columns 
                    WHERE table_name = :table_name 
                    AND column_name = :column_name
                    AND table_schema = 'public'
                """
                )
                result = conn.execute(
                    query, {"table_name": table, "column_name": column}
                )
                row = result.fetchone()

                if row:
                    type_results[f"{table}.{column}"] = {
                        "data_type": row.data_type,
                        "is_nullable": row.is_nullable,
                        "exists": True,
                    }
                else:
                    type_results[f"{table}.{column}"] = {"exists": False}
            except Exception as e:
                type_results[f"{table}.{column}"] = {"error": str(e), "exists": False}

    return type_results


def validate_data_integrity():
    """Validate that timestamp fields have proper types after migration."""
    engine = get_sync_engine()

    conversion_tests = [
        {
            "name": "positions_timestamp_types",
            "query": """
                SELECT 
                    COUNT(*) as total_rows,
                    COUNT(CASE WHEN sync_timestamp IS NOT NULL THEN 1 END) as non_null_timestamps
                FROM positions
            """,
            "description": "Check position timestamp field after migration",
        },
        {
            "name": "daily_prices_date_types",
            "query": """
                SELECT 
                    COUNT(*) as total_rows,
                    COUNT(CASE WHEN date IS NOT NULL THEN 1 END) as non_null_dates
                FROM daily_prices
            """,
            "description": "Check daily prices date field after migration",
        },
        {
            "name": "timestamp_operations_work",
            "query": """
                SELECT 
                    NOW() as current_time,
                    NOW()::date as current_date,
                    (NOW() - INTERVAL '1 day') as yesterday
            """,
            "description": "Test that timestamp operations work correctly",
        },
    ]

    integrity_results = {}

    with engine.connect() as conn:
        for test in conversion_tests:
            try:
                result = conn.execute(text(test["query"]))
                row = result.fetchone()
                if row:
                    integrity_results[test["name"]] = {
                        "success": True,
                        "results": dict(row._mapping),
                        "description": test["description"],
                    }
                else:
                    integrity_results[test["name"]] = {
                        "success": False,
                        "error": "No data returned",
                        "description": test["description"],
                    }
            except Exception as e:
                integrity_results[test["name"]] = {
                    "success": False,
                    "error": str(e),
                    "description": test["description"],
                }

    return integrity_results


def main():
    """Run all validation tests."""
    logger.info("🔍 Starting timestamp field validation...")

    logger.info("\n📊 Testing timestamp field queries...")
    query_results = test_timestamp_field_queries()

    logger.info("\n🔧 Checking data types...")
    type_results = check_data_types()

    logger.info("\n✅ Validating data integrity...")
    integrity_results = validate_data_integrity()

    # Print summary
    logger.info("\n" + "=" * 60)
    logger.info("VALIDATION SUMMARY")
    logger.info("=" * 60)

    logger.info("\n🔍 Query Test Results:")
    for test_name, result in query_results.items():
        status = "✅ PASS" if result["success"] else "❌ FAIL"
        logger.info(f"  {status} {test_name}")
        if not result["success"]:
            logger.info(f"    Error: {result['error']}")

    logger.info("\n🔧 Data Type Results:")
    for field, result in type_results.items():
        if result.get("exists", False):
            data_type = result.get("data_type", "unknown")
            nullable = result.get("is_nullable", "unknown")
            logger.info(f"  {field}: {data_type} (nullable: {nullable})")
        else:
            logger.info(f"  {field}: NOT FOUND")

    logger.info("\n✅ Data Integrity Results:")
    for test_name, result in integrity_results.items():
        status = "✅ PASS" if result["success"] else "❌ FAIL"
        logger.info(f"  {status} {test_name}")
        if result["success"]:
            logger.info(f"    Results: {result['results']}")

    # Overall success status
    all_queries_pass = all(r["success"] for r in query_results.values())
    all_integrity_pass = all(r["success"] for r in integrity_results.values())

    if all_queries_pass and all_integrity_pass:
        logger.info("\n🎉 ALL VALIDATION TESTS PASSED!")
        return 0
    else:
        logger.info("\n❌ SOME VALIDATION TESTS FAILED!")
        return 1


if __name__ == "__main__":
    sys.exit(main())
