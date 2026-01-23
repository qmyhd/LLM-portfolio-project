"""
Discord NLP Processing Lambda Handler

Triggered by EventBridge (CloudWatch Events) on a schedule.
Processes pending Discord messages through the NLP pipeline.

Schedule: Every 15 minutes
    cron(0/15 * * * ? *)

This function:
1. Fetches messages with parse_status = NULL from discord_messages
2. Runs OpenAI structured output parsing
3. Stores parsed ideas in discord_parsed_ideas
4. Updates parse_status on processed messages
"""

import os
import sys
from datetime import datetime
from typing import Any, Dict, Optional

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

# Default batch size (can be overridden in event)
DEFAULT_BATCH_SIZE = 50
MAX_BATCH_SIZE = 200


def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Lambda handler for Discord NLP processing.

    Args:
        event: EventBridge event or custom event with optional parameters:
            - batch_size: Number of messages to process (default: 50)
            - channel_id: Optional filter to specific channel
            - dry_run: If True, parse but don't save (default: False)
        context: Lambda context

    Returns:
        Lambda response with processing results
    """
    start_time = datetime.utcnow()
    logger.info(f"Discord NLP processing started at {start_time.isoformat()}")

    # Parse event parameters
    batch_size = min(
        event.get("batch_size", DEFAULT_BATCH_SIZE),
        MAX_BATCH_SIZE,
    )
    channel_id = event.get("channel_id")
    dry_run = event.get("dry_run", False)

    logger.info(
        f"Parameters: batch_size={batch_size}, channel_id={channel_id}, dry_run={dry_run}"
    )

    # Step 1: Load secrets
    if not load_secrets():
        return error_response("Failed to load secrets from AWS Secrets Manager")

    # Step 2: Validate database connection
    if not validate_db_connection(use_rds=False):
        return error_response("Database connection validation failed")

    # Step 3: Validate OpenAI API key
    if not os.environ.get("OPENAI_API_KEY"):
        return error_response("OPENAI_API_KEY not configured")

    # Step 4: Fetch pending messages
    try:
        from src.db import execute_sql

        # Build query for pending messages
        query = """
            SELECT message_id, content, author_id, channel_id, created_at
            FROM discord_messages
            WHERE parse_status IS NULL
              AND content IS NOT NULL
              AND LENGTH(content) > 10
        """
        params = {}

        if channel_id:
            query += " AND channel_id = :channel_id"
            params["channel_id"] = str(channel_id)

        query += " ORDER BY created_at DESC LIMIT :limit"
        params["limit"] = batch_size

        pending_messages = execute_sql(query, params=params, fetch_results=True)

        if not pending_messages:
            logger.info("No pending messages to process")
            return success_response(
                message="No pending messages to process",
                data={"processed": 0, "pending": 0},
            )

        logger.info(f"Found {len(pending_messages)} pending messages")

    except Exception as e:
        logger.exception("Failed to fetch pending messages")
        return error_response(
            message="Failed to fetch pending messages",
            error=str(e),
        )

    # Step 5: Process messages through NLP pipeline
    try:
        from src.nlp.openai_parser import process_message
        from src.db import save_parsed_ideas_atomic

        results = {
            "processed": 0,
            "ideas_created": 0,
            "errors": 0,
            "noise": 0,
            "skipped": 0,
        }

        for row in pending_messages:
            message_id = str(row[0])
            content = row[1]
            author_id = str(row[2]) if row[2] else None
            msg_channel_id = str(row[3]) if row[3] else None
            created_at = row[4]

            try:
                # Parse message with OpenAI
                # process_message returns a Dict with: status, ideas, model, error_reason, call_stats
                result = process_message(
                    text=content,
                    message_id=message_id,
                    author_id=author_id,
                    channel_id=msg_channel_id,
                    created_at=created_at.isoformat() if created_at else None,
                )

                # Check result status
                status = result.get("status", "error")

                if status in ("noise", "skipped"):
                    results["noise"] += 1
                    if not dry_run:
                        save_parsed_ideas_atomic(
                            message_id=message_id,
                            ideas=[],
                            status=status,
                            prompt_version="lambda-v1",
                        )
                    continue

                if status == "error":
                    results["errors"] += 1
                    if not dry_run:
                        save_parsed_ideas_atomic(
                            message_id=message_id,
                            ideas=[],
                            status="error",
                            prompt_version="lambda-v1",
                            error_reason=result.get("error_reason", "Unknown error")[
                                :500
                            ],
                        )
                    continue

                # Get ideas from result dict (already in database-ready format)
                ideas = result.get("ideas", [])
                model = result.get("model", "gpt-4o-mini")

                # Add author/channel metadata if not present
                for idea in ideas:
                    idea["author_id"] = idea.get("author_id") or author_id
                    idea["channel_id"] = idea.get("channel_id") or msg_channel_id
                    idea["prompt_version"] = "lambda-v1"

                if not dry_run:
                    save_parsed_ideas_atomic(
                        message_id=message_id,
                        ideas=ideas,
                        status="ok" if ideas else "noise",
                        prompt_version="lambda-v1",
                    )

                results["processed"] += 1
                results["ideas_created"] += len(ideas)

            except Exception as e:
                logger.warning(f"Failed to process message {message_id}: {e}")
                results["errors"] += 1

                if not dry_run:
                    save_parsed_ideas_atomic(
                        message_id=message_id,
                        ideas=[],
                        status="error",
                        prompt_version="lambda-v1",
                        error_reason=str(e)[:500],
                    )

        # Calculate duration
        duration = (datetime.utcnow() - start_time).total_seconds()

        logger.info(f"Discord NLP processing completed in {duration:.2f}s")
        logger.info(f"Results: {results}")

        return success_response(
            message="Discord NLP processing completed",
            data={
                "duration_seconds": round(duration, 2),
                "results": results,
                "timestamp": start_time.isoformat(),
                "dry_run": dry_run,
            },
        )

    except ImportError as e:
        logger.error(f"Import error: {e}")
        return error_response(
            message="NLP modules not available",
            error=str(e),
        )
    except Exception as e:
        logger.exception("Discord NLP processing failed")
        return error_response(
            message="Discord NLP processing failed",
            error=str(e),
        )


# Local testing
if __name__ == "__main__":
    # Simulate EventBridge event with custom parameters
    test_event = {
        "source": "aws.events",
        "time": datetime.utcnow().isoformat(),
        "detail-type": "Scheduled Event",
        "batch_size": 10,
        "dry_run": True,  # Don't save to DB during testing
    }

    result = handler(test_event, None)
    print(result)
