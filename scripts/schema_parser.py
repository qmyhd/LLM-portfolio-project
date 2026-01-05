#!/usr/bin/env python3
"""
Database Schema Parser
=====================

Parses SQL DDL files to generate Python schema definitions, eliminating
the triple maintenance problem where schema info is duplicated across:
- SQL migrations (000_baseline.sql + 015-020_*.sql)
- Python validation (expected_schemas.py)
- Documentation (EXPECTED_SCHEMAS.md)

**Processing Model**:
- Reads ALL schema/*.sql files in numerical order (000, 015, 016, 017, 018, 019, 020)
- Starts with baseline (000_baseline.sql) for CREATE TABLE statements
- Applies subsequent migrations (ALTER TABLE, DROP COLUMN, etc.)
- Generates final schema reflecting all applied migrations

Output formats:
- expected_schemas.py (Python dict for verify_database.py)
- generated_schemas.py (Pydantic dataclasses - deprecated)

This creates a single source of truth from the SQL migration files.

**Important**: If you manually edit expected_schemas.py, those changes will be
overwritten on next run. Instead, create a numbered migration SQL file.
"""

import re
import sys
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)
import logging

logger = logging.getLogger(__name__)


class EnhancedSchemaParser:
    """Enhanced schema parser that handles all migration files and ALTER statements."""

    def __init__(self, schema_dir: Path):
        self.schema_dir = schema_dir
        self.tables: Dict[str, Dict] = {}
        self.indexes: Dict[str, List[Dict]] = {}
        self.constraints: Dict[str, List[Dict]] = {}

    def parse_all_migrations(self) -> Dict[str, Any]:
        """Parse all schema files in order and build complete schema."""
        # Get all SQL files in the schema directory - includes 000_baseline.sql and any others
        schema_files = sorted(self.schema_dir.glob("*.sql"))

        logger.info(f"Processing {len(schema_files)} schema files in order")

        for schema_file in schema_files:
            logger.info(f"Processing {schema_file.name}")
            self._parse_migration_file(schema_file)

        return {
            "tables": self.tables,
            "indexes": self.indexes,
            "constraints": self.constraints,
            "generated_at": datetime.now().strftime("%Y-%m-%d"),  # Current date
            "source_files": [f.name for f in schema_files],
        }

    def _parse_migration_file(self, file_path: Path):
        """Parse a single migration file."""
        try:
            content = file_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            # Try with cp1252 encoding as fallback
            try:
                content = file_path.read_text(encoding="cp1252")
            except UnicodeDecodeError:
                # Final fallback: read with errors ignored
                content = file_path.read_text(encoding="utf-8", errors="ignore")
                logger.warning(f"Had to ignore encoding errors in {file_path.name}")

        # Remove comments and DO blocks but preserve SQL structure
        content = self._clean_sql_content(content)

        # Parse CREATE TABLE statements first
        self._parse_create_tables(content)

        # Parse DROP TABLE statements
        self._parse_drop_tables(content)

        # Then parse ALTER TABLE statements
        self._parse_alter_tables(content)

        # Parse CREATE INDEX statements
        self._parse_create_indexes(content)

        # Parse constraint additions
        self._parse_add_constraints(content)

    def _clean_sql_content(self, content: str) -> str:
        """Clean SQL content by removing comments and normalizing whitespace."""
        # Remove line comments
        content = re.sub(r"--.*$", "", content, flags=re.MULTILINE)

        # Remove block comments
        content = re.sub(r"/\*.*?\*/", "", content, flags=re.DOTALL)

        # Remove DO blocks but extract only the SQL statements we care about
        do_blocks = re.finditer(
            r"DO \$\$ BEGIN(.*?)END \$\$;", content, re.DOTALL | re.IGNORECASE
        )
        extracted_sql_statements = []
        for block in do_blocks:
            block_content = block.group(1)

            # Extract all supported DDL statements, filtering out control flow
            # CREATE TABLE statements
            create_table_statements = re.findall(
                r"CREATE TABLE\s+(?:IF NOT EXISTS\s+)?\w+\s*\([^;]+\);",
                block_content,
                re.IGNORECASE | re.DOTALL,
            )

            # ALTER TABLE ADD COLUMN statements (avoid ADD CONSTRAINT)
            add_column_statements = re.findall(
                r"ALTER TABLE\s+\w+\s+ADD\s+COLUMN\s+\w+\s+[^;]+;",
                block_content,
                re.IGNORECASE,
            )

            # ALTER TABLE ADD CONSTRAINT statements
            add_constraint_statements = re.findall(
                r"ALTER TABLE\s+\w+\s+ADD\s+CONSTRAINT\s+\w+\s+[^;]+;",
                block_content,
                re.IGNORECASE | re.DOTALL,
            )

            # ALTER TABLE RENAME CONSTRAINT statements
            rename_constraint_statements = re.findall(
                r"ALTER TABLE\s+\w+\s+RENAME\s+CONSTRAINT\s+\w+\s+TO\s+\w+;",
                block_content,
                re.IGNORECASE,
            )

            # ALTER TABLE RENAME COLUMN statements
            rename_column_statements = re.findall(
                r"ALTER TABLE\s+\w+\s+RENAME\s+COLUMN\s+\w+\s+TO\s+\w+;",
                block_content,
                re.IGNORECASE,
            )

            # DROP COLUMN statements
            drop_column_statements = re.findall(
                r"ALTER TABLE\s+\w+\s+DROP\s+COLUMN\s+\w+;",
                block_content,
                re.IGNORECASE,
            )

            # DROP CONSTRAINT statements
            drop_constraint_statements = re.findall(
                r"ALTER TABLE\s+\w+\s+DROP\s+CONSTRAINT\s+(?:IF\s+EXISTS\s+)?\w+;",
                block_content,
                re.IGNORECASE,
            )

            # DROP TABLE statements
            drop_table_statements = re.findall(
                r"DROP TABLE\s+(?:IF\s+EXISTS\s+)?\w+\s*(?:CASCADE)?;",
                block_content,
                re.IGNORECASE,
            )

            # CREATE INDEX statements
            create_index_statements = re.findall(
                r"CREATE\s+(?:UNIQUE\s+)?INDEX\s+(?:IF NOT EXISTS\s+)?[\w\s]+ON\s+\w+\s*\([^)]+\)[^;]*;",
                block_content,
                re.IGNORECASE,
            )

            # DROP INDEX statements
            drop_index_statements = re.findall(
                r"DROP INDEX\s+(?:IF\s+EXISTS\s+)?\w+;",
                block_content,
                re.IGNORECASE,
            )

            # Collect all extracted statements
            extracted_sql_statements.extend(create_table_statements)
            extracted_sql_statements.extend(add_column_statements)
            extracted_sql_statements.extend(add_constraint_statements)
            extracted_sql_statements.extend(rename_constraint_statements)
            extracted_sql_statements.extend(rename_column_statements)
            extracted_sql_statements.extend(drop_column_statements)
            extracted_sql_statements.extend(drop_constraint_statements)
            extracted_sql_statements.extend(drop_table_statements)
            extracted_sql_statements.extend(create_index_statements)
            extracted_sql_statements.extend(drop_index_statements)
            # Remove the entire DO block from content
            content = content.replace(block.group(0), "")

        # Add extracted statements back to content
        if extracted_sql_statements:
            content = content + " " + " ".join(extracted_sql_statements)

        # Normalize whitespace
        content = re.sub(r"\s+", " ", content)

        return content.strip()

    def _parse_create_tables(self, content: str):
        """Parse CREATE TABLE statements."""
        # Updated pattern to handle PostgreSQL dump format with schema qualifiers
        create_table_pattern = r'CREATE TABLE (?:IF NOT EXISTS\s+)?(?:"public"\.)?(?:")?"?(\w+)"?\s*\((.*?)\);'

        matches = re.finditer(create_table_pattern, content, re.IGNORECASE | re.DOTALL)

        for match in matches:
            table_name = match.group(1).lower()
            columns_def = match.group(2)

            logger.info(f"Found CREATE TABLE: {table_name}")

            if table_name not in self.tables:
                self.tables[table_name] = {
                    "columns": {},
                    "primary_keys": [],
                    "unique_constraints": [],
                    "foreign_keys": [],
                    "indexes": [],
                }

            self._parse_table_columns(table_name, columns_def)

    def _parse_table_columns(self, table_name: str, columns_def: str):
        """Parse column definitions from CREATE TABLE statement."""
        columns = self._split_column_definitions(columns_def)

        for column_def in columns:
            column_def = column_def.strip()
            if not column_def:
                continue

            # Handle constraint definitions that start with CONSTRAINT keyword
            if column_def.upper().startswith("CONSTRAINT"):
                logger.debug(f"Found CONSTRAINT in {table_name}: {column_def[:80]}...")
                # Extract constraint name and definition for tracking
                constraint_match = re.match(
                    r'CONSTRAINT\s+"?(\w+)"?\s+(.*)',
                    column_def,
                    re.IGNORECASE | re.DOTALL,
                )
                if constraint_match:
                    constraint_name = constraint_match.group(1)
                    constraint_def = constraint_match.group(2)

                    # Handle PRIMARY KEY constraints (CONSTRAINT "name" PRIMARY KEY (col1, col2))
                    if "PRIMARY KEY" in constraint_def.upper():
                        pk_match = re.search(
                            r"PRIMARY KEY\s*\((.*?)\)", constraint_def, re.IGNORECASE
                        )
                        if pk_match:
                            pk_columns = [
                                col.strip().strip("\"'")
                                for col in pk_match.group(1).split(",")
                            ]
                            self.tables[table_name]["primary_keys"].extend(pk_columns)
                            logger.info(
                                f"Found named PK constraint on {table_name}: {pk_columns}"
                            )

                    elif "UNIQUE" in constraint_def.upper():
                        # Extract unique constraint columns
                        unique_match = re.search(
                            r"UNIQUE\s*\((.*?)\)", constraint_def, re.IGNORECASE
                        )
                        if unique_match:
                            if table_name not in self.constraints:
                                self.constraints[table_name] = []
                            self.constraints[table_name].append(
                                {
                                    "name": constraint_name,
                                    "definition": f"UNIQUE ({unique_match.group(1)})",
                                }
                            )
                continue

            # Handle inline constraint definitions (PRIMARY KEY, UNIQUE, CHECK without CONSTRAINT keyword)
            # Check if this is a table-level constraint by seeing if it starts with a constraint keyword
            constraint_keywords = ["PRIMARY KEY", "UNIQUE", "CHECK", "FOREIGN KEY"]
            is_table_constraint = any(
                column_def.upper().strip().startswith(keyword)
                for keyword in constraint_keywords
            )

            if is_table_constraint:
                if "PRIMARY KEY" in column_def.upper():
                    pk_match = re.search(
                        r"PRIMARY KEY\s*\((.*?)\)", column_def, re.IGNORECASE
                    )
                    if pk_match:
                        pk_columns = [
                            col.strip().strip("\"'")
                            for col in pk_match.group(1).split(",")
                        ]
                        self.tables[table_name]["primary_keys"].extend(pk_columns)
                continue

            self._parse_single_column(table_name, column_def)

    def _parse_single_column(self, table_name: str, column_def: str):
        """Parse a single column definition."""
        parts = column_def.strip().split()
        if len(parts) < 2:
            return

        column_name = parts[0].strip("\"'").lower()
        data_type = parts[1].upper()

        # Handle special types
        if data_type.endswith("[]"):
            data_type = f"ARRAY[{data_type[:-2]}]"
        elif data_type == "_TEXT":
            data_type = "ARRAY[TEXT]"
        elif data_type == "JSONB":
            data_type = "JSONB"

        # Extract constraints and defaults
        remaining = " ".join(parts[2:]).upper()

        nullable = "NOT NULL" not in remaining
        default_match = re.search(r"DEFAULT\s+(.*?)(?:\s|$)", remaining)
        default_value = default_match.group(1).strip() if default_match else None

        constraints = []
        if "PRIMARY KEY" in remaining:
            constraints.append("PRIMARY KEY")
            self.tables[table_name]["primary_keys"].append(column_name)
        if "UNIQUE" in remaining:
            constraints.append("UNIQUE")

        self.tables[table_name]["columns"][column_name] = {
            "data_type": data_type,
            "nullable": nullable,
            "default": default_value,
            "constraints": constraints,
        }

    def _split_column_definitions(self, columns_def: str) -> List[str]:
        """Split column definitions by comma, respecting nested parentheses."""
        columns = []
        current_column = ""
        paren_depth = 0

        for char in columns_def:
            if char == "(":
                paren_depth += 1
            elif char == ")":
                paren_depth -= 1
            elif char == "," and paren_depth == 0:
                columns.append(current_column.strip())
                current_column = ""
                continue

            current_column += char

        if current_column.strip():
            columns.append(current_column.strip())

        return columns

    def _parse_alter_tables(self, content: str):
        """Parse ALTER TABLE statements to modify existing schema."""
        # FIRST: Handle multi-column ADD COLUMN statements (comma-separated)
        # Pattern: ALTER TABLE x ADD COLUMN col1 TYPE, ADD COLUMN col2 TYPE;
        multi_add_pattern = r"ALTER TABLE\s+(?:public\.)?(\w+)\s+((?:ADD\s+COLUMN\s+(?:IF NOT EXISTS\s+)?\w+\s+\w+(?:\[\])?(?:\([^)]+\))?[^,;]*,?\s*)+);"

        for match in re.finditer(multi_add_pattern, content, re.IGNORECASE | re.DOTALL):
            table_name = match.group(1).lower()
            columns_block = match.group(2)

            # Parse each ADD COLUMN clause within the block
            single_add_pattern = r"ADD\s+COLUMN\s+(?:IF NOT EXISTS\s+)?(\w+)\s+(\w+(?:\[\])?(?:\([^)]+\))?)\s*([^,;]*)"

            for col_match in re.finditer(
                single_add_pattern, columns_block, re.IGNORECASE
            ):
                column_name = col_match.group(1).lower()
                data_type = col_match.group(2).upper()
                constraints_def = col_match.group(3) if col_match.group(3) else ""

                if table_name not in self.tables:
                    self.tables[table_name] = {
                        "columns": {},
                        "primary_keys": [],
                        "unique_constraints": [],
                        "foreign_keys": [],
                        "indexes": [],
                    }

                nullable = "NOT NULL" not in constraints_def.upper()
                default_match = re.search(
                    r"DEFAULT\s+(\S+)", constraints_def, re.IGNORECASE
                )
                default_value = (
                    default_match.group(1).strip() if default_match else None
                )

                self.tables[table_name]["columns"][column_name] = {
                    "data_type": data_type,
                    "nullable": nullable,
                    "default": default_value,
                    "constraints": [],
                }
                logger.debug(f"Added column {table_name}.{column_name} ({data_type})")

        # THEN: Handle single-column ADD COLUMN statements (original pattern)
        # Updated to handle IF NOT EXISTS
        add_column_pattern = r"ALTER TABLE\s+(?:public\.)?(\w+)\s+ADD\s+COLUMN\s+(?:IF NOT EXISTS\s+)?(\w+)\s+(\w+(?:\[\])?(?:\([^)]+\))?)\s*(.*?);"

        for match in re.finditer(add_column_pattern, content, re.IGNORECASE):
            table_name = match.group(1).lower()
            column_name = match.group(2).lower()
            data_type = match.group(3).upper()
            constraints_def = match.group(4)

            # Skip if already added by multi-column pattern
            if (
                table_name in self.tables
                and column_name in self.tables[table_name]["columns"]
            ):
                continue

            if table_name not in self.tables:
                self.tables[table_name] = {
                    "columns": {},
                    "primary_keys": [],
                    "unique_constraints": [],
                    "foreign_keys": [],
                    "indexes": [],
                }

            nullable = "NOT NULL" not in constraints_def.upper()
            default_match = re.search(
                r"DEFAULT\s+(.*?)(?:\s|$)", constraints_def, re.IGNORECASE
            )
            default_value = default_match.group(1).strip() if default_match else None

            self.tables[table_name]["columns"][column_name] = {
                "data_type": data_type,
                "nullable": nullable,
                "default": default_value,
                "constraints": [],
            }

        # DROP COLUMN (handles IF EXISTS clause)
        drop_column_pattern = r"ALTER TABLE\s+(?:IF EXISTS\s+)?(?:public\.)?(\w+)\s+DROP\s+(?:COLUMN\s+)?(?:IF EXISTS\s+)?(\w+);"

        for match in re.finditer(drop_column_pattern, content, re.IGNORECASE):
            table_name = match.group(1).lower()
            column_name = match.group(2).lower()

            if (
                table_name in self.tables
                and column_name in self.tables[table_name]["columns"]
            ):
                del self.tables[table_name]["columns"][column_name]
                logger.info(f"Dropped column {table_name}.{column_name}")

        # ALTER COLUMN TYPE
        alter_type_pattern = r"ALTER TABLE\s+(?:public\.)?(\w+)\s+ALTER\s+(?:COLUMN\s+)?(\w+)\s+(?:SET\s+DATA\s+)?TYPE\s+(\w+(?:\[\])?(?:\([^)]+\))?)"

        for match in re.finditer(alter_type_pattern, content, re.IGNORECASE):
            table_name = match.group(1).lower()
            column_name = match.group(2).lower()
            new_type = match.group(3).upper()

            if (
                table_name in self.tables
                and column_name in self.tables[table_name]["columns"]
            ):
                self.tables[table_name]["columns"][column_name]["data_type"] = new_type
                logger.info(f"Changed {table_name}.{column_name} type to {new_type}")

        # DROP CONSTRAINT (especially for primary keys)
        drop_constraint_pattern = r"ALTER TABLE\s+(?:public\.)?(\w+)\s+DROP\s+CONSTRAINT\s+(?:IF EXISTS\s+)?(\w+)(?:;|,)"

        for match in re.finditer(drop_constraint_pattern, content, re.IGNORECASE):
            table_name = match.group(1).lower()
            constraint_name = match.group(2).lower()

            if table_name in self.tables:
                # If this was a primary key constraint, clear the primary_keys list
                if constraint_name.endswith("_pkey") or "pkey" in constraint_name:
                    self.tables[table_name]["primary_keys"] = []
                    logger.info(
                        f"Dropped primary key constraint {constraint_name} from {table_name}"
                    )

        # ADD CONSTRAINT PRIMARY KEY (handles both multi-line and single-line format)
        # After cleaning, newlines are converted to spaces so we need to handle both formats
        add_pk_pattern = r'ALTER TABLE\s+(?:ONLY\s+)?(?:"?\w+"?\.)?\"?(\w+)\"?\s+ADD\s+CONSTRAINT\s+\"?\w+\"?\s+PRIMARY KEY\s*\(([^)]+)\)'

        matches = list(re.finditer(add_pk_pattern, content, re.IGNORECASE))

        for match in matches:
            table_name = match.group(1).lower()
            pk_columns = [col.strip().strip('"') for col in match.group(2).split(",")]

            if table_name not in self.tables:
                self.tables[table_name] = {
                    "columns": {},
                    "primary_keys": [],
                    "unique_constraints": [],
                    "foreign_keys": [],
                    "indexes": [],
                }

            self.tables[table_name]["primary_keys"] = pk_columns
            logger.info(f"Set primary key for {table_name}: {pk_columns}")

        # RENAME CONSTRAINT (track constraint name changes)
        rename_constraint_pattern = (
            r"ALTER TABLE\s+(\w+)\s+RENAME\s+CONSTRAINT\s+(\w+)\s+TO\s+(\w+)(?:;|,)"
        )

        for match in re.finditer(rename_constraint_pattern, content, re.IGNORECASE):
            table_name = match.group(1).lower()
            old_name = match.group(2).lower()
            new_name = match.group(3).lower()
            logger.info(f"Renamed constraint {old_name} to {new_name} on {table_name}")

        # RENAME COLUMN (track column name changes)
        rename_column_pattern = r"ALTER TABLE\s+(?:public\.)?(\w+)\s+RENAME\s+COLUMN\s+(\w+)\s+TO\s+(\w+)(?:;|,)"

        for match in re.finditer(rename_column_pattern, content, re.IGNORECASE):
            table_name = match.group(1).lower()
            old_name = match.group(2).lower()
            new_name = match.group(3).lower()

            if (
                table_name in self.tables
                and old_name in self.tables[table_name]["columns"]
            ):
                # Move the column definition to the new name
                column_def = self.tables[table_name]["columns"][old_name]
                del self.tables[table_name]["columns"][old_name]
                self.tables[table_name]["columns"][new_name] = column_def
                logger.info(f"Renamed column {table_name}.{old_name} to {new_name}")

        # DROP TABLE (remove table from schema)
        drop_table_pattern = r"DROP TABLE\s+(?:IF\s+EXISTS\s+)?(\w+)(?:\s+CASCADE)?\s*;"

        for match in re.finditer(drop_table_pattern, content, re.IGNORECASE):
            table_name = match.group(1).lower()
            if table_name in self.tables:
                del self.tables[table_name]
                logger.info(f"Removed table {table_name} from schema (DROP TABLE)")

    def _parse_create_indexes(self, content: str):
        """Parse CREATE INDEX statements."""
        index_pattern = r"CREATE\s+(?:UNIQUE\s+)?INDEX\s+(?:IF NOT EXISTS\s+)?(\w+)\s+ON\s+(\w+)\s*\((.*?)\)"

        for match in re.finditer(index_pattern, content, re.IGNORECASE):
            index_name = match.group(1)
            table_name = match.group(2).lower()
            columns = match.group(3)

            if table_name not in self.indexes:
                self.indexes[table_name] = []

            self.indexes[table_name].append(
                {
                    "name": index_name,
                    "columns": [col.strip() for col in columns.split(",")],
                    "unique": "UNIQUE" in match.group(0).upper(),
                }
            )

    def _parse_drop_tables(self, content: str):
        """Parse DROP TABLE statements and remove tables from schema."""
        drop_table_pattern = r"DROP TABLE\s+(?:IF EXISTS\s+)?(\w+)(?:\s+CASCADE)?\s*;"

        for match in re.finditer(drop_table_pattern, content, re.IGNORECASE):
            table_name = match.group(1).lower()

            # Remove table from all tracking dictionaries
            if table_name in self.tables:
                del self.tables[table_name]
                logger.info(f"Removed table {table_name} from schema (DROP TABLE)")

            if table_name in self.indexes:
                del self.indexes[table_name]

            if table_name in self.constraints:
                del self.constraints[table_name]

    def _parse_add_constraints(self, content: str):
        """Parse constraint additions."""
        constraint_pattern = r"ALTER TABLE\s+(\w+)\s+ADD\s+CONSTRAINT\s+(\w+)\s+(.*?);"

        for match in re.finditer(constraint_pattern, content, re.IGNORECASE):
            table_name = match.group(1).lower()
            constraint_name = match.group(2)
            constraint_def = match.group(3)

            if table_name not in self.constraints:
                self.constraints[table_name] = []

            self.constraints[table_name].append(
                {"name": constraint_name, "definition": constraint_def.strip()}
            )

            # If it's a unique constraint, track it specially
            if "UNIQUE" in constraint_def.upper():
                if table_name not in self.tables:
                    self.tables[table_name] = {
                        "columns": {},
                        "primary_keys": [],
                        "unique_constraints": [],
                        "foreign_keys": [],
                        "indexes": [],
                    }
                self.tables[table_name]["unique_constraints"].append(constraint_name)


def generate_comprehensive_schemas(schema_data: Dict[str, Any]) -> str:
    """Generate comprehensive Python schema definitions."""
    code_lines = [
        "#!/usr/bin/env python3",
        '"""',
        "Generated Schema Definitions",
        "===========================",
        "",
        "This file is auto-generated by schema_parser.py from migration files.",
        f'Generated at: {schema_data["generated_at"]}',
        f'Source files: {", ".join(schema_data["source_files"])}',
        "",
        "DO NOT EDIT MANUALLY - regenerate using:",
        "python scripts/schema_parser.py",
        '"""',
        "",
        "from typing import Dict, Any, List",
        "",
        "# Complete expected schema definitions from all migration files",
        "EXPECTED_SCHEMAS: Dict[str, Dict[str, Any]] = {",
    ]

    # Generate table definitions
    for table_name, table_def in schema_data["tables"].items():
        code_lines.extend([f'    "{table_name}": {{', f'        "required_fields": {{'])

        for col_name, col_def in table_def["columns"].items():
            # Convert to verification script format
            verification_type = _convert_to_verification_type(col_def["data_type"])
            code_lines.append(f'            "{col_name}": "{verification_type}",')

        code_lines.extend(
            [
                "        },",
                f'        "primary_keys": {table_def["primary_keys"]},',
                f'        "unique_constraints": {table_def.get("unique_constraints", [])},',
                f'        "description": "Auto-generated from migration files"',
                "    },",
            ]
        )

    code_lines.extend(
        [
            "}",
            "",
            "# Index definitions by table",
            f'EXPECTED_INDEXES: Dict[str, List[Dict[str, Any]]] = {schema_data["indexes"]}',
            "",
            "# Constraint definitions by table",
            f'EXPECTED_CONSTRAINTS: Dict[str, List[Dict[str, Any]]] = {schema_data["constraints"]}',
            "",
            "# Schema metadata",
            "SCHEMA_METADATA = {",
            f'    "generated_at": "{schema_data["generated_at"]}",',
            f'    "source_files": {schema_data["source_files"]},',
            f'    "table_count": {len(schema_data["tables"])},',
            f'    "total_columns": {sum(len(t["columns"]) for t in schema_data["tables"].values())}',
            "}",
            "",
            "# Legacy compatibility - map to old format for existing verification scripts",
            "SCHEMA_DEFINITIONS = EXPECTED_SCHEMAS",
        ]
    )

    return "\n".join(code_lines)


def _convert_to_verification_type(pg_type: str) -> str:
    """Convert PostgreSQL type to verification script type with improved normalization."""
    if not pg_type:
        return "text"

    # Normalize the type string
    base_type = pg_type.upper().strip()

    # Remove parentheses and content for type comparison
    base_type_clean = re.sub(r"\([^)]*\)", "", base_type)

    # Handle arrays first
    if base_type_clean.endswith("[]") or base_type_clean.startswith("ARRAY"):
        return "array"

    # Normalize to base type for comparison
    t = base_type_clean.lower()

    # Apply specific normalization rules as requested
    if t.startswith("numeric") or t.startswith("decimal"):
        return "numeric"

    if t in ("json", "jsonb"):
        return "json"

    if t.endswith("[]"):
        return "array"

    if t == "bigint":
        return "bigint"

    if t == "date":
        return "date"

    # Preserve timestamp type distinctions
    if "timestamp with time zone" in t or "timestamptz" in t:
        return "timestamptz"
    elif "timestamp without time zone" in t or t == "timestamp":
        return "timestamp"

    # Standard type mappings preserving PostgreSQL types
    type_mapping = {
        "text": "text",
        "varchar": "text",
        "character": "text",
        "char": "text",
        "character varying": "text",
        "integer": "integer",
        "int": "integer",
        "smallint": "integer",
        "serial": "integer",
        "bigserial": "bigint",
        "bigint": "bigint",
        "real": "numeric",
        "float": "numeric",
        "double": "numeric",
        "double precision": "numeric",
        "numeric": "numeric",
        "decimal": "numeric",
        "boolean": "boolean",
        "bool": "boolean",
        "date": "date",
        "time": "time",
        "json": "jsonb",
        "jsonb": "jsonb",
        "uuid": "text",
        "bytea": "binary",
    }

    return type_mapping.get(t, "text")


class SQLSchemaParser:
    """Parse PostgreSQL DDL to extract schema information."""

    def __init__(self):
        self.tables = {}

    def parse_create_table(self, ddl_content: str) -> Dict[str, Any]:
        """Parse CREATE TABLE statements from DDL content."""
        tables = {}

        # First, handle PostgreSQL DO blocks by extracting the CREATE TABLE parts
        processed_sql = self._extract_from_do_blocks(ddl_content)

        # Find all CREATE TABLE statements
        table_pattern = r"CREATE TABLE(?:\s+IF NOT EXISTS)?\s+(\w+)\s*\(\s*(.*?)\s*\);"

        for match in re.finditer(
            table_pattern, processed_sql, re.DOTALL | re.IGNORECASE
        ):
            table_name = match.group(1)
            columns_text = match.group(2)

            # Parse column definitions
            columns = self._parse_columns(columns_text)

            if columns:
                tables[table_name] = {
                    "required_fields": columns,
                    "description": f"Auto-generated from DDL for {table_name}",
                    "source": "parsed_from_sql",
                }

        return tables

    def _extract_from_do_blocks(self, sql: str) -> str:
        """Extract CREATE TABLE statements from PostgreSQL DO blocks."""
        # Pattern to match DO $$ BEGIN ... END $$; blocks (no escaping needed for literal $)
        do_block_pattern = r"DO\s+\$\$\s+BEGIN(.*?)END\s+\$\$;"

        extracted_sql = sql
        matches = list(re.finditer(do_block_pattern, sql, re.IGNORECASE | re.DOTALL))

        logger.info(f"Found {len(matches)} DO blocks to process")

        for match in matches:
            block_content = match.group(1)
            # Extract CREATE TABLE from the block content - need to handle nested parentheses
            create_table_pattern = (
                r"CREATE\s+TABLE[^;]*\([^)]*(?:\([^)]*\)[^)]*)*\)[^;]*;"
            )
            table_matches = list(
                re.finditer(
                    create_table_pattern, block_content, re.IGNORECASE | re.DOTALL
                )
            )

            logger.info(
                f"Found {len(table_matches)} CREATE TABLE statements in DO block"
            )

            for table_match in table_matches:
                create_statement = table_match.group(0)
                logger.info(f"Extracted CREATE TABLE: {create_statement[:100]}...")
                # Add the extracted CREATE TABLE to processed SQL
                extracted_sql += "\n" + create_statement

        return extracted_sql

    def _parse_columns(self, columns_text: str) -> Dict[str, str]:
        """Parse column definitions from CREATE TABLE column list."""
        columns = {}

        # Split by comma but handle nested parentheses
        column_defs = self._split_column_definitions(columns_text)

        for col_def in column_defs:
            col_def = col_def.strip()
            if not col_def or col_def.upper().startswith(
                ("PRIMARY KEY", "FOREIGN KEY", "UNIQUE", "CHECK", "INDEX")
            ):
                continue

            # Extract column name and type
            parts = col_def.split()
            if len(parts) >= 2:
                col_name = parts[0].strip()
                col_type = parts[1].strip().upper()

                # Normalize PostgreSQL types to standard types
                normalized_type = self._normalize_type(col_type)
                columns[col_name] = normalized_type

        return columns

    def _split_column_definitions(self, text: str) -> List[str]:
        """Split column definitions by comma, respecting parentheses."""
        parts = []
        current = ""
        paren_depth = 0

        for char in text:
            if char == "(":
                paren_depth += 1
            elif char == ")":
                paren_depth -= 1
            elif char == "," and paren_depth == 0:
                parts.append(current.strip())
                current = ""
                continue

            current += char

        if current.strip():
            parts.append(current.strip())

        return parts

    def _normalize_type(self, pg_type: str) -> str:
        """Normalize PostgreSQL types preserving important distinctions like timestamptz vs timestamp."""
        pg_type = pg_type.upper().strip()

        # Handle parameterized types
        base_type = pg_type.split("(")[0]

        # Special handling for timestamp types to preserve timezone info
        if "TIMESTAMP WITH TIME ZONE" in pg_type or "TIMESTAMPTZ" == base_type:
            return "timestamptz"
        elif "TIMESTAMP WITHOUT TIME ZONE" in pg_type or "TIMESTAMP" == base_type:
            return "timestamp"

        type_mapping = {
            "TEXT": "text",
            "VARCHAR": "text",
            "CHARACTER": "text",
            "CHAR": "text",
            "INTEGER": "integer",
            "INT": "integer",
            "BIGINT": "bigint",
            "SERIAL": "integer",
            "BIGSERIAL": "bigint",
            "SMALLINT": "integer",
            "REAL": "numeric",
            "FLOAT": "numeric",
            "DOUBLE": "numeric",
            "NUMERIC": "numeric",
            "DECIMAL": "numeric",
            "BOOLEAN": "boolean",
            "BOOL": "boolean",
            "DATE": "date",
            "TIME": "time",
            "JSON": "jsonb",
            "JSONB": "jsonb",
            "UUID": "text",
            "BYTEA": "binary",
        }

        return type_mapping.get(base_type, "text")

    def parse_file(self, file_path: Path) -> Dict[str, Any]:
        """Parse a SQL DDL file and return schema information."""
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()

            # Remove comments and normalize whitespace
            content = self._clean_sql_content(content)

            return self.parse_create_table(content)

        except Exception as e:
            logger.error(f"Error parsing SQL file {file_path}: {e}")
            return {}

    def _clean_sql_content(self, content: str) -> str:
        """Remove comments and normalize SQL content for parsing."""
        # Remove -- comments
        content = re.sub(r"--.*$", "", content, flags=re.MULTILINE)

        # Remove /* */ comments
        content = re.sub(r"/\*.*?\*/", "", content, flags=re.DOTALL)

        # Remove DO $$ blocks (PostgreSQL specific)
        content = re.sub(
            r"DO\s+\$\$.*?\$\$;", "", content, flags=re.DOTALL | re.IGNORECASE
        )

        # Normalize whitespace
        content = re.sub(r"\s+", " ", content)

        return content


def generate_python_schemas(sql_files: List[Path]) -> str:
    """Generate Python schema dictionaries from SQL files."""
    parser = SQLSchemaParser()
    all_tables = {}

    for sql_file in sql_files:
        logger.info(f"Parsing {sql_file}")
        tables = parser.parse_file(sql_file)
        all_tables.update(tables)

    # Generate Python code
    python_code = '''"""
Generated Schema Definitions
===========================

Auto-generated from SQL DDL files. Do not edit manually.
Run `python scripts/schema_parser.py` to regenerate.
"""

# Schema definitions parsed from SQL DDL
SCHEMA_DEFINITIONS = {
'''

    for table_name, table_info in all_tables.items():
        python_code += f'    "{table_name}": {{\n'
        python_code += f'        "required_fields": {{\n'

        for field_name, field_type in table_info["required_fields"].items():
            python_code += f'            "{field_name}": "{field_type}",\n'

        python_code += f"        }},\n"
        python_code += f'        "description": "{table_info["description"]}",\n'
        python_code += f"    }},\n"

    python_code += "}\n"

    return python_code


def generate_dataclass_schemas(schema_data: Dict[str, Any]) -> str:
    """Generate Python dataclass definitions with proper typing and primary key ordering."""

    # Type mapping with correct conversions
    TYPE_MAPPING = {
        "text": "str",
        "varchar": "str",
        "character varying": "str",
        "uuid": "str",  # Keep as str for simplicity
        "timestamp": "datetime",
        "timestamptz": "datetime",
        "timestamp with time zone": "datetime",
        "timestamp without time zone": "datetime",
        "date": "date",
        "numeric": "Decimal",
        "real": "float",
        "integer": "int",
        "bigint": "int",
        "boolean": "bool",
        "jsonb": "JSON",  # Proper JSON type mapping
        "json": "JSON",
        "time": "time",
        "time without time zone": "time",
    }

    # Special handling for JSONB arrays
    JSONB_ARRAY_FIELDS = {
        "orders": {"child_brokerage_order_ids": "Optional[List[str]]"}
    }

    code_lines = [
        '"""',
        "Generated dataclass schemas from SSOT baseline SQL schema.",
        f"Auto-generated on {datetime.now().strftime('%B %d, %Y')}",
        f"Total tables: {len(schema_data['tables'])}",
        '"""',
        "from dataclasses import dataclass",
        "from datetime import datetime, date, time",
        "from decimal import Decimal",
        "from typing import Optional, List, Union, Dict, Any",
        "",
        "# JSON type for proper JSONB mapping",
        "JSON = Union[Dict[str, Any], List[Any]]",
        "",
        "",
    ]

    # Generate dataclass for each table
    for table_name in sorted(schema_data["tables"].keys()):
        table_info = schema_data["tables"][table_name]
        class_name = "".join(word.capitalize() for word in table_name.split("_"))

        code_lines.extend(
            [
                "@dataclass",
                f"class {class_name}:",
                f'    """Data model for {table_name} table."""',
            ]
        )

        # Get primary keys from parsed SQL (not hardcoded overrides)
        primary_keys = table_info.get("primary_keys", [])

        # Generate primary key fields first
        processed_fields = set()
        for pk in primary_keys:
            if pk in table_info["columns"]:
                col_info = table_info["columns"][pk]
                python_type = _get_python_type(
                    col_info, table_name, pk, TYPE_MAPPING, JSONB_ARRAY_FIELDS
                )
                code_lines.append(f"    {pk}: {python_type}")
                processed_fields.add(pk)

        # Generate remaining fields in alphabetical order
        remaining_fields = []
        for col_name, col_info in table_info["columns"].items():
            if col_name not in processed_fields:
                python_type = _get_python_type(
                    col_info, table_name, col_name, TYPE_MAPPING, JSONB_ARRAY_FIELDS
                )
                remaining_fields.append((col_name, python_type))

        for col_name, python_type in sorted(remaining_fields):
            code_lines.append(f"    {col_name}: {python_type}")

        code_lines.append("")

    return "\n".join(code_lines)


def _get_python_type(col_info, table_name, col_name, type_mapping, jsonb_array_fields):
    """Get the correct Python type for a column."""
    # Handle different column info structures
    if isinstance(col_info, dict):
        if "type" in col_info:
            data_type = col_info["type"].lower()
            is_nullable = col_info.get("nullable", True)
        elif "data_type" in col_info:
            data_type = col_info["data_type"].lower()
            is_nullable = col_info.get("nullable", True)
        else:
            # Fallback if structure is unexpected
            logger.warning(
                f"Unexpected column info structure for {table_name}.{col_name}: {col_info}"
            )
            return "str"
    else:
        # Handle case where col_info is just the type string
        data_type = str(col_info).lower()
        is_nullable = True

    # Special handling for JSONB arrays (specific known fields)
    if table_name in jsonb_array_fields and col_name in jsonb_array_fields[table_name]:
        return jsonb_array_fields[table_name][col_name]

    # Map PostgreSQL type to Python type
    python_type = type_mapping.get(data_type, "str")

    # Make nullable fields Optional (except primary key fields which should not be Optional)
    if is_nullable and not python_type.startswith("Optional"):
        python_type = f"Optional[{python_type}]"

    return python_type


def _table_name_to_class_name(table_name: str) -> str:
    """Convert table name to Python class name."""
    # Handle special cases
    name_mapping = {
        "account_balances": "AccountBalance",
        "daily_prices": "DailyPrice",
        "realtime_prices": "RealtimePrice",
        "stock_metrics": "StockMetrics",
        "discord_messages": "DiscordMessage",
        "discord_market_clean": "DiscordMarketClean",
        "discord_trading_clean": "DiscordTradingClean",
        "discord_processing_log": "DiscordProcessingLog",
        "processing_status": "ProcessingStatus",
        "twitter_data": "TwitterData",
        "chart_metadata": "ChartMetadata",
        "schema_migrations": "SchemaMigration",
    }

    if table_name in name_mapping:
        return name_mapping[table_name]

    # Default: capitalize and remove underscores
    return "".join(word.capitalize() for word in table_name.split("_"))


def _get_table_description(table_name: str) -> str:
    """Get description for table."""
    descriptions = {
        "accounts": "SnapTrade account information",
        "account_balances": "Account balance information",
        "positions": "SnapTrade position data",
        "orders": "Trading orders with comprehensive tracking",
        "symbols": "Symbol metadata and trading information",
        "daily_prices": "Daily OHLCV price data",
        "realtime_prices": "Real-time price updates",
        "stock_metrics": "Financial metrics and ratios",
        "discord_messages": "Discord message data with analysis",
        "discord_market_clean": "Cleaned market-related Discord messages",
        "discord_trading_clean": "Cleaned trading-related Discord messages",
        "discord_processing_log": "Processing status for Discord messages",
        "processing_status": "Processing status tracking",
        "twitter_data": "Twitter/X data from Discord shared links",
        "chart_metadata": "Chart generation metadata (natural key)",
        "schema_migrations": "Schema version tracking",
    }
    return descriptions.get(table_name, f"Generated from {table_name} table")


def _convert_to_python_type(pg_type: str) -> str:
    """Convert PostgreSQL type to Python type with proper mappings."""
    if not pg_type:
        return "str"

    pg_type = pg_type.upper().strip()

    # Handle arrays/JSONB first
    if "JSONB" in pg_type:
        return "List[str]"  # Special case for child_brokerage_order_ids

    if pg_type.endswith("[]") or pg_type.startswith("ARRAY"):
        return "List[str]"

    # Remove parentheses for comparison
    base_type = re.sub(r"\([^)]*\)", "", pg_type)

    type_mapping = {
        "TEXT": "str",
        "VARCHAR": "str",
        "CHARACTER": "str",
        "CHAR": "str",
        "INTEGER": "int",
        "INT": "int",
        "BIGINT": "int",
        "SMALLINT": "int",
        "SERIAL": "int",
        "BIGSERIAL": "int",
        "REAL": "float",  # PostgreSQL float4
        "FLOAT": "float",
        "DOUBLE": "float",
        "NUMERIC": "Decimal",  # High precision financial data
        "DECIMAL": "Decimal",
        "BOOLEAN": "bool",
        "BOOL": "bool",
        "DATE": "date",
        "TIME": "time",
        "TIMESTAMP": "datetime",  # Both timestamp and timestamptz -> datetime
        "TIMESTAMPTZ": "datetime",
    }

    # Handle timestamp variants
    if "TIMESTAMP" in base_type:
        return "datetime"

    return type_mapping.get(base_type, "str")


def generate_expected_schemas(schema_data: Dict[str, Any]) -> str:
    """Generate EXPECTED_SCHEMAS dictionary format for verify_database.py compatibility."""
    code_lines = [
        '"""',
        "Generated EXPECTED_SCHEMAS dictionary from SSOT baseline.",
        f"Auto-generated on {datetime.now().strftime('%B %d, %Y')}",
        "This provides compatibility with verify_database.py and other validation scripts.",
        '"""',
        "from typing import Dict, Any, List",
        "",
        "# Expected schema definitions for validation scripts",
        "EXPECTED_SCHEMAS: Dict[str, Dict[str, Any]] = {",
    ]

    # Generate schema dictionary entries for each table
    for table_name in sorted(schema_data["tables"].keys()):
        table_info = schema_data["tables"][table_name]

        code_lines.extend(
            [
                f'    "{table_name}": {{',
                '        "required_fields": {',
            ]
        )

        # Generate field definitions with verification types
        for col_name in sorted(table_info["columns"].keys()):
            col_info = table_info["columns"][col_name]
            verification_type = _convert_to_verification_type(col_info["data_type"])
            code_lines.append(f'            "{col_name}": "{verification_type}",')

        code_lines.extend(
            [
                "        },",
                f'        "primary_keys": {table_info["primary_keys"]},',
                f'        "description": "Auto-generated from {table_name} table"',
                "    },",
            ]
        )

    code_lines.extend(
        [
            "}",
            "",
            "# Schema metadata for reference",
            "SCHEMA_METADATA = {",
            f'    "generated_at": "{schema_data["generated_at"]}",',
            f'    "source_files": {schema_data["source_files"]},',
            f'    "table_count": {len(schema_data["tables"])},',
            f'    "total_columns": {sum(len(t["columns"]) for t in schema_data["tables"].values())}',
            "}",
        ]
    )

    return "\n".join(code_lines)


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Generate Python schema definitions from SQL DDL"
    )
    parser.add_argument(
        "--output",
        choices=["dataclass", "expected", "both"],
        default="expected",
        help="Output type: expected for src/expected_schemas.py (default), dataclass for src/generated_schemas.py (deprecated), both for both files",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    # Find schema files - Process baseline + all migrations for accurate types
    project_root = Path(__file__).parent.parent
    schema_dir = project_root / "schema"

    # Check baseline file exists
    baseline_file = schema_dir / "000_baseline.sql"
    if not baseline_file.exists():
        logger.error("SSOT baseline file (000_baseline.sql) not found")
        return 1

    logger.info("Processing baseline + migrations for accurate schema types")

    # Enhanced parsing with schema evolution - process all migrations
    enhanced_parser = EnhancedSchemaParser(schema_dir)

    # Parse all migrations for accurate final schema
    schema_data = enhanced_parser.parse_all_migrations()

    # Debug: check if tables were parsed
    logger.info(
        f"Parsed {len(schema_data['tables'])} tables from baseline + migrations"
    )
    for table_name in schema_data["tables"].keys():
        logger.info(f"  • Found table: {table_name}")

    # Filter out excluded tables (deprecated stock_charts table)
    excluded_tables = ["stock_charts"]
    for table in excluded_tables:
        if table in schema_data["tables"]:
            del schema_data["tables"][table]
            logger.info(f"Excluded table: {table}")

    # Generate output based on user selection
    outputs_generated = []

    if args.output in ["dataclass", "both"]:
        # Generate dataclass schema definitions
        dataclass_code = generate_dataclass_schemas(schema_data)
        dataclass_file = project_root / "src" / "generated_schemas.py"

        try:
            with open(dataclass_file, "w", encoding="utf-8") as f:
                f.write(dataclass_code)
            logger.info(f"Generated dataclass schema definitions: {dataclass_file}")
            outputs_generated.append(f"dataclass → {dataclass_file}")
        except Exception as e:
            logger.error(f"Error writing dataclass file: {e}")
            return 1

    if args.output in ["expected", "both"]:
        # Generate EXPECTED_SCHEMAS dictionary
        expected_code = generate_expected_schemas(schema_data)
        expected_file = project_root / "src" / "expected_schemas.py"

        try:
            with open(expected_file, "w", encoding="utf-8") as f:
                f.write(expected_code)
            logger.info(f"Generated EXPECTED_SCHEMAS dictionary: {expected_file}")
            outputs_generated.append(f"expected → {expected_file}")
        except Exception as e:
            logger.error(f"Error writing expected schemas file: {e}")
            return 1

    # Success message
    print(f"✅ Generated schema definitions from SSOT baseline:")
    for output in outputs_generated:
        print(f"   • {output}")

    # Show summary
    print(f"📊 Parsed {len(schema_data['tables'])} tables from SSOT baseline:")
    for table_name, table_info in schema_data["tables"].items():
        field_count = len(table_info["columns"])
        pk_count = len(table_info["primary_keys"])
        constraint_count = len(table_info.get("unique_constraints", []))
        print(
            f"   • {table_name}: {field_count} columns, {pk_count} PKs, {constraint_count} constraints"
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
