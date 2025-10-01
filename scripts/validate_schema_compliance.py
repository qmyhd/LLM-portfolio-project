#!/usr/bin/env python3
"""
Schema Drift Detection System
Implements the 5 'live snapshot' queries and diffs against baseline + incremental schemas
Fails CI if any new table, missing PK, PK order change, or type drift appears

Usage:
    python scripts/validate_schema_compliance.py --check-all
    python scripts/validate_schema_compliance.py --tables-only
    python scripts/validate_schema_compliance.py --pk-only
    python scripts/validate_schema_compliance.py --ci-mode  # Fail on any drift
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Tuple, Any
import subprocess

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

try:
    from config import settings
    from db import execute_sql
except ImportError:
    print("Missing dependencies. Ensure src/ modules are available.")
    sys.exit(1)

# Expected schema based on 000_baseline.sql + 014-017 migrations
EXPECTED_TABLES = {
    "accounts",
    "account_balances",
    "positions",
    "orders",
    "symbols",
    "daily_prices",
    "realtime_prices",
    "stock_metrics",
    "discord_messages",
    "discord_market_clean",
    "discord_trading_clean",
    "discord_processing_log",
    "processing_status",
    "twitter_data",
    "chart_metadata",
    "schema_migrations",
}

# Expected Primary Key Orders (from baseline + migrations analysis)
EXPECTED_PRIMARY_KEYS = {
    "accounts": ["id"],
    "account_balances": [
        "account_id",
        "currency_code",
        "snapshot_date",
    ],  # Note: May be different order based on migration
    "positions": ["symbol", "account_id"],
    "orders": ["brokerage_order_id"],
    "symbols": ["id"],
    "daily_prices": ["symbol", "date"],
    "realtime_prices": ["symbol", "timestamp"],
    "stock_metrics": ["date", "symbol"],  # Critical: Fixed in migration 015
    "discord_messages": ["message_id"],
    "discord_market_clean": ["message_id"],
    "discord_trading_clean": ["message_id"],
    "discord_processing_log": ["message_id", "channel"],
    "processing_status": ["message_id"],
    "twitter_data": ["tweet_id"],
    "chart_metadata": ["symbol", "period", "interval", "theme"],
    "schema_migrations": ["version"],
}


class SchemaValidator:
    def __init__(self):
        self.drift_detected = False
        self.errors = []

    def execute_query(self, query: str) -> List[Dict]:
        """Execute SQL query and return results"""
        try:
            result = execute_sql(query, fetch_results=True)
            if not result:
                return []

            # Convert various result types to list of dicts
            formatted_results = []
            for row in result:
                if hasattr(row, "_asdict"):
                    # Named tuple
                    formatted_results.append(row._asdict())
                elif isinstance(row, dict):
                    formatted_results.append(row)
                elif hasattr(row, "keys"):
                    # SQLAlchemy Row object - convert to dict
                    formatted_results.append(
                        {col: getattr(row, col) for col in row.keys()}
                    )
                else:
                    # Fallback - assume it's a tuple/list and skip
                    continue
            return formatted_results
        except Exception as e:
            print(f"Query execution error: {e}")
            return []

    def snapshot_1_list_tables(self) -> Dict[str, Any]:
        """Live Snapshot Query 1: List all tables with basic metadata"""
        query = """
        SELECT 
            table_name,
            table_type,
            is_insertable_into,
            is_typed
        FROM information_schema.tables 
        WHERE table_schema = 'public'
        ORDER BY table_name;
        """

        results = self.execute_query(query)
        tables = {r["table_name"] for r in results if r["table_type"] == "BASE TABLE"}

        print(f"📊 Snapshot 1: Found {len(tables)} tables")
        print(f"Tables: {sorted(tables)}")

        # Check for unexpected tables
        unexpected = tables - EXPECTED_TABLES
        missing = EXPECTED_TABLES - tables

        if unexpected:
            self.errors.append(f"❌ Unexpected tables found: {unexpected}")
            self.drift_detected = True

        if missing:
            self.errors.append(f"❌ Missing expected tables: {missing}")
            self.drift_detected = True

        return {
            "tables": sorted(tables),
            "unexpected": list(unexpected),
            "missing": list(missing),
        }

    def snapshot_2_primary_keys(self) -> Dict[str, List[str]]:
        """Live Snapshot Query 2: Primary key column order for all tables"""
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

        results = self.execute_query(query)
        live_pks = {r["table_name"]: r["pk_columns"] for r in results}

        print(f"🔑 Snapshot 2: Found primary keys for {len(live_pks)} tables")

        # Check PK compliance
        for table, expected_pk in EXPECTED_PRIMARY_KEYS.items():
            if table not in live_pks:
                self.errors.append(f"❌ Table {table} missing primary key")
                self.drift_detected = True
                continue

            live_pk = live_pks[table]
            if live_pk != expected_pk:
                self.errors.append(
                    f"❌ PK drift in {table}: expected {expected_pk}, got {live_pk}"
                )
                self.drift_detected = True

        return live_pks

    def snapshot_3_column_types(self) -> Dict[str, Dict[str, str]]:
        """Live Snapshot Query 3: Column data types for critical tables"""
        query = """
        SELECT 
            table_name,
            column_name,
            data_type,
            udt_name,
            is_nullable,
            column_default
        FROM information_schema.columns
        WHERE table_schema = 'public'
            AND table_name IN ('stock_metrics', 'daily_prices', 'realtime_prices', 'positions', 'accounts')
        ORDER BY table_name, ordinal_position;
        """

        results = self.execute_query(query)

        # Group by table
        tables = {}
        for r in results:
            table = r["table_name"]
            if table not in tables:
                tables[table] = {}
            tables[table][r["column_name"]] = {
                "data_type": r["data_type"],
                "udt_name": r["udt_name"],
                "is_nullable": r["is_nullable"],
            }

        print(f"📋 Snapshot 3: Column types for {len(tables)} critical tables")

        # Validate timestamp migration (017) was applied correctly
        if "stock_metrics" in tables and "date" in tables["stock_metrics"]:
            date_type = tables["stock_metrics"]["date"]["data_type"]
            if date_type != "date":
                self.errors.append(
                    f"❌ stock_metrics.date should be 'date' type, got '{date_type}'"
                )
                self.drift_detected = True

        return tables

    def snapshot_4_constraints(self) -> Dict[str, List[Dict]]:
        """Live Snapshot Query 4: All constraints (unique, foreign key, check)"""
        query = """
        SELECT 
            tc.table_name,
            tc.constraint_name,
            tc.constraint_type,
            array_agg(kcu.column_name ORDER BY kcu.ordinal_position) as columns
        FROM information_schema.table_constraints tc
        LEFT JOIN information_schema.key_column_usage kcu 
            ON tc.constraint_name = kcu.constraint_name
            AND tc.table_schema = kcu.table_schema
        WHERE tc.table_schema = 'public'
            AND tc.constraint_type IN ('UNIQUE', 'FOREIGN KEY', 'CHECK')
            AND tc.table_name NOT LIKE '%backup%'
        GROUP BY tc.table_name, tc.constraint_name, tc.constraint_type
        ORDER BY tc.table_name, tc.constraint_type;
        """

        results = self.execute_query(query)

        # Group by table
        constraints = {}
        for r in results:
            table = r["table_name"]
            if table not in constraints:
                constraints[table] = []
            constraints[table].append(
                {
                    "name": r["constraint_name"],
                    "type": r["constraint_type"],
                    "columns": r["columns"],
                }
            )

        print(f"🔒 Snapshot 4: Constraints for {len(constraints)} tables")
        return constraints

    def snapshot_5_rls_policies(self) -> Dict[str, List[Dict]]:
        """Live Snapshot Query 5: RLS policies (should exist for all tables per migration 016)"""
        query = """
        SELECT 
            schemaname,
            tablename,
            policyname,
            permissive,
            roles,
            cmd,
            qual,
            with_check
        FROM pg_policies 
        WHERE schemaname = 'public'
        ORDER BY tablename, policyname;
        """

        results = self.execute_query(query)

        # Group by table
        policies = {}
        for r in results:
            table = r["tablename"]
            if table not in policies:
                policies[table] = []
            policies[table].append(
                {
                    "name": r["policyname"],
                    "permissive": r["permissive"],
                    "roles": r["roles"],
                    "cmd": r["cmd"],
                }
            )

        print(f"🛡️ Snapshot 5: RLS policies for {len(policies)} tables")

        # Verify all operational tables have RLS policies (migration 016 requirement)
        tables_with_policies = set(policies.keys())
        expected_rls_tables = EXPECTED_TABLES - {
            "schema_migrations"
        }  # schema_migrations may not need RLS

        missing_policies = expected_rls_tables - tables_with_policies
        if missing_policies:
            self.errors.append(f"❌ Tables missing RLS policies: {missing_policies}")
            self.drift_detected = True

        return policies

    def run_all_snapshots(self) -> Dict[str, Any]:
        """Run all 5 live snapshot queries"""
        print("🔍 Running Complete Schema Drift Analysis...")
        print("=" * 60)

        results = {
            "1_tables": self.snapshot_1_list_tables(),
            "2_primary_keys": self.snapshot_2_primary_keys(),
            "3_column_types": self.snapshot_3_column_types(),
            "4_constraints": self.snapshot_4_constraints(),
            "5_rls_policies": self.snapshot_5_rls_policies(),
        }

        print("\n" + "=" * 60)
        if self.drift_detected:
            print("❌ SCHEMA DRIFT DETECTED!")
            for error in self.errors:
                print(f"   {error}")
            print(
                f"\n💡 Run migration 018 to fix: python scripts/apply_migration.py 018"
            )
        else:
            print("✅ SCHEMA COMPLIANCE VERIFIED - No drift detected!")

        return results

    def save_snapshot(self, results: Dict[str, Any], output_path: Path):
        """Save snapshot results to JSON file"""
        with open(output_path, "w") as f:
            json.dump(results, f, indent=2, default=str)
        print(f"📄 Snapshot saved to: {output_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Schema drift detection and validation"
    )
    parser.add_argument(
        "--check-all", action="store_true", help="Run all 5 snapshot queries"
    )
    parser.add_argument(
        "--tables-only", action="store_true", help="Only check table list (snapshot 1)"
    )
    parser.add_argument(
        "--pk-only", action="store_true", help="Only check primary keys (snapshot 2)"
    )
    parser.add_argument(
        "--ci-mode", action="store_true", help="CI mode - exit 1 on any drift"
    )
    parser.add_argument("--save-snapshot", type=str, help="Save results to JSON file")

    args = parser.parse_args()

    validator = SchemaValidator()

    if args.tables_only:
        results = {"1_tables": validator.snapshot_1_list_tables()}
    elif args.pk_only:
        results = {"2_primary_keys": validator.snapshot_2_primary_keys()}
    else:
        results = validator.run_all_snapshots()

    if args.save_snapshot:
        validator.save_snapshot(results, Path(args.save_snapshot))

    # Exit with error code for CI
    if args.ci_mode and validator.drift_detected:
        print("\n🚨 CI MODE: Exiting with error code due to schema drift")
        sys.exit(1)

    if validator.drift_detected:
        sys.exit(1)

    print("\n✅ Schema validation completed successfully")


if __name__ == "__main__":
    main()
