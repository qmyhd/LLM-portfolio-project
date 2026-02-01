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

import pytest

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


@pytest.mark.openai
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
# Quality Check Tests (merged from test_parser_quality_checks.py)
# =============================================================================


# Actions that are exempt from min-length check (trade executions are action-focused)
TRADE_EXECUTION_ACTIONS = {"buy", "sell", "trim", "add", "short", "hedge"}
MIN_IDEA_TEXT_LENGTH = 20


def check_idea_quality(ideas):
    """Check for quality issues: short ideas, duplicates."""
    issues = []

    # Check for too-short ideas (exempt trade executions)
    short_ideas = []
    for idea in ideas:
        text_len = len(idea.get("idea_text", ""))
        if text_len >= MIN_IDEA_TEXT_LENGTH:
            continue

        action = (idea.get("action") or "").lower()
        instrument = (idea.get("instrument") or "").lower()

        if action in TRADE_EXECUTION_ACTIONS:
            continue
        if instrument in {"crypto", "cryptocurrency"}:
            continue

        short_ideas.append(idea)

    if short_ideas:
        issues.append(f"{len(short_ideas)} non-trade/non-crypto ideas too short")

    # Check for duplicates
    texts = [idea.get("idea_text", "").lower() for idea in ideas]
    for i, t1 in enumerate(texts):
        for j, t2 in enumerate(texts[i + 1 :], i + 1):
            if t1 and t2 and t1 == t2:
                issues.append(f"duplicate ideas at indices {i} and {j}")

    if issues:
        return False, "; ".join(issues)
    return True, "quality checks passed"


class TestQualityCheckExemptions:
    """Test that trade execution ideas are exempt from short-length check."""

    def test_short_buy_action_is_exempt(self):
        """Short BUY idea should pass quality check."""
        ideas = [{"idea_text": "BUY COHR", "action": "buy"}]
        passed, msg = check_idea_quality(ideas)
        assert passed, f"Short BUY idea should be exempt: {msg}"

    def test_short_crypto_instrument_is_exempt(self):
        """Short crypto idea should pass quality check."""
        ideas = [{"idea_text": "BTC short 65k", "action": None, "instrument": "crypto"}]
        passed, msg = check_idea_quality(ideas)
        assert passed, f"Short crypto idea should be exempt: {msg}"

    def test_short_sell_action_is_exempt(self):
        """Short SELL idea should pass quality check."""
        ideas = [{"idea_text": "SELL NVDA", "action": "sell"}]
        passed, msg = check_idea_quality(ideas)
        assert passed, f"Short SELL idea should be exempt: {msg}"

    def test_short_watch_action_is_not_exempt(self):
        """Short WATCH idea should NOT be exempt."""
        ideas = [{"idea_text": "Watch AAPL", "action": "watch"}]
        passed, msg = check_idea_quality(ideas)
        assert not passed, "Short WATCH idea should NOT be exempt"
        assert "too short" in msg

    def test_short_narrative_fails_quality_check(self):
        """Short narrative without action should fail quality check."""
        ideas = [{"idea_text": "Good point", "action": None}]
        passed, msg = check_idea_quality(ideas)
        assert not passed, "Short narrative should fail quality check"
        assert "too short" in msg

    def test_long_idea_always_passes(self):
        """Ideas longer than MIN_IDEA_TEXT_LENGTH always pass."""
        ideas = [
            {
                "idea_text": "This is a sufficiently long idea text for testing",
                "action": None,
            },
        ]
        passed, msg = check_idea_quality(ideas)
        assert passed, f"Long idea should pass: {msg}"


class TestDuplicateDetection:
    """Test duplicate idea detection logic."""

    def test_exact_duplicate_detected(self):
        """Exact text duplicates should be flagged."""
        ideas = [
            {"idea_text": "This is the same idea text repeated"},
            {"idea_text": "This is the same idea text repeated"},
        ]
        passed, msg = check_idea_quality(ideas)
        assert not passed, "Exact duplicates should be flagged"
        assert "duplicate ideas" in msg

    def test_different_ideas_pass(self):
        """Different ideas should pass duplicate check."""
        ideas = [
            {"idea_text": "NVDA looking bullish into earnings"},
            {"idea_text": "AMD consolidating before breakout"},
        ]
        passed, msg = check_idea_quality(ideas)
        assert passed, f"Different ideas should pass: {msg}"

    def test_case_insensitive_duplicate_detection(self):
        """Duplicate detection should be case-insensitive."""
        ideas = [
            {"idea_text": "BUY AAPL AT 180"},
            {"idea_text": "buy aapl at 180"},
        ]
        passed, _ = check_idea_quality(ideas)
        assert not passed, "Case-insensitive duplicates should be flagged"


class TestEdgeCases:
    """Test edge cases for quality checks."""

    def test_empty_ideas_list_passes(self):
        """Empty ideas list should pass quality check."""
        passed, msg = check_idea_quality([])
        assert passed, f"Empty list should pass: {msg}"

    def test_missing_idea_text_treated_as_empty(self):
        """Missing idea_text key with buy action should pass."""
        ideas = [{"action": "buy"}]
        passed, msg = check_idea_quality(ideas)
        assert passed, f"Missing idea_text with buy action should pass: {msg}"
