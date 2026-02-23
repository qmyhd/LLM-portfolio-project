#!/usr/bin/env python3
"""
Daily Stock Profile Refresh Job

Wrapper script for daily scheduled refresh of stock_profile_current and
appending snapshots to stock_profile_history.

Designed to be called by:
- PM2 via ecosystem.config.js (preferred for EC2)
- Cron job
- Manual execution

Usage:
    python scripts/daily_stock_refresh.py          # Full refresh
    python scripts/daily_stock_refresh.py --dry-run  # Preview only

Environment:
    Requires DATABASE_URL (Supabase) configured.
    STOCK_REFRESH_TIMEOUT: Internal timeout in seconds (default: 600).
"""

from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
from datetime import datetime
from pathlib import Path

# Add project root to path for imports
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.env_bootstrap import bootstrap_env  # noqa: E402

bootstrap_env()

from scripts.backfill_stock_profiles import refresh_stock_profiles

# Configurable timeout via environment variable (default 600s = 10 min)
STOCK_REFRESH_TIMEOUT = int(os.environ.get("STOCK_REFRESH_TIMEOUT", "600"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
        (
            logging.FileHandler(
                PROJECT_ROOT / "data" / "logs" / "stock_refresh.log", mode="a"
            )
            if (PROJECT_ROOT / "data" / "logs").exists()
            else logging.StreamHandler()
        ),
    ],
)
logger = logging.getLogger(__name__)


class TimeoutError(Exception):
    """Custom timeout exception."""

    pass


def timeout_handler(signum, frame):
    """Signal handler for timeout."""
    raise TimeoutError(f"Stock refresh timed out after {STOCK_REFRESH_TIMEOUT}s")


def run_daily_refresh(dry_run: bool = False) -> bool:
    """
    Execute the daily stock profile refresh.

    Includes internal timeout handling to prevent hanging.

    Returns:
        True if successful (no failures), False otherwise
    """
    start_time = datetime.now()
    logger.info("=" * 60)
    logger.info(f"Daily Stock Profile Refresh - {start_time.isoformat()}")
    logger.info(f"Timeout: {STOCK_REFRESH_TIMEOUT}s")
    logger.info("=" * 60)

    # Set up timeout signal (Unix only)
    if hasattr(signal, "SIGALRM"):
        signal.signal(signal.SIGALRM, timeout_handler)
        signal.alarm(STOCK_REFRESH_TIMEOUT)

    try:
        results = refresh_stock_profiles(
            tickers=None,  # All tracked tickers
            update_current=True,
            update_history=True,
            dry_run=dry_run,
        )

        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()

        logger.info("=" * 60)
        logger.info("Refresh Complete")
        logger.info(f"  Duration: {duration:.1f} seconds")
        logger.info(
            f"  Current profiles: {results['current_success']} success, {results['current_failed']} failed"
        )
        logger.info(
            f"  History records: {results['history_success']} success, {results['history_failed']} failed"
        )
        logger.info("=" * 60)

        # Return success if no failures
        return results["current_failed"] == 0 and results["history_failed"] == 0

    except TimeoutError as e:
        logger.warning(f"⏰ {e}")
        logger.warning("Stock refresh timed out but continuing (non-critical)")
        return False

    except Exception as e:
        logger.exception(f"Fatal error during refresh: {e}")
        return False

    finally:
        # Cancel the alarm if it was set
        if hasattr(signal, "SIGALRM"):
            signal.alarm(0)


def main():
    parser = argparse.ArgumentParser(description="Daily stock profile refresh job")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without writing to database",
    )

    args = parser.parse_args()

    # Ensure logs directory exists
    logs_dir = PROJECT_ROOT / "data" / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    success = run_daily_refresh(dry_run=args.dry_run)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
