#!/usr/bin/env python3
"""
Unified Database Deployment Script
===================================

Migration runner for the LLM Portfolio Journal.

Design principles
-----------------
* **Immutable ledger** – once a migration file is applied, it is NEVER edited.
  Fixes go in a new NNN_*.sql file.
* **Exact-key tracking** – the ``schema_migrations`` table stores the full
  filename stem (e.g. ``061_cleanup_migration_ledger``), not a numeric prefix.
* **Baseline + incremental** – fresh installs execute ``060_baseline_current.sql``
  to create the entire schema, then run any subsequent migrations.  Existing
  databases skip the baseline and run only unapplied migrations.
* **Raw psycopg2 execution** – migrations are executed as-is through the
  PostgreSQL wire protocol, avoiding SQL-splitting bugs with ``DO $$`` blocks,
  dollar-quoted functions, or embedded semicolons.

Directory layout
----------------
::

    schema/
        060_baseline_current.sql   ← full schema snapshot for fresh installs
        061_*.sql                  ← incremental migrations
        archive/                   ← retired migrations (000-059), kept for
                                     reference but never executed
"""

import sys
import argparse
import logging
import json
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple

# ---------------------------------------------------------------------------
# Path bootstrapping
# ---------------------------------------------------------------------------
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "src"))

from src.env_bootstrap import bootstrap_env

bootstrap_env()

from src.config import settings
from src.db import get_sync_engine, test_connection, execute_sql

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Baseline filename constant
# ---------------------------------------------------------------------------
BASELINE_STEM = "060_baseline_current"


class UnifiedDatabaseDeployer:
    """Database deployer that honours the immutable-ledger convention."""

    def __init__(
        self,
        database_url: Optional[str] = None,
        schema_dir: Optional[Path] = None,
        *,
        dry_run: bool = False,
    ):
        self.database_url = database_url or self._get_database_url()
        self.schema_dir = schema_dir or (project_root / "schema")
        self.dry_run = dry_run

    # ------------------------------------------------------------------
    # Public entry points
    # ------------------------------------------------------------------

    def deploy_full(
        self, force: bool = False, skip_baseline: bool = False
    ) -> Dict[str, Any]:
        """Full deployment: connection test -> baseline -> migrations -> RLS -> verify.

        When ``self.dry_run`` is *True* the deployer reports what *would* happen
        without executing any SQL or recording any ledger entries.
        """
        if self.dry_run:
            return self._dry_run_report(force, skip_baseline)

        results: Dict[str, Any] = {
            "mode": "full_deployment",
            "steps": {},
            "summary": {"successful_steps": 0, "failed_steps": 0, "total_steps": 0},
        }

        steps: List[Tuple[str, Any]] = [
            ("Connection Test", self._test_connection),
        ]

        # Decide whether to run the baseline
        if not skip_baseline:
            is_existing = self._is_database_initialised()
            if is_existing and not force:
                # Mark baseline as applied without executing it
                self._record_migration(BASELINE_STEM)
                results["steps"]["Deploy Baseline Schema"] = {
                    "success": True,
                    "message": "Existing database detected - baseline marked applied (skip)",
                    "details": {"skipped": True},
                    "status": "SKIPPED",
                }
                results["summary"]["successful_steps"] += 1
                results["summary"]["total_steps"] += 1
            else:
                steps.append(
                    (
                        "Deploy Baseline Schema",
                        lambda: self._deploy_single_file(f"{BASELINE_STEM}.sql", force),
                    )
                )
        else:
            results["steps"]["Deploy Baseline Schema"] = {
                "success": True,
                "message": "Baseline skipped via --skip-baseline",
                "details": {"skipped": True},
                "status": "SKIPPED",
            }
            results["summary"]["successful_steps"] += 1
            results["summary"]["total_steps"] += 1

        steps.extend(
            [
                ("Deploy Migrations", lambda: self._deploy_migrations(force)),
                ("Configure RLS Policies", self._configure_rls_policies),
                ("Verify Deployment", self._verify_deployment),
            ]
        )

        results["summary"]["total_steps"] += len(steps)

        for step_name, step_func in steps:
            try:
                success, message, details = step_func()
                status = "SUCCESS" if success else "FAILED"
                results["steps"][step_name] = {
                    "success": success,
                    "message": message,
                    "details": details or {},
                    "status": status,
                }
                if success:
                    results["summary"]["successful_steps"] += 1
                    logger.info("Step succeeded: %s", step_name)
                else:
                    results["summary"]["failed_steps"] += 1
                    logger.error("Step FAILED: %s - %s", step_name, message)
                    if not force:
                        logger.error(
                            "Aborting deployment (use --force to continue past errors)"
                        )
                        break
            except Exception as e:
                results["steps"][step_name] = {
                    "success": False,
                    "message": f"Exception: {e}",
                    "details": {},
                    "status": "ERROR",
                }
                results["summary"]["failed_steps"] += 1
                logger.error(f"Step error: {step_name} - {e}")
                if not force:
                    break

        return results

    def deploy_schema_only(self, force: bool = False) -> Dict[str, Any]:
        """Deploy all schema/*.sql files (baseline + migrations).

        Stops on first failure.
        """
        results: Dict[str, Any] = {
            "mode": "schema_only",
            "files": {},
            "summary": {"deployed_files": 0, "failed_files": 0},
        }
        for sql_file in self._sorted_migration_files(include_baseline=True):
            try:
                ok, msg, det = self._deploy_single_file(sql_file.name, force)
                if det.get("skipped"):
                    status = "SKIPPED"
                elif ok:
                    status = "DEPLOYED"
                else:
                    status = "FAILED"
                results["files"][sql_file.name] = {
                    "success": ok,
                    "message": msg,
                    "details": det or {},
                    "status": status,
                }
                if ok:
                    results["summary"]["deployed_files"] += 1
                else:
                    results["summary"]["failed_files"] += 1
                    if not force:
                        break  # stop on first failure
            except Exception as e:
                results["files"][sql_file.name] = {
                    "success": False,
                    "message": str(e),
                    "details": {},
                    "status": "ERROR",
                }
                results["summary"]["failed_files"] += 1
                if not force:
                    break  # stop on first failure
        return results

    def deploy_policies_only(self) -> Dict[str, Any]:
        """RLS policies-only deployment."""
        ok, msg, det = self._configure_rls_policies()
        return {
            "mode": "policies_only",
            "success": ok,
            "message": msg,
            "details": det or {},
            "status": "CONFIGURED" if ok else "FAILED",
        }

    # ------------------------------------------------------------------
    # Dry-run
    # ------------------------------------------------------------------

    def _dry_run_report(
        self, force: bool = False, skip_baseline: bool = False
    ) -> Dict[str, Any]:
        """Read-only report of what *would* be applied."""
        results: Dict[str, Any] = {
            "mode": "dry_run",
            "pending": [],
            "skipped": [],
            "summary": {"pending_count": 0, "skipped_count": 0},
        }

        # Baseline decision
        if not skip_baseline:
            is_existing = self._is_database_initialised()
            if is_existing and not force:
                results["skipped"].append(f"{BASELINE_STEM}.sql (existing DB)")
            else:
                if not self._is_migration_applied(BASELINE_STEM) or force:
                    results["pending"].append(f"{BASELINE_STEM}.sql")
                else:
                    results["skipped"].append(f"{BASELINE_STEM}.sql (already applied)")
        else:
            results["skipped"].append(f"{BASELINE_STEM}.sql (--skip-baseline)")

        # Incremental migrations
        for mf in self._sorted_migration_files(include_baseline=False):
            if not force and self._is_migration_applied(mf.stem):
                results["skipped"].append(f"{mf.name} (already applied)")
            else:
                results["pending"].append(mf.name)

        results["summary"]["pending_count"] = len(results["pending"])
        results["summary"]["skipped_count"] = len(results["skipped"])
        return results

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _get_database_url() -> str:
        from src.config import get_database_url

        return get_database_url()

    def _sorted_migration_files(self, *, include_baseline: bool = False) -> List[Path]:
        """Return schema/*.sql sorted by numeric prefix.  Ignores archive/."""
        files: List[Path] = []
        for p in self.schema_dir.glob("*.sql"):
            try:
                int(p.name[:3])
            except (ValueError, IndexError):
                continue
            if not include_baseline and p.stem == BASELINE_STEM:
                continue
            files.append(p)
        files.sort(key=lambda p: int(p.name[:3]))
        return files

    # ------------------------------------------------------------------
    # Migration execution
    # ------------------------------------------------------------------

    def _deploy_migrations(
        self, force: bool = False
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """Deploy incremental migrations (everything except baseline).

        Stops on the first failure so the ledger never records a version that
        only partially applied.
        """
        migration_files = self._sorted_migration_files(include_baseline=False)
        deployed = skipped = 0
        errors: List[str] = []

        for mf in migration_files:
            logger.info("Processing migration: %s", mf.name)
            ok, msg, det = self._deploy_single_file(mf.name, force)
            if ok:
                if det.get("skipped"):
                    skipped += 1
                    logger.info("  -> SKIPPED (already applied)")
                else:
                    deployed += 1
                    logger.info("  -> APPLIED")
            else:
                errors.append(f"{mf.name}: {msg}")
                logger.error("  -> FAILED: %s", msg)
                break  # stop on first failure

        if errors:
            return False, f"Errors: {'; '.join(errors)}", {"errors": errors}
        return (
            True,
            f"Deployed {deployed}, skipped {skipped}",
            {"deployed": deployed, "skipped": skipped, "total": len(migration_files)},
        )

    def _deploy_single_file(
        self, filename: str, force: bool = False
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """Deploy one SQL file.  Tracks by exact filename stem."""
        sql_path = self.schema_dir / filename
        if not sql_path.exists():
            return False, f"File not found: {filename}", {}

        stem = sql_path.stem  # e.g. '061_cleanup_migration_ledger'

        if not force and self._is_migration_applied(stem):
            return (
                True,
                f"{stem} already applied",
                {"skipped": True, "migration": stem},
            )

        try:
            sql = sql_path.read_text(encoding="utf-8")
            self._execute_raw(sql)
            self._record_migration(stem)
            logger.info(f"Applied {filename}")
            return True, f"Deployed {filename}", {"migration": stem}
        except Exception as e:
            logger.error(f"Failed {filename}: {e}")
            return False, f"Failed: {e}", {"migration": stem, "error": str(e)}

    # ------------------------------------------------------------------
    # Raw psycopg2 execution (no SQL splitting)
    # ------------------------------------------------------------------

    @staticmethod
    def _execute_raw(sql_content: str) -> None:
        """Execute an entire migration file in one transaction via raw psycopg2.

        Uses ``autocommit = False`` (the default) so the whole file runs in a
        single transaction.  On success we ``COMMIT``; on any error we
        ``ROLLBACK`` so a failed migration leaves no partial state.

        This avoids SQL statement splitting which breaks on:
        - ``DO $$ ... $$`` blocks
        - ``CREATE FUNCTION ... AS $function$ ... $function$``
        - Any PL/pgSQL containing semicolons inside dollar-quoted strings
        """
        engine = get_sync_engine()
        raw = engine.raw_connection()
        try:
            raw.autocommit = False  # explicit transaction
            cur = raw.cursor()
            cur.execute(sql_content)
            raw.commit()
            cur.close()
            logger.debug("Raw SQL executed and committed (%d chars)", len(sql_content))
        except Exception:
            raw.rollback()
            raise
        finally:
            raw.close()

    # ------------------------------------------------------------------
    # Ledger helpers
    # ------------------------------------------------------------------

    def _is_migration_applied(self, stem: str) -> bool:
        """Check for an exact match on the full filename stem."""
        try:
            rows = execute_sql(
                "SELECT 1 FROM schema_migrations WHERE version = :v",
                {"v": stem},
                fetch_results=True,
            )
            return bool(rows)
        except Exception:
            return False

    @staticmethod
    def _record_migration(stem: str) -> None:
        """Insert into the ledger (upsert for safety)."""
        try:
            execute_sql(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version    TEXT PRIMARY KEY,
                    description TEXT,
                    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            execute_sql(
                "INSERT INTO schema_migrations (version) VALUES (:v) "
                "ON CONFLICT (version) DO NOTHING",
                {"v": stem},
            )
        except Exception as e:
            logger.warning(f"Could not record migration {stem}: {e}")

    def _is_database_initialised(self) -> bool:
        """True when the public schema already has user tables beyond just
        ``schema_migrations``.

        The baseline should only run on a *completely* empty database (zero
        public tables, or only the ``schema_migrations`` bookkeeping table).
        """
        try:
            rows = execute_sql(
                """
                SELECT table_name
                FROM   information_schema.tables
                WHERE  table_schema = 'public'
                  AND  table_type   = 'BASE TABLE'
                  AND  table_name  != 'schema_migrations'
                LIMIT 1
                """,
                fetch_results=True,
            )
            has_user_tables = bool(rows)
            if has_user_tables:
                logger.info("Existing database detected (found table: %s)", rows[0][0])
            else:
                logger.info("Empty database detected - baseline will run")
            return has_user_tables
        except Exception as exc:
            logger.warning("Could not check DB state (%s); assuming existing", exc)
            return True  # safe default: skip baseline rather than clobber data

    # ------------------------------------------------------------------
    # RLS configuration
    # ------------------------------------------------------------------

    def _configure_rls_policies(self) -> Tuple[bool, str, Dict[str, Any]]:
        """Ensure RLS + service_role policy exist on core tables."""
        core_tables = [
            "accounts",
            "account_balances",
            "positions",
            "symbols",
            "schema_migrations",
        ]
        configured = 0
        errors: List[str] = []

        for table in core_tables:
            try:
                execute_sql(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")
                execute_sql(
                    f"""
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
                )
                configured += 1
            except Exception as e:
                if "does not exist" not in str(e).lower():
                    errors.append(f"{table}: {e}")

        ok = len(errors) == 0
        msg = f"RLS configured for {configured} tables"
        if errors:
            msg += f", {len(errors)} errors"
        return ok, msg, {"configured": configured, "errors": errors}

    # ------------------------------------------------------------------
    # Post-deployment verification
    # ------------------------------------------------------------------

    def _verify_deployment(self) -> Tuple[bool, str, Dict[str, Any]]:
        """Run the schema verifier."""
        try:
            from scripts.verify_database import DatabaseSchemaVerifier

            verifier = DatabaseSchemaVerifier(database_url=self.database_url)
            basic = verifier.verify_basic()
            summary = basic.get("summary", {})
            tables = summary.get("existing_tables", 0)
            missing = summary.get("missing_tables", 0)
            ok = basic["database_connected"] and tables >= 3
            msg = f"{tables} tables found"
            if missing:
                msg += f", {missing} missing"
            return ok, msg, {"tables": tables, "missing": missing}
        except Exception as e:
            return False, f"Verification error: {e}", {"error": str(e)}

    # ------------------------------------------------------------------
    # Connection test
    # ------------------------------------------------------------------

    @staticmethod
    def _test_connection() -> Tuple[bool, str, Dict[str, Any]]:
        try:
            info = test_connection()
            if info["status"] == "connected":
                return True, f"Connected to {info.get('database', 'db')}", info
            return False, f"Failed: {info.get('error', '?')}", info
        except Exception as e:
            return False, str(e), {}


# =========================================================================
# CLI output
# =========================================================================


def _print_results(results: Dict[str, Any], verbose: bool = False) -> None:
    mode = results.get("mode", "unknown")
    print(f"\n{'=' * 70}")
    print(f"  DATABASE DEPLOYMENT - {mode.upper()}")
    print(f"{'=' * 70}")

    if mode == "dry_run":
        s = results["summary"]
        print(
            f"  {s['pending_count']} migration(s) to apply, "
            f"{s['skipped_count']} already applied\n"
        )
        if results["pending"]:
            print("  PENDING:")
            for f in results["pending"]:
                print(f"    - {f}")
        if verbose and results["skipped"]:
            print("  SKIPPED:")
            for f in results["skipped"]:
                print(f"    - {f}")
        if s["pending_count"] == 0:
            print("  Nothing to do — database is up to date.")
    elif mode == "full_deployment":
        s = results["summary"]
        print(f"  {s['successful_steps']}/{s['total_steps']} steps succeeded\n")
        for name, info in results["steps"].items():
            print(f"  [{info['status']}]  {name}")
            if verbose or not info["success"]:
                print(f"           {info['message']}")
    elif mode == "schema_only":
        s = results["summary"]
        print(f"  {s['deployed_files']} deployed, {s['failed_files']} failed\n")
        for fname, info in results["files"].items():
            print(f"  [{info['status']}]  {fname}")
            if verbose or not info["success"]:
                print(f"           {info['message']}")
    elif mode == "policies_only":
        print(f"  [{results['status']}]  {results['message']}")

    print()


# =========================================================================
# CLI entry point
# =========================================================================


def main() -> int:
    parser = argparse.ArgumentParser(
        description="LLM Portfolio Journal - database deployer",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python deploy_database.py                    # Full deploy (auto-detects fresh vs existing)
  python deploy_database.py --dry-run          # Preview what would be applied (read-only)
  python deploy_database.py --skip-baseline    # Existing DB, skip baseline check
  python deploy_database.py --schema-only      # Apply all schema files
  python deploy_database.py --policies-only    # RLS policies only
  python deploy_database.py --force            # Re-apply everything
        """,
    )
    parser.add_argument("--schema-only", action="store_true", help="Schema files only")
    parser.add_argument("--policies-only", action="store_true", help="RLS only")
    parser.add_argument(
        "--skip-baseline",
        action="store_true",
        help="Skip baseline (existing DB)",
    )
    parser.add_argument("--force", action="store_true", help="Force re-apply")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview pending migrations without executing (read-only)",
    )
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument("--json", action="store_true", help="JSON output")
    parser.add_argument("--database-url", help="Override DATABASE_URL")
    parser.add_argument("--schema-dir", type=Path, help="Override schema directory")

    args = parser.parse_args()
    deployer = UnifiedDatabaseDeployer(
        args.database_url, args.schema_dir, dry_run=args.dry_run
    )

    if args.dry_run:
        results = deployer.deploy_full(args.force, skip_baseline=args.skip_baseline)
    elif args.schema_only:
        results = deployer.deploy_schema_only(args.force)
    elif args.policies_only:
        results = deployer.deploy_policies_only()
    else:
        results = deployer.deploy_full(args.force, skip_baseline=args.skip_baseline)

    if args.json:
        print(json.dumps(results, indent=2, default=str))
    else:
        _print_results(results, args.verbose)

    # Exit code
    if results.get("mode") == "dry_run":
        return 0  # read-only, always succeeds
    elif results.get("mode") == "full_deployment":
        return 1 if results["summary"]["failed_steps"] > 0 else 0
    elif results.get("mode") == "schema_only":
        return 1 if results["summary"]["failed_files"] > 0 else 0
    elif results.get("mode") == "policies_only":
        return 0 if results.get("success") else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
