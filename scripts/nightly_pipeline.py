#!/usr/bin/env python3
"""
Nightly Pipeline Orchestrator

Runs after market close (1 AM ET) to:
1. Backfill OHLCV data from Databento
2. Run NLP batch processing on pending Discord messages
3. Refresh stock profile data

Designed to be run by systemd timer (nightly-pipeline.timer).
"""

import logging
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

# Project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent


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

    # Step 1: OHLCV Backfill (Databento → RDS)
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
            timeout=300,  # 5 min
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
    critical_failures = [
        results.get("ohlcv") is False,
        results.get("nlp") is False,
    ]
    if any(critical_failures):
        logger.error("Pipeline completed with failures")
        sys.exit(1)

    logger.info("Pipeline completed successfully")
    sys.exit(0)


if __name__ == "__main__":
    main()
