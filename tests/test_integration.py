#!/usr/bin/env python3
"""
Quick integration test for the repository cleanup tasks.
"""

import sys
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).resolve().parents[1]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))


def test_ticker_extraction_integration():
    """Test that data_collector properly uses message_cleaner for ticker extraction."""
    from src.message_cleaner import extract_ticker_symbols
    from src.data_collector import append_discord_message_to_csv

    # Test direct function call
    test_message = "I bought $AAPL and $TSLA today! Also considering $NVDA"
    tickers = extract_ticker_symbols(test_message)

    print("✅ Ticker extraction integration test:")
    print(f"   Message: {test_message}")
    print(f"   Extracted tickers: {tickers}")
    print(f"   Expected: ['$AAPL', '$TSLA', '$NVDA']")

    # Assertions: each ticker must be present
    assert "$AAPL" in tickers, "$AAPL should be extracted"
    assert "$TSLA" in tickers, "$TSLA should be extracted"
    assert "$NVDA" in tickers, "$NVDA should be extracted"
    assert set(tickers) == {
        "$AAPL",
        "$TSLA",
        "$NVDA",
    }, f"Expected exactly 3 tickers, got {tickers}"
    print("   Result: ✅ PASS")


def test_import_consolidation():
    """Test that modules import correctly after consolidation."""
    modules_to_test = [
        (
            "src.message_cleaner",
            [
                "extract_ticker_symbols",
                "calculate_sentiment",
                "clean_text",
            ],
        ),
        ("src.snaptrade_collector", ["SnapTradeCollector"]),
        ("src.data_collector", ["append_discord_message_to_csv", "update_all_data"]),
        ("src.bot.commands.process", ["register"]),
    ]

    print("✅ Import consolidation test:")
    errors = []

    for module_name, expected_items in modules_to_test:
        module = __import__(module_name, fromlist=expected_items)

        missing_items = []
        for item in expected_items:
            if not hasattr(module, item):
                missing_items.append(item)

        if missing_items:
            print(f"   ❌ {module_name}: Missing {missing_items}")
            errors.append(f"{module_name}: Missing {missing_items}")
        else:
            print(f"   ✅ {module_name}: All items available")

    # Single assertion at end with all errors
    assert not errors, f"Import consolidation failed: {errors}"


def main():
    """Run all integration tests."""
    print("Repository Cleanup Integration Tests")
    print("=" * 50)

    tests = [
        ("Ticker Extraction Integration", test_ticker_extraction_integration),
        ("Import Consolidation", test_import_consolidation),
    ]

    passed = 0
    failed = 0
    total = len(tests)

    for test_name, test_func in tests:
        print(f"\n{test_name}:")
        try:
            test_func()
            passed += 1
        except AssertionError as e:
            print(f"   ❌ ASSERTION FAILED: {e}")
            failed += 1
        except Exception as e:
            print(f"   ❌ ERROR: {e}")
            failed += 1

    print(f"\n{'='*50}")
    print(f"Test Results: {passed}/{total} passed")

    if failed == 0:
        print("🎉 All tests passed! Repository cleanup successful.")
        return 0
    else:
        print("❌ Some tests failed. Check the output above.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
