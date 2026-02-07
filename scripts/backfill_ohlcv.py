#!/usr/bin/env python3
"""
OHLCV Backfill CLI

Fetches daily bars from Databento and saves to Supabase PostgreSQL.

Environment Variables (required on EC2):
    DATABENTO_API_KEY, DATABASE_URL (Supabase)

Usage:
    python scripts/backfill_ohlcv.py --daily              # Last 5 days
    python scripts/backfill_ohlcv.py --full               # Full historical
    python scripts/backfill_ohlcv.py --start 2024-01-01   # Custom range
"""

import argparse
import logging
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

# Add project root to path
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv

# Load environment variables
load_dotenv(project_root / ".env")

# Bootstrap AWS secrets FIRST, before any other src imports
from src.env_bootstrap import bootstrap_env

bootstrap_env()


def setup_logging(verbose: bool = False) -> None:
    """Configure logging."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def parse_date(date_str: str) -> date:
    """Parse date string in YYYY-MM-DD format."""
    return datetime.strptime(date_str, "%Y-%m-%d").date()


def main():
    parser = argparse.ArgumentParser(
        description="Databento OHLCV Backfill (Supabase)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    # Mode selection
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--full",
        action="store_true",
        help="Full historical backfill (2023-03-28 to yesterday)",
    )
    mode_group.add_argument(
        "--daily",
        action="store_true",
        help="Daily update (last 5 days)",
    )
    mode_group.add_argument(
        "--new-symbols",
        action="store_true",
        help="Auto-detect and backfill symbols in positions with no recent OHLCV data",
    )

    # Date range
    parser.add_argument(
        "--start",
        type=str,
        help="Start date (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--end",
        type=str,
        help="End date (YYYY-MM-DD), defaults to yesterday",
    )

    # Symbol selection
    parser.add_argument(
        "--symbols",
        type=str,
        help="Comma-separated list of symbols (default: portfolio symbols)",
    )

    # Options
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch data but don't save anywhere",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose logging",
    )
    parser.add_argument(
        "--lookback",
        type=int,
        default=5,
        help="Lookback days for daily update (default: 5)",
    )

    args = parser.parse_args()
    setup_logging(args.verbose)

    logger = logging.getLogger("backfill_ohlcv")

    # Import collector (after path setup)
    try:
        from src.databento_collector import DatabentoCollector
    except ImportError as e:
        logger.error(f"Failed to import DatabentoCollector: {e}")
        logger.error(
            "Make sure you're running from the project root with venv activated"
        )
        sys.exit(1)

    # Initialize collector
    try:
        collector = DatabentoCollector()
        logger.info("DatabentoCollector initialized")
    except ValueError as e:
        logger.error(f"Configuration error: {e}")
        sys.exit(1)

    # Determine symbols
    symbols = None
    if args.symbols:
        symbols = [s.strip().upper() for s in args.symbols.split(",")]
        logger.info(f"Using specified symbols: {symbols}")
    elif hasattr(args, "new_symbols") and args.new_symbols:
        # Auto-detect symbols missing OHLCV data
        symbols = collector.get_symbols_missing_ohlcv(lookback_days=30)
        if not symbols:
            logger.info("No new symbols missing OHLCV data - nothing to do")
            sys.exit(0)
        logger.info(f"Auto-detected {len(symbols)} symbols missing OHLCV: {symbols}")
    else:
        symbols = collector.get_all_tracked_symbols()
        logger.info(f"Using portfolio symbols: {len(symbols)} symbols")

    # Determine date range
    if hasattr(args, "new_symbols") and args.new_symbols:
        # For new symbols: backfill 1 year of data
        start_date = date.today() - timedelta(days=365)
        end_date = date.today() - timedelta(days=1)
        logger.info(f"New symbol backfill: {start_date} to {end_date}")
    elif args.full:
        # Full backfill from EQUS.MINI start date
        start_date = date(2023, 3, 28)
        end_date = date.today() - timedelta(days=1)
        logger.info(f"Full backfill mode: {start_date} to {end_date}")
    elif args.daily:
        # Daily update with lookback
        end_date = date.today() - timedelta(days=1)
        start_date = end_date - timedelta(days=args.lookback)
        logger.info(f"Daily update mode: {start_date} to {end_date}")
    elif args.start:
        start_date = parse_date(args.start)
        end_date = (
            parse_date(args.end) if args.end else date.today() - timedelta(days=1)
        )
        logger.info(f"Custom range: {start_date} to {end_date}")
    else:
        parser.error("Specify --full, --daily, --new-symbols, or --start date")

    # Validate dates
    if start_date > end_date:
        logger.error(f"Start date ({start_date}) must be before end date ({end_date})")
        sys.exit(1)

    if end_date >= date.today():
        logger.warning(f"End date adjusted to yesterday (can't fetch today's data)")
        end_date = date.today() - timedelta(days=1)

    # Run backfill
    try:
        if args.dry_run:
            # Just fetch and display
            df = collector.fetch_daily_bars(
                symbols=symbols,
                start=start_date,
                end=end_date,
            )
            logger.info(f"Fetched {len(df)} rows (dry run)")
            if len(df) > 0:
                print("\nSample data:")
                print(df.head(20).to_string())
                print(f"\nDate range: {df['date'].min()} to {df['date'].max()}")
                print(f"Symbols: {sorted(df['symbol'].unique())}")
        else:
            # Full backfill with saves
            results = collector.run_backfill(
                start=start_date,
                end=end_date,
                symbols=symbols,
            )

            logger.info("=" * 50)
            logger.info("BACKFILL COMPLETE")
            logger.info("=" * 50)
            logger.info(f"Fetched rows: {results['fetched_rows']}")
            logger.info(f"Supabase rows upserted: {results['supabase_rows']}")

    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.exception(f"Backfill failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
