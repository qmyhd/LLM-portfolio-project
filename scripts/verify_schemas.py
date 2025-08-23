#!/usr/bin/env python3
"""
Database Schema Verification Script

Comprehensive verification of database schemas across PostgreSQL/Supabase,
including table existence, field types, and data integrity checks.

Usage:
    python scripts/verify_schemas.py [--database-url URL] [--table TABLE] [--verbose]

Examples:
    python scripts/verify_schemas.py
    python scripts/verify_schemas.py --table accounts
    python scripts/verify_schemas.py --database-url postgresql://... --verbose
"""

import argparse
import logging
import sys
import os
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple

# Add project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

try:
    from sqlalchemy import create_engine, inspect, text
    from sqlalchemy.engine import Engine
    from sqlalchemy.exc import SQLAlchemyError

    SQLALCHEMY_AVAILABLE = True
except ImportError:
    SQLALCHEMY_AVAILABLE = False

from src.config import settings

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Expected database schemas - Updated to match SnapTrade API specifications
EXPECTED_SCHEMAS = {
    "accounts": {
        "required_fields": {
            "id": "text",
            "brokerage_authorization": "text",
            "portfolio_group": "text",
            "name": "text",
            "number": "text",
            "institution_name": "text",
            "last_successful_sync": "timestamp",
            "total_equity": "numeric",
            "created_at": "timestamp",
            "updated_at": "timestamp",
        },
        "description": "SnapTrade account information",
    },
    "account_balances": {
        "required_fields": {
            "id": "bigint",
            "account_id": "text",
            "currency_code": "text",
            "currency_name": "text",
            "currency_id": "text",
            "cash": "numeric",
            "buying_power": "numeric",
            "snapshot_date": "date",
            "created_at": "timestamp",
        },
        "unique_constraints": [["account_id", "currency_code", "snapshot_date"]],
        "description": "Account balance snapshots per currency",
    },
    "positions": {
        "required_fields": {
            "id": "bigint",
            "account_id": "text",
            "symbol": "text",
            "symbol_id": "text",
            "symbol_description": "text",
            "quantity": "numeric",
            "price": "numeric",
            "equity": "numeric",
            "average_buy_price": "numeric",
            "open_pnl": "numeric",
            "asset_type": "text",
            "currency": "text",
            "logo_url": "text",
            "sync_timestamp": "timestamp",
        },
        "description": "Portfolio positions with PnL tracking",
    },
    "orders": {
        "required_fields": {
            "id": "bigint",
            "account_id": "text",
            "brokerage_order_id": "text",
            "status": "text",
            "symbol": "text",
            "extracted_symbol": "text",
            "universal_symbol": "json",
            "quote_universal_symbol": "json",
            "quote_currency": "json",
            "option_symbol": "json",
            "action": "text",
            "total_quantity": "numeric",
            "open_quantity": "numeric",
            "canceled_quantity": "numeric",
            "filled_quantity": "numeric",
            "execution_price": "numeric",
            "limit_price": "numeric",
            "stop_price": "numeric",
            "order_type": "text",
            "time_in_force": "text",
            "time_placed": "timestamp",
            "time_updated": "timestamp",
            "time_executed": "timestamp",
            "expiry_date": "timestamp",
            "child_brokerage_order_ids": "json",
            "sync_timestamp": "timestamp",
        },
        "unique_constraints": [["brokerage_order_id"]],
        "description": "Trading orders and executions with full lifecycle tracking",
    },
    "symbols": {
        "required_fields": {
            "id": "text",
            "ticker": "text",
            "description": "text",
            "asset_type": "text",
            "type_code": "text",
            "exchange_id": "text",
            "exchange_code": "text",
            "exchange_name": "text",
            "mic_code": "text",
            "timezone": "text",
            "figi_code": "text",
            "raw_symbol": "text",
            "logo_url": "text",
            "base_currency_code": "text",
            "is_supported": "boolean",
            "is_quotable": "boolean",
            "is_tradable": "boolean",
            "created_at": "timestamp",
            "updated_at": "timestamp",
        },
        "description": "Symbol metadata and exchange information",
    },
}


class SchemaVerifier:
    """Database schema verification utility."""

    def __init__(self, database_url: Optional[str] = None):
        """Initialize the schema verifier."""
        self.database_url = database_url or self._get_database_url()
        self.engine: Optional[Engine] = None
        self.inspector = None

    def _get_database_url(self) -> str:
        """Get database URL with fallback logic."""
        # Use the centralized get_database_url function
        from src.config import get_database_url

        return get_database_url()

    def connect(self) -> bool:
        """Establish database connection."""
        if not SQLALCHEMY_AVAILABLE:
            logger.error("❌ SQLAlchemy not available - cannot verify schemas")
            return False

        try:
            self.engine = create_engine(self.database_url)
            self.inspector = inspect(self.engine)

            # Test connection
            with self.engine.connect() as conn:
                conn.execute(text("SELECT 1"))

            logger.info(f"✅ Connected to database: {self.database_url[:50]}...")
            return True

        except Exception as e:
            logger.error(f"❌ Failed to connect to database: {e}")
            return False

    def get_table_info(self, table_name: str) -> Optional[Dict[str, Any]]:
        """Get detailed information about a table."""
        if not self.inspector:
            return None

        try:
            if table_name not in self.inspector.get_table_names():
                return None

            columns = self.inspector.get_columns(table_name)
            indexes = self.inspector.get_indexes(table_name)

            return {
                "exists": True,
                "columns": {col["name"]: str(col["type"]).lower() for col in columns},
                "column_count": len(columns),
                "indexes": [idx["name"] for idx in indexes],
                "raw_columns": columns,
            }

        except Exception as e:
            logger.error(f"❌ Error getting table info for {table_name}: {e}")
            return None

    def verify_table_schema(
        self, table_name: str, expected_schema: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Verify a single table against expected schema."""
        result = {
            "table_name": table_name,
            "exists": False,
            "schema_match": False,
            "missing_fields": [],
            "extra_fields": [],
            "type_mismatches": [],
            "field_count": 0,
            "issues": [],
        }

        table_info = self.get_table_info(table_name)
        if not table_info:
            result["issues"].append(f"Table '{table_name}' does not exist")
            return result

        result["exists"] = True
        result["field_count"] = table_info["column_count"]

        # Check required fields
        required_fields = expected_schema["required_fields"]
        actual_columns = table_info["columns"]

        # Find missing fields
        for field_name, expected_type in required_fields.items():
            if field_name not in actual_columns:
                result["missing_fields"].append(field_name)
                result["issues"].append(f"Missing required field: {field_name}")

        # Find extra fields (not necessarily an issue)
        for field_name in actual_columns:
            if field_name not in required_fields:
                result["extra_fields"].append(field_name)

        # Check field types for existing fields
        for field_name, expected_type in required_fields.items():
            if field_name in actual_columns:
                actual_type = actual_columns[field_name]
                if not self._types_compatible(actual_type, expected_type):
                    result["type_mismatches"].append(
                        {
                            "field": field_name,
                            "expected": expected_type,
                            "actual": actual_type,
                        }
                    )
                    result["issues"].append(
                        f"Type mismatch for {field_name}: expected {expected_type}, got {actual_type}"
                    )

        # Overall schema match
        result["schema_match"] = (
            len(result["missing_fields"]) == 0 and len(result["type_mismatches"]) == 0
        )

        return result

    def _types_compatible(self, actual_type: str, expected_type: str) -> bool:
        """Check if database types are compatible."""
        actual_type = actual_type.lower()
        expected_type = expected_type.lower()

        # Exact match
        if actual_type == expected_type:
            return True

        # Text/String types
        text_types = ["text", "varchar", "character varying", "string", "char"]
        if expected_type == "text" and any(t in actual_type for t in text_types):
            return True

        # Numeric types (includes real, decimal, numeric)
        numeric_types = ["real", "float", "double", "numeric", "decimal", "money"]
        if expected_type in ["real", "numeric"] and any(
            t in actual_type for t in numeric_types
        ):
            return True

        # Integer types (includes bigint)
        int_types = ["integer", "int", "bigint", "smallint", "serial", "bigserial"]
        if expected_type in ["integer", "bigint"] and any(
            t in actual_type for t in int_types
        ):
            return True

        # Timestamp/datetime types
        timestamp_types = [
            "timestamp",
            "datetime",
            "timestamptz",
            "timestamp with time zone",
        ]
        if expected_type == "timestamp" and any(
            t in actual_type for t in timestamp_types
        ):
            return True

        # Date types
        date_types = ["date"]
        if expected_type == "date" and any(t in actual_type for t in date_types):
            return True

        # Boolean types
        bool_types = ["boolean", "bool", "bit"]
        if expected_type == "boolean" and any(t in actual_type for t in bool_types):
            return True

        # JSON types
        json_types = ["json", "jsonb", "text"]  # JSON often stored as text
        if expected_type == "json" and any(t in actual_type for t in json_types):
            return True

        return False

    def get_table_row_counts(self, table_names: List[str]) -> Dict[str, int]:
        """Get row counts for specified tables."""
        counts = {}

        if not self.engine:
            return counts

        try:
            with self.engine.connect() as conn:
                for table_name in table_names:
                    try:
                        result = conn.execute(
                            text(f"SELECT COUNT(*) FROM {table_name}")
                        )
                        counts[table_name] = result.scalar()
                    except Exception as e:
                        logger.warning(f"Could not get row count for {table_name}: {e}")
                        counts[table_name] = -1

        except Exception as e:
            logger.error(f"Error getting row counts: {e}")

        return counts

    def verify_all_schemas(self, verbose: bool = False) -> Dict[str, Any]:
        """Verify all expected schemas."""
        if not self.connect():
            return {"error": "Could not connect to database"}

        results = {
            "database_url": (
                self.database_url[:50] + "..."
                if len(self.database_url) > 50
                else self.database_url
            ),
            "timestamp": str(pd.Timestamp.now()),
            "tables": {},
            "summary": {
                "total_tables": len(EXPECTED_SCHEMAS),
                "tables_exist": 0,
                "schemas_match": 0,
                "total_issues": 0,
            },
        }

        # Verify each table
        for table_name, expected_schema in EXPECTED_SCHEMAS.items():
            table_result = self.verify_table_schema(table_name, expected_schema)
            results["tables"][table_name] = table_result

            # Update summary
            if table_result["exists"]:
                results["summary"]["tables_exist"] += 1
            if table_result["schema_match"]:
                results["summary"]["schemas_match"] += 1
            results["summary"]["total_issues"] += len(table_result["issues"])

        # Get row counts for existing tables
        existing_tables = [
            name for name, info in results["tables"].items() if info["exists"]
        ]
        if existing_tables:
            row_counts = self.get_table_row_counts(existing_tables)
            results["row_counts"] = row_counts

        return results

    def print_verification_report(self, results: Dict[str, Any], verbose: bool = False):
        """Print a formatted verification report."""
        print("\n" + "=" * 80)
        print("DATABASE SCHEMA VERIFICATION REPORT")
        print("=" * 80)

        print(f"\nDatabase: {results['database_url']}")
        print(f"Timestamp: {results['timestamp']}")

        # Summary
        summary = results["summary"]
        print(f"\nSUMMARY:")
        print(f"  Total tables expected: {summary['total_tables']}")
        print(f"  Tables that exist: {summary['tables_exist']}")
        print(f"  Schemas that match: {summary['schemas_match']}")
        print(f"  Total issues found: {summary['total_issues']}")

        # Overall status
        if summary["schemas_match"] == summary["total_tables"]:
            print(f"  Status: ✅ ALL SCHEMAS VALID")
        elif summary["tables_exist"] == summary["total_tables"]:
            print(f"  Status: ⚠️  ALL TABLES EXIST BUT SCHEMA ISSUES FOUND")
        else:
            print(f"  Status: ❌ MISSING TABLES OR SCHEMA ISSUES")

        # Table details
        print(f"\nTABLE DETAILS:")
        for table_name, table_info in results["tables"].items():
            status = (
                "✅"
                if table_info["schema_match"]
                else "❌" if table_info["exists"] else "🚫"
            )
            print(f"\n  {status} {table_name}")
            print(f"    Description: {EXPECTED_SCHEMAS[table_name]['description']}")

            if not table_info["exists"]:
                print(f"    Status: Table does not exist")
                continue

            print(f"    Fields: {table_info['field_count']}")

            if "row_counts" in results and table_name in results["row_counts"]:
                count = results["row_counts"][table_name]
                print(
                    f"    Rows: {count:,}"
                    if count >= 0
                    else "    Rows: Unable to count"
                )

            if table_info["missing_fields"]:
                print(f"    Missing fields: {', '.join(table_info['missing_fields'])}")

            if table_info["type_mismatches"]:
                print(f"    Type mismatches: {len(table_info['type_mismatches'])}")
                if verbose:
                    for mismatch in table_info["type_mismatches"]:
                        print(
                            f"      {mismatch['field']}: expected {mismatch['expected']}, got {mismatch['actual']}"
                        )

            if table_info["extra_fields"] and verbose:
                print(f"    Extra fields: {', '.join(table_info['extra_fields'])}")

            if table_info["issues"] and verbose:
                for issue in table_info["issues"]:
                    print(f"    ⚠️  {issue}")

        print("\n" + "=" * 80)


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Verify database schemas",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    parser.add_argument(
        "--database-url", help="Database URL (default: auto-detect from config)"
    )

    parser.add_argument("--table", help="Verify specific table only")

    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Verbose output with detailed field information",
    )

    parser.add_argument("--json", action="store_true", help="Output results as JSON")

    args = parser.parse_args()

    # Initialize verifier
    verifier = SchemaVerifier(database_url=args.database_url)

    # Run verification
    if args.table:
        if args.table not in EXPECTED_SCHEMAS:
            logger.error(f"❌ Unknown table: {args.table}")
            logger.info(f"Available tables: {', '.join(EXPECTED_SCHEMAS.keys())}")
            sys.exit(1)

        if not verifier.connect():
            sys.exit(1)

        result = verifier.verify_table_schema(args.table, EXPECTED_SCHEMAS[args.table])

        if args.json:
            import json

            print(json.dumps(result, indent=2))
        else:
            status = (
                "✅" if result["schema_match"] else "❌" if result["exists"] else "🚫"
            )
            print(f"\n{status} Table: {args.table}")
            if result["issues"]:
                for issue in result["issues"]:
                    print(f"  ⚠️  {issue}")
            else:
                print(f"  Schema is valid")
    else:
        results = verifier.verify_all_schemas(verbose=args.verbose)

        if "error" in results:
            logger.error(f"❌ {results['error']}")
            sys.exit(1)

        if args.json:
            import json

            print(json.dumps(results, indent=2))
        else:
            verifier.print_verification_report(results, verbose=args.verbose)

        # Exit with error code if issues found
        if results["summary"]["total_issues"] > 0:
            sys.exit(1)


if __name__ == "__main__":
    # Import pandas here to avoid import issues if not available
    try:
        import pandas as pd
    except ImportError:
        import datetime

        class MockPandas:
            @staticmethod
            def Timestamp():
                return datetime.datetime.now()

        pd = MockPandas()

    main()
