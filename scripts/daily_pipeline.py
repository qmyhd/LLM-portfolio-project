#!/usr/bin/env python3
"""
Daily Data Pipeline for EC2

Unified script that runs all daily data collection tasks:
1. SnapTrade sync (accounts, positions, orders, balances)
2. Discord message processing (NLP parsing of unprocessed messages)
3. OHLCV daily bars (Databento backfill)

Usage:
    # Run all tasks
    python scripts/daily_pipeline.py

    # Run specific tasks
    python scripts/daily_pipeline.py --snaptrade
    python scripts/daily_pipeline.py --discord
    python scripts/daily_pipeline.py --ohlcv

    # Dry run (no database writes)
    python scripts/daily_pipeline.py --dry-run

Cron Schedule (add via `crontab -e`):
    # Daily pipeline at 1:00 AM ET (6:00 AM UTC)
    0 6 * * * cd /home/ec2-user/LLM-portfolio-project && /home/ec2-user/.venv/bin/python scripts/daily_pipeline.py >> /var/log/daily_pipeline.log 2>&1

    # Evening SnapTrade sync at 8:00 PM ET (1:00 AM UTC next day)
    0 1 * * * cd /home/ec2-user/LLM-portfolio-project && /home/ec2-user/.venv/bin/python scripts/daily_pipeline.py --snaptrade >> /var/log/daily_pipeline.log 2>&1
"""

import argparse
import json
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Add project root to path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("daily_pipeline")

# Pipeline status file for tracking last runs
STATUS_FILE = BASE_DIR / "data" / ".pipeline_status.json"


def load_pipeline_status() -> dict:
    """Load pipeline status from JSON file."""
    if STATUS_FILE.exists():
        try:
            with open(STATUS_FILE) as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Could not load pipeline status: {e}")
    return {}


def save_pipeline_status(status: dict) -> None:
    """Save pipeline status to JSON file."""
    STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(STATUS_FILE, "w") as f:
            json.dump(status, f, indent=2, default=str)
    except Exception as e:
        logger.error(f"Could not save pipeline status: {e}")


def update_pipeline_timestamp(pipeline_name: str) -> None:
    """Update the last run timestamp for a pipeline."""
    status = load_pipeline_status()
    status[pipeline_name] = {
        "last_run": datetime.now(timezone.utc).isoformat(),
        "success": True,
    }
    save_pipeline_status(status)


def get_last_run(pipeline_name: str) -> datetime | None:
    """Get the last run timestamp for a pipeline."""
    status = load_pipeline_status()
    if pipeline_name in status:
        try:
            return datetime.fromisoformat(status[pipeline_name]["last_run"])
        except (KeyError, ValueError):
            pass
    return None


# =============================================================================
# SNAPTRADE SYNC
# =============================================================================


def run_snaptrade_sync(dry_run: bool = False) -> dict:
    """
    Fetch and sync SnapTrade data (accounts, positions, orders, balances).

    Uses the existing SnapTradeCollector.collect_all_data() method.
    """
    logger.info("=" * 60)
    logger.info("SNAPTRADE SYNC")
    logger.info("=" * 60)

    results = {
        "success": False,
        "accounts": 0,
        "positions": 0,
        "orders": 0,
        "balances": 0,
        "errors": [],
    }

    try:
        from src.snaptrade_collector import SnapTradeCollector

        collector = SnapTradeCollector()

        if dry_run:
            logger.info("DRY RUN: Would sync SnapTrade data")
            results["success"] = True
            return results

        # Collect all data using existing method
        collection_results = collector.collect_all_data(write_parquet=False)

        results.update(collection_results)
        results["success"] = collection_results.get("success", False)

        logger.info(f"✅ SnapTrade sync complete:")
        logger.info(f"   Accounts: {results['accounts']}")
        logger.info(f"   Positions: {results['positions']}")
        logger.info(f"   Orders: {results['orders']}")
        logger.info(f"   Balances: {results['balances']}")

        if results["success"]:
            update_pipeline_timestamp("snaptrade")

    except ImportError as e:
        logger.warning(f"SnapTrade SDK not available: {e}")
        results["errors"].append(str(e))
    except Exception as e:
        logger.error(f"SnapTrade sync failed: {e}")
        results["errors"].append(str(e))

    return results


# =============================================================================
# DISCORD MESSAGE PROCESSING
# =============================================================================


def run_discord_processing(dry_run: bool = False) -> dict:
    """
    Process unprocessed Discord messages through the NLP pipeline.

    Uses existing channel_processor and NLP parsing logic.
    """
    logger.info("=" * 60)
    logger.info("DISCORD MESSAGE PROCESSING")
    logger.info("=" * 60)

    results = {
        "success": False,
        "messages_processed": 0,
        "ideas_extracted": 0,
        "errors": [],
    }

    try:
        from src.db import execute_sql

        # Get count of unprocessed messages
        unprocessed_query = """
            SELECT COUNT(*) FROM discord_messages dm
            WHERE dm.parse_status IS NULL OR dm.parse_status = 'pending'
        """
        count_result = execute_sql(unprocessed_query, fetch_results=True)
        unprocessed_count = count_result[0][0] if count_result else 0

        logger.info(f"Found {unprocessed_count} messages pending NLP processing")

        if unprocessed_count == 0:
            logger.info("No messages to process")
            results["success"] = True
            update_pipeline_timestamp("discord_nlp")
            return results

        if dry_run:
            logger.info(f"DRY RUN: Would process {unprocessed_count} messages")
            results["success"] = True
            return results

        # Run the NLP parsing pipeline
        # Import and run the parse_messages script logic
        from scripts.nlp.parse_messages import main as parse_main

        # Process in batches
        batch_size = 50
        total_processed = 0
        total_ideas = 0

        while total_processed < min(unprocessed_count, 500):  # Cap at 500 per run
            try:
                # parse_main returns (processed_count, ideas_count)
                processed, ideas = parse_main(
                    limit=batch_size, skip_existing=True, verbose=False
                )
                if processed == 0:
                    break
                total_processed += processed
                total_ideas += ideas
                logger.info(
                    f"   Processed batch: {processed} messages, {ideas} ideas extracted"
                )
            except Exception as batch_error:
                logger.warning(f"Batch processing error: {batch_error}")
                break

        results["messages_processed"] = total_processed
        results["ideas_extracted"] = total_ideas
        results["success"] = True

        logger.info(f"✅ Discord processing complete:")
        logger.info(f"   Messages processed: {total_processed}")
        logger.info(f"   Ideas extracted: {total_ideas}")

        update_pipeline_timestamp("discord_nlp")

    except ImportError as e:
        logger.warning(f"NLP pipeline not available: {e}")
        results["errors"].append(str(e))
    except Exception as e:
        logger.error(f"Discord processing failed: {e}")
        results["errors"].append(str(e))

    return results


# =============================================================================
# OHLCV BACKFILL
# =============================================================================


def run_ohlcv_backfill(dry_run: bool = False, days: int = 5) -> dict:
    """
    Backfill OHLCV daily bars from Databento.

    Uses the existing DatabentoCollector from databento_collector.py.
    """
    logger.info("=" * 60)
    logger.info("OHLCV DAILY BACKFILL")
    logger.info("=" * 60)

    results = {
        "success": False,
        "bars_inserted": 0,
        "symbols_processed": 0,
        "errors": [],
    }

    try:
        from src.databento_collector import DatabentoCollector

        collector = DatabentoCollector()

        if dry_run:
            logger.info(f"DRY RUN: Would backfill {days} days of OHLCV data")
            results["success"] = True
            return results

        # Calculate date range
        end_date = datetime.now(timezone.utc).date() - timedelta(days=1)
        start_date = end_date - timedelta(days=days)

        logger.info(f"Backfilling OHLCV data from {start_date} to {end_date}")

        # Run backfill
        backfill_results = collector.backfill_daily(
            start_date=start_date,
            end_date=end_date,
            write_supabase=True,
        )

        results["bars_inserted"] = backfill_results.get("total_bars", 0)
        results["symbols_processed"] = backfill_results.get("symbols_processed", 0)
        results["success"] = backfill_results.get("success", False)

        logger.info(f"✅ OHLCV backfill complete:")
        logger.info(f"   Bars inserted: {results['bars_inserted']}")
        logger.info(f"   Symbols processed: {results['symbols_processed']}")

        if results["success"]:
            update_pipeline_timestamp("ohlcv")

    except ImportError as e:
        logger.warning(f"Databento collector not available: {e}")
        results["errors"].append(str(e))
    except Exception as e:
        logger.error(f"OHLCV backfill failed: {e}")
        results["errors"].append(str(e))

    return results


# =============================================================================
# MAIN ORCHESTRATION
# =============================================================================


def main():
    """Main entry point for the daily pipeline."""
    parser = argparse.ArgumentParser(
        description="Daily Data Pipeline - orchestrates all data collection tasks"
    )
    parser.add_argument(
        "--snaptrade", action="store_true", help="Run only SnapTrade sync"
    )
    parser.add_argument(
        "--discord", action="store_true", help="Run only Discord message processing"
    )
    parser.add_argument("--ohlcv", action="store_true", help="Run only OHLCV backfill")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview actions without making changes",
    )
    parser.add_argument(
        "--ohlcv-days",
        type=int,
        default=5,
        help="Number of days to backfill for OHLCV (default: 5)",
    )
    args = parser.parse_args()

    # If no specific task is requested, run all
    run_all = not (args.snaptrade or args.discord or args.ohlcv)

    logger.info("=" * 80)
    logger.info("DAILY DATA PIPELINE")
    logger.info(f"Started at: {datetime.now(timezone.utc).isoformat()}")
    logger.info(f"Dry run: {args.dry_run}")
    logger.info("=" * 80)

    all_results = {}

    # SnapTrade sync
    if run_all or args.snaptrade:
        all_results["snaptrade"] = run_snaptrade_sync(dry_run=args.dry_run)

    # Discord processing
    if run_all or args.discord:
        all_results["discord"] = run_discord_processing(dry_run=args.dry_run)

    # OHLCV backfill
    if run_all or args.ohlcv:
        all_results["ohlcv"] = run_ohlcv_backfill(
            dry_run=args.dry_run, days=args.ohlcv_days
        )

    # Summary
    logger.info("=" * 80)
    logger.info("PIPELINE SUMMARY")
    logger.info("=" * 80)

    overall_success = True
    for task_name, task_results in all_results.items():
        status = "✅" if task_results.get("success") else "❌"
        logger.info(f"{status} {task_name}: {task_results}")
        if not task_results.get("success"):
            overall_success = False

    logger.info("=" * 80)
    logger.info(f"Completed at: {datetime.now(timezone.utc).isoformat()}")
    logger.info(f"Overall status: {'SUCCESS' if overall_success else 'FAILED'}")
    logger.info("=" * 80)

    return 0 if overall_success else 1


if __name__ == "__main__":
    sys.exit(main())
