#!/usr/bin/env python
"""Quick test for triage noise vs tech insights."""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv()

from src.nlp.openai_parser import triage_message

# Test cases: (message, expected_is_noise)
noise_tests = [
    ("lol", True),
    ("!help", True),
    ("nice", True),
    ("The semiconductor cycle is turning", False),  # Tech insight
    ("Memory prices bottoming out", False),  # Tech insight
    ("AI inference costs dropping fast", False),  # Tech insight
    ("AAPL looking strong at 180", False),  # Has ticker
]

print("Testing noise detection:")
print("-" * 60)
passed = 0
for msg, expected_noise in noise_tests:
    result = triage_message(msg)
    status = "PASS" if result.is_noise == expected_noise else "FAIL"
    if status == "PASS":
        passed += 1
    print(f'{status}: "{msg}" -> noise={result.is_noise} (expected={expected_noise})')

print("-" * 60)
print(f"Results: {passed}/{len(noise_tests)} passed")
