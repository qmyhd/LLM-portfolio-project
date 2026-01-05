#!/usr/bin/env python
"""
Triage Regression Test Suite

Runs the triage regression fixture against the live triage_message() function.
Use this test whenever you modify TRIAGE_SYSTEM_PROMPT or related logic.

Note: Bot commands are pre-filtered before triage in the actual pipeline
(see process_message() which calls is_bot_command() before triage).
This test simulates that behavior.

Usage:
    python tests/test_triage_regression.py
    pytest tests/test_triage_regression.py -v
"""

import json
import sys
from pathlib import Path
from typing import List, Dict, Any

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv()

from src.nlp.openai_parser import triage_message
from src.nlp.preclean import is_bot_command, is_url_only


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "triage_regression.jsonl"


def load_regression_cases() -> List[Dict[str, Any]]:
    """Load test cases from JSONL fixture, skipping comments and empty lines."""
    cases = []
    with open(FIXTURE_PATH, "r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                case = json.loads(line)
                case["line_num"] = line_num
                cases.append(case)
            except json.JSONDecodeError as e:
                print(f"WARNING: Invalid JSON on line {line_num}: {e}")
    return cases


def run_triage_regression(verbose: bool = True) -> Dict[str, Any]:
    """
    Run all triage regression cases.

    Args:
        verbose: Print detailed PASS/FAIL for each case

    Returns:
        Summary dict with pass/fail counts and failed cases
    """
    cases = load_regression_cases()

    if not cases:
        print("ERROR: No test cases loaded from fixture")
        return {"total": 0, "passed": 0, "failed": 0, "failures": []}

    print(f"Loaded {len(cases)} triage regression cases")
    print("-" * 70)

    passed = 0
    failed = 0
    failures = []

    for case in cases:
        text = case["text"]
        expected_noise = case["expected_noise"]
        category = case.get("category", "unknown")

        try:
            # Pre-filter: Bot commands and URL-only are handled before triage
            # See process_message() in openai_parser.py
            if is_bot_command(text):
                actual_noise = True  # Bot commands are always noise
            elif is_url_only(text):
                actual_noise = True  # URL-only messages are always noise
            else:
                result = triage_message(text)
                actual_noise = result.is_noise

            if actual_noise == expected_noise:
                passed += 1
                status = "PASS"
            else:
                failed += 1
                status = "FAIL"
                failures.append(
                    {
                        "text": text,
                        "expected_noise": expected_noise,
                        "actual_noise": actual_noise,
                        "category": category,
                    }
                )

            if verbose:
                # Truncate long messages for display
                display_text = text[:50] + "..." if len(text) > 50 else text
                expected_str = "NOISE" if expected_noise else "NOT_NOISE"
                actual_str = "NOISE" if actual_noise else "NOT_NOISE"
                print(
                    f'{status}: [{category}] "{display_text}" (expected={expected_str}, actual={actual_str})'
                )

        except Exception as e:
            failed += 1
            failures.append(
                {
                    "text": text,
                    "expected_noise": expected_noise,
                    "actual_noise": None,
                    "category": category,
                    "error": str(e),
                }
            )
            if verbose:
                print(f'ERROR: [{category}] "{text[:50]}" - {e}')

    print("-" * 70)
    print(f"SUMMARY: {passed}/{len(cases)} passed, {failed} failed")

    if failures and verbose:
        print("\nFAILURES:")
        for f in failures:
            print(
                f'  - "{f["text"][:60]}" expected={f["expected_noise"]}, got={f["actual_noise"]}'
            )

    return {
        "total": len(cases),
        "passed": passed,
        "failed": failed,
        "failures": failures,
    }


# =============================================================================
# Pytest Integration
# =============================================================================


def test_triage_regression_all_pass():
    """Pytest test: All regression cases must pass."""
    result = run_triage_regression(verbose=False)

    if result["failures"]:
        failure_msgs = []
        for f in result["failures"]:
            expected = "NOISE" if f["expected_noise"] else "NOT_NOISE"
            actual = "NOISE" if f["actual_noise"] else "NOT_NOISE"
            failure_msgs.append(f'"{f["text"][:40]}" expected {expected}, got {actual}')

        failure_report = "\n".join(failure_msgs)
        raise AssertionError(
            f"Triage regression failed: {result['failed']}/{result['total']} cases\n{failure_report}"
        )

    assert result["passed"] == result["total"]


# =============================================================================
# CLI Entry Point
# =============================================================================


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run triage regression tests")
    parser.add_argument("--quiet", "-q", action="store_true", help="Only show summary")
    args = parser.parse_args()

    result = run_triage_regression(verbose=not args.quiet)

    # Exit with error code if any failures
    sys.exit(1 if result["failed"] > 0 else 0)
