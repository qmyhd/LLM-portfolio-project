"""Smoke tests for the Discord channel-name → channel-type classifier.

These pin the most-specific-wins ordering so a future contributor doesn't
accidentally re-order the list and break the sentiment feed's channel
filters (trading-picks vs general chat).
"""

import pytest

from src.bot.events import get_channel_type


@pytest.mark.parametrize(
    "channel_name,expected",
    [
        # Trading variants — most specific first
        ("trading-picks", "trading"),
        ("trade-picks", "trading"),
        ("trading-signals", "trading"),
        ("trading-alerts", "trading"),
        ("trading-ideas", "trading"),
        ("daily-picks", "trading"),
        ("signals", "trading"),
        ("alerts", "trading"),
        ("trading", "trading"),
        ("trades", "trading"),
        ("swing-trades", "trading"),
        # Market variants
        ("market-news", "market"),
        ("news", "market"),
        ("market", "market"),
        ("market-chat", "market"),
        ("macro", "market"),
        ("earnings-watch", "market"),
        # General fallback
        ("general", "general"),
        ("chat", "general"),
        ("off-topic", "general"),
        ("random", "general"),
        ("", "general"),
    ],
)
def test_get_channel_type(channel_name: str, expected: str) -> None:
    assert get_channel_type(channel_name) == expected


def test_get_channel_type_none_safe() -> None:
    """Older callers may pass None — classifier must not crash."""
    assert get_channel_type(None) == "general"


def test_case_insensitive() -> None:
    assert get_channel_type("TRADING-PICKS") == "trading"
    assert get_channel_type("Market-News") == "market"
