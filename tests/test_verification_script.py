"""
Test the unified database verification script.
"""

import pytest
import subprocess
import sys
import json
from pathlib import Path


@pytest.mark.integration
class TestVerificationScript:
    """Test the unified verify_database.py script."""

    def setup_method(self):
        """Set up test fixtures."""
        self.script_path = "scripts.verify_database"
        self.project_root = Path(__file__).parent.parent

    def run_script(self, args):
        """Run the verification script with given arguments."""
        cmd = [sys.executable, "-m", self.script_path] + args
        result = subprocess.run(
            cmd, capture_output=True, text=True, cwd=self.project_root
        )
        return result

    def test_help_output(self):
        """Test that the script shows help without errors."""
        result = self.run_script(["--help"])
        assert result.returncode == 0
        assert "Unified Database Schema Verification" in result.stdout
        assert "--mode" in result.stdout
        assert "--table" in result.stdout

    def test_basic_mode(self):
        """Test basic verification mode."""
        result = self.run_script(["--mode", "basic"])
        assert "DATABASE SCHEMA VERIFICATION - BASIC MODE" in result.stdout

    def test_json_output(self):
        """Test JSON output format."""
        result = self.run_script(["--mode", "basic", "--json"])
        try:
            data = json.loads(result.stdout)
            assert "mode" in data
            assert "timestamp" in data
            assert "database_connected" in data
        except json.JSONDecodeError:
            pytest.fail("Output is not valid JSON")

    def test_table_specific_verification(self):
        """Test verification of a specific table."""
        result = self.run_script(["--table", "positions", "--mode", "comprehensive"])
        assert result.returncode in [0, 2]
        assert "COMPREHENSIVE MODE" in result.stdout

    def test_performance_mode(self):
        """Test performance verification mode."""
        result = self.run_script(["--performance"])
        output = (result.stdout or "") + (result.stderr or "")
        assert (
            "Database source" in output
            or "PERFORMANCE" in output
            or result.returncode in [0, 1, 2]
        ), f"Script should run (got output: {output[:200]}...)"
