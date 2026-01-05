"""
Channel-specific data processing module.
Handles cleaning and processing of Discord messages for different channels.
Delegates all cleaning logic to the message_cleaner module.
"""

import logging
from typing import Any, Dict

from src.db import (
    get_connection,
    get_unprocessed_messages,
    mark_message_processed,
    execute_sql,
    save_parsed_ideas_atomic,
)
from src.message_cleaner import process_messages_for_channel

logger = logging.getLogger(__name__)


def process_channel_data(
    channel_name: str, channel_type: str = "trading"
) -> Dict[str, Any]:
    """Process unprocessed messages for a specific channel using the unified message cleaner.

    This function implements a resumable processing pipeline:
    1. Queries for messages without processed_for_cleaning flag (via processing_status table)
    2. Processes them through the cleaning pipeline
    3. Marks them as processed (never deletes raw messages)

    Deduplication & Processing Guarantees:
    - Only processes messages not yet marked as processed_for_cleaning
    - Raw messages in discord_messages table are NEVER deleted
    - Processing flags in processing_status table track what's been processed
    - Safe to re-run: Already-processed messages are automatically skipped
    - Resumable: If interrupted, next run continues from where it left off

    Args:
        channel_name: Name of the Discord channel
        channel_type: Type of channel ("trading" or "market", default: "trading")

    Returns:
        Dictionary with processing results and statistics
    """
    try:
        # Get unprocessed messages for the channel
        # This queries for messages WITHOUT processed_for_cleaning flag
        # Ensures we process each message exactly once
        unprocessed_messages = get_unprocessed_messages(channel_name, "cleaning")

        if not unprocessed_messages:
            return {
                "success": True,
                "channel": channel_name,
                "processed_count": 0,
                "message": "No new messages to process",
            }

        # Convert raw message tuples to list of dicts for the message cleaner
        message_dicts = []
        for message in unprocessed_messages:
            # Query returns: (message_id, author, content, channel, timestamp)
            if len(message) >= 5:
                message_dict = {
                    "message_id": message[0],  # Index 0: message_id
                    "author": message[1],  # Index 1: author
                    "content": message[2],  # Index 2: content
                    "channel": message[3],  # Index 3: channel
                    "created_at": message[4],  # Index 4: timestamp
                }
                message_dicts.append(message_dict)

        # Process messages using the unified cleaner
        # Note: No connection wrapper needed - execute_sql manages its own transactions
        cleaned_df, stats = process_messages_for_channel(
            messages=message_dicts,
            channel_name=channel_name,
            channel_type=channel_type,
            database_connection=None,  # execute_sql manages its own connections
            save_parquet=False,  # We'll handle this elsewhere if needed
            save_database=True,
        )

        # Mark messages as processed
        if not cleaned_df.empty:
            message_ids = cleaned_df["message_id"].tolist()
            for msg_id in message_ids:
                mark_message_processed(msg_id, channel_name, "cleaning")

        logger.info(
            f"Processed {stats['processed_count']} messages for channel {channel_name}"
        )

        return {
            "success": stats["success"],
            "channel": channel_name,
            "channel_type": channel_type,
            "processed_count": stats["processed_count"],
            "message": f"Successfully processed {stats['processed_count']} messages",
            "avg_sentiment": stats.get("avg_sentiment", 0.0),
            "total_tickers": stats.get("total_tickers", 0),
            "unique_tickers": stats.get("unique_tickers", 0),
        }

    except Exception as e:
        logger.error(f"Error processing channel {channel_name}: {e}")
        return {
            "success": False,
            "channel": channel_name,
            "processed_count": 0,
            "error": str(e),
        }


# =============================================================================
# NEW OPENAI PARSING PIPELINE (Primary path for new data)
# =============================================================================


def parse_messages_with_llm(
    message_ids: list = None,
    limit: int = 100,
    skip_triage: bool = False,
    force_long_context: bool = False,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """
    Parse messages using the OpenAI LLM pipeline.

    This is the PRIMARY path for new message parsing. It extracts structured
    trading ideas with labels, entities, and levels using OpenAI's structured outputs.

    Results are saved to discord_parsed_ideas table and parse_status is updated
    on discord_messages.

    Args:
        message_ids: Optional list of specific message IDs to parse
        limit: Maximum messages to process (default 100)
        skip_triage: Skip the cheap triage step
        force_long_context: Force use of long-context model
        dry_run: Don't save to database

    Returns:
        Dict with processing statistics
    """
    import json
    from src.nlp.openai_parser import (
        process_message,
        CURRENT_PROMPT_VERSION,
    )
    from src.nlp.preclean import normalize_text

    stats = {
        "total_messages": 0,
        "parsed_ok": 0,
        "parsed_noise": 0,
        "parsed_error": 0,
        "ideas_extracted": 0,
        "errors": [],
    }

    # Fetch messages to parse
    if message_ids:
        # Parse specific messages
        placeholders = ", ".join([f"'{mid}'" for mid in message_ids])
        query = f"""
            SELECT message_id, content, author, channel_id, created_at
            FROM discord_messages
            WHERE message_id IN ({placeholders})
        """
        messages = execute_sql(query, fetch_results=True)
    else:
        # Parse pending messages
        query = """
            SELECT message_id, content, author, channel_id, created_at
            FROM discord_messages
            WHERE parse_status = 'pending'
            AND content IS NOT NULL
            AND LENGTH(content) > 10
            ORDER BY created_at DESC
            LIMIT :limit
        """
        messages = execute_sql(query, params={"limit": limit}, fetch_results=True)

    if not messages:
        logger.info("No messages to parse")
        return stats

    stats["total_messages"] = len(messages)
    logger.info(f"Parsing {len(messages)} messages with LLM")

    for row in messages:
        message_id, content, author, channel_id, created_at = row

        try:
            # Normalize text first
            cleaned_text = normalize_text(content) if content else ""

            if not cleaned_text or len(cleaned_text) < 10:
                # Too short to parse - use atomic helper for consistency
                if not dry_run:
                    from src.nlp.schemas import CURRENT_PROMPT_VERSION

                    save_parsed_ideas_atomic(
                        message_id=message_id,
                        ideas=[],
                        status="skipped",
                        prompt_version=CURRENT_PROMPT_VERSION,
                        error_reason="Content too short",
                    )
                continue

            # Call the LLM parser
            result = process_message(
                text=cleaned_text,
                message_id=message_id,
                author_id=str(author) if author else None,
                channel_id=str(channel_id) if channel_id else None,
                created_at=created_at.isoformat() if created_at else None,
                skip_triage=skip_triage,
                force_long_context=force_long_context,
            )

            status = result["status"]
            ideas = result.get("ideas", [])
            error_reason = result.get("error_reason")

            # Update stats
            if status == "ok":
                stats["parsed_ok"] += 1
                stats["ideas_extracted"] += len(ideas)
            elif status == "noise":
                stats["parsed_noise"] += 1
            elif status == "error":
                stats["parsed_error"] += 1
                stats["errors"].append(f"{message_id}: {error_reason}")

            if not dry_run:
                # Use atomic helper for reparse safety
                # This acquires lock, deletes old ideas, inserts new ones,
                # and updates status in a SINGLE transaction
                from src.nlp.schemas import CURRENT_PROMPT_VERSION

                save_parsed_ideas_atomic(
                    message_id=message_id,
                    ideas=ideas,
                    status=status,
                    prompt_version=CURRENT_PROMPT_VERSION,
                    error_reason=error_reason,
                )

        except Exception as e:
            logger.error(f"Failed to parse message {message_id}: {e}")
            stats["parsed_error"] += 1
            stats["errors"].append(f"{message_id}: {str(e)}")

            if not dry_run:
                # Use atomic helper even for error case (status update only, no ideas)
                from src.nlp.schemas import CURRENT_PROMPT_VERSION

                save_parsed_ideas_atomic(
                    message_id=message_id,
                    ideas=[],  # No ideas on error
                    status="error",
                    prompt_version=CURRENT_PROMPT_VERSION,
                    error_reason=str(e),
                )

    logger.info(
        f"LLM parsing complete: {stats['parsed_ok']} ok, "
        f"{stats['parsed_noise']} noise, {stats['parsed_error']} errors, "
        f"{stats['ideas_extracted']} ideas extracted"
    )

    return stats


# =============================================================================
# DEPRECATED HELPER FUNCTIONS
# These are kept for backwards compatibility but should NOT be used.
# Use save_parsed_ideas_atomic() from src.db instead - it's the CANONICAL
# atomic helper that prevents the "separate transactions" bug.
# =============================================================================


def _delete_existing_ideas(message_id: str) -> None:
    """
    DEPRECATED: Use save_parsed_ideas_atomic() instead.

    This function acquires an advisory lock but releases it immediately
    when the execute_sql() transaction commits. The subsequent INSERT
    operations run in SEPARATE transactions without the lock protection.

    This is the "separate transactions" bug that save_parsed_ideas_atomic() fixes.
    """
    import warnings

    warnings.warn(
        "_delete_existing_ideas is deprecated. Use save_parsed_ideas_atomic() instead.",
        DeprecationWarning,
        stacklevel=2,
    )

    # Acquire advisory lock for this message
    try:
        lock_key = int(message_id)
    except ValueError:
        lock_key = hash(message_id) & 0x7FFFFFFFFFFFFFFF

    execute_sql(
        "SELECT pg_advisory_xact_lock(:lock_key)", params={"lock_key": lock_key}
    )

    query = """
        DELETE FROM discord_parsed_ideas
        WHERE message_id = CAST(:message_id AS text)
    """
    execute_sql(query, params={"message_id": str(message_id)})


def _update_parse_status(
    message_id: str,
    status: str,
    error_reason: str = None,
) -> None:
    """
    DEPRECATED: Use save_parsed_ideas_atomic() instead.

    This function runs in its own transaction, separate from delete/insert.
    """
    import warnings

    warnings.warn(
        "_update_parse_status is deprecated. Use save_parsed_ideas_atomic() instead.",
        DeprecationWarning,
        stacklevel=2,
    )

    from src.nlp.schemas import CURRENT_PROMPT_VERSION

    query = """
        UPDATE discord_messages
        SET parse_status = :status,
            prompt_version = :prompt_version,
            error_reason = :error_reason
        WHERE message_id = CAST(:message_id AS text)
    """
    execute_sql(
        query,
        params={
            "message_id": str(message_id),
            "status": status,
            "prompt_version": CURRENT_PROMPT_VERSION,
            "error_reason": error_reason,
        },
    )


def _save_parsed_ideas(ideas: list) -> int:
    """
    DEPRECATED: Use save_parsed_ideas_atomic() instead.

    Save parsed ideas to discord_parsed_ideas with INSERT.

    WARNING: This function runs each INSERT in a SEPARATE transaction,
    without the advisory lock protection. Use save_parsed_ideas_atomic() instead.

    Since we call _delete_existing_ideas() before this, we can use plain INSERT.
    The unique constraint is (message_id, soft_chunk_index, local_idea_index).
    """
    import json
    import warnings

    warnings.warn(
        "_save_parsed_ideas is deprecated. Use save_parsed_ideas_atomic() instead.",
        DeprecationWarning,
        stacklevel=2,
    )

    inserted = 0
    for idea in ideas:
        try:
            query = """
                INSERT INTO discord_parsed_ideas (
                    message_id, idea_index, soft_chunk_index, local_idea_index,
                    idea_text, idea_summary, context_summary,
                    primary_symbol, symbols, instrument, direction,
                    action, time_horizon, trigger_condition,
                    levels, option_type, strike, expiry, premium,
                    labels, label_scores, is_noise,
                    author_id, channel_id, model, prompt_version, confidence,
                    raw_json, source_created_at
                ) VALUES (
                    :message_id, :idea_index, :soft_chunk_index, :local_idea_index,
                    :idea_text, :idea_summary, :context_summary,
                    :primary_symbol, :symbols, :instrument, :direction,
                    :action, :time_horizon, :trigger_condition,
                    :levels, :option_type, :strike, :expiry, :premium,
                    :labels, :label_scores, :is_noise,
                    :author_id, :channel_id, :model, :prompt_version, :confidence,
                    :raw_json, :source_created_at
                )
            """

            params = {
                "message_id": str(idea["message_id"]),  # Ensure TEXT type
                "idea_index": idea["idea_index"],
                "soft_chunk_index": idea.get("soft_chunk_index", 0),
                "local_idea_index": idea.get("local_idea_index", idea["idea_index"]),
                "idea_text": idea["idea_text"],
                "idea_summary": idea.get("idea_summary"),
                "context_summary": idea.get("context_summary"),
                "primary_symbol": idea.get("primary_symbol"),
                "symbols": idea.get("symbols", []),
                "instrument": idea.get("instrument"),
                "direction": idea.get("direction"),
                "action": idea.get("action"),
                "time_horizon": idea.get("time_horizon"),
                "trigger_condition": idea.get("trigger_condition"),
                "levels": json.dumps(idea.get("levels", [])),
                "option_type": idea.get("option_type"),
                "strike": idea.get("strike"),
                "expiry": idea.get("expiry"),
                "premium": idea.get("premium"),
                "labels": idea.get("labels", []),
                "label_scores": json.dumps(idea.get("label_scores", {})),
                "is_noise": idea.get("is_noise", False),
                "author_id": idea.get("author_id"),
                "channel_id": idea.get("channel_id"),
                "model": idea.get("model", "unknown"),
                "prompt_version": idea.get("prompt_version", "unknown"),
                "confidence": idea.get("confidence"),
                "raw_json": json.dumps(idea.get("raw_json", {})),
                "source_created_at": idea.get("source_created_at"),
            }

            execute_sql(query, params=params)
            inserted += 1

        except Exception as e:
            logger.error(f"Failed to save idea: {e}")

    return inserted
