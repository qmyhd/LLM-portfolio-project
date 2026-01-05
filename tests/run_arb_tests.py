import json
import sys
import os
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).resolve().parents[1]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from src.sports.arbitrage_calculator import calculate_arbitrage, calculate_hedge


def run_tests():
    json_path = Path(__file__).parent / "arb_cases.json"
    with open(json_path, "r") as f:
        cases = json.load(f)

    print(f"{'Case Name':<45} | {'Status':<10} | {'Details'}")
    print("-" * 100)

    passed_count = 0
    for case in cases:
        inputs = case["inputs"]
        expected = case["expected"]
        case_type = case.get("type", "arbitrage")  # Default to arbitrage

        # Choose the right function based on case type
        if case_type == "hedge":
            # Map inputs for calculate_hedge
            hedge_inputs = {
                "odds1": inputs.get("odds1"),
                "stake1": inputs.get("stake1"),
                "odds2": inputs.get("odds2"),
                "boost_pct": inputs.get("boost_pct", 0),
                "hedge_pct": inputs.get("hedge_pct", 100),
            }
            res = calculate_hedge(**hedge_inputs)
        else:
            # Use calculate_arbitrage for standard cases
            arb_inputs = {
                "odds1": inputs.get("odds1"),
                "odds2": inputs.get("odds2"),
                "total_stake": inputs.get("total_stake", 100.0),
                "is_boosted1": inputs.get("is_boosted1", False),
                "is_boosted2": inputs.get("is_boosted2", False),
                "boost_pct1": inputs.get("boost_pct1", 0.0),
                "boost_pct2": inputs.get("boost_pct2", 0.0),
                "max_stake1": inputs.get("max_stake1"),
                "max_stake2": inputs.get("max_stake2"),
                "bias_to_bet1": inputs.get("bias_to_bet1", 50.0),
            }
            res = calculate_arbitrage(**arb_inputs)

        if not res:
            print(f"{case['name']:<45} | {'FAIL':<10} | Result was None")
            continue

        # Check expectations
        errors = []
        for key, val in expected.items():
            if not hasattr(res, key):
                errors.append(f"Missing field {key}")
                continue

            actual = getattr(res, key)

            # Handle American odds strings (e.g. "+420" vs 420)
            if isinstance(actual, str) and isinstance(val, (int, float)):
                try:
                    actual_float = float(actual.replace("+", ""))
                    if abs(actual_float - val) > 0.5:
                        errors.append(
                            f"{key}: exp {val}, got {actual} (parsed {actual_float})"
                        )
                except ValueError:
                    errors.append(f"{key}: exp {val}, got {actual} (parse failed)")
            # Handle float comparison
            elif isinstance(val, (int, float)):
                if isinstance(actual, (int, float)):
                    if abs(actual - val) > 0.5:  # 0.5 tolerance for rounding
                        errors.append(f"{key}: exp {val}, got {actual:.2f}")
                else:
                    errors.append(
                        f"{key}: exp {val} (num), got {actual} ({type(actual)})"
                    )
            else:
                if actual != val:
                    errors.append(f"{key}: exp {val}, got {actual}")

        if not errors:
            print(f"{case['name']:<45} | {'PASS':<10} | All checks passed")
            passed_count += 1
        else:
            print(f"{case['name']:<45} | {'FAIL':<10} | {', '.join(errors)}")

    print("-" * 100)
    print(
        f"Total: {len(cases)}, Passed: {passed_count}, Failed: {len(cases) - passed_count}"
    )
    return passed_count == len(cases)


if __name__ == "__main__":
    run_tests()
