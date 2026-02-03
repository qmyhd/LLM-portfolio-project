#!/usr/bin/env python3
"""
Nightly Pipeline Orchestrator

Runs after market close (1 AM ET) to:
1. SnapTrade sync (accounts, positions, orders, balances)
2. Backfill OHLCV data from Databento
3. Run NLP batch processing on pending Discord messages
4. Refresh stock profile data

Designed to be run by systemd timer (nightly-pipeline.timer).

Environment Variables:
    REQUIRE_SNAPTRADE: If "1", abort pipeline on SnapTrade failure. Default "0" (continue).

This is the CANONICAL pipeline.
Use: sudo systemctl start nightly-pipeline.service
"""

import logging
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# Project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Bootstrap AWS secrets FIRST, before any other src imports
from src.env_bootstrap import bootstrap_env

bootstrap_env()

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

# Environment variable: if "1", SnapTrade failure aborts pipeline
REQUIRE_SNAPTRADE = os.environ.get("REQUIRE_SNAPTRADE", "0") == "1"


def run_snaptrade_sync(timeout: int = 600) -> bool:
    """Run SnapTrade sync to fetch accounts, positions, orders, balances.

    Includes a user auth smoke test before attempting data collection.

    Args:
        timeout: Maximum execution time in seconds

    Returns:
        True if sync succeeded, False otherwise
    """
    try:
        from src.snaptrade_collector import SnapTradeCollector

        logger.info("Initializing SnapTrade collector...")
        collector = SnapTradeCollector()

        # Run user auth smoke test first
        logger.info("Running SnapTrade user auth smoke test...")
        auth_ok, auth_msg = collector.verify_user_auth()

        if not auth_ok:
            logger.error(f"SnapTrade user auth failed: {auth_msg}")
            return False

        logger.info("Fetching SnapTrade data...")
        results = collector.collect_all_data(write_parquet=False)

        if results.get("success"):
            logger.info(f"✅ SnapTrade sync complete:")
            logger.info(f"   Accounts: {results.get('accounts', 0)}")
            logger.info(f"   Positions: {results.get('positions', 0)}")
            logger.info(f"   Orders: {results.get('orders', 0)}")
            logger.info(f"   Balances: {results.get('balances', 0)}")
            return True
        else:
            logger.error(
                f"SnapTrade sync returned failure: {results.get('errors', [])}"
            )
            return False

    except ImportError as e:
        logger.warning(f"SnapTrade SDK not available: {e}")
        return False
    except Exception as e:
        logger.error(f"SnapTrade sync failed: {e}")
        return False


def run_script(script_path: str, args: list[str] = None, timeout: int = 600) -> bool:
    """Run a Python script with optional arguments.

    Args:
        script_path: Relative path from project root
        args: Optional list of command-line arguments
        timeout: Maximum execution time in seconds

    Returns:
        True if script succeeded, False otherwise
    """
    full_path = PROJECT_ROOT / script_path
    if not full_path.exists():
        logger.warning(f"Script not found: {full_path}")
        return False

    cmd = [sys.executable, str(full_path)]
    if args:
        cmd.extend(args)

    logger.info(f"Running: {' '.join(cmd)}")
    try:
        result = subprocess.run(
            cmd,
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

        if result.returncode == 0:
            logger.info(f"✅ {script_path} completed successfully")
            if result.stdout:
                logger.debug(result.stdout[-1000:])  # Last 1000 chars
            return True
        else:
            logger.error(f"❌ {script_path} failed with code {result.returncode}")
            if result.stderr:
                logger.error(result.stderr[-1000:])
            return False

    except subprocess.TimeoutExpired:
        logger.error(f"⏰ {script_path} timed out after {timeout}s")
        return False
    except Exception as e:
        logger.error(f"💥 Error running {script_path}: {e}")
        return False


def main():
    """Run the nightly pipeline."""
    start_time = datetime.now()
    logger.info("=" * 60)
    logger.info(f"🌙 Nightly Pipeline Started at {start_time.isoformat()}")
    logger.info("=" * 60)

    results = {}

    # Step 0: SnapTrade Sync (accounts, positions, orders, balances)
    logger.info("\n💼 Step 0: SnapTrade Sync")
    results["snaptrade"] = run_snaptrade_sync(timeout=600)  # 10 min

    # Step 1: OHLCV Backfill (Databento → Supabase)
    logger.info("\n📊 Step 1: OHLCV Backfill")
    results["ohlcv"] = run_script(
        "scripts/backfill_ohlcv.py",
        args=["--daily"],
        timeout=900,  # 15 min
    )

    # Step 2: NLP Batch Processing
    logger.info("\n🧠 Step 2: NLP Batch Processing")
    results["nlp"] = run_script(
        "scripts/nlp/batch_backfill.py",
        args=["--limit", "500"],
        timeout=1200,  # 20 min
    )

    # Step 3: Stock Profile Refresh (if script exists)
    logger.info("\n📈 Step 3: Stock Profile Refresh")
    if (PROJECT_ROOT / "scripts/daily_stock_refresh.py").exists():
        results["stock_refresh"] = run_script(
            "scripts/daily_stock_refresh.py",
            timeout=600,  # 10 min (increased from 5 min)
        )
    else:
        logger.info("Skipping stock refresh (script not found)")
        results["stock_refresh"] = None

    # Summary
    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds()

    logger.info("\n" + "=" * 60)
    logger.info(f"🏁 Nightly Pipeline Completed in {duration:.1f}s")
    logger.info("=" * 60)

    for task, success in results.items():
        if success is None:
            status = "⏭️ Skipped"
        elif success:
            status = "✅ Success"
        else:
            status = "❌ Failed"
        logger.info(f"  {task}: {status}")

    # Exit with error if any critical task failed
    # OHLCV and NLP are always critical
    critical_failures = [
        results.get("ohlcv") is False,
        results.get("nlp") is False,
    ]

    # SnapTrade is critical only if REQUIRE_SNAPTRADE=1
    if REQUIRE_SNAPTRADE and results.get("snaptrade") is False:
        logger.error("SnapTrade sync failed and REQUIRE_SNAPTRADE=1 - aborting")
        critical_failures.append(True)
    elif results.get("snaptrade") is False:
        logger.warning("⚠️ SnapTrade sync failed (REQUIRE_SNAPTRADE=0, continuing)")

    # Stock refresh failure is non-critical (logs warning only)
    if results.get("stock_refresh") is False:
        logger.warning("⚠️ Stock refresh failed (non-critical)")

    if any(critical_failures):
        logger.error("Pipeline completed with critical failures")
        sys.exit(1)

    logger.info("Pipeline completed successfully")
    sys.exit(0)


if __name__ == "__main__":
    main()
