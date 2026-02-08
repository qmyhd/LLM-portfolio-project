#!/usr/bin/env python3
"""
Unified Database Deployment Script
=================================

Consolidates functionality from:
- init_database.py (database initialization)
- deploy_schema.ps1/.sh (schema deployment)

Provides comprehensive database setup with:
- Schema deployment from SQL files
- RLS policy configuration
- Connection testing
- Schema verification
- Environment-specific configurations
"""

import sys
import argparse
import logging
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
import subprocess
import json

try:
    import sqlparse

    HAS_SQLPARSE = True
except ImportError:
    HAS_SQLPARSE = False

# Add project root and src to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "src"))

# Bootstrap AWS secrets FIRST, before any other src imports
from src.env_bootstrap import bootstrap_env

bootstrap_env()

from src.config import settings
from src.db import get_sync_engine, test_connection, execute_sql

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class UnifiedDatabaseDeployer:
    """Unified database deployment with multiple deployment modes."""

    def __init__(
        self, database_url: Optional[str] = None, schema_dir: Optional[Path] = None
    ):
        self.database_url = database_url or self._get_database_url()
        self.schema_dir = schema_dir or (project_root / "schema")
        self.engine = None

    def _get_database_url(self) -> str:
        """Get database URL with fallback logic."""
        from src.config import get_database_url

        return get_database_url()

    def deploy_full(
        self, force: bool = False, skip_baseline: bool = False
    ) -> Dict[str, Any]:
        """Full deployment: schema + policies + verification."""
        results = {
            "mode": "full_deployment",
            "timestamp": str(pd.Timestamp.now()) if "pd" in globals() else "unknown",
            "steps": {},
            "summary": {"successful_steps": 0, "failed_steps": 0, "total_steps": 0},
        }

        steps = [
            ("Connection Test", self._test_connection),
        ]

        # Only deploy baseline if not skipped and not already present
        if not skip_baseline:
            if not self._is_baseline_applied() or force:
                steps.append(
                    (
                        "Deploy Baseline Schema",
                        lambda: self._deploy_schema_file("000_baseline.sql", force),
                    )
                )
            else:
                # Log that baseline was skipped
                results["steps"]["Deploy Baseline Schema"] = {
                    "success": True,
                    "message": "Baseline schema already applied, skipping (use --force to reapply)",
                    "details": {"skipped": True, "reason": "baseline_already_exists"},
                    "status": "⏭️  SKIPPED",
                }
                results["summary"]["successful_steps"] += 1
                results["summary"]["total_steps"] += 1
        else:
            # Log that baseline was explicitly skipped
            results["steps"]["Deploy Baseline Schema"] = {
                "success": True,
                "message": "Baseline schema deployment skipped via --skip-baseline flag",
                "details": {"skipped": True, "reason": "explicit_skip"},
                "status": "⏭️  SKIPPED",
            }
            results["summary"]["successful_steps"] += 1
            results["summary"]["total_steps"] += 1

        # Add remaining steps
        steps.extend(
            [
                (
                    "Deploy Migrations",
                    lambda: self._deploy_migrations(force),
                ),
                ("Configure RLS Policies", self._configure_rls_policies),
                ("Verify Deployment", self._verify_deployment),
            ]
        )

        results["summary"]["total_steps"] = len(steps)

        for step_name, step_func in steps:
            try:
                success, message, details = step_func()
                results["steps"][step_name] = {
                    "success": success,
                    "message": message,
                    "details": details or {},
                    "status": "✅ SUCCESS" if success else "❌ FAILED",
                }

                if success:
                    results["summary"]["successful_steps"] += 1
                else:
                    results["summary"]["failed_steps"] += 1
                    logger.error(f"Step failed: {step_name} - {message}")

                    # Stop on critical failures unless force is enabled
                    if not force and step_name in [
                        "Connection Test",
                        "Deploy Base Schema",
                    ]:
                        logger.error("Critical step failed, stopping deployment")
                        break

            except Exception as e:
                results["steps"][step_name] = {
                    "success": False,
                    "message": f"Step failed with error: {e}",
                    "details": {},
                    "status": "❌ ERROR",
                }
                results["summary"]["failed_steps"] += 1
                logger.error(f"Step error: {step_name} - {e}")

                if not force:
                    break

        return results

    def deploy_schema_only(self, force: bool = False) -> Dict[str, Any]:
        """Schema-only deployment."""
        results = {
            "mode": "schema_only",
            "timestamp": str(pd.Timestamp.now()) if "pd" in globals() else "unknown",
            "files": {},
            "summary": {"deployed_files": 0, "failed_files": 0},
        }

        # Find all SQL files in schema directory
        sql_files = sorted(self.schema_dir.glob("*.sql"))

        for sql_file in sql_files:
            try:
                success, message, details = self._deploy_schema_file(
                    sql_file.name, force
                )
                results["files"][sql_file.name] = {
                    "success": success,
                    "message": message,
                    "details": details or {},
                    "status": "✅ DEPLOYED" if success else "❌ FAILED",
                }

                if success:
                    results["summary"]["deployed_files"] += 1
                else:
                    results["summary"]["failed_files"] += 1

            except Exception as e:
                results["files"][sql_file.name] = {
                    "success": False,
                    "message": f"Deployment failed: {e}",
                    "details": {},
                    "status": "❌ ERROR",
                }
                results["summary"]["failed_files"] += 1

        return results

    def deploy_policies_only(self) -> Dict[str, Any]:
        """RLS policies-only deployment."""
        results = {
            "mode": "policies_only",
            "timestamp": str(pd.Timestamp.now()) if "pd" in globals() else "unknown",
        }

        success, message, details = self._configure_rls_policies()
        results["success"] = success
        results["message"] = message
        results["details"] = details or {}
        results["status"] = "✅ CONFIGURED" if success else "❌ FAILED"

        return results

    def _test_connection(self) -> Tuple[bool, str, Dict[str, Any]]:
        """Test database connectivity."""
        try:
            connection_info = test_connection()
            if connection_info["status"] == "connected":
                return (
                    True,
                    f"Connected to {connection_info.get('database', 'database')}",
                    connection_info,
                )
            else:
                return (
                    False,
                    f"Connection failed: {connection_info.get('error', 'Unknown error')}",
                    connection_info,
                )
        except Exception as e:
            return False, f"Connection test failed: {e}", {}

    def _deploy_migrations(
        self, force: bool = False
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """Deploy all migration files (NNN_*.sql) in numeric order, excluding baseline and archive."""
        try:
            # Find all migration files (NNN_*.sql) excluding baseline and archive
            migration_files = []
            for sql_file in self.schema_dir.glob("*.sql"):
                if sql_file.name != "000_baseline.sql" and "archive" not in str(
                    sql_file.parent
                ):
                    # Extract number from filename (e.g., 014_security_fixes.sql -> 014)
                    try:
                        file_num = int(sql_file.name[:3])
                        migration_files.append((file_num, sql_file))
                    except ValueError:
                        # Skip non-numbered files
                        continue

            # Sort migrations by number
            migration_files.sort(key=lambda x: x[0])

            deployed_count = 0
            skipped_count = 0
            errors = []

            for file_num, migration_file in migration_files:
                success, message, details = self._deploy_schema_file(
                    migration_file.name, force
                )
                if success:
                    if details.get("skipped", False):
                        skipped_count += 1
                    else:
                        deployed_count += 1
                else:
                    errors.append(f"{migration_file.name}: {message}")

            if errors:
                return (
                    False,
                    f"Migration errors: {'; '.join(errors)}",
                    {"errors": errors},
                )

            return (
                True,
                f"Deployed {deployed_count} migrations, skipped {skipped_count}",
                {
                    "deployed": deployed_count,
                    "skipped": skipped_count,
                    "total_files": len(migration_files),
                },
            )

        except Exception as e:
            return False, f"Failed to deploy migrations: {e}", {"error": str(e)}

    def _deploy_schema_file(
        self, filename: str, force: bool = False
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """Deploy a single schema file."""
        schema_file = self.schema_dir / filename

        if not schema_file.exists():
            return False, f"Schema file not found: {filename}", {}

        try:
            # Read SQL content
            sql_content = schema_file.read_text(encoding="utf-8")

            # Check if already applied (look for migration record)
            migration_name = Path(filename).stem  # Remove .sql extension
            if not force and self._is_migration_applied(migration_name):
                return (
                    True,
                    f"Migration {migration_name} already applied (use --force to reapply)",
                    {"skipped": True, "migration_name": migration_name},
                )

            # Execute SQL
            statements = self._split_sql_statements(sql_content)
            executed_statements = 0

            for statement in statements:
                statement = statement.strip()
                if not statement or statement.startswith("--"):
                    continue

                execute_sql(statement)
                executed_statements += 1

            # Record migration
            self._record_migration(migration_name)

            return (
                True,
                f"Deployed {filename}: {executed_statements} statements executed",
                {
                    "file": filename,
                    "statements_executed": executed_statements,
                    "migration_recorded": True,
                },
            )

        except Exception as e:
            return (
                False,
                f"Failed to deploy {filename}: {e}",
                {"file": filename, "error": str(e)},
            )

    def _configure_rls_policies(self) -> Tuple[bool, str, Dict[str, Any]]:
        """Configure Row Level Security policies."""
        # PostgreSQL-only system, always configure RLS
        policies_configured = 0
        errors = []

        # Core tables that need RLS (as specified in user requirements)
        # Note: discord_processing_log was dropped in migration 049
        tables_with_rls = [
            "accounts",
            "account_balances",
            "positions",
            "symbols",
            "schema_migrations",
        ]

        try:
            for table in tables_with_rls:
                try:
                    # Enable RLS on table
                    execute_sql(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")

                    # Create service role allow-all policy (if not exists)
                    policy_sql = f"""
                        DO $$ BEGIN
                            IF NOT EXISTS (
                                SELECT 1 FROM pg_policies 
                                WHERE tablename = '{table}' 
                                AND policyname = 'service_role_all'
                            ) THEN
                                CREATE POLICY "service_role_all" ON {table}
                                FOR ALL TO service_role USING (true) WITH CHECK (true);
                            END IF;
                        END $$;
                    """
                    execute_sql(policy_sql)
                    policies_configured += 1

                except Exception as e:
                    # Table might not exist, that's ok for some tables
                    if "does not exist" not in str(e).lower():
                        errors.append(f"{table}: {e}")

            success = len(errors) == 0
            message = f"Configured RLS policies for {policies_configured} tables"
            if errors:
                message += f", {len(errors)} errors"

            return (
                success,
                message,
                {
                    "policies_configured": policies_configured,
                    "errors": errors,
                    "tables_processed": len(tables_with_rls),
                },
            )

        except Exception as e:
            return (
                False,
                f"RLS configuration failed: {e}",
                {"policies_configured": policies_configured, "error": str(e)},
            )

    def _verify_deployment(self) -> Tuple[bool, str, Dict[str, Any]]:
        """Verify deployment by running basic checks."""
        try:
            # Use the unified verifier for consistency
            from scripts.verify_database import UnifiedDatabaseVerifier

            verifier = UnifiedDatabaseVerifier(self.database_url)
            basic_results = verifier.verify_basic()

            success = (
                basic_results["database_connected"]
                and basic_results["summary"]["tables_exist"] >= 3  # Minimum expected
            )

            message = (
                f"Verification: {basic_results['summary']['tables_exist']} tables exist"
            )
            if basic_results["summary"]["issues"]:
                message += f", {len(basic_results['summary']['issues'])} issues found"

            return (
                success,
                message,
                {
                    "tables_exist": basic_results["summary"]["tables_exist"],
                    "issues_found": len(basic_results["summary"]["issues"]),
                    "verification_details": basic_results,
                },
            )

        except Exception as e:
            return False, f"Verification failed: {e}", {"error": str(e)}

    def _is_migration_applied(self, migration_name: str) -> bool:
        """Check if migration is already applied."""
        try:
            result = execute_sql(
                "SELECT version FROM schema_migrations WHERE version = :migration_name",
                {"migration_name": migration_name},
                fetch_results=True,
            )
            return bool(result)
        except Exception:
            # Table might not exist yet
            return False

    def _is_baseline_applied(self) -> bool:
        """
        Check if baseline schema is already applied by looking for core tables.
        This allows skipping baseline.sql if database is already initialized.
        """
        try:
            # Check if 'accounts' table exists - a core table that's only created in baseline
            result = execute_sql(
                """
                SELECT EXISTS (
                    SELECT 1 FROM information_schema.tables 
                    WHERE table_name = 'accounts' AND table_schema = 'public'
                )
                """,
                fetch_results=True,
            )
            return result[0][0] if result else False
        except Exception as e:
            logger.debug(f"Could not check baseline status: {e}")
            # If we can't check, assume it's not applied
            return False

    def _record_migration(self, migration_name: str):
        """Record migration in schema_migrations table."""
        try:
            # Ensure table exists
            execute_sql(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version VARCHAR(255) PRIMARY KEY,
                    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """
            )

            # Record migration
            execute_sql(
                "INSERT INTO schema_migrations (version) VALUES (:migration_name) ON CONFLICT (version) DO NOTHING",
                {"migration_name": migration_name},
            )
        except Exception as e:
            logger.warning(f"Could not record migration {migration_name}: {e}")

    def _split_sql_statements(self, sql_content: str) -> List[str]:
        """
        Split SQL content into individual statements using sqlparse.

        Handles:
        - DO $$ blocks (treated as single statements)
        - -- and /* */ comments (preserved in context, but leading comments removed)
        - Multi-line statements (preserves structure)
        - Quoted strings and identifiers
        """
        if not HAS_SQLPARSE:
            logger.debug("sqlparse not available, using simple SQL splitter")
            return self._split_sql_statements_simple(sql_content)

        try:
            # Use sqlparse to split statements - respects DO blocks and comments
            parsed = sqlparse.parse(sql_content)
            statements = []

            for statement in parsed:
                # Convert statement back to string and strip whitespace
                stmt_str = str(statement).strip()

                # Skip empty statements
                if not stmt_str:
                    continue

                # Skip comment-only statements
                if stmt_str.startswith("--") or stmt_str.startswith("/*"):
                    continue

                statements.append(stmt_str)

            return statements
        except Exception as e:
            logger.warning(f"sqlparse failed, falling back to simple split: {e}")
            # Fallback to simple split if sqlparse fails
            return self._split_sql_statements_simple(sql_content)

    def _split_sql_statements_simple(self, sql_content: str) -> List[str]:
        """
        Simple fallback SQL statement splitter.
        Preserves newlines and handles basic cases when sqlparse is unavailable.
        """
        statements = []
        current_statement = []
        in_single_quote = False
        in_double_quote = False
        in_block_comment = False
        i = 0

        while i < len(sql_content):
            char = sql_content[i]
            next_char = sql_content[i + 1] if i + 1 < len(sql_content) else None

            # Handle block comments /* */
            if not in_single_quote and not in_double_quote:
                if char == "/" and next_char == "*":
                    in_block_comment = True
                    current_statement.append(char)
                    i += 1
                    current_statement.append(next_char)
                    i += 1
                    continue
                elif char == "*" and next_char == "/" and in_block_comment:
                    in_block_comment = False
                    current_statement.append(char)
                    i += 1
                    current_statement.append(next_char)
                    i += 1
                    continue

            # Handle quotes
            if char == "'" and not in_double_quote and not in_block_comment:
                in_single_quote = not in_single_quote
            elif char == '"' and not in_single_quote and not in_block_comment:
                in_double_quote = not in_double_quote

            # Handle line comments (only outside quotes/blocks)
            if (
                char == "-"
                and next_char == "-"
                and not in_single_quote
                and not in_double_quote
                and not in_block_comment
            ):
                # Skip until end of line
                while i < len(sql_content) and sql_content[i] != "\n":
                    i += 1
                if i < len(sql_content):
                    current_statement.append("\n")
                    i += 1
                continue

            # Handle statement terminator
            if (
                char == ";"
                and not in_single_quote
                and not in_double_quote
                and not in_block_comment
            ):
                current_statement.append(char)
                stmt = "".join(current_statement).strip()
                if stmt and not stmt.startswith("--"):
                    statements.append(stmt)
                current_statement = []
                i += 1
                continue

            current_statement.append(char)
            i += 1

        # Add final statement if exists
        if current_statement:
            stmt = "".join(current_statement).strip()
            if stmt and not stmt.startswith("--"):
                statements.append(stmt)

        return statements


def print_deployment_results(results: Dict[str, Any], verbose: bool = False):
    """Print deployment results in a formatted way."""
    mode = results.get("mode", "unknown")
    timestamp = results.get("timestamp", "unknown")

    print(f"\n{'='*80}")
    print(f"DATABASE DEPLOYMENT RESULTS - {mode.upper()}")
    print(f"{'='*80}")
    print(f"Timestamp: {timestamp}")

    if mode == "full_deployment":
        print_full_deployment_results(results, verbose)
    elif mode == "schema_only":
        print_schema_deployment_results(results, verbose)
    elif mode == "policies_only":
        print_policies_deployment_results(results, verbose)


def print_full_deployment_results(results: Dict[str, Any], verbose: bool):
    """Print full deployment results."""
    summary = results["summary"]

    print(
        f"\nSUMMARY: {summary['successful_steps']}/{summary['total_steps']} steps completed"
    )

    print(f"\nDEPLOYMENT STEPS:")
    for step_name, info in results["steps"].items():
        print(f"  {info['status']} {step_name}")

        if verbose or not info["success"]:
            print(f"    {info['message']}")

            if info.get("details") and verbose:
                details = info["details"]
                for key, value in details.items():
                    print(f"      {key}: {value}")


def print_schema_deployment_results(results: Dict[str, Any], verbose: bool):
    """Print schema deployment results."""
    summary = results["summary"]

    print(
        f"\nSUMMARY: {summary['deployed_files']} deployed, {summary['failed_files']} failed"
    )

    print(f"\nSCHEMA FILES:")
    for filename, info in results["files"].items():
        print(f"  {info['status']} {filename}")

        if verbose or not info["success"]:
            print(f"    {info['message']}")


def print_policies_deployment_results(results: Dict[str, Any], verbose: bool):
    """Print policies deployment results."""
    print(f"\nRLS POLICIES: {results['status']}")
    print(f"Message: {results['message']}")

    if verbose and results.get("details"):
        details = results["details"]
        for key, value in details.items():
            print(f"  {key}: {value}")


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Unified database deployment",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python deploy_database.py                         # Full deployment
  python deploy_database.py --schema-only          # Schema files only
  python deploy_database.py --policies-only        # RLS policies only
  python deploy_database.py --force                # Force reapply migrations
  python deploy_database.py --skip-baseline        # Skip baseline.sql (use for existing DBs)
  python deploy_database.py --skip-baseline --force # Force remaining migrations, skip baseline
        """,
    )

    parser.add_argument(
        "--schema-only", action="store_true", help="Deploy schema files only"
    )
    parser.add_argument(
        "--policies-only", action="store_true", help="Configure RLS policies only"
    )
    parser.add_argument(
        "--skip-baseline",
        action="store_true",
        help="Skip baseline.sql deployment (use if database already has core tables)",
    )
    parser.add_argument(
        "--force", action="store_true", help="Force reapply existing migrations"
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    parser.add_argument("--database-url", help="Database URL (default: from config)")
    parser.add_argument(
        "--schema-dir", type=Path, help="Schema directory (default: ./schema)"
    )

    args = parser.parse_args()

    # Initialize deployer
    deployer = UnifiedDatabaseDeployer(args.database_url, args.schema_dir)

    # Run deployment
    if args.schema_only:
        results = deployer.deploy_schema_only(args.force)
    elif args.policies_only:
        results = deployer.deploy_policies_only()
    else:
        results = deployer.deploy_full(args.force, skip_baseline=args.skip_baseline)

    # Output results
    if args.json:
        print(json.dumps(results, indent=2, default=str))
    else:
        print_deployment_results(results, args.verbose)

    # Exit with appropriate code
    if results.get("mode") == "full_deployment":
        return 1 if results["summary"]["failed_steps"] > 0 else 0
    elif results.get("mode") == "schema_only":
        return 1 if results["summary"]["failed_files"] > 0 else 0
    elif results.get("mode") == "policies_only":
        return 1 if not results.get("success") else 0

    return 0


if __name__ == "__main__":
    # Import pandas if available for timestamps
    try:
        import pandas as pd
    except ImportError:
        import datetime

        class MockPandas:
            @staticmethod
            def Timestamp():
                return datetime.datetime.now()

        pd = MockPandas()

    sys.exit(main())
