#!/usr/bin/env python
"""
Alias Mapping Unit Tests

Fast, deterministic tests for company name → ticker conversion.
These tests do NOT call OpenAI and should run in <1 second.

Usage:
    pytest tests/test_alias_mapping.py -v
    python tests/test_alias_mapping.py
"""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.nlp.preclean import apply_alias_mapping, extract_tickers_from_text


# =============================================================================
# ALIAS MAPPING TESTS
# =============================================================================


def test_nvidia_alias_mapping():
    """Test that 'nvidia' gets converted to $NVDA."""
    input_text = "Buy any nvidia dip"
    result = apply_alias_mapping(input_text)

    assert "$NVDA" in result, f"Expected $NVDA in result, got: {result}"
    assert (
        "nvidia" not in result.lower() or "$NVDA" in result
    ), "nvidia should be replaced with $NVDA"


def test_tsmc_alias_mapping():
    """Test that 'tsmc' gets converted to $TSM."""
    input_text = "tsmc looking strong"
    result = apply_alias_mapping(input_text)

    assert "$TSM" in result, f"Expected $TSM in result, got: {result}"
    assert (
        "tsmc" not in result.lower() or "$TSM" in result
    ), "tsmc should be replaced with $TSM"


def test_multiple_aliases_in_one_message():
    """Test that multiple company names are all converted."""
    input_text = "Buy any nvidia or tsmc dip"
    result = apply_alias_mapping(input_text)

    assert "$NVDA" in result, f"Expected $NVDA in result, got: {result}"
    assert "$TSM" in result, f"Expected $TSM in result, got: {result}"

    # Extract tickers to verify both are present
    tickers = extract_tickers_from_text(result)
    assert "NVDA" in tickers, f"Expected NVDA in extracted tickers, got: {tickers}"
    assert "TSM" in tickers, f"Expected TSM in extracted tickers, got: {tickers}"


def test_google_waymo_alias_mapping():
    """Test that 'google' and 'waymo' both map to $GOOGL."""
    input_text = "super bullish google + waymo long term"
    result = apply_alias_mapping(input_text)

    assert "$GOOGL" in result, f"Expected $GOOGL in result, got: {result}"

    # Count how many times GOOGL appears (should be 2, once for each alias)
    tickers = extract_tickers_from_text(result)
    googl_count = tickers.count("GOOGL")
    assert googl_count == 2, f"Expected 2 GOOGL mentions, got {googl_count}"


def test_already_ticker_format():
    """Test that existing $TICKER format is preserved."""
    input_text = "$NVDA and $TSM looking good"
    result = apply_alias_mapping(input_text)

    # Should not double-prefix
    assert "$$NVDA" not in result, "Should not double-prefix tickers"
    assert "$NVDA" in result, "Should preserve existing $NVDA"
    assert "$TSM" in result, "Should preserve existing $TSM"


def test_case_insensitive_mapping():
    """Test that company names are matched case-insensitively."""
    # Test various capitalizations
    test_cases = [
        "NVIDIA is great",
        "Nvidia is great",
        "nvidia is great",
        "NVidia is great",
    ]

    for input_text in test_cases:
        result = apply_alias_mapping(input_text)
        assert "$NVDA" in result, f"Failed for: {input_text} → {result}"


def test_word_boundary_matching():
    """Test that partial matches are NOT replaced."""
    # "nvidiawesome" should NOT match "nvidia"
    input_text = "nvidiawesome is not a real word"
    result = apply_alias_mapping(input_text)

    assert "$NVDA" not in result, "Should not match partial words like 'nvidiawesome'"


def test_multiple_mappings_same_company():
    """Test that different aliases for same company all map correctly."""
    test_cases = [
        ("google is great", "$GOOGL"),
        ("alphabet acquisition", "$GOOGL"),
        ("waymo expansion", "$GOOGL"),
        ("youtube revenue", "$GOOGL"),
    ]

    for input_text, expected_ticker in test_cases:
        result = apply_alias_mapping(input_text)
        assert (
            expected_ticker in result
        ), f"Failed for {input_text}: expected {expected_ticker} in {result}"


def test_empty_and_none_inputs():
    """Test that empty/None inputs are handled gracefully."""
    assert apply_alias_mapping("") == ""
    assert apply_alias_mapping(None) == None


def test_no_aliases_present():
    """Test that text without aliases is returned unchanged."""
    input_text = "The market is volatile today"
    result = apply_alias_mapping(input_text)

    assert result == input_text, "Text without aliases should be unchanged"


def test_mixed_tickers_and_aliases():
    """Test messages with both existing tickers and aliases."""
    input_text = "Bought $AAPL, watching nvidia and tsmc"
    result = apply_alias_mapping(input_text)

    # All three should be present as tickers
    assert "$AAPL" in result
    assert "$NVDA" in result
    assert "$TSM" in result

    # Extract and count
    tickers = extract_tickers_from_text(result)
    assert len(tickers) == 3, f"Expected 3 tickers, got: {tickers}"


# =============================================================================
# TICKER EXTRACTION TESTS
# =============================================================================


def test_extract_tickers_from_mapped_text():
    """Test that extract_tickers_from_text works correctly after mapping."""
    input_text = "Buy nvidia or tsmc dip"
    mapped = apply_alias_mapping(input_text)
    tickers = extract_tickers_from_text(mapped)

    assert "NVDA" in tickers
    assert "TSM" in tickers
    assert len(tickers) == 2


def test_extract_tickers_deduplication():
    """Test that duplicate ticker mentions are preserved (not deduplicated)."""
    input_text = "$AAPL is great, $AAPL to the moon"
    tickers = extract_tickers_from_text(input_text)

    # Should return both mentions
    assert tickers.count("AAPL") == 2


# =============================================================================
# CLI Entry Point
# =============================================================================


if __name__ == "__main__":
    print("Running alias mapping unit tests...\n")

    tests = [
        test_nvidia_alias_mapping,
        test_tsmc_alias_mapping,
        test_multiple_aliases_in_one_message,
        test_google_waymo_alias_mapping,
        test_already_ticker_format,
        test_case_insensitive_mapping,
        test_word_boundary_matching,
        test_multiple_mappings_same_company,
        test_empty_and_none_inputs,
        test_no_aliases_present,
        test_mixed_tickers_and_aliases,
        test_extract_tickers_from_mapped_text,
        test_extract_tickers_deduplication,
    ]

    passed = 0
    failed = 0

    for test_func in tests:
        try:
            test_func()
            print(f"✅ {test_func.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"❌ {test_func.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"💥 {test_func.__name__}: {type(e).__name__}: {e}")
            failed += 1

    print(f"\n{'='*70}")
    print(f"SUMMARY: {passed}/{len(tests)} passed, {failed} failed")
    print(f"{'='*70}")

    sys.exit(0 if failed == 0 else 1)
