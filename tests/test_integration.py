"""
Quick integration test for repository setup validation.

Verifies that core modules import correctly after setup.
"""

import pytest


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
        ("src.bot.commands.process", ["register"]),
    ]

    errors = []

    for module_name, expected_items in modules_to_test:
        module = __import__(module_name, fromlist=expected_items)

        missing_items = []
        for item in expected_items:
            if not hasattr(module, item):
                missing_items.append(item)

        if missing_items:
            errors.append(f"{module_name}: Missing {missing_items}")

    assert not errors, f"Import consolidation failed: {errors}"
