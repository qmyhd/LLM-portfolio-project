#!/usr/bin/env python3
"""Quick test of helper functions"""

from src.nlp.preclean import apply_alias_mapping
from src.nlp.openai_parser import (
    detect_instrument_type,
    extract_strike_info,
    extract_price_levels,
)

print("=" * 70)
print("ALIAS MAPPING TESTS")
print("=" * 70)

tests = [
    "super bullish uber business model",
    "Waymo exclusivity for 3-5 years",
    "google vs tesla in autonomous driving",
    "Bitcoin hit ATH",
]

for test in tests:
    result = apply_alias_mapping(test)
    print(f"Input:  {test}")
    print(f"Output: {result}")
    print()

print("=" * 70)
print("INSTRUMENT DETECTION TESTS")
print("=" * 70)

tests = [
    "AAPL 180c looking good",
    "Bought NVDA shares",
    "Bitcoin hit ATH @109.5K",
    "$GOOGL: $180 call if down on Monday",
]

for test in tests:
    result = detect_instrument_type(test)
    print(f"Text: {test}")
    print(f"Type: {result}")
    print()

print("=" * 70)
print("STRIKE INFO EXTRACTION TESTS")
print("=" * 70)

tests = [
    "AAPL 180c",
    "$95 put for $1.76",
    "July 18th puts for $CRWV",
    "$GOOGL: $180 call if down on Monday",
    "Buying Tesla $400 calls",
]

for test in tests:
    result = extract_strike_info(test)
    print(f"Text: {test}")
    print(f"Info: {result}")
    print()

print("=" * 70)
print("PRICE LEVELS EXTRACTION TESTS")
print("=" * 70)

tests = [
    "bounced off $147, needs to hold 150",
    "next move into the $170 area",
    "support at $93-$105 range",
    "set a stop loss at $12ish",
]

for test in tests:
    result = extract_price_levels(test)
    print(f"Text: {test}")
    print(f"Levels: {result}")
    print()

print("=" * 70)
print("✅ ALL TESTS COMPLETE")
print("=" * 70)
