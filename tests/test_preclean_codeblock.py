#!/usr/bin/env python
"""
Test code block handling in preclean.py

Verifies that multi-line code blocks preserve their content after normalization,
fixing the bug where code blocks were completely removed.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.nlp.preclean import normalize_text


def test_code_block_preserves_tickers():
    """Test that tickers inside code blocks are preserved after normalization."""
    text = """My watchlist for today:
```
$AAPL 180 call target
$GOOGL 195 resistance
$MSFT 450 support
```
Let me know your thoughts."""

    result = normalize_text(text)

    # All tickers should be preserved
    assert "$AAPL" in result, f"$AAPL not found in: {result}"
    assert "$GOOGL" in result, f"$GOOGL not found in: {result}"
    assert "$MSFT" in result, f"$MSFT not found in: {result}"

    # Code block markers should be removed
    assert "```" not in result, f"Code block markers still present: {result}"

    print("✅ Code block ticker preservation test passed")
    print(f"   Output: {result[:100]}...")


def test_code_block_with_language_specifier():
    """Test that code blocks with language specifiers are handled correctly."""
    text = """Here's my analysis:
```python
# This is Python code
x = 100
```
Back to normal text."""

    result = normalize_text(text)

    # Content should be preserved (even if it's actual code)
    assert "x = 100" in result, f"Code content not found: {result}"

    # Markers removed
    assert "```" not in result, f"Code block markers still present: {result}"

    print("✅ Code block with language specifier test passed")


def test_inline_code_preserves_content():
    """Test that inline code preserves content (existing behavior)."""
    text = "Check out `$AAPL` for a breakout play"

    result = normalize_text(text)

    assert "$AAPL" in result, f"$AAPL not found: {result}"
    assert "`" not in result, f"Backticks still present: {result}"

    print("✅ Inline code preservation test passed")


def test_empty_code_block():
    """Test handling of empty code blocks."""
    text = "Before\n```\n```\nAfter"

    result = normalize_text(text)

    assert "Before" in result, f"Before not found: {result}"
    assert "After" in result, f"After not found: {result}"

    print("✅ Empty code block test passed")


def test_nested_backticks():
    """Test that the regex doesn't get confused by nested/mismatched backticks."""
    text = "Start ```code``` middle ```more``` end"

    result = normalize_text(text)

    assert "code" in result, f"First code content not found: {result}"
    assert "more" in result, f"Second code content not found: {result}"
    assert "```" not in result, f"Backticks still present: {result}"

    print("✅ Multiple code blocks test passed")


if __name__ == "__main__":
    test_code_block_preserves_tickers()
    test_code_block_with_language_specifier()
    test_inline_code_preserves_content()
    test_empty_code_block()
    test_nested_backticks()
    print("\n✅ ALL CODE BLOCK TESTS PASSED")
