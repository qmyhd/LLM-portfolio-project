#!/usr/bin/env python
"""
Unit tests for parser quality check functions.

These tests validate that the check_idea_quality() function correctly
handles edge cases like:
- Short trade execution ideas (should be exempt)
- Duplicate idea detection
- Quality check skip flag

These are hard failures (not warnings) for critical quality logic.
"""

import pytest
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Import check functions from the sibling module
from test_parser_regression import (
    check_idea_quality,
    TRADE_EXECUTION_ACTIONS,
    MIN_IDEA_TEXT_LENGTH,
)


class TestQualityCheckExemptions:
    """Test that trade execution ideas are exempt from short-length check."""

    def test_short_buy_action_is_exempt(self):
        """Short BUY idea should pass quality check."""
        ideas = [
            {"idea_text": "BUY COHR", "action": "buy"},  # 8 chars < 20
        ]
        passed, msg = check_idea_quality(ideas)
        assert passed, f"Short BUY idea should be exempt: {msg}"

    def test_short_crypto_instrument_is_exempt(self):
        """Short crypto idea should pass quality check (crypto is terse)."""
        ideas = [
            {
                "idea_text": "BTC short 65k",
                "action": None,
                "instrument": "crypto",
            },  # 13 chars < 20
        ]
        passed, msg = check_idea_quality(ideas)
        assert passed, f"Short crypto idea should be exempt: {msg}"

    def test_short_sell_action_is_exempt(self):
        """Short SELL idea should pass quality check."""
        ideas = [
            {"idea_text": "SELL NVDA", "action": "sell"},  # 9 chars < 20
        ]
        passed, msg = check_idea_quality(ideas)
        assert passed, f"Short SELL idea should be exempt: {msg}"

    def test_short_trim_action_is_exempt(self):
        """Short TRIM idea should pass quality check."""
        ideas = [
            {"idea_text": "Trimmed AMD", "action": "trim"},  # 11 chars < 20
        ]
        passed, msg = check_idea_quality(ideas)
        assert passed, f"Short TRIM idea should be exempt: {msg}"

    def test_short_watch_action_is_not_exempt(self):
        """Short WATCH idea should NOT be exempt (not a trade execution)."""
        ideas = [
            {"idea_text": "Watch AAPL", "action": "watch"},  # 10 chars < 20
        ]
        passed, msg = check_idea_quality(ideas)
        # WATCH is not in TRADE_EXECUTION_ACTIONS, so should fail
        assert not passed, "Short WATCH idea should NOT be exempt"
        assert "too short" in msg

    def test_short_narrative_fails_quality_check(self):
        """Short narrative without action should fail quality check."""
        ideas = [
            {"idea_text": "Good point", "action": None},  # 10 chars < 20
        ]
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

    def test_similar_but_not_exact_pass(self):
        """Similar but not exact ideas should pass."""
        ideas = [
            {"idea_text": "NVDA looking bullish into earnings report"},
            {"idea_text": "NVDA looks bullish into earnings next week"},
        ]
        passed, msg = check_idea_quality(ideas)
        assert passed, f"Similar but not exact should pass: {msg}"


class TestMixedIdeas:
    """Test quality checks with mixed idea types."""

    def test_mixed_short_trade_and_long_narrative(self):
        """Mix of short trade execution and long narrative should pass."""
        ideas = [
            {"idea_text": "BUY AAPL", "action": "buy"},  # Short but exempt
            {
                "idea_text": "AAPL looking strong going into Q4 earnings with iPhone sales momentum",
                "action": None,
            },
        ]
        passed, msg = check_idea_quality(ideas)
        assert passed, f"Mixed ideas should pass: {msg}"

    def test_all_trade_execution_actions_exempt(self):
        """All trade execution actions should be exempt from short check."""
        for action in TRADE_EXECUTION_ACTIONS:
            ideas = [{"idea_text": "X", "action": action}]  # 1 char
            passed, msg = check_idea_quality(ideas)
            assert passed, f"Action '{action}' should be exempt: {msg}"


class TestEdgeCases:
    """Test edge cases for quality checks."""

    def test_empty_ideas_list_passes(self):
        """Empty ideas list should pass quality check."""
        passed, msg = check_idea_quality([])
        assert passed, f"Empty list should pass: {msg}"

    def test_missing_idea_text_treated_as_empty(self):
        """Missing idea_text key should be treated as empty string."""
        ideas = [{"action": "buy"}]  # No idea_text key
        passed, msg = check_idea_quality(ideas)
        # Empty string is < MIN_IDEA_TEXT_LENGTH but action=buy is exempt
        assert passed, f"Missing idea_text with buy action should pass: {msg}"

    def test_case_insensitive_duplicate_detection(self):
        """Duplicate detection should be case-insensitive."""
        ideas = [
            {"idea_text": "BUY AAPL AT 180"},
            {"idea_text": "buy aapl at 180"},
        ]
        passed, msg = check_idea_quality(ideas)
        assert not passed, "Case-insensitive duplicates should be flagged"
        assert "duplicate ideas" in msg


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
