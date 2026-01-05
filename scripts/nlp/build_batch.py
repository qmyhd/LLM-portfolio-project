#!/usr/bin/env python3
"""
Build JSONL batch file for OpenAI Batch API.

Generates a .jsonl file where each line is a request for processing
a message chunk. This can be submitted to OpenAI's Batch API for
cost-effective batch processing (50% discount).

Usage:
    # Build batch file for all pending messages
    python scripts/nlp/build_batch.py --output batch_requests.jsonl

    # Build for specific limit
    python scripts/nlp/build_batch.py --limit 1000 --output batch_1k.jsonl

    # Skip triage (include all chunks, no filtering)
    python scripts/nlp/build_batch.py --skip-triage --output batch.jsonl

    # Show stats only
    python scripts/nlp/build_batch.py --stats-only

Batch API Notes:
    - Each line must be a valid JSON object
    - custom_id format: "msg-{message_id}-chunk-{chunk_index}"
    - Method: POST, URL: /v1/chat/completions
    - Batch jobs complete within 24 hours (usually much faster)
    - 50% cost discount vs synchronous API

Endpoint Decision:
    OpenAI Batch API ONLY supports:
    - /v1/chat/completions (Chat Completions)
    - /v1/embeddings (Embeddings)

    The Responses API (/v1/responses) is NOT supported for batch processing.
    Our live parser uses Responses API for structured outputs, but batch must
    use Chat Completions with JSON schema in response_format.
    Both produce identical MessageParseResult output (same Pydantic schema).
"""

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Any, Optional

# Add project root to path
sys.path.insert(0, str(__file__).rsplit("scripts", 1)[0].rstrip("/\\"))

from src.db import execute_sql
from src.nlp.soft_splitter import prepare_for_parsing, summarize_splits
from src.nlp.openai_parser import (
    build_batch_request,
    _build_parser_system_prompt,
    MODEL_MAIN,
)
from src.nlp.schemas import CURRENT_PROMPT_VERSION
from src.nlp.preclean import should_skip_message  # SSOT prefilter

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def get_pending_messages(
    limit: Optional[int] = None,
    min_length: int = 10,
) -> List[Dict[str, Any]]:
    """
    Fetch messages pending parsing from the database.

    Args:
        limit: Maximum number of messages to fetch
        min_length: Minimum content length

    Returns:
        List of message dicts
    """
    query = """
        SELECT 
            message_id,
            content,
            author,
            channel,
            created_at
        FROM discord_messages
        WHERE parse_status = 'pending'
        AND content IS NOT NULL
        AND LENGTH(content) > :min_length
        ORDER BY created_at DESC
    """
    if limit:
        query += f" LIMIT {limit}"

    params = {"min_length": min_length}
    result = execute_sql(query, params=params, fetch_results=True)

    if not result:
        return []

    return [
        {
            "message_id": row[0],
            "content": row[1],
            "author": row[2],
            "channel_id": str(row[3]) if row[3] else None,  # column is 'channel'
            "created_at": row[4].isoformat() if row[4] else None,
        }
        for row in result
    ]


def build_batch_file(
    messages: List[Dict[str, Any]],
    output_path: Path,
    skip_triage: bool = False,
    mark_skipped_in_db: bool = False,
) -> Dict[str, Any]:
    """
    Build JSONL batch file from messages.

    Args:
        messages: List of message dicts
        output_path: Path to write JSONL file
        skip_triage: If True, include all chunks without triage
        mark_skipped_in_db: If True, update parse_status for skipped messages

    Returns:
        Stats dict with lists of skipped message IDs
    """
    stats = {
        "messages_processed": 0,
        "messages_skipped": 0,
        "chunks_generated": 0,
        "total_chars": 0,
        "bot_commands_skipped": 0,
        "url_only_skipped": 0,
        "bot_response_skipped": 0,
        "empty_after_clean_skipped": 0,
        # Track skipped message IDs by reason for database update
        "skipped_ids_by_reason": {
            "bot_command": [],
            "url_only": [],
            "bot_response": [],
            "empty": [],
            "empty_after_clean": [],
        },
        "empty_after_clean_samples": [],  # First 5 samples with original content
    }

    with open(output_path, "w", encoding="utf-8") as f:
        for message in messages:
            message_id = message["message_id"]
            content = message["content"]

            # =================================================================
            # PREFILTERS - SINGLE SOURCE OF TRUTH (from preclean.should_skip_message)
            # =================================================================
            # Build message_meta from the message dict for bot detection
            message_meta = {
                "author": message.get("author"),
                "is_bot": message.get("is_bot", False),
            }

            should_skip, skip_reason = should_skip_message(content, message_meta)
            if should_skip:
                # Map skip reasons to stats keys (handle None case)
                reason_to_stat = {
                    "bot_command": "bot_commands_skipped",
                    "url_only": "url_only_skipped",
                    "bot_response": "bot_response_skipped",
                    "empty": "empty_after_clean_skipped",
                }
                stat_key = reason_to_stat.get(
                    skip_reason or "empty", "empty_after_clean_skipped"
                )
                stats[stat_key] = stats.get(stat_key, 0) + 1
                stats["messages_skipped"] += 1

                # Track ID by reason for database marking (use "empty" if None)
                reason_key = skip_reason or "empty"
                if reason_key in stats["skipped_ids_by_reason"]:
                    stats["skipped_ids_by_reason"][reason_key].append(message_id)
                continue

            # Preclean and soft split
            chunks = prepare_for_parsing(content)

            if not chunks:
                stats["empty_after_clean_skipped"] += 1
                stats["skipped_ids_by_reason"]["empty_after_clean"].append(message_id)
                stats["messages_skipped"] += 1
                # Store samples for debugging (first 5)
                if len(stats["empty_after_clean_samples"]) < 5:
                    stats["empty_after_clean_samples"].append(
                        {
                            "message_id": message_id,
                            "original_content": content[:500],  # Truncate for display
                        }
                    )
                continue

            stats["messages_processed"] += 1

            # Build request for each chunk
            for chunk_idx, chunk in enumerate(chunks):
                request = build_batch_request(
                    message_id=message_id,
                    text=chunk.text,
                    chunk_index=chunk_idx,
                )

                # Write JSONL line
                f.write(json.dumps(request) + "\n")

                stats["chunks_generated"] += 1
                stats["total_chars"] += len(chunk.text)

    # Mark skipped messages in database if requested
    if mark_skipped_in_db:
        _mark_skipped_messages(stats)

    return stats


def _mark_skipped_messages(stats: Dict[str, Any]) -> int:
    """
    Update parse_status in database for skipped messages.

    This prevents them from appearing in future pending queries.

    Args:
        stats: Stats dict with skipped_ids_by_reason

    Returns:
        Total number of messages marked
    """
    total_marked = 0

    # Get the new unified structure
    skipped_by_reason = stats.get("skipped_ids_by_reason", {})

    # Mark all skipped messages with their reason
    for reason, message_ids in skipped_by_reason.items():
        if not message_ids:
            continue

        for msg_id in message_ids:
            try:
                execute_sql(
                    """
                    UPDATE discord_messages
                    SET parse_status = 'skipped',
                        error_reason = :error_reason
                    WHERE message_id = CAST(:message_id AS text)
                    """,
                    params={"message_id": str(msg_id), "error_reason": reason},
                )
                total_marked += 1
            except Exception as e:
                logger.warning(
                    f"Failed to mark message {msg_id} as skipped ({reason}): {e}"
                )

    logger.info(f"Marked {total_marked} messages as skipped in database")
    return total_marked


def estimate_batch_cost(stats: Dict[str, Any]) -> Dict[str, float]:
    """
    Estimate batch processing cost.

    Args:
        stats: Stats from build_batch_file()

    Returns:
        Cost estimates
    """
    # Rough estimates (4 chars per token average)
    system_tokens = len(_build_parser_system_prompt()) // 4

    input_tokens_per_chunk = (
        system_tokens + (stats["total_chars"] // stats["chunks_generated"] // 4)
        if stats["chunks_generated"] > 0
        else 0
    )
    output_tokens_per_chunk = 500  # Estimated structured output

    total_input_tokens = input_tokens_per_chunk * stats["chunks_generated"]
    total_output_tokens = output_tokens_per_chunk * stats["chunks_generated"]

    # Batch API pricing (50% off normal rates)
    # gpt-4o-mini: Input $0.075/1M, Output $0.30/1M (batch)
    batch_cost = (total_input_tokens * 0.075 + total_output_tokens * 0.30) / 1_000_000

    # Normal API for comparison
    normal_cost = (total_input_tokens * 0.15 + total_output_tokens * 0.60) / 1_000_000

    return {
        "total_input_tokens": total_input_tokens,
        "total_output_tokens": total_output_tokens,
        "batch_cost_usd": batch_cost,
        "normal_cost_usd": normal_cost,
        "savings_usd": normal_cost - batch_cost,
    }


def create_manifest(
    output_path: Path,
    stats: Dict[str, Any],
    cost_estimate: Dict[str, float],
) -> Path:
    """
    Create a manifest file alongside the batch JSONL.

    Args:
        output_path: Path to JSONL file
        stats: Build stats
        cost_estimate: Cost estimates

    Returns:
        Path to manifest file
    """
    manifest_path = output_path.with_suffix(".manifest.json")

    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "jsonl_file": output_path.name,
        "model": MODEL_MAIN,
        "prompt_version": CURRENT_PROMPT_VERSION,
        "stats": stats,
        "cost_estimate": cost_estimate,
        "instructions": {
            "submit": f"openai api batches create -f {output_path.name} --endpoint /v1/chat/completions",
            "check": "openai api batches list",
            "retrieve": "openai api batches retrieve <batch_id>",
            "download": "openai api batches retrieve <batch_id> --download output.jsonl",
            "ingest": f"python scripts/nlp/ingest_batch.py --input output.jsonl",
        },
    }

    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    return manifest_path


def main():
    parser = argparse.ArgumentParser(
        description="Build JSONL batch file for OpenAI Batch API"
    )
    parser.add_argument(
        "--output",
        "-o",
        type=str,
        default="batch_requests.jsonl",
        help="Output JSONL file path",
    )
    parser.add_argument(
        "--limit", type=int, default=None, help="Maximum number of messages to include"
    )
    parser.add_argument(
        "--skip-triage",
        action="store_true",
        help="Skip triage filtering (include all chunks)",
    )
    parser.add_argument(
        "--stats-only", action="store_true", help="Only show stats, don't create file"
    )
    parser.add_argument(
        "--mark-skipped",
        action="store_true",
        help="Mark bot commands and empty-after-clean messages as 'skipped' in database",
    )
    parser.add_argument(
        "--show-samples",
        action="store_true",
        help="Show samples of empty-after-clean messages for debugging",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Enable verbose logging"
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    output_path = Path(args.output)

    # Fetch messages
    logger.info("Fetching pending messages...")
    messages = get_pending_messages(limit=args.limit)

    if not messages:
        logger.info("No pending messages found")
        return

    logger.info(f"Found {len(messages)} messages")

    # Stats-only mode
    if args.stats_only:
        # Quick estimate without building file
        total_chunks = 0
        total_chars = 0
        for msg in messages:
            chunks = prepare_for_parsing(msg["content"])
            total_chunks += len(chunks)
            total_chars += sum(len(c.text) for c in chunks)

        logger.info(f"\nEstimated batch stats:")
        logger.info(f"  Messages: {len(messages)}")
        logger.info(f"  Chunks: {total_chunks}")
        logger.info(f"  Avg chunks/message: {total_chunks / len(messages):.1f}")
        logger.info(f"  Total chars: {total_chars:,}")

        stats = {"chunks_generated": total_chunks, "total_chars": total_chars}
        cost = estimate_batch_cost(stats)
        logger.info(f"\nCost estimate:")
        logger.info(f"  Batch API: ${cost['batch_cost_usd']:.4f}")
        logger.info(f"  Normal API: ${cost['normal_cost_usd']:.4f}")
        logger.info(f"  Savings: ${cost['savings_usd']:.4f}")
        return

    # Build batch file
    logger.info(f"Building batch file: {output_path}")

    stats = build_batch_file(
        messages=messages,
        output_path=output_path,
        skip_triage=args.skip_triage,
        mark_skipped_in_db=args.mark_skipped,
    )

    # Cost estimate
    cost = estimate_batch_cost(stats)

    # Create manifest
    manifest_path = create_manifest(output_path, stats, cost)

    # Summary
    logger.info("\n" + "=" * 50)
    logger.info("BATCH FILE CREATED")
    logger.info("=" * 50)
    logger.info(f"Output: {output_path}")
    logger.info(f"Manifest: {manifest_path}")
    logger.info(f"\nStats:")
    logger.info(f"  Messages processed: {stats['messages_processed']}")
    logger.info(f"  Bot commands skipped: {stats['bot_commands_skipped']}")
    logger.info(f"  URL-only skipped: {stats.get('url_only_skipped', 0)}")
    logger.info(f"  Bot responses skipped: {stats.get('bot_response_skipped', 0)}")
    logger.info(f"  Empty after clean: {stats['empty_after_clean_skipped']}")
    logger.info(f"  Chunks generated: {stats['chunks_generated']}")
    logger.info(f"  Total chars: {stats['total_chars']:,}")

    # Show samples if requested or if there are skipped messages
    if args.show_samples and stats["empty_after_clean_samples"]:
        logger.info("\n" + "-" * 50)
        logger.info("EMPTY AFTER CLEAN SAMPLES (original content):")
        logger.info("-" * 50)
        for i, sample in enumerate(stats["empty_after_clean_samples"], 1):
            logger.info(f"\n  [{i}] message_id: {sample['message_id']}")
            logger.info(f"      content: {sample['original_content'][:200]}...")

    total_skipped = (
        stats["bot_commands_skipped"]
        + stats.get("url_only_skipped", 0)
        + stats.get("bot_response_skipped", 0)
        + stats["empty_after_clean_skipped"]
    )
    if args.mark_skipped:
        logger.info(f"\n✅ Marked {total_skipped} messages as 'skipped' in database")

    logger.info(f"\nCost estimate:")
    logger.info(f"  Batch API: ${cost['batch_cost_usd']:.4f}")
    logger.info(f"  Normal API: ${cost['normal_cost_usd']:.4f}")
    logger.info(f"  Savings: ${cost['savings_usd']:.4f} (50%)")
    logger.info(f"\nNext steps:")
    logger.info(
        f"  1. Submit: openai api batches create -f {output_path} --endpoint /v1/chat/completions"
    )
    logger.info(f"  2. Check: openai api batches list")
    logger.info(f"  3. Download results when complete")
    logger.info(
        f"  4. Ingest: python scripts/nlp/ingest_batch.py --input <output_file>"
    )


if __name__ == "__main__":
    main()
