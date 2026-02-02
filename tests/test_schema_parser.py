"""
Tests for schema_parser.py ReDoS vulnerability fix.

Verifies that the iterative CREATE TABLE extraction handles:
- Malicious input with many unbalanced parentheses (ReDoS attack vector)
- Valid CREATE TABLE statements with nested parentheses
- Multiple CREATE TABLE statements in a single block
- Oversized DO blocks (defense-in-depth)
"""

import pytest
import time
from pathlib import Path
import sys

# Ensure scripts directory is importable
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from schema_parser import SQLSchemaParser


class TestReDoSVulnerabilityFix:
    """Test that the ReDoS vulnerability is fixed."""

    @pytest.fixture
    def parser(self):
        """Create a SQLSchemaParser instance for testing."""
        return SQLSchemaParser()

    def test_malicious_nested_parens_does_not_hang(self, parser):
        """Ensure malicious input with many open parens doesn't cause exponential backtracking."""
        # This input would cause catastrophic backtracking with the old regex
        # Pattern: CREATE TABLE x((((((((((...  (30+ unbalanced open parens)
        malicious_input = "CREATE TABLE x(" + "(" * 30 + "some content"

        start = time.time()
        # Should complete quickly, not hang
        result = parser._extract_create_table_iterative(malicious_input)
        elapsed = time.time() - start

        # Should complete in under 1 second (old regex would take exponential time)
        assert elapsed < 1.0, f"Parsing took {elapsed}s - possible ReDoS vulnerability"
        # Should return empty since parens are unbalanced
        assert len(result) == 0

    def test_malicious_do_block_does_not_hang(self, parser):
        """Ensure malicious DO block input doesn't cause exponential backtracking."""
        malicious_content = "CREATE TABLE x(" + "(" * 50 + "content"
        malicious_sql = f"DO $$ BEGIN {malicious_content} END $$;"

        start = time.time()
        result = parser._extract_from_do_blocks(malicious_sql)
        elapsed = time.time() - start

        assert elapsed < 1.0, f"Parsing took {elapsed}s - possible ReDoS vulnerability"

    def test_valid_nested_parens_still_parsed(self, parser):
        """Ensure valid CREATE TABLE with nested parens is correctly parsed."""
        valid_sql = """
        CREATE TABLE test_table (
            id SERIAL PRIMARY KEY,
            price NUMERIC(10,2),
            data JSONB DEFAULT '{}',
            CHECK (price > 0)
        );
        """

        result = parser._extract_create_table_iterative(valid_sql)

        assert len(result) == 1
        assert "test_table" in result[0]
        assert "NUMERIC(10,2)" in result[0]
        assert "CHECK (price > 0)" in result[0]

    def test_multiple_create_tables_extracted(self, parser):
        """Test extraction of multiple CREATE TABLE statements."""
        sql = """
        CREATE TABLE foo (id INT);
        CREATE TABLE bar (name TEXT, value NUMERIC(5,2));
        CREATE TABLE baz (
            id SERIAL PRIMARY KEY,
            ref_id INT REFERENCES foo(id),
            data JSONB
        );
        """

        result = parser._extract_create_table_iterative(sql)

        assert len(result) == 3
        assert "foo" in result[0]
        assert "bar" in result[1]
        assert "baz" in result[2]
        assert "NUMERIC(5,2)" in result[1]

    def test_deeply_nested_parens_handled(self, parser):
        """Test handling of deeply nested but balanced parentheses."""
        # Valid SQL with multiple levels of nesting
        sql = """
        CREATE TABLE complex_table (
            id SERIAL PRIMARY KEY,
            computed INT CHECK (id > 0 AND (id < 1000 OR (id > 2000 AND id < 3000))),
            price NUMERIC(10,2) DEFAULT (0.00)
        );
        """

        result = parser._extract_create_table_iterative(sql)

        assert len(result) == 1
        assert "complex_table" in result[0]
        # Verify deeply nested content preserved
        assert "id > 2000 AND id < 3000" in result[0]

    def test_case_insensitive_create_table(self, parser):
        """Test that CREATE TABLE matching is case-insensitive."""
        sql = """
        create table lowercase_table (id INT);
        CREATE TABLE UPPERCASE_TABLE (id INT);
        Create Table MixedCase_Table (id INT);
        """

        result = parser._extract_create_table_iterative(sql)

        assert len(result) == 3

    def test_no_create_tables_returns_empty(self, parser):
        """Test that SQL without CREATE TABLE returns empty list."""
        sql = """
        ALTER TABLE foo ADD COLUMN bar TEXT;
        DROP TABLE baz;
        SELECT * FROM qux;
        """

        result = parser._extract_create_table_iterative(sql)

        assert len(result) == 0

    def test_create_table_without_semicolon(self, parser):
        """Test handling of CREATE TABLE without trailing semicolon."""
        sql = "CREATE TABLE no_semi (id INT)"

        result = parser._extract_create_table_iterative(sql)

        assert len(result) == 1
        assert "no_semi" in result[0]

    def test_oversized_do_block_skipped(self, parser):
        """Test that oversized DO blocks are skipped for defense-in-depth."""
        # Create content larger than MAX_BLOCK_SIZE (100KB)
        huge_content = "x" * 150_000
        huge_sql = f"DO $$ BEGIN {huge_content} END $$;"

        # Should not raise and should complete quickly
        start = time.time()
        result = parser._extract_from_do_blocks(huge_sql)
        elapsed = time.time() - start

        assert elapsed < 2.0, "Oversized block handling took too long"
        # Original SQL returned, oversized block content not appended
        assert huge_content not in result or result == huge_sql


class TestCreateTableExtractionEdgeCases:
    """Edge case tests for CREATE TABLE extraction."""

    @pytest.fixture
    def parser(self):
        return SQLSchemaParser()

    def test_create_table_if_not_exists(self, parser):
        """Test CREATE TABLE IF NOT EXISTS variant."""
        sql = "CREATE TABLE IF NOT EXISTS conditional_table (id INT);"

        result = parser._extract_create_table_iterative(sql)

        assert len(result) == 1
        assert "IF NOT EXISTS" in result[0]

    def test_create_table_with_schema_prefix(self, parser):
        """Test CREATE TABLE with schema prefix."""
        sql = "CREATE TABLE public.schema_table (id INT);"

        result = parser._extract_create_table_iterative(sql)

        assert len(result) == 1
        assert "public.schema_table" in result[0]

    def test_empty_input(self, parser):
        """Test empty string input."""
        result = parser._extract_create_table_iterative("")
        assert len(result) == 0

    def test_whitespace_only_input(self, parser):
        """Test whitespace-only input."""
        result = parser._extract_create_table_iterative("   \n\t\n   ")
        assert len(result) == 0
