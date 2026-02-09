#!/usr/bin/env python3
"""
Backfill account activities from SnapTrade.

Usage:
    python scripts/backfill_activities.py                  # last 90 days (default)
    python scripts/backfill_activities.py --days 365       # last year
    python scripts/backfill_activities.py --start 2025-01-01 --end 2025-12-31
    python scripts/backfill_activities.py --account-id <id>
"""

import argparse
import logging
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Ensure project root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.snaptrade_collector import SnapTradeCollector  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill SnapTrade account activities into the activities table."
    )
    parser.add_argument(
        "--days",
        type=int,
        default=90,
        help="Number of days to look back (default: 90). Ignored if --start is set.",
    )
    parser.add_argument(
        "--start",
        type=str,
        default=None,
        help="Inclusive start date (YYYY-MM-DD).",
    )
    parser.add_argument(
        "--end",
        type=str,
        default=None,
        help="Inclusive end date (YYYY-MM-DD). Default: today.",
    )
    parser.add_argument(
        "--account-id",
        type=str,
        default=None,
        help="SnapTrade account ID. Default: ROBINHOOD_ACCOUNT_ID from .env.",
    )
    parser.add_argument(
        "--type",
        type=str,
        default=None,
        help="Activity type filter (BUY, SELL, DIVIDEND, etc.).",
    )
    args = parser.parse_args()

    # Resolve date range
    now = datetime.now(timezone.utc)
    if args.start:
        start_date = args.start
    else:
        start_date = (now - timedelta(days=args.days)).strftime("%Y-%m-%d")

    end_date = args.end or now.strftime("%Y-%m-%d")

    logger.info(f"📅 Activities backfill: {start_date} → {end_date}")

    # Initialize collector
    try:
        collector = SnapTradeCollector()
    except Exception as e:
        logger.error(f"Failed to initialize SnapTradeCollector: {e}")
        sys.exit(1)

    # Fetch activities
    df = collector.get_activities(
        account_id=args.account_id,
        start_date=start_date,
        end_date=end_date,
        activity_type=args.type,
    )

    if df.empty:
        logger.info("No activities returned for the specified range.")
        return

    # Write to database
    logger.info(f"💾 Upserting {len(df)} activities to database...")
    success = collector.write_to_database(df, "activities", conflict_columns=["id"])

    if not success:
        logger.error("❌ Database write failed")
        sys.exit(1)

    # Summary: breakdown by activity_type
    type_counts: Counter = Counter(df["activity_type"].tolist())
    logger.info(f"✅ Backfill complete: {len(df)} total activities")
    for act_type, count in type_counts.most_common():
        logger.info(f"   {act_type or 'UNKNOWN'}: {count}")


if __name__ == "__main__":
    main()
