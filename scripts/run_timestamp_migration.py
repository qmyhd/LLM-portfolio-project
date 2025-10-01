#!/usr/bin/env python3
"""
Execute timestamp field migration script.
Applies migration 017 and validates the results.
"""
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

# Add the src directory to the path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from src.db import get_sync_engine
from sqlalchemy import text

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def check_migration_status():
    """Check if migration 017 has already been applied."""
    engine = get_sync_engine()

    with engine.connect() as conn:
        try:
            result = conn.execute(
                text(
                    """
                SELECT version, applied_at 
                FROM schema_migrations 
                WHERE version = '017'
            """
                )
            )
            row = result.fetchone()
            return row is not None, row.applied_at if row else None
        except Exception as e:
            logger.warning(f"Could not check migration status: {e}")
            return False, None


def backup_timestamp_data():
    """Create backup of critical timestamp data before migration."""
    engine = get_sync_engine()

    backup_queries = [
        {
            "name": "positions_backup",
            "query": """
                CREATE TABLE IF NOT EXISTS positions_backup_017 AS 
                SELECT * FROM positions WHERE sync_timestamp IS NOT NULL
            """,
        },
        {
            "name": "accounts_backup",
            "query": """
                CREATE TABLE IF NOT EXISTS accounts_backup_017 AS
                SELECT * FROM accounts WHERE sync_timestamp IS NOT NULL
            """,
        },
        {
            "name": "account_balances_backup",
            "query": """
                CREATE TABLE IF NOT EXISTS account_balances_backup_017 AS
                SELECT * FROM account_balances WHERE snapshot_date IS NOT NULL
            """,
        },
    ]

    with engine.begin() as conn:
        for backup in backup_queries:
            try:
                logger.info(f"Creating backup: {backup['name']}")
                conn.execute(text(backup["query"]))
                logger.info(f"  ✅ Backup {backup['name']} completed")
            except Exception as e:
                logger.error(f"  ❌ Backup {backup['name']} failed: {e}")
                return False

    return True


def run_migration():
    """Execute the timestamp migration SQL script."""
    migration_file = (
        Path(__file__).parent.parent / "schema" / "017_timestamp_field_migration.sql"
    )

    if not migration_file.exists():
        logger.error(f"Migration file not found: {migration_file}")
        return False

    logger.info(f"Reading migration file: {migration_file}")

    try:
        migration_sql = migration_file.read_text(encoding="utf-8")
        logger.info(f"Migration SQL loaded: {len(migration_sql)} characters")
    except Exception as e:
        logger.error(f"Failed to read migration file: {e}")
        return False

    engine = get_sync_engine()

    logger.info("Executing migration 017...")

    try:
        with engine.begin() as conn:
            # Execute the migration SQL
            conn.execute(text(migration_sql))
            logger.info("✅ Migration 017 executed successfully")
            return True
    except Exception as e:
        logger.error(f"❌ Migration 017 failed: {e}")
        return False


def validate_migration():
    """Run validation tests after migration."""
    logger.info("Running post-migration validation...")

    # Import validation script
    sys.path.insert(0, str(Path(__file__).parent))

    try:
        from validate_timestamp_migration import (
            test_timestamp_field_queries,
            check_data_types,
            validate_data_integrity,
        )

        # Run validation tests
        query_results = test_timestamp_field_queries()
        type_results = check_data_types()
        integrity_results = validate_data_integrity()

        # Check results
        query_success = all(r["success"] for r in query_results.values())
        integrity_success = all(r["success"] for r in integrity_results.values())

        # Check expected data types
        expected_types = {
            "positions.sync_timestamp": "timestamp with time zone",
            "accounts.sync_timestamp": "timestamp with time zone",
            "accounts.last_successful_sync": "timestamp with time zone",
            "account_balances.sync_timestamp": "timestamp with time zone",
            "account_balances.snapshot_date": "date",
            "daily_prices.date": "date",
            "realtime_prices.timestamp": "timestamp with time zone",
            "stock_metrics.date": "date",
            "discord_processing_log.processed_date": "date",
            "twitter_data.discord_date": "timestamp with time zone",
        }

        type_success = True
        for field, expected_type in expected_types.items():
            if field in type_results:
                actual_type = type_results[field].get("data_type", "")
                if actual_type != expected_type:
                    logger.error(
                        f"❌ Type mismatch for {field}: expected {expected_type}, got {actual_type}"
                    )
                    type_success = False
                else:
                    logger.info(f"✅ Type correct for {field}: {actual_type}")
            else:
                logger.warning(f"⚠️  Field not found: {field}")

        overall_success = query_success and integrity_success and type_success

        if overall_success:
            logger.info("🎉 Migration validation PASSED!")
        else:
            logger.error("❌ Migration validation FAILED!")

        return overall_success

    except ImportError as e:
        logger.error(f"Could not import validation functions: {e}")
        return False


def cleanup_backup_tables():
    """Optionally cleanup backup tables after successful migration."""
    response = input("\nDo you want to cleanup backup tables? (y/N): ").lower().strip()

    if response == "y":
        engine = get_sync_engine()

        backup_tables = [
            "positions_backup_017",
            "accounts_backup_017",
            "account_balances_backup_017",
        ]

        with engine.begin() as conn:
            for table in backup_tables:
                try:
                    conn.execute(text(f"DROP TABLE IF EXISTS {table}"))
                    logger.info(f"✅ Dropped backup table: {table}")
                except Exception as e:
                    logger.error(f"❌ Failed to drop backup table {table}: {e}")
    else:
        logger.info("Backup tables preserved for safety")


def main():
    """Main migration execution function."""
    logger.info("🚀 Starting timestamp field migration (017)")

    # Check if migration already applied
    is_applied, applied_at = check_migration_status()
    if is_applied:
        logger.warning(f"⚠️  Migration 017 already applied at {applied_at}")
        response = input("Do you want to continue anyway? (y/N): ").lower().strip()
        if response != "y":
            logger.info("Migration aborted by user")
            return 0

    # Step 1: Create backups
    logger.info("\n📦 Step 1: Creating data backups...")
    if not backup_timestamp_data():
        logger.error("❌ Backup creation failed. Migration aborted.")
        return 1

    # Step 2: Run migration
    logger.info("\n🔧 Step 2: Executing migration...")
    if not run_migration():
        logger.error("❌ Migration execution failed.")
        return 1

    # Step 3: Validate migration
    logger.info("\n✅ Step 3: Validating migration...")
    if not validate_migration():
        logger.error("❌ Migration validation failed.")
        return 1

    # Step 4: Optional cleanup
    logger.info("\n🧹 Step 4: Cleanup (optional)...")
    cleanup_backup_tables()

    logger.info("\n🎉 Timestamp field migration completed successfully!")
    logger.info("\nNext steps:")
    logger.info("1. Test your application with the new timestamp types")
    logger.info("2. Update any hardcoded timestamp handling in your code")
    logger.info("3. Monitor query performance improvements")

    return 0


if __name__ == "__main__":
    sys.exit(main())
