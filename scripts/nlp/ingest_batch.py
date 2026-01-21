#!/usr/bin/env python3
"""
Ingest OpenAI Batch API results into the database.

Reads the output JSONL from a completed batch job and:
1. Parses each response into MessageParseResult
2. Inserts ideas into discord_parsed_ideas table
3. Updates parse_status on discord_messages

Usage:
    # Ingest batch results
    python scripts/nlp/ingest_batch.py --input batch_output.jsonl

    # Dry run (don't save to database)
    python scripts/nlp/ingest_batch.py --input batch_output.jsonl --dry-run

    # Show detailed parsing for each response
    python scripts/nlp/ingest_batch.py --input batch_output.jsonl --verbose
"""

import argparse
import json
import logging
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple

# Add project root to path
sys.path.insert(0, str(__file__).rsplit("scripts", 1)[0].rstrip("/\\"))

from src.db import execute_sql, transaction
from sqlalchemy import text
from src.nlp.schemas import (
    MessageParseResult,
    parsed_idea_to_db_row,
    CURRENT_PROMPT_VERSION,
)
from src.nlp.openai_parser import parse_batch_response, MODEL_MAIN

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def parse_custom_id(custom_id: str) -> Tuple[str, int]:
    """
    Parse custom_id to extract message_id and chunk_index.

    Format: "msg-{message_id}-chunk-{chunk_index}"

    Args:
        custom_id: The custom ID from batch response

    Returns:
        Tuple of (message_id as string, chunk_index as int)
    """
    # "msg-123456789-chunk-0"
    parts = custom_id.split("-")
    if len(parts) >= 4 and parts[0] == "msg" and parts[2] == "chunk":
        message_id = str(parts[1])  # Always string
        chunk_index = int(parts[3])
        return message_id, chunk_index

    raise ValueError(f"Invalid custom_id format: {custom_id}")


def load_batch_output(input_path: Path) -> List[Dict[str, Any]]:
    """
    Load and parse the batch output JSONL file.

    Args:
        input_path: Path to the batch output JSONL

    Returns:
        List of response dicts
    """
    responses = []

    with open(input_path, "r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue

            try:
                response = json.loads(line)
                responses.append(response)
            except json.JSONDecodeError as e:
                logger.error(f"Line {line_num}: Invalid JSON - {e}")

    return responses


def get_message_metadata(message_ids: List[int]) -> Dict[int, Dict[str, Any]]:
    """
    Fetch metadata for messages from database.

    Args:
        message_ids: List of message IDs

    Returns:
        Dict mapping message_id to metadata
    """
    if not message_ids:
        return {}

    # Build query with IN clause - message_id is TEXT type, so quote values
    placeholders = ", ".join(f"'{mid}'" for mid in message_ids)
    # Note: discord_messages uses 'channel' column, but discord_parsed_ideas uses 'channel_id'
    query = f"""
        SELECT 
            message_id,
            author,
            channel,
            created_at
        FROM discord_messages
        WHERE message_id IN ({placeholders})
    """

    result = execute_sql(query, fetch_results=True)

    if not result:
        return {}

    return {
        row[0]: {
            "author": row[1],
            "channel_id": (
                str(row[2]) if row[2] else None
            ),  # Stored as channel_id in parsed_ideas
            "created_at": row[3].isoformat() if row[3] else None,
        }
        for row in result
    }


def save_parsed_ideas(ideas: List[Dict[str, Any]], conn=None) -> int:
    """
    Save parsed ideas to discord_parsed_ideas table.

    Uses plain INSERT since delete_existing_ideas_for_messages() is called first.
    This prevents stale rows from reparsing (reparse safety).

    Args:
        ideas: List of idea dicts
        conn: Optional SQLAlchemy connection for transaction support

    Returns:
        Number of ideas inserted
    """
    if not ideas:
        return 0

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

            # Convert Python types to PostgreSQL types
            params = {
                "message_id": str(idea["message_id"]),
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
                "model": idea["model"],
                "prompt_version": idea["prompt_version"],
                "confidence": idea.get("confidence"),
                "raw_json": json.dumps(idea.get("raw_json", {})),
                "source_created_at": idea.get("source_created_at"),
            }

            if conn is not None:
                # Use provided connection (within transaction)
                conn.execute(text(query), params)
            else:
                # Fallback to standalone execute_sql (backward compat)
                execute_sql(query, params=params)
            inserted += 1

        except Exception as e:
            logger.error(f"Failed to insert idea: {e}")

    return inserted


def delete_and_insert_ideas_atomic(
    message_ids: List[int], ideas: List[Dict[str, Any]]
) -> Tuple[int, int]:
    """
    Atomically delete existing ideas and insert new ones in a single transaction.

    Uses advisory locks to prevent concurrent workers from interleaving:
    - Lock all message_ids
    - Delete existing ideas for those messages
    - Insert new ideas
    - Release locks (automatic on commit)

    Args:
        message_ids: List of message IDs to process
        ideas: List of idea dicts to insert

    Returns:
        Tuple of (deleted_count, inserted_count)
    """
    if not message_ids:
        return 0, 0

    deleted = 0
    inserted = 0

    with transaction() as conn:
        # Step 1: Acquire advisory locks for all message IDs
        for mid in message_ids:
            try:
                lock_key = int(mid)
            except (ValueError, TypeError):
                lock_key = hash(str(mid)) & 0x7FFFFFFFFFFFFFFF

            conn.execute(
                text("SELECT pg_advisory_xact_lock(:lock_key)"), {"lock_key": lock_key}
            )

        logger.debug(f"Acquired advisory locks for {len(message_ids)} messages")

        # Step 2: Delete existing ideas
        placeholders = ", ".join(f"'{mid}'" for mid in message_ids)
        delete_query = f"""
            DELETE FROM discord_parsed_ideas 
            WHERE message_id IN ({placeholders})
        """
        result = conn.execute(text(delete_query))
        deleted = result.rowcount if result.rowcount else len(message_ids)
        logger.debug(f"Deleted existing ideas for {len(message_ids)} messages")

        # Step 3: Insert new ideas (using same connection)
        inserted = save_parsed_ideas(ideas, conn=conn)

        # Transaction commits and locks release on context exit

    return deleted, inserted


def delete_existing_ideas_for_messages(message_ids: List[int]) -> int:
    """
    Delete existing ideas for a batch of messages (reparse safety).

    DEPRECATED: Use delete_and_insert_ideas_atomic() instead to ensure
    advisory locks persist across the delete+insert sequence.

    Uses advisory locks to prevent concurrent workers from clobbering each other.

    Args:
        message_ids: List of message IDs to clean up

    Returns:
        Number of rows deleted
    """
    if not message_ids:
        return 0

    # Acquire advisory locks for all message IDs
    for mid in message_ids:
        try:
            lock_key = int(mid)
        except (ValueError, TypeError):
            lock_key = hash(str(mid)) & 0x7FFFFFFFFFFFFFFF

        # Try to acquire lock (non-blocking check first, then block)
        execute_sql(
            "SELECT pg_advisory_xact_lock(:lock_key)", params={"lock_key": lock_key}
        )

    logger.debug(f"Acquired advisory locks for {len(message_ids)} messages")

    # Build query with IN clause
    placeholders = ", ".join(f"'{mid}'" for mid in message_ids)
    query = f"""
        DELETE FROM discord_parsed_ideas 
        WHERE message_id IN ({placeholders})
    """

    execute_sql(query)
    logger.info(f"Deleted existing ideas for {len(message_ids)} messages")
    return len(message_ids)


def update_message_statuses(
    message_statuses: Dict[int, Tuple[str, Optional[str]]],
) -> int:
    """
    Batch update parse_status on discord_messages.

    Args:
        message_statuses: Dict mapping message_id to (status, error_reason)

    Returns:
        Number of messages updated
    """
    updated = 0
    for message_id, (status, error_reason) in message_statuses.items():
        try:
            query = """
                UPDATE discord_messages
                SET parse_status = :status,
                    prompt_version = :prompt_version,
                    error_reason = :error_reason
                WHERE message_id = CAST(:message_id AS text)
            """
            params = {
                "message_id": str(message_id),
                "status": status,
                "prompt_version": CURRENT_PROMPT_VERSION,
                "error_reason": error_reason,
            }
            execute_sql(query, params=params)
            updated += 1
        except Exception as e:
            logger.error(f"Failed to update message {message_id}: {e}")

    return updated


def process_batch_output(
    responses: List[Dict[str, Any]],
    dry_run: bool = False,
) -> Dict[str, Any]:
    """
    Process batch output and save to database.

    Args:
        responses: List of batch response dicts
        dry_run: Don't save to database

    Returns:
        Processing stats
    """
    stats = {
        "total_responses": len(responses),
        "successful": 0,
        "failed": 0,
        "ideas_extracted": 0,
        "messages_updated": 0,
    }

    # Group responses by message_id (a message may have multiple chunks)
    message_chunks: Dict[int, List[Tuple[int, Optional[MessageParseResult]]]] = (
        defaultdict(list)
    )

    # Collect all message IDs for metadata lookup
    all_message_ids = set()

    for response in responses:
        custom_id = response.get("custom_id", "")

        try:
            message_id, chunk_index = parse_custom_id(custom_id)
            all_message_ids.add(message_id)
        except ValueError as e:
            logger.error(str(e))
            stats["failed"] += 1
            continue

        # Check for API error
        if response.get("error"):
            logger.error(f"{custom_id}: API error - {response['error']}")
            message_chunks[message_id].append((chunk_index, None))
            stats["failed"] += 1
            continue

        # Parse response
        try:
            body = response.get("response", {}).get("body", {})
            choices = body.get("choices", [])

            if choices:
                content = choices[0].get("message", {}).get("content", "")
                result = MessageParseResult.model_validate_json(content)
                message_chunks[message_id].append((chunk_index, result))
                stats["successful"] += 1
            else:
                logger.warning(f"{custom_id}: No choices in response")
                message_chunks[message_id].append((chunk_index, None))
                stats["failed"] += 1

        except Exception as e:
            logger.error(f"{custom_id}: Parse error - {e}")
            message_chunks[message_id].append((chunk_index, None))
            stats["failed"] += 1

    # Get message metadata
    logger.info(f"Fetching metadata for {len(all_message_ids)} messages...")
    metadata = get_message_metadata(list(all_message_ids))

    # Build ideas and status updates
    all_ideas = []
    message_statuses: Dict[int, Tuple[str, Optional[str]]] = {}

    for message_id, chunks in message_chunks.items():
        # Sort chunks by index (deterministic ordering)
        chunks.sort(key=lambda x: x[0])

        # Check if all chunks succeeded
        all_success = all(result is not None for _, result in chunks)
        any_success = any(result is not None for _, result in chunks)

        if not any_success:
            message_statuses[message_id] = ("error", "All chunks failed to parse")
            continue

        # Get message metadata
        msg_meta = metadata.get(message_id, {})

        # Extract ideas from all successful chunks
        # Use deterministic indexing: soft_chunk_index + local_idea_index
        global_idea_index = 0
        has_ideas = False

        for soft_chunk_index, result in chunks:
            if result is None:
                continue

            # local_idea_index is the index within this soft chunk
            for local_idea_index, idea in enumerate(result.ideas):
                if not idea.is_noise:
                    row = parsed_idea_to_db_row(
                        idea=idea,
                        message_id=message_id,
                        idea_index=global_idea_index,  # Global ordering
                        context_summary=result.context_summary,
                        model=MODEL_MAIN,  # Use env-configured model (matches build_batch_request)
                        prompt_version=CURRENT_PROMPT_VERSION,
                        confidence=result.confidence,
                        raw_json={
                            "chunk_index": soft_chunk_index,
                            "result": result.model_dump(),
                        },
                        author_id=msg_meta.get("author"),
                        channel_id=msg_meta.get("channel_id"),
                        source_created_at=msg_meta.get("created_at"),
                    )
                    # Add chunk indexing for deterministic uniqueness
                    row["soft_chunk_index"] = soft_chunk_index
                    row["local_idea_index"] = local_idea_index

                    all_ideas.append(row)
                    global_idea_index += 1
                    has_ideas = True

        # Determine status
        if has_ideas:
            status = "ok" if all_success else "ok"  # Still ok if we got ideas
            message_statuses[message_id] = (status, None)
        else:
            # All ideas were noise
            message_statuses[message_id] = ("noise", "All extracted ideas were noise")

    stats["ideas_extracted"] = len(all_ideas)

    # Save to database with reparse safety (atomic delete+insert in single transaction)
    if not dry_run:
        # Use atomic function for delete+insert to ensure advisory locks persist
        successful_message_ids = [
            mid
            for mid, (status, _) in message_statuses.items()
            if status in ("ok", "noise")
        ]
        if successful_message_ids or all_ideas:
            logger.info(
                f"Atomic delete+insert for {len(successful_message_ids)} messages, {len(all_ideas)} ideas..."
            )
            deleted, inserted = delete_and_insert_ideas_atomic(
                successful_message_ids, all_ideas
            )
            logger.info(f"Deleted existing, inserted {inserted} ideas")

        # Update message statuses (separate transaction is OK - no race condition here)
        logger.info(f"Updating {len(message_statuses)} message statuses...")
        updated = update_message_statuses(message_statuses)
        stats["messages_updated"] = updated
    else:
        logger.info(f"[DRY RUN] Would insert {len(all_ideas)} ideas")
        logger.info(f"[DRY RUN] Would update {len(message_statuses)} message statuses")

        # Show sample ideas
        if all_ideas:
            logger.info("\nSample ideas:")
            for idea in all_ideas[:5]:
                symbol = idea.get("primary_symbol", "N/A")
                text = (
                    idea["idea_text"][:60] + "..."
                    if len(idea["idea_text"]) > 60
                    else idea["idea_text"]
                )
                labels = ", ".join(idea.get("labels", [])[:2])
                logger.info(f"  [{symbol}] {text} ({labels})")

    return stats


# Alias for run_batch.py compatibility
process_batch_responses = process_batch_output


def main():
    parser = argparse.ArgumentParser(
        description="Ingest OpenAI Batch API results into database"
    )
    parser.add_argument(
        "--input", "-i", type=str, required=True, help="Path to batch output JSONL file"
    )
    parser.add_argument("--dry-run", action="store_true", help="Don't save to database")
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Enable verbose logging"
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    input_path = Path(args.input)

    if not input_path.exists():
        logger.error(f"Input file not found: {input_path}")
        sys.exit(1)

    # Load batch output
    logger.info(f"Loading batch output: {input_path}")
    responses = load_batch_output(input_path)
    logger.info(f"Loaded {len(responses)} responses")

    if not responses:
        logger.info("No responses to process")
        return

    # Process
    stats = process_batch_output(responses, dry_run=args.dry_run)

    # Summary
    logger.info("\n" + "=" * 50)
    logger.info("INGESTION COMPLETE")
    logger.info("=" * 50)
    logger.info(f"Total responses: {stats['total_responses']}")
    logger.info(f"  Successful: {stats['successful']}")
    logger.info(f"  Failed: {stats['failed']}")
    logger.info(f"Ideas extracted: {stats['ideas_extracted']}")
    if not args.dry_run:
        logger.info(f"Messages updated: {stats['messages_updated']}")


if __name__ == "__main__":
    main()
