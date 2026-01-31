#!/usr/bin/env python3
"""
Unified Database Schema Verification Script
==========================================

Single source of truth for database schema verification, replacing the old
verify_schemas.py and consolidating all verification functionality.

Features:
- Uses EXPECTED_SCHEMAS from src.expected_schemas as authoritative schema source
- Supports basic, comprehensive, and performance validation modes
- Warn-only mode (default) for CI/CD friendliness with --strict override
- Uses only public database helpers for maintainability
- PostgreSQL-focused with proper connection pooling
- JSON output support for automation integration
- SQLAlchemy inspection for actual database schema discovery
- Comprehensive table, column, and constraint verification
- Type normalization and compatibility checking

Usage:
    python scripts/verify_database.py [options]

Examples:
    python scripts/verify_database.py                           # Full verification
    python scripts/verify_database.py --table orders           # Specific table
    python scripts/verify_database.py --mode basic             # Basic checks only
    python scripts/verify_database.py --verbose --json         # Detailed JSON output
    python scripts/verify_database.py --performance            # Include index checks
"""

import sys
import argparse
import logging
import json
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple, Set
from datetime import datetime
import traceback

# Add project root to path for imports
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Bootstrap AWS secrets FIRST, before any other src imports
from src.env_bootstrap import bootstrap_env

bootstrap_env()

try:
    from sqlalchemy import create_engine, inspect, text, MetaData
    from sqlalchemy.engine import Engine
    from sqlalchemy.exc import SQLAlchemyError

    SQLALCHEMY_AVAILABLE = True
except ImportError:
    SQLALCHEMY_AVAILABLE = False
    print("❌ SQLAlchemy not available. Install with: pip install sqlalchemy")
    sys.exit(1)

try:
    from src.config import settings, get_database_url
    from src.db import get_sync_engine, test_connection, execute_sql
    from src.expected_schemas import EXPECTED_SCHEMAS
except ImportError as e:
    print(f"❌ Required modules not available: {e}")
    print("Ensure you're running from the project root and dependencies are installed")
    sys.exit(1)

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class DatabaseSchemaVerifier:
    """Comprehensive database schema verification using generated schemas."""

    def __init__(
        self,
        database_url: Optional[str] = None,
        verbose: bool = False,
        warn_only: bool = True,
    ):
        self.database_url = database_url or get_database_url()
        self.verbose = verbose
        self.warn_only = warn_only  # Default to warn-only mode
        self.engine: Optional[Engine] = None
        self.inspector = None
        self.expected_schemas = EXPECTED_SCHEMAS

        # Type mapping for normalization - must match schema_parser.py output
        self.type_mappings = {
            # PostgreSQL -> normalized type (matching schema_parser.py)
            "character varying": "text",
            "varchar": "text",
            "text": "text",
            "character": "text",
            "char": "text",
            "bigint": "bigint",
            "integer": "integer",
            "int": "integer",
            "smallint": "integer",
            "serial": "integer",
            "bigserial": "bigint",
            "numeric": "numeric",
            "decimal": "numeric",
            "real": "numeric",
            "float": "numeric",
            "double": "numeric",
            "double precision": "numeric",
            "boolean": "boolean",
            "bool": "boolean",
            # CRITICAL: Preserve timestamptz vs timestamp distinction
            "timestamp with time zone": "timestamptz",
            "timestamptz": "timestamptz",
            "timestamp without time zone": "timestamp",
            "timestamp": "timestamp",
            "date": "date",
            "time": "time",
            "json": "jsonb",
            "jsonb": "jsonb",
            "uuid": "text",
            "bytea": "binary",
            "array": "array",
            "text[]": "array",
        }

    def connect(self) -> bool:
        """Establish database connection using public db helpers only."""
        try:
            # Use public helpers - test_connection validates connectivity
            connection_result = test_connection()

            if connection_result.get("status") == "connected":
                # Only create engine/inspector if connection succeeds
                self.engine = get_sync_engine()
                self.inspector = inspect(self.engine)

                if self.verbose:
                    db_type = connection_result.get("type", "unknown")
                    logger.info(f"✅ Connected to {db_type} database")

                return True
            else:
                logger.error(f"❌ Database connection failed: {connection_result}")
                return False

        except Exception as e:
            logger.error(f"❌ Database connection failed: {e}")
            return False

    def get_actual_tables(self) -> List[str]:
        """Get list of actual tables in the database."""
        if not self.inspector:
            return []

        try:
            return self.inspector.get_table_names()
        except Exception as e:
            logger.error(f"Error getting table names: {e}")
            return []

    def get_actual_columns(self, table_name: str) -> Dict[str, Any]:
        """Get actual column definitions for a table."""
        if not self.inspector:
            return {}

        try:
            columns = self.inspector.get_columns(table_name)
            column_dict = {}

            for col in columns:
                # Normalize the type
                raw_type = str(col["type"]).lower()
                normalized_type = self.normalize_type(raw_type)

                column_dict[col["name"]] = {
                    "type": normalized_type,
                    "raw_type": raw_type,
                    "nullable": col.get("nullable", True),
                    "default": col.get("default"),
                    "primary_key": col.get("primary_key", False),
                }

            return column_dict

        except Exception as e:
            logger.error(f"Error getting columns for {table_name}: {e}")
            return {}

    def get_actual_constraints(self, table_name: str) -> Dict[str, List[str]]:
        """Get actual constraints for a table."""
        if not self.inspector:
            return {"primary_keys": [], "unique_constraints": [], "foreign_keys": []}

        try:
            # Primary keys
            pk_constraint = self.inspector.get_pk_constraint(table_name)
            primary_keys = (
                pk_constraint.get("constrained_columns", []) if pk_constraint else []
            )

            # Unique constraints
            unique_constraints = []
            for constraint in self.inspector.get_unique_constraints(table_name):
                constraint_name = constraint.get("name", "unnamed")
                unique_constraints.append(constraint_name)

            # Foreign keys
            foreign_keys = []
            for fk in self.inspector.get_foreign_keys(table_name):
                fk_name = fk.get("name", "unnamed")
                foreign_keys.append(fk_name)

            return {
                "primary_keys": primary_keys,
                "unique_constraints": unique_constraints,
                "foreign_keys": foreign_keys,
            }

        except Exception as e:
            logger.error(f"Error getting constraints for {table_name}: {e}")
            return {"primary_keys": [], "unique_constraints": [], "foreign_keys": []}

    def get_actual_indexes(self, table_name: str) -> List[Dict[str, Any]]:
        """Get actual indexes for a table."""
        if not self.inspector:
            return []

        try:
            indexes = []
            for idx in self.inspector.get_indexes(table_name):
                indexes.append(
                    {
                        "name": idx.get("name"),
                        "columns": idx.get("column_names", []),
                        "unique": idx.get("unique", False),
                    }
                )
            return indexes

        except Exception as e:
            logger.error(f"Error getting indexes for {table_name}: {e}")
            return []

    def normalize_type(self, db_type: str) -> str:
        """Normalize database type to standard type."""
        db_type = db_type.lower().strip()

        # Handle parameterized types like varchar(255), numeric(18,6)
        if "(" in db_type:
            base_type = db_type.split("(")[0].strip()
        else:
            base_type = db_type

        return self.type_mappings.get(base_type, base_type)

    def types_compatible(self, expected_type: str, actual_type: str) -> bool:
        """Check if expected and actual types are compatible."""
        expected_norm = self.normalize_type(expected_type)
        actual_norm = self.normalize_type(actual_type)

        # Exact match
        if expected_norm == actual_norm:
            return True

        # Special compatibility rules
        compatible_groups = [
            {"text", "character varying", "varchar"},
            {"numeric", "decimal", "real", "double precision"},
            {"integer", "int", "bigint"},
            {
                "timestamp",
                "timestamptz",
                "timestamp without time zone",
                "timestamp with time zone",
            },
            {"json", "jsonb"},
        ]

        for group in compatible_groups:
            if expected_norm in group and actual_norm in group:
                return True

        return False

    def verify_table_existence(self) -> Dict[str, Any]:
        """Verify that all expected tables exist."""
        actual_tables = set(self.get_actual_tables())
        # Use expected schemas for table validation
        expected_tables = set(self.expected_schemas.keys())

        missing_tables = expected_tables - actual_tables
        extra_tables = actual_tables - expected_tables
        existing_tables = expected_tables & actual_tables

        return {
            "expected_count": len(expected_tables),
            "actual_count": len(actual_tables),
            "existing_tables": list(existing_tables),
            "missing_tables": list(missing_tables),
            "extra_tables": list(extra_tables),
            "success": len(missing_tables) == 0,
        }

    def verify_table_columns(self, table_name: str) -> Dict[str, Any]:
        """Verify columns for a specific table."""
        # Skip validation when expected_schemas is disabled
        if not self.expected_schemas:
            return {
                "status": "skipped",
                "reason": "Expected schemas validation disabled",
            }

        if table_name not in self.expected_schemas:
            return {"error": f"Table {table_name} not in expected schemas"}

        expected_columns = self.expected_schemas[table_name].get("required_fields", {})
        actual_columns = self.get_actual_columns(table_name)

        expected_set = set(expected_columns.keys())
        actual_set = set(actual_columns.keys())

        missing_columns = expected_set - actual_set
        extra_columns = actual_set - expected_set
        common_columns = expected_set & actual_set

        # Check type compatibility for common columns
        type_mismatches = []
        for col_name in common_columns:
            expected_type = expected_columns[col_name]
            actual_type = actual_columns[col_name]["type"]

            if not self.types_compatible(expected_type, actual_type):
                type_mismatches.append(
                    {
                        "column": col_name,
                        "expected_type": expected_type,
                        "actual_type": actual_type,
                        "raw_type": actual_columns[col_name]["raw_type"],
                    }
                )

        return {
            "table": table_name,
            "expected_column_count": len(expected_columns),
            "actual_column_count": len(actual_columns),
            "missing_columns": list(missing_columns),
            "extra_columns": list(extra_columns),
            "type_mismatches": type_mismatches,
            "success": len(missing_columns) == 0 and len(type_mismatches) == 0,
        }

    def verify_table_constraints(self, table_name: str) -> Dict[str, Any]:
        """Verify constraints for a specific table."""
        if table_name not in self.expected_schemas:
            return {"error": f"Table {table_name} not in expected schemas"}

        expected_schema = self.expected_schemas[table_name]
        expected_unique_constraints = expected_schema.get("unique_constraints", [])
        expected_primary_keys = expected_schema.get("primary_keys", [])

        actual_constraints = self.get_actual_constraints(table_name)
        actual_unique_constraints = actual_constraints["unique_constraints"]
        actual_primary_keys = actual_constraints["primary_keys"]

        return {
            "table": table_name,
            "primary_keys": {
                "expected": expected_primary_keys,
                "actual": actual_primary_keys,
                "match": set(expected_primary_keys) == set(actual_primary_keys),
            },
            "unique_constraints": {
                "expected": expected_unique_constraints,
                "actual": actual_unique_constraints,
                "missing": [
                    uc
                    for uc in expected_unique_constraints
                    if uc not in actual_unique_constraints
                ],
                "extra": [
                    uc
                    for uc in actual_unique_constraints
                    if uc not in expected_unique_constraints
                ],
            },
        }

    def verify_rls_status(self) -> Dict[str, Any]:
        """
        Verify Row-Level Security (RLS) is enabled on all tables.

        Queries pg_catalog.pg_class to check relrowsecurity flag for each table.
        All operational tables should have RLS enabled for security compliance.

        Returns:
            Dict with RLS status for each table and summary statistics
        """
        results = {
            "timestamp": datetime.now().isoformat(),
            "schema_checked": "public",  # Document which schema is checked
            "tables_checked": 0,
            "tables_with_rls": 0,
            "tables_without_rls": 0,
            "table_status": {},
            "missing_rls": [],
            "summary": {},
        }

        if not self.inspector:
            results["summary"] = {
                "status": "failed",
                "error": "Database not connected",
            }
            return results

        try:
            # Query PostgreSQL system catalog for RLS status
            query = text(
                """
                SELECT 
                    c.relname AS table_name,
                    c.relrowsecurity AS rls_enabled,
                    COALESCE(pol_count.count, 0) AS policy_count
                FROM pg_catalog.pg_class c
                LEFT JOIN (
                    SELECT tablename, COUNT(*) as count
                    FROM pg_catalog.pg_policies
                    WHERE schemaname = 'public'
                    GROUP BY tablename
                ) pol_count ON c.relname = pol_count.tablename
                WHERE c.relnamespace = (
                    SELECT oid FROM pg_catalog.pg_namespace WHERE nspname = 'public'
                )
                AND c.relkind = 'r'  -- Only regular tables
                ORDER BY c.relname
            """
            )

            with self.engine.connect() as conn:
                result = conn.execute(query)
                db_rls_status = {
                    row[0]: {"enabled": row[1], "policies": row[2]} for row in result
                }

            # Check each expected table
            for table_name in self.expected_schemas.keys():
                results["tables_checked"] += 1

                if table_name in db_rls_status:
                    rls_info = db_rls_status[table_name]
                    rls_enabled = rls_info["enabled"]
                    policy_count = rls_info["policies"]

                    results["table_status"][table_name] = {
                        "rls_enabled": rls_enabled,
                        "policy_count": policy_count,
                        "status": "✅ Enabled" if rls_enabled else "❌ Disabled",
                    }

                    if rls_enabled:
                        results["tables_with_rls"] += 1
                    else:
                        results["tables_without_rls"] += 1
                        results["missing_rls"].append(table_name)

                    if self.verbose:
                        status_symbol = "✅" if rls_enabled else "❌"
                        logger.info(
                            f"  {status_symbol} {table_name}: RLS={'enabled' if rls_enabled else 'DISABLED'}, "
                            f"Policies={policy_count}"
                        )
                else:
                    results["table_status"][table_name] = {
                        "rls_enabled": None,
                        "policy_count": 0,
                        "status": "⚠️  Table not found",
                        "error": "Table does not exist in database",
                    }
                    if self.verbose:
                        logger.warning(
                            f"  ⚠️  {table_name}: Table not found in database"
                        )

            # Generate summary
            all_have_rls = results["tables_without_rls"] == 0
            results["summary"] = {
                "status": "success" if all_have_rls else "failed",
                "all_tables_have_rls": all_have_rls,
                "compliance_percentage": (
                    round(
                        (results["tables_with_rls"] / results["tables_checked"]) * 100,
                        1,
                    )
                    if results["tables_checked"] > 0
                    else 0
                ),
                "message": (
                    f"✅ All {results['tables_with_rls']} tables have RLS enabled"
                    if all_have_rls
                    else f"❌ {results['tables_without_rls']} table(s) missing RLS: {', '.join(results['missing_rls'])}"
                ),
            }

        except SQLAlchemyError as e:
            logger.error(f"Error verifying RLS status: {e}")
            results["summary"] = {
                "status": "error",
                "error": str(e),
            }

        return results

    def verify_basic(self) -> Dict[str, Any]:
        """Basic verification: connectivity and table existence."""
        results = {
            "mode": "basic",
            "timestamp": datetime.now().isoformat(),
            "database_connected": False,
            "table_verification": {},
            "summary": {},
        }

        # Test connectivity
        results["database_connected"] = self.connect()
        if not results["database_connected"]:
            results["summary"] = {
                "status": "failed",
                "error": "Database connection failed",
            }
            return results

        # Verify table existence
        table_results = self.verify_table_existence()
        results["table_verification"] = table_results

        # Summary
        results["summary"] = {
            "status": "success" if table_results["success"] else "failed",
            "total_expected_tables": table_results["expected_count"],
            "existing_tables": len(table_results["existing_tables"]),
            "missing_tables": len(table_results["missing_tables"]),
            "extra_tables": len(table_results["extra_tables"]),
        }

        return results

    def verify_comprehensive(
        self, specific_table: Optional[str] = None
    ) -> Dict[str, Any]:
        """Comprehensive verification: tables, columns, types, constraints."""
        results = {
            "mode": "comprehensive",
            "timestamp": datetime.now().isoformat(),
            "database_connected": False,
            "table_verification": {},
            "column_verification": {},
            "constraint_verification": {},
            "summary": {},
        }

        # Test connectivity
        results["database_connected"] = self.connect()
        if not results["database_connected"]:
            results["summary"] = {
                "status": "failed",
                "error": "Database connection failed",
            }
            return results

        # Determine tables to check
        if specific_table:
            if not self.expected_schemas or specific_table not in self.expected_schemas:
                results["summary"] = {
                    "status": "failed",
                    "error": f"Table {specific_table} not in expected schemas",
                }
                return results
            tables_to_check = [specific_table]
        else:
            # Basic table verification first
            table_results = self.verify_table_existence()
            results["table_verification"] = table_results
            tables_to_check = table_results["existing_tables"]

        # Column verification
        column_results = {}
        constraint_results = {}
        total_issues = 0

        for table in tables_to_check:
            # Column verification
            col_result = self.verify_table_columns(table)
            column_results[table] = col_result

            # In warn-only mode, log schema differences but continue
            if self.warn_only and col_result.get("missing_columns"):
                logger.warning(
                    f"Schema difference in {table}: missing columns {col_result['missing_columns']} - continuing anyway"
                )
            if self.warn_only and col_result.get("type_mismatches"):
                logger.warning(
                    f"Schema difference in {table}: type mismatches {[m['column'] for m in col_result['type_mismatches']]} - continuing anyway"
                )

            if not col_result.get("success", True):
                total_issues += len(col_result.get("missing_columns", [])) + len(
                    col_result.get("type_mismatches", [])
                )

            # Constraint verification
            constraint_result = self.verify_table_constraints(table)
            constraint_results[table] = constraint_result

            # Count constraint issues
            pk_match = constraint_result.get("primary_keys", {}).get("match", True)
            unique_missing = len(
                constraint_result.get("unique_constraints", {}).get("missing", [])
            )
            if not pk_match or unique_missing > 0:
                total_issues += 1 + unique_missing

        results["column_verification"] = column_results
        results["constraint_verification"] = constraint_results

        # RLS verification (if not checking specific table)
        if not specific_table:
            if self.verbose:
                logger.info("\n🔒 Verifying Row-Level Security (RLS) status...")
            rls_results = self.verify_rls_status()
            results["rls_verification"] = rls_results

            # Add RLS issues to total count
            if not rls_results["summary"].get("all_tables_have_rls", True):
                total_issues += rls_results["tables_without_rls"]

        # Summary
        results["summary"] = {
            "status": "success" if total_issues == 0 else "failed",
            "tables_checked": len(tables_to_check),
            "total_issues": total_issues,
            # Include table existence info from table_results (for print_basic_results)
            "total_expected_tables": results.get("table_verification", {}).get(
                "expected_count", 0
            ),
            "existing_tables": len(
                results.get("table_verification", {}).get("existing_tables", [])
            ),
            "missing_tables": len(
                results.get("table_verification", {}).get("missing_tables", [])
            ),
            "extra_tables": len(
                results.get("table_verification", {}).get("extra_tables", [])
            ),
            "has_missing_columns": any(
                len(cr.get("missing_columns", [])) > 0 for cr in column_results.values()
            ),
            "has_type_mismatches": any(
                len(cr.get("type_mismatches", [])) > 0 for cr in column_results.values()
            ),
            "has_constraint_issues": any(
                not cr.get("primary_keys", {}).get("match", True)
                for cr in constraint_results.values()
            ),
        }

        # Add RLS summary if checked
        if not specific_table and "rls_verification" in results:
            results["summary"]["has_rls_issues"] = not results["rls_verification"][
                "summary"
            ].get("all_tables_have_rls", True)
            results["summary"]["rls_compliance"] = results["rls_verification"][
                "summary"
            ].get("compliance_percentage", 0)

        return results

    def verify_performance(self) -> Dict[str, Any]:
        """Performance verification: check important indexes."""
        results = {
            "mode": "performance",
            "timestamp": datetime.now().isoformat(),
            "database_connected": False,
            "index_verification": {},
            "summary": {},
        }

        # Test connectivity
        results["database_connected"] = self.connect()
        if not results["database_connected"]:
            results["summary"] = {
                "status": "failed",
                "error": "Database connection failed",
            }
            return results

        # Define critical indexes (column patterns to look for)
        critical_indexes = {
            "orders": [["symbol"], ["time_placed"], ["account_id"]],
            "positions": [["symbol"], ["account_id"]],
            "discord_messages": [["timestamp"], ["author"]],
            "symbols": [["ticker"]],  # Should be unique
            "ohlcv_daily": [["symbol"], ["date"]],  # Replaces daily_prices
        }

        index_results = {}
        missing_indexes = []

        for table, expected_index_columns in critical_indexes.items():
            if table not in self.get_actual_tables():
                continue

            actual_indexes = self.get_actual_indexes(table)
            table_index_coverage = []

            for expected_columns in expected_index_columns:
                # Check if there's an index covering these columns
                found_index = False
                for idx in actual_indexes:
                    idx_columns = idx.get("columns", [])
                    if set(expected_columns).issubset(set(idx_columns)):
                        found_index = True
                        table_index_coverage.append(
                            {
                                "columns": expected_columns,
                                "found": True,
                                "index_name": idx["name"],
                            }
                        )
                        break

                if not found_index:
                    table_index_coverage.append(
                        {"columns": expected_columns, "found": False}
                    )
                    missing_indexes.append(f"{table}({','.join(expected_columns)})")

            index_results[table] = {
                "expected_indexes": len(expected_index_columns),
                "coverage": table_index_coverage,
                "actual_indexes": actual_indexes,
            }

        results["index_verification"] = index_results
        results["summary"] = {
            "status": "success" if len(missing_indexes) == 0 else "warning",
            "missing_critical_indexes": missing_indexes,
            "tables_checked": len(index_results),
        }

        return results


def print_results(
    results: Dict[str, Any], verbose: bool = False, json_output: bool = False
):
    """Print verification results in formatted output."""
    if json_output:
        print(json.dumps(results, indent=2, default=str))
        return

    mode = results.get("mode", "unknown")
    timestamp = results.get("timestamp", "unknown")

    print(f"\n{'='*80}")
    print(f"DATABASE SCHEMA VERIFICATION - {mode.upper()} MODE")
    print(f"{'='*80}")
    print(f"Timestamp: {timestamp}")
    print(
        f"Database Connected: {'✅ Yes' if results.get('database_connected') else '❌ No'}"
    )

    if not results.get("database_connected"):
        print("\n❌ Cannot proceed with verification - database connection failed")
        return

    summary = results.get("summary", {})
    status = summary.get("status", "unknown")

    print(
        f"Overall Status: {'✅ PASS' if status == 'success' else '⚠️ WARNING' if status == 'warning' else '❌ FAIL'}"
    )

    if mode == "basic":
        print_basic_results(results, verbose)
    elif mode == "comprehensive":
        print_comprehensive_results(results, verbose)
    elif mode == "performance":
        print_performance_results(results, verbose)


def print_basic_results(results: Dict[str, Any], verbose: bool):
    """Print basic verification results."""
    table_verification = results.get("table_verification", {})
    summary = results.get("summary", {})

    print(f"\n📊 TABLE EXISTENCE VERIFICATION")
    print(f"   Expected Tables: {summary.get('total_expected_tables', 0)}")
    print(f"   Existing Tables: {summary.get('existing_tables', 0)}")
    print(f"   Missing Tables: {summary.get('missing_tables', 0)}")
    print(f"   Extra Tables: {summary.get('extra_tables', 0)}")

    if table_verification.get("missing_tables"):
        print(f"\n❌ MISSING TABLES:")
        for table in table_verification["missing_tables"]:
            print(f"   • {table}")

    if table_verification.get("extra_tables") and verbose:
        print(f"\n⚠️ EXTRA TABLES (not in expected schema):")
        for table in table_verification["extra_tables"]:
            print(f"   • {table}")


def print_comprehensive_results(results: Dict[str, Any], verbose: bool):
    """Print comprehensive verification results."""
    print_basic_results(results, verbose)

    column_verification = results.get("column_verification", {})
    constraint_verification = results.get("constraint_verification", {})
    summary = results.get("summary", {})

    print(f"\n📋 COLUMN & TYPE VERIFICATION")
    print(f"   Tables Checked: {summary.get('tables_checked', 0)}")
    print(f"   Total Issues: {summary.get('total_issues', 0)}")

    # Show column issues
    for table, col_result in column_verification.items():
        if not col_result.get("success", True) or verbose:
            print(f"\n  📄 Table: {table}")
            print(
                f"     Expected Columns: {col_result.get('expected_column_count', 0)}"
            )
            print(f"     Actual Columns: {col_result.get('actual_column_count', 0)}")

            if col_result.get("missing_columns"):
                print(
                    f"     ❌ Missing Columns: {', '.join(col_result['missing_columns'])}"
                )

            if col_result.get("type_mismatches"):
                print(f"     ⚠️ Type Mismatches:")
                for mismatch in col_result["type_mismatches"]:
                    print(
                        f"        • {mismatch['column']}: expected {mismatch['expected_type']}, got {mismatch['actual_type']}"
                    )

            if col_result.get("extra_columns") and verbose:
                print(
                    f"     ➕ Extra Columns: {', '.join(col_result['extra_columns'])}"
                )

    # Show constraint issues
    print(f"\n🔒 CONSTRAINT VERIFICATION")
    constraint_issues = False
    for table, constraint_result in constraint_verification.items():
        pk_info = constraint_result.get("primary_keys", {})
        unique_info = constraint_result.get("unique_constraints", {})

        if not pk_info.get("match", True) or unique_info.get("missing") or verbose:
            if not constraint_issues:
                constraint_issues = True

            print(f"\n  📄 Table: {table}")

            if not pk_info.get("match", True):
                print(f"     ❌ Primary Key Mismatch:")
                print(f"        Expected: {pk_info.get('expected', [])}")
                print(f"        Actual: {pk_info.get('actual', [])}")

            if unique_info.get("missing"):
                print(
                    f"     ❌ Missing Unique Constraints: {', '.join(unique_info['missing'])}"
                )

            if unique_info.get("extra") and verbose:
                print(
                    f"     ➕ Extra Unique Constraints: {', '.join(unique_info['extra'])}"
                )

    if not constraint_issues:
        print(f"   ✅ All constraints verified successfully")

    # Show RLS verification if available
    rls_verification = results.get("rls_verification")
    if rls_verification:
        rls_summary = rls_verification.get("summary", {})
        schema_checked = rls_verification.get("schema_checked", "public")

        print(f"\n🔒 ROW-LEVEL SECURITY (RLS) VERIFICATION")
        print(f"   Schema Checked: {schema_checked}")
        print(f"   Tables Checked: {rls_verification.get('tables_checked', 0)}")
        print(f"   Tables with RLS: {rls_verification.get('tables_with_rls', 0)}")
        print(f"   Tables without RLS: {rls_verification.get('tables_without_rls', 0)}")
        print(f"   Compliance: {rls_summary.get('compliance_percentage', 0):.1f}%")

        if rls_verification.get("missing_rls"):
            print(f"\n   ❌ Tables Missing RLS Policies:")
            for table in rls_verification["missing_rls"]:
                print(f"      • {table}")
        else:
            print(f"   ✅ All tables have RLS enabled")


def print_performance_results(results: Dict[str, Any], verbose: bool):
    """Print performance verification results."""
    index_verification = results.get("index_verification", {})
    summary = results.get("summary", {})

    print(f"\n⚡ PERFORMANCE INDEX VERIFICATION")
    print(f"   Tables Checked: {summary.get('tables_checked', 0)}")

    missing_indexes = summary.get("missing_critical_indexes", [])
    if missing_indexes:
        print(f"   ⚠️ Missing Critical Indexes: {len(missing_indexes)}")
        for idx in missing_indexes:
            print(f"      • {idx}")
    else:
        print(f"   ✅ All critical indexes found")

    if verbose:
        print(f"\n📊 DETAILED INDEX COVERAGE:")
        for table, idx_info in index_verification.items():
            print(f"\n  📄 Table: {table}")
            for coverage in idx_info.get("coverage", []):
                status = "✅" if coverage["found"] else "❌"
                idx_name = (
                    f" ({coverage.get('index_name', '')})" if coverage["found"] else ""
                )
                print(f"     {status} Index on {coverage['columns']}{idx_name}")


def main():
    """Main CLI interface."""
    parser = argparse.ArgumentParser(
        description="Unified Database Schema Verification",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                                    # Full comprehensive verification
  %(prog)s --mode basic                       # Basic connectivity and table checks
  %(prog)s --table orders                     # Verify specific table
  %(prog)s --performance                      # Include performance index checks
  %(prog)s --verbose --json                   # Detailed JSON output
  %(prog)s --database-url postgresql://...    # Custom database URL
        """,
    )

    parser.add_argument(
        "--database-url", help="Database URL (overrides environment config)"
    )

    parser.add_argument("--table", help="Verify specific table only")

    parser.add_argument(
        "--mode",
        choices=["basic", "comprehensive", "performance"],
        default="comprehensive",
        help="Verification mode (default: comprehensive)",
    )

    parser.add_argument(
        "--performance",
        action="store_true",
        help="Include performance index verification (sets mode to performance)",
    )

    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Verbose output with detailed information",
    )

    parser.add_argument(
        "--json", action="store_true", help="Output results in JSON format"
    )

    parser.add_argument(
        "--strict",
        action="store_true",
        help="Strict mode: fail on schema differences (default: warn-only)",
    )

    args = parser.parse_args()

    # Override mode if performance flag is set
    if args.performance:
        args.mode = "performance"

    # Set up logging level
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    try:
        # Initialize verifier (warn_only=True unless --strict)
        verifier = DatabaseSchemaVerifier(
            database_url=args.database_url,
            verbose=args.verbose,
            warn_only=not args.strict,  # Default to warn-only mode
        )

        # Run verification based on mode
        if args.mode == "basic":
            results = verifier.verify_basic()
        elif args.mode == "comprehensive":
            results = verifier.verify_comprehensive(specific_table=args.table)
        elif args.mode == "performance":
            results = verifier.verify_performance()
        else:
            raise ValueError(f"Unknown mode: {args.mode}")

        # Print results
        print_results(results, verbose=args.verbose, json_output=args.json)

        # Exit with appropriate code
        summary = results.get("summary", {})
        status = summary.get("status", "failed")

        if status == "success":
            sys.exit(0)
        elif status == "warning":
            sys.exit(1)  # Warning
        else:
            sys.exit(2)  # Failure

    except KeyboardInterrupt:
        print("\n⏹️ Verification interrupted by user")
        sys.exit(130)
    except Exception as e:
        logger.error(f"❌ Verification failed with error: {e}")
        if args.verbose:
            traceback.print_exc()
        sys.exit(2)


if __name__ == "__main__":
    main()
