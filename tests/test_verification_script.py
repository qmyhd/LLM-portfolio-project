"""
Test the unified database verification script.
"""

import unittest
import subprocess
import sys
import json
from pathlib import Path


class TestVerificationScript(unittest.TestCase):
    """Test the unified verify_database.py script."""

    def setUp(self):
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
        self.assertEqual(result.returncode, 0)
        self.assertIn("Unified Database Schema Verification", result.stdout)
        self.assertIn("--mode", result.stdout)
        self.assertIn("--table", result.stdout)

    def test_basic_mode(self):
        """Test basic verification mode."""
        result = self.run_script(["--mode", "basic"])
        # Should complete without crashing
        self.assertIn("DATABASE SCHEMA VERIFICATION - BASIC MODE", result.stdout)

    def test_json_output(self):
        """Test JSON output format."""
        result = self.run_script(["--mode", "basic", "--json"])
        try:
            data = json.loads(result.stdout)
            self.assertIn("mode", data)
            self.assertIn("timestamp", data)
            self.assertIn("database_connected", data)
        except json.JSONDecodeError:
            self.fail("Output is not valid JSON")

    def test_table_specific_verification(self):
        """Test verification of a specific table."""
        result = self.run_script(["--table", "positions", "--mode", "comprehensive"])
        # Should complete (return code 2 means verification failed, which is expected)
        self.assertIn(result.returncode, [0, 2])  # 0 = success, 2 = verification failed
        self.assertIn("COMPREHENSIVE MODE", result.stdout)

    def test_performance_mode(self):
        """Test performance verification mode."""
        result = self.run_script(["--performance"])
        # Should complete and indicate performance mode
        self.assertIn("PERFORMANCE MODE", result.stdout)


if __name__ == "__main__":
    unittest.main()
