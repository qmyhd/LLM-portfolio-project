#!/usr/bin/env python3
"""
Environment Doctor — prints presence (True/False) for critical credentials
and reports which config loader populated them.

Usage:
    python scripts/env_doctor.py          # quick check
    python scripts/env_doctor.py --verbose # show masked values + loader detail
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Allow running from repo root
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# ---- Bootstrap (mirrors production path) ------------------------------------
from src.env_bootstrap import bootstrap_env, is_bootstrapped

aws_count = bootstrap_env()

# NOW safe to import config
from src.config import settings  # noqa: E402


def _mask(val: str) -> str:
    """Mask credential value for display: first 4 chars + '***' + last 4."""
    if not val:
        return "(empty)"
    if len(val) <= 10:
        return val[:2] + "***"
    return val[:4] + "***" + val[-4:]


def main() -> None:
    parser = argparse.ArgumentParser(description="Environment credential doctor")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show masked values")
    args = parser.parse_args()

    cfg = settings()

    # ---- Loader source report -----------------------------------------------
    loader_source: str
    central_env = Path("/etc/llm-portfolio/llm.env")
    use_aws = os.environ.get("USE_AWS_SECRETS", "").lower()

    if use_aws in ("1", "true", "yes") and is_bootstrapped():
        loader_source = f"AWS Secrets Manager ({aws_count} secrets loaded)"
    elif central_env.exists():
        loader_source = f"Central env file ({central_env})"
    else:
        dotenv_path = Path(__file__).resolve().parents[1] / ".env"
        if dotenv_path.exists():
            loader_source = f"Local .env ({dotenv_path})"
        else:
            loader_source = "Environment variables only (no .env found)"

    print("=" * 60)
    print("  Environment Doctor")
    print("=" * 60)
    print(f"\n  Config loader : {loader_source}")
    print(f"  Bootstrapped  : {is_bootstrapped()}")
    print(f"  USE_AWS_SECRETS: {os.environ.get('USE_AWS_SECRETS', '(not set)')}")
    print()

    # ---- Credential checks --------------------------------------------------
    creds = {
        "SnapTrade": [
            ("SNAPTRADE_CLIENT_ID", cfg.SNAPTRADE_CLIENT_ID),
            ("SNAPTRADE_CONSUMER_KEY", cfg.SNAPTRADE_CONSUMER_KEY),
            ("SNAPTRADE_USER_ID", cfg.SNAPTRADE_USER_ID),
            ("SNAPTRADE_USER_SECRET", cfg.SNAPTRADE_USER_SECRET),
            ("SNAPTRADE_CLIENT_SECRET", cfg.SNAPTRADE_CLIENT_SECRET),
        ],
        "Database": [
            ("DATABASE_URL", cfg.DATABASE_URL),
            ("DATABASE_DIRECT_URL", cfg.DATABASE_DIRECT_URL),
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

    for section, items in creds.items():
        print(f"  [{section}]")
        for name, value in items:
            present = bool(value)
            is_required = name in required
            marker = "OK" if present else ("MISSING" if is_required else "optional")
            if not present and is_required:
                all_ok = False

            line = f"    {name:30s}  {str(present):5s}  [{marker}]"
            if args.verbose and present:
                line += f"  {_mask(value)}"
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
        env_val = os.environ.get(key, "")
        cfg_val = getattr(cfg, key, "")
        if env_val and cfg_val and env_val != cfg_val:
            print(f"    WARNING: {key} differs between os.environ and settings()")
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
