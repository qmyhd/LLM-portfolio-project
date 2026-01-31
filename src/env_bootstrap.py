"""
Environment Bootstrap Module

Loads AWS Secrets Manager secrets before any config/database imports.
Must be called at the very top of entry points BEFORE other src imports.

This solves the chicken-and-egg problem where:
1. src/config.py tries to read DATABASE_URL from environment
2. But AWS secrets haven't been loaded yet
3. So get_database_url() raises RuntimeError

Usage (at TOP of entry point files, BEFORE other src imports):

    # app/main.py, src/bot/bot.py, scripts/deploy_database.py, etc.
    from src.env_bootstrap import bootstrap_env
    bootstrap_env()  # Load AWS secrets if enabled

    # Now safe to import from src.config, src.db, etc.
    from src.config import settings
    from src.db import execute_sql

Environment Variables:
    USE_AWS_SECRETS: Set to "1" to enable AWS secrets loading
    AWS_SECRET_NAME: Secret name in AWS Secrets Manager (e.g., "qqqAppsecrets")
    AWS_REGION: AWS region (default: "us-east-1")
"""

import os
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_bootstrapped = False


def bootstrap_env() -> int:
    """
    Bootstrap environment by loading AWS secrets if enabled.

    Call this at the TOP of entry points, BEFORE importing from src.config or src.db.
    Safe to call multiple times - only loads secrets once.

    Returns:
        Number of secrets loaded (0 if AWS secrets disabled or already loaded)

    Raises:
        Exception: If AWS secrets are enabled but cannot be loaded
    """
    global _bootstrapped

    if _bootstrapped:
        return 0  # Already done

    # First, try to load from /etc/llm-portfolio/llm.env if it exists
    central_env = Path("/etc/llm-portfolio/llm.env")
    if central_env.exists():
        try:
            with open(central_env) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        key, value = line.split("=", 1)
                        os.environ.setdefault(key.strip(), value.strip())
            logger.debug(f"Loaded central env from {central_env}")
        except Exception as e:
            logger.warning(f"Failed to load {central_env}: {e}")

    # Check if AWS secrets should be used
    use_aws = os.environ.get("USE_AWS_SECRETS", "").lower()

    if use_aws not in ("1", "true", "yes"):
        _bootstrapped = True
        return 0

    # Load AWS secrets BEFORE config is imported
    try:
        from src.aws_secrets import load_secrets_to_env

        count = load_secrets_to_env()
        logger.info(f"Bootstrapped {count} secrets from AWS Secrets Manager")
        _bootstrapped = True
        return count
    except Exception as e:
        logger.error(f"Failed to load AWS secrets: {e}")
        raise


def is_bootstrapped() -> bool:
    """Check if environment has been bootstrapped."""
    return _bootstrapped
