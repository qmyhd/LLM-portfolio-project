#!/usr/bin/env python3
"""Quick pre-push validation script."""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "src"))

from src.env_bootstrap import bootstrap_env # type: ignore

bootstrap_env()

from src.db import execute_sql # type: ignore


def main():
    print("\n" + "=" * 60)
    print("  PRE-PUSH VALIDATION")
    print("=" * 60)

    # 1. Table count
    try:
        tables = execute_sql(
            "SELECT COUNT(*) FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_type = 'BASE TABLE'",
            fetch_results=True,
        )
        table_count = tables[0][0]
        print(f"\n✓ Tables in database: {table_count}")
        if table_count < 15:
            print("  ⚠ Warning: Expected 17-20 tables")
    except Exception as e:
        print(f"\n✗ Failed to count tables: {e}")
        return 1

    # 2. Migration ledger
    try:
        migrations = execute_sql(
            "SELECT COUNT(*) FROM schema_migrations", fetch_results=True
        )
        migration_count = migrations[0][0]
        print(f"✓ Migrations applied: {migration_count}")

        # Show latest migrations
        recent = execute_sql(
            "SELECT version FROM schema_migrations " "ORDER BY applied_at DESC LIMIT 5",
            fetch_results=True,
        )
        print("\n  Most recent migrations:")
        for row in recent:
            print(f"    - {row[0]}")
    except Exception as e:
        print(f"\n✗ Failed to check migrations: {e}")
        return 1

    # 3. Key tables check
    key_tables = [
        "positions",
        "orders",
        "ohlcv_daily",
        "discord_parsed_ideas",
        "schema_migrations",
    ]
    print("\n  Key tables:")
    for table in key_tables:
        try:
            count = execute_sql(f"SELECT COUNT(*) FROM {table}", fetch_results=True)
            print(f"    ✓ {table}: {count[0][0]} rows")
        except Exception as e:
            print(f"    ✗ {table}: {e}")
            return 1

    print("\n" + "=" * 60)
    print("  ALL CHECKS PASSED")
    print("=" * 60 + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
