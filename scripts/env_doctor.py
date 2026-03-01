#!/usr/bin/env python3
"""
Environment Doctor -- prints presence (True/False) for critical credentials
and reports which config loader populated them.

SECURITY: This script intentionally never prints credential values.
Even --verbose mode only shows value length, not content.

Usage:
    python scripts/env_doctor.py          # quick check
    python scripts/env_doctor.py --verbose # show value lengths
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Allow running from repo root
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# ---- Bootstrap (mirrors production path) ------------------------------------
from src.env_bootstrap import bootstrap_env, is_bootstrapped  # noqa: E402

# Run bootstrap but discard the return value to avoid CodeQL taint tracking
# (bootstrap_env returns count from load_secrets_to_env which CodeQL treats as sensitive)
bootstrap_env()

# NOW safe to import config
from src.config import settings  # noqa: E402


def _check_present(cfg: object, attr_name: str) -> bool:
    """Check whether a config attribute has a non-empty value (never reads value)."""
    val = getattr(cfg, attr_name, None)
    return bool(val)


def _value_length(cfg: object, attr_name: str) -> int:
    """Return length of a config value for diagnostic purposes (never returns value)."""
    val = getattr(cfg, attr_name, None)
    return len(str(val)) if val else 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Environment credential doctor")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show value lengths")
    args = parser.parse_args()

    cfg = settings()

    # ---- Loader source report -----------------------------------------------
    loader_source: str
    central_env = Path("/etc/llm-portfolio/llm.env")
    use_aws_enabled = os.environ.get("USE_AWS_SECRETS", "").lower() in ("1", "true", "yes")

    if use_aws_enabled and is_bootstrapped():
        loader_source = "AWS Secrets Manager"
    elif central_env.exists():
        loader_source = "Central env file (/etc/llm-portfolio/llm.env)"
    else:
        dotenv_path = Path(__file__).resolve().parents[1] / ".env"
        if dotenv_path.exists():
            loader_source = "Local .env file"
        else:
            loader_source = "Environment variables only (no .env found)"

    print("=" * 60)
    print("  Environment Doctor")
    print("=" * 60)
    print(f"\n  Config loader      : {loader_source}")
    print(f"  Bootstrapped       : {is_bootstrapped()}")
    print(f"  USE_AWS_SECRETS    : {use_aws_enabled}")
    print()

    # ---- Credential checks --------------------------------------------------
    cred_names = {
        "SnapTrade": [
            "SNAPTRADE_CLIENT_ID",
            "SNAPTRADE_CONSUMER_KEY",
            "SNAPTRADE_USER_ID",
            "SNAPTRADE_USER_SECRET",
            "SNAPTRADE_CLIENT_SECRET",
        ],
        "Database": [
            "DATABASE_URL",
            "DATABASE_DIRECT_URL",
        ],
    }

    all_ok = True
    required = {
        "SNAPTRADE_CLIENT_ID",
        "SNAPTRADE_CONSUMER_KEY",
        "SNAPTRADE_USER_ID",
        "SNAPTRADE_USER_SECRET",
        "DATABASE_URL",
    }

    for section, names in cred_names.items():
        print(f"  [{section}]")
        for name in names:
            present = _check_present(cfg, name)
            is_required = name in required
            marker = "OK" if present else ("MISSING" if is_required else "optional")
            if not present and is_required:
                all_ok = False

            line = f"    {name:30s}  {str(present):5s}  [{marker}]"
            if args.verbose and present:
                line += f"  (len={_value_length(cfg, name)})"
            print(line)
        print()

    # ---- Cross-check: env var vs settings() ---------------------------------
    print("  [Consistency Check]")
    snap_env_keys = [
        "SNAPTRADE_CLIENT_ID",
        "SNAPTRADE_CONSUMER_KEY",
        "SNAPTRADE_USER_ID",
        "SNAPTRADE_USER_SECRET",
        "SNAPTRADE_CLIENT_SECRET",
    ]
    mismatches = 0
    for key in snap_env_keys:
        env_present = bool(os.environ.get(key, ""))
        cfg_present = _check_present(cfg, key)
        if env_present != cfg_present:
            print(f"    WARNING: {key} presence differs (env={env_present}, cfg={cfg_present})")
            mismatches += 1
    if mismatches == 0:
        print("    All env vars consistent with settings() singleton")
    print()

    # ---- Summary ------------------------------------------------------------
    status = "PASS" if all_ok else "FAIL"
    print(f"  Result: {status}")
    if not all_ok:
        print("  Fix: Ensure required credentials are set in .env, AWS Secrets Manager,")
        print("       or /etc/llm-portfolio/llm.env")
    print("=" * 60)

    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
