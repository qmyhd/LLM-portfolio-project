#!/usr/bin/env python3
"""
Post-Migration Data Processing Validation
========================================

This script validates that your Supabase database is correctly set up
for data processing after running the schema migrations.
"""

import sys
from pathlib import Path
import logging

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from sqlalchemy import text as sql_text
from src.config import settings
from src.db import get_sync_engine, test_connection
from src.message_cleaner import get_table_name_for_channel_type, CHANNEL_TYPE_TO_TABLE

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def validate_database_connection():
    """Test basic database connectivity"""
    logger.info("🔌 Testing database connection...")

    try:
        connection_info = test_connection()
        if connection_info["status"] == "connected":
            logger.info(
                f"✅ Connected to {connection_info.get('database', 'database')}"
            )
            return True
        else:
            logger.error(
                f"❌ Connection failed: {connection_info.get('error', 'Unknown error')}"
            )
            return False
    except Exception as e:
        logger.error(f"❌ Connection test failed: {e}")
        return False


def validate_table_structure():
    """Verify all expected tables exist with correct structure"""
    logger.info("📋 Validating table structure...")

    expected_tables = [
        "discord_messages",
        "discord_market_clean",
        "discord_trading_clean",
        "schema_migrations",
        "orders",
        "accounts",
        "account_balances",
        "symbols",
    ]

    try:
        engine = get_sync_engine()
        with engine.connect() as conn:
            # Check table existence
            result = conn.execute(
                sql_text(
                    """
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_schema = 'public'
                ORDER BY table_name
            """
                )
            )
            existing_tables = [row[0] for row in result.fetchall()]

            missing_tables = []
            for table in expected_tables:
                if table in existing_tables:
                    logger.info(f"✅ {table}")
                else:
                    logger.error(f"❌ {table}")
                    missing_tables.append(table)

            if missing_tables:
                logger.error(f"Missing tables: {missing_tables}")
                return False

            # Check for old discord_general_clean table
            if "discord_general_clean" in existing_tables:
                logger.warning(
                    "⚠️  discord_general_clean table still exists - migration may be needed"
                )

            return True

    except Exception as e:
        logger.error(f"❌ Table structure validation failed: {e}")
        return False


def validate_channel_mapping():
    """Test the channel type to table mapping system"""
    logger.info("🗺️  Validating channel type mapping...")

    try:
        # Test all mappings
        for channel_type, expected_table in CHANNEL_TYPE_TO_TABLE.items():
            actual_table = get_table_name_for_channel_type(channel_type)
            if actual_table == expected_table:
                logger.info(f"✅ {channel_type} → {actual_table}")
            else:
                logger.error(
                    f"❌ {channel_type}: expected {expected_table}, got {actual_table}"
                )
                return False

        return True

    except Exception as e:
        logger.error(f"❌ Channel mapping validation failed: {e}")
        return False


def validate_unique_constraints():
    """Check that unique constraints exist on message_id columns"""
    logger.info("🔒 Validating unique constraints...")

    try:
        engine = get_sync_engine()
        with engine.connect() as conn:
            # Check for unique indexes on message_id
            result = conn.execute(
                sql_text(
                    """
                SELECT 
                    tablename,
                    indexname,
                    indexdef
                FROM pg_indexes 
                WHERE schemaname = 'public' 
                    AND tablename IN ('discord_market_clean', 'discord_trading_clean')
                    AND (indexdef LIKE '%UNIQUE%' AND indexdef LIKE '%message_id%')
                ORDER BY tablename
            """
                )
            )

            indexes = result.fetchall()

            expected_tables = ["discord_market_clean", "discord_trading_clean"]
            found_tables = {row[0] for row in indexes}

            for table in expected_tables:
                if table in found_tables:
                    logger.info(f"✅ {table} has unique message_id constraint")
                else:
                    logger.warning(f"⚠️  {table} missing unique message_id constraint")

            return len(found_tables) >= 2

    except Exception as e:
        logger.error(f"❌ Unique constraint validation failed: {e}")
        return False


def main():
    """Run all validation checks"""
    logger.info("🔍 Starting post-migration validation...")

    checks = [
        ("Database Connection", validate_database_connection),
        ("Table Structure", validate_table_structure),
        ("Channel Mapping", validate_channel_mapping),
        ("Unique Constraints", validate_unique_constraints),
    ]

    passed = 0
    total = len(checks)

    for check_name, check_func in checks:
        logger.info(f"\n{'='*20} {check_name} {'='*20}")
        if check_func():
            passed += 1

    logger.info(f"\n🏁 Validation Results: {passed}/{total} checks passed")

    if passed == total:
        logger.info(
            "✅ All validations passed! Your database is ready for data processing."
        )
        logger.info("\nNext steps:")
        logger.info("1. Run bootstrap for automated setup: python scripts/bootstrap.py")
        logger.info("2. Generate journal: python generate_journal.py --force")
        return 0
    else:
        logger.error("❌ Some validations failed. Please review the schema deployment.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
