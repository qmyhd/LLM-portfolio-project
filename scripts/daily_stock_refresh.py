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
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

# Add project root to path for imports
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.backfill_stock_profiles import refresh_stock_profiles

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


def run_daily_refresh(dry_run: bool = False) -> bool:
    """
    Execute the daily stock profile refresh.

    Returns:
        True if successful (no failures), False otherwise
    """
    start_time = datetime.now()
    logger.info("=" * 60)
    logger.info(f"Daily Stock Profile Refresh - {start_time.isoformat()}")
    logger.info("=" * 60)

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

    except Exception as e:
        logger.exception(f"Fatal error during refresh: {e}")
        return False


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
