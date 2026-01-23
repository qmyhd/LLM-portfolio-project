"""
SnapTrade Sync Lambda Handler

Triggered by EventBridge (CloudWatch Events) on a schedule.
Syncs portfolio data from SnapTrade API to Supabase.

Schedule: Every 30 minutes during market hours (9:00-16:30 EST, Mon-Fri)

EventBridge Rule Example:
    cron(0/30 13-21 ? * MON-FRI *)  # UTC (9:00-16:30 EST)
"""

import os
import sys
from datetime import datetime
from typing import Any, Dict

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from lambdas.shared import (
    configure_logging,
    error_response,
    load_secrets,
    success_response,
    validate_db_connection,
)

logger = configure_logging("INFO")


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Lambda handler for SnapTrade sync.

    Args:
        event: EventBridge event (contains time, source, etc.)
        context: Lambda context (request_id, function_name, etc.)

    Returns:
        Lambda response with sync results
    """
    start_time = datetime.utcnow()
    logger.info(f"SnapTrade sync started at {start_time.isoformat()}")
    logger.info(f"Event source: {event.get('source', 'unknown')}")

    # Step 1: Load secrets from AWS Secrets Manager
    if not load_secrets():
        return error_response("Failed to load secrets from AWS Secrets Manager")

    # Step 2: Validate database connection
    if not validate_db_connection(use_rds=False):
        return error_response("Database connection validation failed")

    # Step 3: Run SnapTrade sync using collect_all_data()
    try:
        from src.snaptrade_collector import SnapTradeCollector

        collector = SnapTradeCollector()

        # Use the canonical collect_all_data method which handles all sync operations
        # This method: gets accounts/positions/orders/balances/symbols and writes to DB
        sync_results = collector.collect_all_data(write_parquet=False)

        # Calculate duration
        duration = (datetime.utcnow() - start_time).total_seconds()

        logger.info(f"SnapTrade sync completed in {duration:.2f}s")
        logger.info(f"Results: {sync_results}")

        return success_response(
            message="SnapTrade sync completed successfully",
            data={
                "duration_seconds": round(duration, 2),
                "results": {
                    "accounts": sync_results.get("accounts", 0),
                    "positions": sync_results.get("positions", 0),
                    "orders": sync_results.get("orders", 0),
                    "balances": sync_results.get("balances", 0),
                    "symbols": sync_results.get("symbols", 0),
                    "success": sync_results.get("success", False),
                    "errors": sync_results.get("errors", []),
                },
                "timestamp": start_time.isoformat(),
            },
        )

    except ImportError as e:
        logger.error(f"Import error: {e}")
        return error_response(
            message="SnapTrade collector not available",
            error=str(e),
        )
    except Exception as e:
        logger.exception("SnapTrade sync failed")
        return error_response(
            message="SnapTrade sync failed",
            error=str(e),
        )


# Local testing
if __name__ == "__main__":
    # Simulate EventBridge event
    test_event = {
        "source": "aws.events",
        "time": datetime.utcnow().isoformat(),
        "detail-type": "Scheduled Event",
    }

    result = handler(test_event, None)
    print(result)
