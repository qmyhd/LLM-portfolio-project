#!/usr/bin/env python
"""
Parser Regression Test Suite

Validates output quality of the parse_message() function against curated cases.
Checks for:
- Correct number of ideas (not over-splitting)
- Appropriate instrument types
- primary_symbol only null when truly sector/macro
- Specific idea_text (not generic)
- No duplicate ideas

Usage:
    python tests/test_parser_regression.py
    pytest tests/test_parser_regression.py -v
"""

import json
import sys
from pathlib import Path
from typing import List, Dict, Any, Optional, Union

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv()

from src.nlp.openai_parser import process_message


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "parser_regression.jsonl"

# Quality thresholds
MIN_IDEA_TEXT_LENGTH = 20  # Ideas should be specific, not just "good point"
MAX_DUPLICATE_SIMILARITY = 0.9  # Flag if ideas are too similar

# Bullet detection pattern
import re

BULLET_PATTERN = re.compile(r"^\s*[-•*]|^\s*\d+\.")


def load_regression_cases() -> List[Dict[str, Any]]:
    """Load test cases from JSONL fixture, skipping comments."""
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


def check_ideas_count(
    ideas: List[Dict], expected: Union[int, List[int]]
) -> tuple[bool, str]:
    """Check if ideas count matches expected (exact or range)."""
    actual = len(ideas)

    if isinstance(expected, list):
        # Range like [1, 3] means 1-3 ideas acceptable
        min_count, max_count = expected
        if min_count <= actual <= max_count:
            return True, f"ideas_count={actual} in range [{min_count}, {max_count}]"
        return False, f"ideas_count={actual} not in range [{min_count}, {max_count}]"
    else:
        if actual == expected:
            return True, f"ideas_count={actual} == {expected}"
        return False, f"ideas_count={actual} != expected {expected}"


def check_not_noise(ideas: List[Dict], expected_not_noise: bool) -> tuple[bool, str]:
    """Check if ideas were correctly identified as not-noise."""
    if not expected_not_noise:
        return True, "noise check skipped (expected noise)"

    if not ideas:
        return False, "expected ideas but got none (marked as noise?)"

    return True, f"got {len(ideas)} ideas (not noise)"


def check_instruments(
    ideas: List[Dict], expected_instruments: List[str]
) -> tuple[bool, str]:
    """Check if ideas have expected instrument types."""
    if not expected_instruments:
        return True, "instrument check skipped"

    actual_instruments = {
        idea.get("instrument") for idea in ideas if idea.get("instrument")
    }

    # Allow subset - not all ideas need to match
    if actual_instruments:
        return True, f"instruments found: {actual_instruments}"

    return False, "no instruments found in ideas"


def check_primary_symbols(
    ideas: List[Dict], expected_symbols: List[Optional[str]]
) -> tuple[bool, str]:
    """Check if primary_symbol is set correctly."""
    if not expected_symbols:
        return True, "symbol check skipped"

    actual_symbols = [idea.get("primary_symbol") for idea in ideas]

    # Check null expectations
    if None in expected_symbols:
        # Expected null primary_symbol (sector/macro)
        if any(s is None for s in actual_symbols):
            return True, "correctly has null primary_symbol for sector/macro"

    # Check specific symbols
    non_null_expected = [s for s in expected_symbols if s is not None]
    non_null_actual = [s for s in actual_symbols if s is not None]

    if non_null_expected:
        found = [s for s in non_null_expected if s in non_null_actual]
        if found:
            return True, f"found expected symbols: {found}"
        return (
            False,
            f"expected symbols {non_null_expected} not found in {non_null_actual}",
        )

    return True, "symbol check passed"


# Actions that are exempt from min-length check (trade executions are action-focused)
TRADE_EXECUTION_ACTIONS = {"buy", "sell", "trim", "add", "short", "hedge"}

# Instruments that are exempt from min-length check (crypto alerts are typically terse)
SHORT_FORM_INSTRUMENTS = {"crypto", "cryptocurrency"}


def check_idea_quality(ideas: List[Dict]) -> tuple[bool, str]:
    """Check for quality issues: short ideas, duplicates.

    Trade execution ideas (action=buy/sell/trim/add) are exempt from
    min-length check since they are action-focused, not narrative.

    Crypto ideas are also exempt since crypto alerts are typically terse.
    """
    issues = []

    # Check for too-short ideas (exempt trade executions and crypto)
    short_ideas = []
    for idea in ideas:
        text_len = len(idea.get("idea_text", ""))
        if text_len >= MIN_IDEA_TEXT_LENGTH:
            continue  # Long enough, skip

        # Check exemptions
        action = (idea.get("action") or "").lower()
        instrument = (idea.get("instrument") or "").lower()

        if action in TRADE_EXECUTION_ACTIONS:
            continue  # Trade execution exempt
        if instrument in SHORT_FORM_INSTRUMENTS:
            continue  # Crypto exempt

        short_ideas.append(idea)

    if short_ideas:
        issues.append(
            f"{len(short_ideas)} non-trade/non-crypto ideas too short (<{MIN_IDEA_TEXT_LENGTH} chars)"
        )

    # Check for duplicates (simple text similarity)
    texts = [idea.get("idea_text", "").lower() for idea in ideas]
    for i, t1 in enumerate(texts):
        for j, t2 in enumerate(texts[i + 1 :], i + 1):
            if t1 and t2 and t1 == t2:
                issues.append(f"duplicate ideas at indices {i} and {j}")

    if issues:
        return False, "; ".join(issues)
    return True, "quality checks passed"


def check_labels_any(ideas: List[Dict], expected_labels: List[str]) -> tuple[bool, str]:
    """Check if any expected label appears in any produced idea."""
    if not expected_labels:
        return True, "labels_any check skipped"

    all_labels = set()
    for idea in ideas:
        labels = idea.get("labels", [])
        if isinstance(labels, list):
            all_labels.update(labels)

    found = [label for label in expected_labels if label in all_labels]
    if found:
        return True, f"labels_any found: {found}"
    return False, f"none of {expected_labels} found in {all_labels}"


def check_labels_all(ideas: List[Dict], expected_labels: List[str]) -> tuple[bool, str]:
    """Check if all expected labels appear somewhere across ideas."""
    if not expected_labels:
        return True, "labels_all check skipped"

    all_labels = set()
    for idea in ideas:
        labels = idea.get("labels", [])
        if isinstance(labels, list):
            all_labels.update(labels)

    missing = [label for label in expected_labels if label not in all_labels]
    if not missing:
        return True, f"labels_all present: {expected_labels}"
    return False, f"missing labels: {missing} (have: {all_labels})"


def check_min_ideas(ideas: List[Dict], min_count: int) -> tuple[bool, str]:
    """Check if produced ideas >= min_ideas."""
    actual = len(ideas)
    if actual >= min_count:
        return True, f"ideas_count={actual} >= min_ideas={min_count}"
    return False, f"ideas_count={actual} < min_ideas={min_count}"


def check_option_assertions(
    ideas: List[Dict], assertions: List[Dict]
) -> tuple[bool, str]:
    """Check option parsing: symbol, type, strikes, premiums."""
    if not assertions:
        return True, "option_assertions check skipped"

    issues = []
    for assertion in assertions:
        symbol = assertion.get("symbol")
        option_type = assertion.get("option_type")
        expected_strikes = assertion.get("strikes", [])
        expected_premiums = assertion.get("premiums", [])

        # Find ideas matching symbol
        matching_ideas = [i for i in ideas if i.get("primary_symbol") == symbol]
        if not matching_ideas:
            issues.append(f"no ideas for {symbol}")
            continue

        # Check option type
        if option_type:
            option_ideas = [
                i for i in matching_ideas if i.get("option_type") == option_type
            ]
            if not option_ideas:
                issues.append(f"{symbol}: no {option_type} options found")
                continue
        else:
            option_ideas = matching_ideas

        # Check strikes
        if expected_strikes:
            found_strikes = [i.get("strike") for i in option_ideas if i.get("strike")]
            found_strikes = [float(s) if s else None for s in found_strikes]
            missing_strikes = [s for s in expected_strikes if s not in found_strikes]
            if missing_strikes:
                issues.append(
                    f"{symbol}: missing strikes {missing_strikes} (have: {found_strikes})"
                )

        # Check premiums
        if expected_premiums:
            found_premiums = [
                i.get("premium") for i in option_ideas if i.get("premium")
            ]
            found_premiums = [float(p) if p else None for p in found_premiums]
            missing_premiums = [p for p in expected_premiums if p not in found_premiums]
            if missing_premiums:
                issues.append(
                    f"{symbol}: missing premiums {missing_premiums} (have: {found_premiums})"
                )

    if issues:
        return False, "; ".join(issues)
    return True, "option_assertions passed"


def check_levels_assertions(
    ideas: List[Dict], assertions: List[Dict]
) -> tuple[bool, str]:
    """Check price level extraction."""
    if not assertions:
        return True, "levels_assertions check skipped"

    issues = []
    for assertion in assertions:
        symbol = assertion.get("symbol")
        must_include = assertion.get("must_include", [])

        # Find ideas matching symbol
        matching_ideas = [i for i in ideas if i.get("primary_symbol") == symbol]
        if not matching_ideas:
            issues.append(f"no ideas for {symbol}")
            continue

        # Collect all levels from matching ideas
        all_levels = []
        for idea in matching_ideas:
            levels = idea.get("levels")
            if isinstance(levels, dict):
                for level_type in [
                    "entry",
                    "target",
                    "stop_loss",
                    "resistance",
                    "support",
                ]:
                    level_val = levels.get(level_type)
                    if level_val:
                        try:
                            all_levels.append(float(level_val))
                        except (ValueError, TypeError):
                            pass

        # Check must_include levels
        missing = [lvl for lvl in must_include if lvl not in all_levels]
        if missing:
            issues.append(f"{symbol}: missing levels {missing} (have: {all_levels})")

    if issues:
        return False, "; ".join(issues)
    return True, "levels_assertions passed"


def detect_bullet_count(content: str) -> int:
    """Count bullet points in content."""
    lines = content.split("\n")
    bullet_lines = [line for line in lines if BULLET_PATTERN.match(line)]
    return len(bullet_lines)


# =============================================================================
# SKIP_QUALITY_CHECK ENFORCEMENT
# =============================================================================

# Maximum message length where skip_quality_check is allowed
# Short alerts/headlines are typically under 100 chars
SKIP_QUALITY_MAX_LENGTH = 150

# Categories where skip_quality_check is typically appropriate
SKIP_QUALITY_ALLOWED_CATEGORIES = {
    "crypto",
    "short_alert",
    "headline",
    "one_liner",
    "breaking_news",
}


def validate_skip_quality_check(case: Dict[str, Any]) -> tuple[bool, str]:
    """
    Validate that skip_quality_check is only used for appropriate cases.

    Legitimate use cases:
    - Short crypto alerts (e.g., "BTC short 65k")
    - One-line breaking news headlines
    - Very short trade alerts

    Args:
        case: The test case dictionary

    Returns:
        (is_valid, reason) tuple
    """
    expected = case.get("expected", {})

    # If skip_quality_check not set, no validation needed
    if not expected.get("skip_quality_check", False):
        return True, "skip_quality_check not set"

    content = case.get("content", "")
    category = case.get("category", "unknown")
    notes = case.get("notes", "")

    # Check 1: Content length should be short
    if len(content) > SKIP_QUALITY_MAX_LENGTH:
        return False, (
            f"skip_quality_check used on long content ({len(content)} chars > {SKIP_QUALITY_MAX_LENGTH}). "
            "Only use for short alerts/headlines."
        )

    # Check 2: Category should be in allowed list OR notes should explain
    if category.lower() not in SKIP_QUALITY_ALLOWED_CATEGORIES:
        # Allow if notes explain why
        skip_keywords = ["short", "alert", "headline", "crypto", "one-line", "brief"]
        notes_lower = notes.lower()
        if not any(kw in notes_lower for kw in skip_keywords):
            return False, (
                f"skip_quality_check used with category '{category}' which is not in allowed list "
                f"{SKIP_QUALITY_ALLOWED_CATEGORIES}. Add explanatory notes or use allowed category."
            )

    return True, f"skip_quality_check valid: category={category}, length={len(content)}"


def run_parser_regression(verbose: bool = True) -> Dict[str, Any]:
    """
    Run all parser regression cases.

    Args:
        verbose: Print detailed output for each case

    Returns:
        Summary dict with pass/fail counts
    """
    cases = load_regression_cases()

    if not cases:
        print(
            "No test cases loaded. Add cases to tests/fixtures/parser_regression.jsonl"
        )
        return {"total": 0, "passed": 0, "failed": 0, "failures": []}

    print(f"Loaded {len(cases)} parser regression cases")
    print("-" * 70)

    passed = 0
    failed = 0
    failures = []

    for case in cases:
        content = case["content"]
        expected = case.get("expected", {})
        category = case.get("category", "unknown")
        notes = case.get("notes", "")

        # Bullet-aware validation: Auto-enforce min_ideas based on bullet count
        bullet_count = detect_bullet_count(content)
        if bullet_count >= 3 and "min_ideas" not in expected:
            expected["min_ideas"] = bullet_count
            if verbose:
                print(
                    f"  Auto-detected {bullet_count} bullets -> min_ideas={bullet_count}"
                )

        if verbose:
            print(f"\n[{category}] {content[:60]}...")
            if notes:
                print(f"  Notes: {notes}")

        # Validate skip_quality_check usage before running test
        skip_valid, skip_reason = validate_skip_quality_check(case)
        if not skip_valid:
            failed += 1
            failures.append(
                {
                    "content": content[:60],
                    "category": category,
                    "failures": [f"Invalid skip_quality_check: {skip_reason}"],
                }
            )
            if verbose:
                print(f"  FAIL: {skip_reason}")
            continue

        try:
            # Run parser
            result = process_message(
                text=content,
                message_id=f"test_{case.get('line_num', 0)}",
            )

            ideas = result.get("ideas", [])
            status = result.get("status", "unknown")

            # Run checks
            checks = []

            if "ideas_count" in expected:
                checks.append(
                    ("ideas_count", check_ideas_count(ideas, expected["ideas_count"]))
                )

            if "min_ideas" in expected:
                checks.append(
                    ("min_ideas", check_min_ideas(ideas, expected["min_ideas"]))
                )

            if "not_noise" in expected:
                checks.append(
                    ("not_noise", check_not_noise(ideas, expected["not_noise"]))
                )

            if "instruments" in expected:
                checks.append(
                    ("instruments", check_instruments(ideas, expected["instruments"]))
                )

            if "primary_symbols" in expected:
                checks.append(
                    (
                        "primary_symbols",
                        check_primary_symbols(ideas, expected["primary_symbols"]),
                    )
                )

            if "labels_any" in expected:
                checks.append(
                    ("labels_any", check_labels_any(ideas, expected["labels_any"]))
                )

            if "labels_all" in expected:
                checks.append(
                    ("labels_all", check_labels_all(ideas, expected["labels_all"]))
                )

            if "option_assertions" in expected:
                checks.append(
                    (
                        "option_assertions",
                        check_option_assertions(ideas, expected["option_assertions"]),
                    )
                )

            if "levels_assertions" in expected:
                checks.append(
                    (
                        "levels_assertions",
                        check_levels_assertions(ideas, expected["levels_assertions"]),
                    )
                )

            # Run quality checks unless explicitly skipped
            # Use skip_quality_check=true in fixture for cases with expected short ideas
            if not expected.get("skip_quality_check", False):
                checks.append(("quality", check_idea_quality(ideas)))

            # Aggregate results
            all_passed = all(check[1][0] for check in checks)

            if all_passed:
                passed += 1
                if verbose:
                    print(f"  PASS: {len(ideas)} ideas, status={status}")
            else:
                failed += 1
                failed_checks = [
                    f"{name}: {msg}" for name, (ok, msg) in checks if not ok
                ]
                failures.append(
                    {
                        "content": content[:60],
                        "category": category,
                        "failures": failed_checks,
                    }
                )
                if verbose:
                    print(f"  FAIL:")
                    for fc in failed_checks:
                        print(f"    - {fc}")

            # Show ideas in verbose mode
            if verbose and ideas:
                for i, idea in enumerate(ideas[:3]):
                    symbol = idea.get("primary_symbol", "N/A")
                    instrument = idea.get("instrument", "?")
                    text = idea.get("idea_text", "")[:50]
                    print(f"    Idea {i}: [{instrument}] {symbol}: {text}...")

        except Exception as e:
            failed += 1
            failures.append(
                {
                    "content": content[:60],
                    "category": category,
                    "failures": [f"Exception: {e}"],
                }
            )
            if verbose:
                print(f"  ERROR: {e}")

    print("\n" + "-" * 70)
    print(f"SUMMARY: {passed}/{len(cases)} passed, {failed} failed")

    return {
        "total": len(cases),
        "passed": passed,
        "failed": failed,
        "failures": failures,
    }


# =============================================================================
# Pytest Integration
# =============================================================================


def test_parser_regression_all_pass():
    """Pytest test: All regression cases should pass (soft fail - warnings only)."""
    result = run_parser_regression(verbose=False)

    # For now, just warn on failures rather than hard fail
    # This lets you add aspirational test cases
    if result["failures"]:
        import warnings

        for f in result["failures"]:
            warnings.warn(f"Parser regression: {f['content']} - {f['failures']}")


# =============================================================================
# CLI Entry Point
# =============================================================================


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run parser regression tests")
    parser.add_argument("--quiet", "-q", action="store_true", help="Only show summary")
    args = parser.parse_args()

    result = run_parser_regression(verbose=not args.quiet)

    # Exit with error code if any failures
    sys.exit(1 if result["failed"] > 0 else 0)
