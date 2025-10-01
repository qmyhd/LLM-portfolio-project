#!/usr/bin/env python3
"""
Repository Audit Script for LLM Portfolio Project

Generates comprehensive machine-readable inventory of:
- Repository files and metadata
- Code ownership analysis
- Database schema comparison
- Cleanup and migration plans

Outputs all reports to ./reports/ directory.
"""

import hashlib
import json
import logging
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Set, Union

# Add src to path for imports
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "src"))

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(project_root / "reports" / "audit.log"),
    ],
)
logger = logging.getLogger(__name__)

# Database introspection imports
try:
    import psycopg2
    from psycopg2.extras import RealDictCursor

    PSYCOPG2_AVAILABLE = True
except ImportError:
    logger.warning("psycopg2 not available - database introspection will be limited")
    PSYCOPG2_AVAILABLE = False

try:
    from src.config import get_database_url, settings

    CONFIG_AVAILABLE = True
except ImportError:
    logger.warning("Config module not available")
    CONFIG_AVAILABLE = False


class RepoAuditor:
    """Comprehensive repository auditing and analysis."""

    def __init__(self):
        self.project_root = project_root
        self.reports_dir = self.project_root / "reports"
        self.reports_dir.mkdir(exist_ok=True)

        # Patterns for code analysis
        self.snaptrade_patterns = [
            r"\bSnapTrade\b",
            r"\bsnaptrade\b",
            r"\bget_accounts\b",
            r"\bget_balances\b",
            r"\bget_positions\b",
            r"\bget_orders\b",
            r"\bSNAPTRADE_\w+\b",
        ]

        self.discord_patterns = [
            r"\bextract_ticker\b",
            r"\bextract_ticker_symbols\b",
            r"\bclean_text\b",
            r"\bcalculate_sentiment\b",
            r"\bclean_messages\b",
            r"\bdiscord\w*clean\b",
        ]

        self.db_write_patterns = [
            r"\bto_sql\b",
            r"\bexecute_sql\b",
            r"\bINSERT\s+INTO\b",
            r"\bON\s+CONFLICT\b",
            r"\bto_parquet\b",
            r"\bparquet\b",
            r"\bUPSERT\b",
            r"\bCREATE\s+TABLE\b",
        ]

        self.table_name_patterns = [
            r"\bdiscord_general_clean\b",
            r"\bdiscord_market_clean\b",
            r"\bdiscord_trading_clean\b",
            r"\bdiscord_messages\b",
            r"\baccounts\b",
            r"\baccount_balances\b",
            r"\bpositions\b",
            r"\borders\b",
            r"\bsymbols\b",
            r"\bx_posts_log\b",
            r"\btwitter_data\b",
            r"\bprocessing_status\b",
            r"\bdaily_prices\b",
            r"\brealtime_prices\b",
            r"\bstock_metrics\b",
            r"\bchart_metadata\b",
        ]

        # File exclusion patterns
        self.exclude_patterns = [
            r"__pycache__",
            r"\.pyc$",
            r"\.pyo$",
            r"\.egg-info",
            r"\.git",
            r"\.pytest_cache",
            r"\.vscode",
            r"\.idea",
            r"node_modules",
        ]

        # Markdown docs that may be outdated
        self.potential_outdated_docs = [
            "DDL_CONSOLIDATION_SUMMARY.md",
            "MESSAGE_CLEANER_FIXES.md",
            "SCHEMA_MIGRATION_COMPLETE.md",
            "docs/CONSOLIDATION_PLAN.md",
            "docs/MESSAGE_CLEANER_FIXES.md",
            "docs/REPOSITORY_CLEANUP_COMPLETE.md",
            "docs/REPOSITORY_ORGANIZATION_COMPLETE.md",
            "docs/SCHEMA_MIGRATION_COMPLETE.md",
            "docs/SNAPTRADE_MIGRATION_COMPLETE.md",
        ]

    def calculate_file_hash(self, file_path: Path) -> str:
        """Calculate SHA256 hash of file contents."""
        try:
            with open(file_path, "rb") as f:
                return hashlib.sha256(f.read()).hexdigest()
        except Exception as e:
            logger.warning(f"Could not hash {file_path}: {e}")
            return "error"

    def should_exclude_file(self, file_path: Path) -> bool:
        """Check if file should be excluded from analysis."""
        path_str = str(file_path)
        return any(re.search(pattern, path_str) for pattern in self.exclude_patterns)

    def scan_repository(self) -> Dict[str, Any]:
        """Scan entire repository and build file inventory."""
        logger.info("Scanning repository files...")

        repo_map = {
            "scan_timestamp": datetime.now(timezone.utc).isoformat(),
            "project_root": str(self.project_root),
            "total_files": 0,
            "total_size_bytes": 0,
            "files": {},
        }

        total_files = 0
        total_size = 0

        # Walk through all files in project
        for file_path in self.project_root.rglob("*"):
            if file_path.is_file() and not self.should_exclude_file(file_path):
                try:
                    stat = file_path.stat()
                    relative_path = file_path.relative_to(self.project_root)

                    file_info = {
                        "path": str(relative_path),
                        "absolute_path": str(file_path),
                        "size_bytes": stat.st_size,
                        "last_modified": datetime.fromtimestamp(
                            stat.st_mtime, timezone.utc
                        ).isoformat(),
                        "extension": file_path.suffix.lower(),
                        "sha256": self.calculate_file_hash(file_path),
                    }

                    # Add file type classification
                    if file_path.suffix.lower() in [".py"]:
                        file_info["type"] = "python"
                    elif file_path.suffix.lower() in [".md"]:
                        file_info["type"] = "markdown"
                    elif file_path.suffix.lower() in [".sql"]:
                        file_info["type"] = "sql"
                    elif file_path.suffix.lower() in [".json"]:
                        file_info["type"] = "json"
                    elif file_path.suffix.lower() in [".yaml", ".yml"]:
                        file_info["type"] = "yaml"
                    else:
                        file_info["type"] = "other"

                    repo_map["files"][str(relative_path)] = file_info
                    total_files += 1
                    total_size += stat.st_size

                except Exception as e:
                    logger.warning(f"Error processing {file_path}: {e}")

        repo_map["total_files"] = total_files
        repo_map["total_size_bytes"] = total_size

        logger.info(f"Scanned {total_files} files totaling {total_size:,} bytes")
        return repo_map

    def find_pattern_matches(
        self, content: str, patterns: List[str]
    ) -> List[Tuple[str, List[int]]]:
        """Find all matches for patterns in content with line numbers."""
        matches = []
        lines = content.split("\n")

        for pattern in patterns:
            pattern_matches = []
            for line_no, line in enumerate(lines, 1):
                if re.search(pattern, line, re.IGNORECASE):
                    pattern_matches.append(line_no)

            if pattern_matches:
                matches.append((pattern, pattern_matches))

        return matches

    def analyze_code_ownership(self, repo_map: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze code ownership and identify duplicates."""
        logger.info("Analyzing code ownership patterns...")

        ownership_analysis = {
            "analysis_timestamp": datetime.now(timezone.utc).isoformat(),
            "snaptrade_operations": {
                "primary_files": [],
                "secondary_files": [],
                "duplicates": [],
            },
            "discord_cleaning": {
                "primary_files": [],
                "secondary_files": [],
                "duplicates": [],
            },
            "db_operations": {"writers": [], "targets": []},
            "parquet_operations": {"writers": [], "targets": []},
            "violations": [],
        }

        # Analyze Python files
        for file_path, file_info in repo_map["files"].items():
            if file_info["type"] != "python":
                continue

            try:
                abs_path = Path(file_info["absolute_path"])
                with open(abs_path, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()

                # Check SnapTrade patterns
                snaptrade_matches = self.find_pattern_matches(
                    content, self.snaptrade_patterns
                )
                if snaptrade_matches:
                    match_info = {
                        "file": file_path,
                        "matches": snaptrade_matches,
                        "match_count": sum(
                            len(matches) for _, matches in snaptrade_matches
                        ),
                    }

                    if "snaptrade_collector.py" in file_path:
                        ownership_analysis["snaptrade_operations"][
                            "primary_files"
                        ].append(match_info)
                    else:
                        ownership_analysis["snaptrade_operations"][
                            "secondary_files"
                        ].append(match_info)
                        ownership_analysis["violations"].append(
                            {
                                "type": "snaptrade_violation",
                                "file": file_path,
                                "description": "SnapTrade operations found outside src/snaptrade_collector.py",
                                "matches": snaptrade_matches,
                            }
                        )

                # Check Discord cleaning patterns
                discord_matches = self.find_pattern_matches(
                    content, self.discord_patterns
                )
                if discord_matches:
                    match_info = {
                        "file": file_path,
                        "matches": discord_matches,
                        "match_count": sum(
                            len(matches) for _, matches in discord_matches
                        ),
                    }

                    if "message_cleaner.py" in file_path:
                        ownership_analysis["discord_cleaning"]["primary_files"].append(
                            match_info
                        )
                    elif "channel_processor.py" in file_path:
                        # channel_processor.py is allowed as orchestration
                        ownership_analysis["discord_cleaning"][
                            "secondary_files"
                        ].append(match_info)
                    else:
                        ownership_analysis["discord_cleaning"]["duplicates"].append(
                            match_info
                        )
                        ownership_analysis["violations"].append(
                            {
                                "type": "discord_violation",
                                "file": file_path,
                                "description": "Discord cleaning operations found outside src/message_cleaner.py",
                                "matches": discord_matches,
                            }
                        )

                # Check database write operations
                db_matches = self.find_pattern_matches(content, self.db_write_patterns)
                if db_matches:
                    ownership_analysis["db_operations"]["writers"].append(
                        {
                            "file": file_path,
                            "matches": db_matches,
                            "match_count": sum(
                                len(matches) for _, matches in db_matches
                            ),
                        }
                    )

                # Check for table name references
                table_matches = self.find_pattern_matches(
                    content, self.table_name_patterns
                )
                if table_matches:
                    ownership_analysis["db_operations"]["targets"].append(
                        {
                            "file": file_path,
                            "matches": table_matches,
                            "match_count": sum(
                                len(matches) for _, matches in table_matches
                            ),
                        }
                    )

                # Check Parquet operations
                parquet_patterns = [
                    r"\bto_parquet\b",
                    r"\bread_parquet\b",
                    r"\.parquet",
                ]
                parquet_matches = self.find_pattern_matches(content, parquet_patterns)
                if parquet_matches:
                    ownership_analysis["parquet_operations"]["writers"].append(
                        {
                            "file": file_path,
                            "matches": parquet_matches,
                            "match_count": sum(
                                len(matches) for _, matches in parquet_matches
                            ),
                        }
                    )

            except Exception as e:
                logger.warning(f"Error analyzing {file_path}: {e}")

        logger.info(
            f"Found {len(ownership_analysis['violations'])} code ownership violations"
        )
        return ownership_analysis

    def extract_schema_from_code(self, repo_map: Dict[str, Any]) -> Dict[str, Any]:
        """Extract expected database schema from code analysis."""
        logger.info("Extracting expected schema from code...")

        schema_analysis = {
            "extraction_timestamp": datetime.now(timezone.utc).isoformat(),
            "expected_tables": {},
            "sql_definitions": [],
            "dataframe_schemas": [],
            "conflicts_detected": [],
        }

        # Analyze SQL files
        for file_path, file_info in repo_map["files"].items():
            if file_info["type"] == "sql":
                try:
                    abs_path = Path(file_info["absolute_path"])
                    with open(abs_path, "r", encoding="utf-8") as f:
                        content = f.read()

                    # Extract CREATE TABLE statements
                    create_table_pattern = re.compile(
                        r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(\w+)\s*\((.*?)\);",
                        re.IGNORECASE | re.DOTALL,
                    )

                    for match in create_table_pattern.finditer(content):
                        table_name = match.group(1)
                        table_def = match.group(2)

                        # Parse column definitions
                        columns = []
                        constraints = []

                        for line in table_def.split("\n"):
                            line = line.strip()
                            if not line or line.startswith("--"):
                                continue

                            if line.upper().startswith(
                                ("PRIMARY KEY", "UNIQUE", "FOREIGN KEY", "CHECK")
                            ):
                                constraints.append(line.rstrip(","))
                            elif line and not line.startswith(")"):
                                # Column definition
                                col_parts = line.split()
                                if len(col_parts) >= 2:
                                    col_name = col_parts[0]
                                    col_type = col_parts[1].upper()
                                    col_attrs = " ".join(col_parts[2:]).rstrip(",")

                                    columns.append(
                                        {
                                            "name": col_name,
                                            "type": col_type,
                                            "attributes": col_attrs,
                                        }
                                    )

                        schema_analysis["expected_tables"][table_name] = {
                            "source_file": file_path,
                            "columns": columns,
                            "constraints": constraints,
                        }

                        schema_analysis["sql_definitions"].append(
                            {
                                "file": file_path,
                                "table": table_name,
                                "definition": table_def.strip(),
                            }
                        )

                except Exception as e:
                    logger.warning(f"Error parsing SQL file {file_path}: {e}")

        # Analyze Python files for DataFrame operations
        for file_path, file_info in repo_map["files"].items():
            if file_info["type"] != "python":
                continue

            try:
                abs_path = Path(file_info["absolute_path"])
                with open(abs_path, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()

                # Find DataFrame.to_sql operations
                to_sql_pattern = re.compile(r'\.to_sql\s*\(\s*["\'](\w+)["\']')
                for match in to_sql_pattern.finditer(content):
                    table_name = match.group(1)

                    schema_analysis["dataframe_schemas"].append(
                        {
                            "file": file_path,
                            "table": table_name,
                            "operation": "to_sql",
                            "line_context": self._get_line_context(
                                content, match.start()
                            ),
                        }
                    )

                # Find execute_sql INSERT operations
                insert_pattern = re.compile(r"INSERT\s+INTO\s+(\w+)", re.IGNORECASE)
                for match in insert_pattern.finditer(content):
                    table_name = match.group(1)

                    schema_analysis["dataframe_schemas"].append(
                        {
                            "file": file_path,
                            "table": table_name,
                            "operation": "INSERT",
                            "line_context": self._get_line_context(
                                content, match.start()
                            ),
                        }
                    )

            except Exception as e:
                logger.warning(
                    f"Error analyzing DataFrame operations in {file_path}: {e}"
                )

        logger.info(
            f"Extracted {len(schema_analysis['expected_tables'])} table definitions from code"
        )
        return schema_analysis

    def _get_line_context(
        self, content: str, position: int, context_lines: int = 2
    ) -> Dict[str, Any]:
        """Get line context around a specific position in content."""
        lines = content[:position].count("\n") + 1
        content_lines = content.split("\n")

        start_line = max(0, lines - context_lines - 1)
        end_line = min(len(content_lines), lines + context_lines)

        return {"line_number": lines, "context": content_lines[start_line:end_line]}

    def introspect_database(self) -> Dict[str, Any]:
        """Introspect actual Supabase database schema."""
        logger.info("Introspecting database schema...")

        db_introspection = {
            "introspection_timestamp": datetime.now(timezone.utc).isoformat(),
            "connection_status": "failed",
            "database_info": {},
            "schemas": {},
            "table_counts": {},
            "error": None,
        }

        if not PSYCOPG2_AVAILABLE or not CONFIG_AVAILABLE:
            db_introspection["error"] = (
                "Database introspection dependencies not available"
            )
            return db_introspection

        try:
            database_url = get_database_url()
            if not database_url.startswith("postgresql"):
                db_introspection["error"] = "Not connected to PostgreSQL database"
                return db_introspection

            # Connect to database
            conn = psycopg2.connect(database_url, cursor_factory=RealDictCursor)
            cur = conn.cursor()

            db_introspection["connection_status"] = "connected"

            # Get database info
            cur.execute("SELECT version(), current_database(), current_user")
            version_info = cur.fetchone()
            if version_info:
                db_introspection["database_info"] = {
                    "version": version_info[0],
                    "database_name": version_info[1],
                    "user": version_info[2],
                }
            else:
                db_introspection["database_info"] = {
                    "error": "Could not fetch database info"
                }

            # Get schemas to inspect
            target_schemas = ["public", "twitter_data"]

            for schema_name in target_schemas:
                # Check if schema exists
                cur.execute(
                    """
                    SELECT schema_name FROM information_schema.schemata 
                    WHERE schema_name = :schema_name
                """,
                    {"schema_name": schema_name},
                )

                if not cur.fetchone():
                    continue

                schema_info = {"tables": {}}

                # Get tables in schema
                cur.execute(
                    """
                    SELECT table_name 
                    FROM information_schema.tables 
                    WHERE table_schema = :schema_name AND table_type = 'BASE TABLE'
                    ORDER BY table_name
                """,
                    {"schema_name": schema_name},
                )

                tables = cur.fetchall()

                for table_row in tables:
                    table_name = table_row[0]  # table_name is first column
                    table_info = {"columns": [], "indexes": [], "constraints": []}

                    # Get columns
                    cur.execute(
                        """
                        SELECT column_name, data_type, is_nullable, column_default,
                               character_maximum_length, numeric_precision, numeric_scale
                        FROM information_schema.columns
                        WHERE table_schema = :schema_name AND table_name = :table_name
                        ORDER BY ordinal_position
                    """,
                        {"schema_name": schema_name, "table_name": table_name},
                    )

                    columns = cur.fetchall()
                    for col in columns:
                        table_info["columns"].append(
                            {
                                "name": col[0],  # column_name
                                "data_type": col[1],  # data_type
                                "is_nullable": col[2],  # is_nullable
                                "default": col[3],  # column_default
                                "max_length": col[4],  # character_maximum_length
                                "precision": col[5],  # numeric_precision
                                "scale": col[6],  # numeric_scale
                            }
                        )

                    # Get indexes
                    cur.execute(
                        """
                        SELECT indexname, indexdef
                        FROM pg_indexes
                        WHERE schemaname = :schema_name AND tablename = :table_name
                    """,
                        {"schema_name": schema_name, "table_name": table_name},
                    )

                    indexes = cur.fetchall()
                    for idx in indexes:
                        table_info["indexes"].append(
                            {
                                "name": idx[0],  # indexname
                                "definition": idx[1],  # indexdef
                            }
                        )

                    # Get constraints
                    cur.execute(
                        """
                        SELECT conname, contype, pg_get_constraintdef(c.oid) as condef
                        FROM pg_constraint c
                        JOIN pg_class t ON c.conrelid = t.oid
                        JOIN pg_namespace n ON t.relnamespace = n.oid
                        WHERE n.nspname = :schema_name AND t.relname = :table_name
                    """,
                        {"schema_name": schema_name, "table_name": table_name},
                    )

                    constraints = cur.fetchall()
                    for con in constraints:
                        table_info["constraints"].append(
                            {
                                "name": con[0],  # conname
                                "type": con[1],  # contype
                                "definition": con[2],  # condef
                            }
                        )

                    # Get row count
                    try:
                        cur.execute(
                            f'SELECT COUNT(*) FROM "{schema_name}"."{table_name}"'
                        )
                        count_result = cur.fetchone()
                        count = count_result[0] if count_result else 0
                        db_introspection["table_counts"][
                            f"{schema_name}.{table_name}"
                        ] = count
                    except Exception as e:
                        logger.warning(
                            f"Could not count rows in {schema_name}.{table_name}: {e}"
                        )
                        db_introspection["table_counts"][
                            f"{schema_name}.{table_name}"
                        ] = "error"

                    schema_info["tables"][table_name] = table_info

                db_introspection["schemas"][schema_name] = schema_info

            cur.close()
            conn.close()

            logger.info(
                f"Introspected {len(target_schemas)} schemas with {sum(len(s['tables']) for s in db_introspection['schemas'].values())} tables"
            )

        except Exception as e:
            logger.error(f"Database introspection failed: {e}")
            db_introspection["error"] = str(e)

        return db_introspection

    def generate_deltas(
        self, schema_from_code: Dict[str, Any], db_introspection: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Generate delta analysis between expected and actual schemas."""
        logger.info("Generating schema delta analysis...")

        deltas = {
            "analysis_timestamp": datetime.now(timezone.utc).isoformat(),
            "missing_tables": [],
            "unexpected_tables": [],
            "column_mismatches": [],
            "missing_indexes": [],
            "type_conflicts": [],
            "summary": {},
        }

        if db_introspection["connection_status"] != "connected":
            deltas["error"] = "Cannot perform delta analysis - database not accessible"
            return deltas

        expected_tables = set(schema_from_code["expected_tables"].keys())
        actual_tables = set()

        # Collect actual table names from all schemas
        for schema_name, schema_info in db_introspection["schemas"].items():
            for table_name in schema_info["tables"].keys():
                actual_tables.add(table_name)

        # Find missing and unexpected tables
        deltas["missing_tables"] = list(expected_tables - actual_tables)
        deltas["unexpected_tables"] = list(actual_tables - expected_tables)

        # Analyze common tables for column mismatches
        common_tables = expected_tables & actual_tables

        for table_name in common_tables:
            expected_table = schema_from_code["expected_tables"][table_name]

            # Find actual table in any schema
            actual_table = None
            for schema_info in db_introspection["schemas"].values():
                if table_name in schema_info["tables"]:
                    actual_table = schema_info["tables"][table_name]
                    break

            if not actual_table:
                continue

            expected_cols = {col["name"]: col for col in expected_table["columns"]}
            actual_cols = {col["name"]: col for col in actual_table["columns"]}

            # Find missing columns
            missing_cols = set(expected_cols.keys()) - set(actual_cols.keys())
            extra_cols = set(actual_cols.keys()) - set(expected_cols.keys())

            if missing_cols or extra_cols:
                deltas["column_mismatches"].append(
                    {
                        "table": table_name,
                        "missing_columns": list(missing_cols),
                        "extra_columns": list(extra_cols),
                    }
                )

            # Check type conflicts for common columns
            common_cols = set(expected_cols.keys()) & set(actual_cols.keys())
            for col_name in common_cols:
                expected_type = expected_cols[col_name]["type"].upper()
                actual_type = actual_cols[col_name]["data_type"].upper()

                # Normalize type names for comparison
                type_mapping = {
                    "TEXT": "VARCHAR",
                    "REAL": "NUMERIC",
                    "INTEGER": "INT",
                    "BIGINT": "INT8",
                    "BOOLEAN": "BOOL",
                }

                expected_normalized = type_mapping.get(expected_type, expected_type)
                actual_normalized = type_mapping.get(actual_type, actual_type)

                if expected_normalized != actual_normalized and not (
                    (
                        expected_normalized
                        and actual_normalized
                        and expected_normalized in actual_normalized
                    )
                    or (
                        expected_normalized
                        and actual_normalized
                        and actual_normalized in expected_normalized
                    )
                ):
                    deltas["type_conflicts"].append(
                        {
                            "table": table_name,
                            "column": col_name,
                            "expected_type": expected_type,
                            "actual_type": actual_type,
                        }
                    )

        # Generate summary
        deltas["summary"] = {
            "total_expected_tables": len(expected_tables),
            "total_actual_tables": len(actual_tables),
            "missing_tables_count": len(deltas["missing_tables"]),
            "unexpected_tables_count": len(deltas["unexpected_tables"]),
            "tables_with_column_mismatches": len(deltas["column_mismatches"]),
            "type_conflicts_count": len(deltas["type_conflicts"]),
        }

        logger.info(f"Delta analysis complete: {deltas['summary']}")
        return deltas

    def generate_cleanup_plan(self, repo_map: Dict[str, Any]) -> str:
        """Generate cleanup plan for outdated files."""
        logger.info("Generating cleanup plan...")

        cleanup_plan = [
            "# Repository Cleanup Plan",
            f"Generated: {datetime.now(timezone.utc).isoformat()}",
            "",
            "## Files recommended for deletion",
            "",
        ]

        # Check for outdated markdown docs
        for doc_path in self.potential_outdated_docs:
            if doc_path in repo_map["files"]:
                file_info = repo_map["files"][doc_path]
                cleanup_plan.append(
                    f"- **{doc_path}** - Potentially outdated documentation (last modified: {file_info['last_modified']})"
                )

        # Look for duplicate Python modules
        cleanup_plan.extend(["", "## Duplicate Python modules to consolidate", ""])

        python_files = [
            path for path, info in repo_map["files"].items() if info["type"] == "python"
        ]

        # Check for database module duplication
        db_modules = [
            f for f in python_files if "database" in f.lower() or f.endswith("db.py")
        ]
        if len(db_modules) > 1:
            cleanup_plan.append(
                "- **Database modules**: Consider consolidating these files:"
            )
            for module in db_modules:
                cleanup_plan.append(f"  - {module}")
            cleanup_plan.append(
                "  - Recommendation: Keep src/db.py (advanced) and remove/refactor src/database.py (simple wrapper)"
            )
            cleanup_plan.append("")

        # Check for old migration scripts
        migration_scripts = [f for f in python_files if "migrate" in f.lower()]
        if migration_scripts:
            cleanup_plan.extend(
                [
                    "- **Old migration scripts**: Review these for one-time usage:",
                ]
            )
            for script in migration_scripts:
                cleanup_plan.append(f"  - {script}")
            cleanup_plan.append("")

        # Check for test files that might be outdated
        test_files = [
            f
            for f in python_files
            if f.startswith("test_") and f != "tests/test_integration.py"
        ]
        if test_files:
            cleanup_plan.extend(
                [
                    "- **Test files**: Review and update or remove outdated tests:",
                ]
            )
            for test_file in test_files:
                cleanup_plan.append(f"  - {test_file}")
            cleanup_plan.append("")

        cleanup_plan.extend(
            [
                "## Files to rename for consistency",
                "",
                "- No renaming recommendations at this time",
                "",
                "## Directories to clean up",
                "",
                "- **__pycache__/**: Already excluded from version control",
                "- **data/testing/**: Review if sample data is still needed",
                "",
                "## Summary",
                "",
                f"- Total files scanned: {repo_map['total_files']}",
                f"- Potential cleanup candidates: {len(self.potential_outdated_docs) + len(db_modules) - 1 + len(migration_scripts)}",
                "- Recommendation: Review each file individually before deletion",
            ]
        )

        return "\n".join(cleanup_plan)

    def generate_migration_plan(self, deltas: Dict[str, Any]) -> str:
        """Generate SQL migration plan."""
        logger.info("Generating migration plan...")

        migration_sql = [
            "-- Migration Plan: Align Database with Expected Schema",
            f"-- Generated: {datetime.now(timezone.utc).isoformat()}",
            "-- All statements are idempotent using IF NOT EXISTS patterns",
            "",
            "-- ==============================================",
            "-- Missing Tables",
            "-- ==============================================",
        ]

        if "missing_tables" in deltas and deltas["missing_tables"]:
            for table_name in deltas["missing_tables"]:
                migration_sql.extend(
                    [
                        f"",
                        f"-- Create missing table: {table_name}",
                        f"-- TODO: Add CREATE TABLE statement for {table_name}",
                        f"-- Refer to schema/000_baseline.sql for table definition",
                    ]
                )
        else:
            migration_sql.append("-- No missing tables detected")

        migration_sql.extend(
            [
                "",
                "-- ==============================================",
                "-- Missing Columns",
                "-- ==============================================",
            ]
        )

        if "column_mismatches" in deltas and deltas["column_mismatches"]:
            for mismatch in deltas["column_mismatches"]:
                table_name = mismatch["table"]
                missing_cols = mismatch.get("missing_columns", [])

                if missing_cols:
                    migration_sql.append(f"")
                    migration_sql.append(f"-- Add missing columns to {table_name}")
                    for col in missing_cols:
                        migration_sql.append(
                            f"ALTER TABLE {table_name} ADD COLUMN IF NOT EXISTS {col} TEXT; -- TODO: specify correct type"
                        )
        else:
            migration_sql.append("-- No missing columns detected")

        # Add specific known migration requirements
        migration_sql.extend(
            [
                "",
                "-- ==============================================",
                "-- Known Required Migrations",
                "-- ==============================================",
                "",
                "-- Ensure accounts table has required columns",
                "DO $$ BEGIN",
                "    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'accounts' AND column_name = 'account_id') THEN",
                "        ALTER TABLE accounts ADD COLUMN account_id TEXT;",
                "        UPDATE accounts SET account_id = id WHERE account_id IS NULL;",
                "        ALTER TABLE accounts ALTER COLUMN account_id SET NOT NULL;",
                "    END IF;",
                "END $$;",
                "",
                "-- Add holdings_last_successful_sync to accounts",
                "ALTER TABLE accounts ADD COLUMN IF NOT EXISTS holdings_last_successful_sync TIMESTAMPTZ;",
                "",
                "-- Add sync_status jsonb column to accounts",
                "ALTER TABLE accounts ADD COLUMN IF NOT EXISTS sync_status JSONB;",
                "",
                "-- Add timestamps to accounts",
                "ALTER TABLE accounts ADD COLUMN IF NOT EXISTS inserted_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP;",
                "ALTER TABLE accounts ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP;",
                "",
                "-- Ensure account_balances has unique constraint",
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_account_balances_unique ",
                "    ON account_balances(account_id, currency_code, snapshot_date);",
                "",
                "-- Add missing columns to positions",
                "ALTER TABLE positions ADD COLUMN IF NOT EXISTS account_id TEXT;",
                "ALTER TABLE positions ADD COLUMN IF NOT EXISTS symbol_description TEXT;",
                "ALTER TABLE positions ADD COLUMN IF NOT EXISTS open_pnl NUMERIC;",
                "ALTER TABLE positions ADD COLUMN IF NOT EXISTS asset_type TEXT;",
                "ALTER TABLE positions ADD COLUMN IF NOT EXISTS logo_url TEXT;",
                "",
                "-- Add missing columns to orders",
                "ALTER TABLE orders ADD COLUMN IF NOT EXISTS account_id TEXT;",
                "ALTER TABLE orders ADD COLUMN IF NOT EXISTS extracted_symbol TEXT;",
                "",
                "-- Convert JSON columns to JSONB in orders",
                "-- TODO: Add specific JSON to JSONB conversions as needed",
                "",
                "-- Create symbols table with proper structure",
                "DO $$ BEGIN",
                "    IF NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'symbols' AND table_schema = 'public') THEN",
                "        CREATE TABLE symbols (",
                "            ticker TEXT PRIMARY KEY,",
                "            figi TEXT UNIQUE,",
                "            is_supported BOOLEAN DEFAULT TRUE,",
                "            is_quotable BOOLEAN DEFAULT TRUE,",
                "            is_tradable BOOLEAN DEFAULT TRUE,",
                "            created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,",
                "            updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP",
                "        );",
                "    END IF;",
                "END $$;",
                "",
                "-- Ensure unique constraints on discord tables",
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_discord_market_clean_message_id ",
                "    ON discord_market_clean(message_id);",
                "",
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_discord_trading_clean_message_id ",
                "    ON discord_trading_clean(message_id);",
                "",
                "-- Create twitter_data schema if needed",
                "CREATE SCHEMA IF NOT EXISTS twitter_data;",
                "",
                "-- Create x_posts_log table in twitter_data schema",
                "DO $$ BEGIN",
                "    IF NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'x_posts_log' AND table_schema = 'twitter_data') THEN",
                "        CREATE TABLE twitter_data.x_posts_log (",
                "            tweet_id TEXT PRIMARY KEY,",
                "            tickers TEXT[],",
                "            content TEXT,",
                "            author_username TEXT,",
                "            created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP",
                "        );",
                "    END IF;",
                "END $$;",
                "",
                "-- Update schema migrations table",
                "INSERT INTO schema_migrations (version, description) ",
                "VALUES ('002_alignment', 'Align schema with code expectations') ",
                "ON CONFLICT (version) DO NOTHING;",
                "",
            ]
        )

        return "\n".join(migration_sql)

    def generate_wiring_plan(self, ownership_analysis: Dict[str, Any]) -> str:
        """Generate wiring plan to enforce single sources of truth."""
        logger.info("Generating wiring plan...")

        wiring_plan = [
            "# Code Wiring Plan - Enforce Single Sources of Truth",
            f"Generated: {datetime.now(timezone.utc).isoformat()}",
            "",
            "## Objective",
            "Consolidate business logic into designated files and eliminate code duplication.",
            "",
            "## Rules to Enforce",
            "",
            "1. **ALL SnapTrade operations** must be in `src/snaptrade_collector.py`",
            "2. **ALL Discord cleaning** must be in `src/message_cleaner.py`",
            "3. **Channel processing** in `src/channel_processor.py` is orchestration only",
            "",
            "## Current Violations",
            "",
        ]

        violation_count = 0

        # SnapTrade violations
        snaptrade_violations = [
            v
            for v in ownership_analysis["violations"]
            if v["type"] == "snaptrade_violation"
        ]
        if snaptrade_violations:
            wiring_plan.extend(
                ["### SnapTrade Operations Found Outside snaptrade_collector.py", ""]
            )

            for violation in snaptrade_violations:
                violation_count += 1
                wiring_plan.append(f"**{violation['file']}**")
                wiring_plan.append(f"- Description: {violation['description']}")
                wiring_plan.append("- Violations:")

                for pattern, line_numbers in violation["matches"]:
                    wiring_plan.append(
                        f"  - Pattern `{pattern}` found on lines: {', '.join(map(str, line_numbers))}"
                    )

                wiring_plan.extend(
                    [
                        "- **Action**: Move SnapTrade calls to snaptrade_collector.py and import from there",
                        "",
                    ]
                )

        # Discord violations
        discord_violations = [
            v
            for v in ownership_analysis["violations"]
            if v["type"] == "discord_violation"
        ]
        if discord_violations:
            wiring_plan.extend(
                ["### Discord Cleaning Found Outside message_cleaner.py", ""]
            )

            for violation in discord_violations:
                violation_count += 1
                wiring_plan.append(f"**{violation['file']}**")
                wiring_plan.append(f"- Description: {violation['description']}")
                wiring_plan.append("- Violations:")

                for pattern, line_numbers in violation["matches"]:
                    wiring_plan.append(
                        f"  - Pattern `{pattern}` found on lines: {', '.join(map(str, line_numbers))}"
                    )

                wiring_plan.extend(
                    [
                        "- **Action**: Move Discord processing functions to message_cleaner.py and import from there",
                        "",
                    ]
                )

        if violation_count == 0:
            wiring_plan.extend(
                ["✅ **No violations detected!** Code is properly organized.", ""]
            )

        # Add implementation steps
        wiring_plan.extend(
            [
                "## Implementation Steps",
                "",
                "### Step 1: Consolidate SnapTrade Operations",
                "",
                "1. Review all SnapTrade API calls outside `src/snaptrade_collector.py`",
                "2. Move functions to SnapTrade collector class methods",
                "3. Update imports: `from src.snaptrade_collector import SnapTradeCollector`",
                "4. Replace direct API calls with collector method calls",
                "",
                "### Step 2: Consolidate Discord Processing",
                "",
                "1. Ensure all ticker extraction, text cleaning, sentiment analysis stays in `message_cleaner.py`",
                "2. `channel_processor.py` should only orchestrate (call methods, don't implement logic)",
                "3. Update imports: `from src.message_cleaner import extract_ticker_symbols, clean_text, calculate_sentiment`",
                "",
                "### Step 3: Database Operations Review",
                "",
                "1. Consider consolidating `src/db.py` and `src/database.py`",
                "2. Recommendation: Keep `src/db.py` (advanced engine) as primary",
                "3. Refactor `src/database.py` to use `src/db.py` internally",
                "4. Update imports throughout codebase",
                "",
                "### Step 4: Validation",
                "",
                "1. Run all tests after refactoring",
                "2. Re-run this audit script to verify violations are resolved",
                "3. Test end-to-end data flows",
                "",
                "## Summary",
                "",
                f"- Total violations found: {violation_count}",
                f"- SnapTrade violations: {len(snaptrade_violations)}",
                f"- Discord processing violations: {len(discord_violations)}",
                "",
                "Priority: **HIGH** - These violations make the codebase harder to maintain and test.",
            ]
        )

        return "\n".join(wiring_plan)

    def run_audit(self) -> None:
        """Run complete repository audit and generate all reports."""
        logger.info("Starting complete repository audit...")
        start_time = datetime.now()

        try:
            # 1. Repository file mapping
            logger.info("Step 1/8: Repository file mapping")
            repo_map = self.scan_repository()
            self._save_json_report("repo_map.json", repo_map)

            # 2. Code ownership analysis
            logger.info("Step 2/8: Code ownership analysis")
            ownership_analysis = self.analyze_code_ownership(repo_map)
            self._save_json_report("code_owners.json", ownership_analysis)

            # 3. Schema extraction from code
            logger.info("Step 3/8: Schema extraction from code")
            schema_from_code = self.extract_schema_from_code(repo_map)
            self._save_json_report("schema_from_code.json", schema_from_code)

            # 4. Database introspection
            logger.info("Step 4/8: Database introspection")
            db_introspection = self.introspect_database()
            self._save_json_report("db_introspection.json", db_introspection)

            # 5. Delta analysis
            logger.info("Step 5/8: Delta analysis")
            deltas = self.generate_deltas(schema_from_code, db_introspection)
            self._save_json_report("deltas.json", deltas)

            # 6. Cleanup plan
            logger.info("Step 6/8: Cleanup plan")
            cleanup_plan = self.generate_cleanup_plan(repo_map)
            self._save_text_report("cleanup_plan.md", cleanup_plan)

            # 7. Migration plan
            logger.info("Step 7/8: Migration plan")
            migration_plan = self.generate_migration_plan(deltas)
            self._save_text_report("migration_plan.sql", migration_plan)

            # 8. Wiring plan
            logger.info("Step 8/8: Wiring plan")
            wiring_plan = self.generate_wiring_plan(ownership_analysis)
            self._save_text_report("wiring_plan.md", wiring_plan)

            duration = datetime.now() - start_time
            logger.info(
                f"✅ Audit completed successfully in {duration.total_seconds():.2f} seconds"
            )

            # Print summary
            self._print_summary(repo_map, ownership_analysis, deltas)

        except Exception as e:
            logger.error(f"❌ Audit failed: {e}")
            raise

    def _save_json_report(self, filename: str, data: Dict[str, Any]) -> None:
        """Save JSON report with pretty formatting."""
        report_path = self.reports_dir / filename
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        logger.info(f"Saved {filename}")

    def _save_text_report(self, filename: str, content: str) -> None:
        """Save text report."""
        report_path = self.reports_dir / filename
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(content)
        logger.info(f"Saved {filename}")

    def _print_summary(
        self,
        repo_map: Dict[str, Any],
        ownership_analysis: Dict[str, Any],
        deltas: Dict[str, Any],
    ) -> None:
        """Print audit summary to console."""
        print("\n" + "=" * 60)
        print("🔍 REPOSITORY AUDIT SUMMARY")
        print("=" * 60)

        print(f"\n📁 Repository Stats:")
        print(f"   • Total files: {repo_map['total_files']:,}")
        print(f"   • Total size: {repo_map['total_size_bytes']:,} bytes")

        print(f"\n🔧 Code Organization:")
        violations = len(ownership_analysis.get("violations", []))
        print(f"   • Code violations: {violations}")
        if violations > 0:
            print(f"   ⚠️  Action needed: Review wiring_plan.md")
        else:
            print(f"   ✅ Code properly organized")

        if "summary" in deltas:
            summary = deltas["summary"]
            print(f"\n🗄️  Database Schema:")
            print(f"   • Expected tables: {summary.get('total_expected_tables', 0)}")
            print(f"   • Actual tables: {summary.get('total_actual_tables', 0)}")
            print(f"   • Missing tables: {summary.get('missing_tables_count', 0)}")
            print(
                f"   • Column mismatches: {summary.get('tables_with_column_mismatches', 0)}"
            )
            print(f"   • Type conflicts: {summary.get('type_conflicts_count', 0)}")

        print(f"\n📋 Reports Generated:")
        for report_file in self.reports_dir.glob("*"):
            if report_file.is_file():
                print(f"   • {report_file.name}")

        print(f"\n📍 Next Steps:")
        print(f"   1. Review cleanup_plan.md for file deletions")
        print(f"   2. Execute migration_plan.sql for schema alignment")
        print(f"   3. Follow wiring_plan.md to fix code organization")
        print(f"   4. Re-run audit after changes to verify fixes")
        print("=" * 60)


def main():
    """Main entry point for the audit script."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Audit LLM Portfolio Project repository"
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Enable verbose logging"
    )
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    try:
        auditor = RepoAuditor()
        auditor.run_audit()
    except KeyboardInterrupt:
        logger.info("Audit interrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Audit failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
