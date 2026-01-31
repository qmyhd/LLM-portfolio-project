#!/usr/bin/env python3
"""
Unified batch backfill orchestrator for Discord message parsing.

Runs the complete batch pipeline safely:
1. Verify schema (database ready)
2. Build batch file with prefilters + mark skipped
3. Upload and run batch job
4. Poll until complete
5. Download and ingest results
6. Run post-run integrity checks
7. Print comprehensive summary

Usage:
    # Full batch backfill with defaults (500 messages)
    python scripts/nlp/batch_backfill.py

    # Custom limit
    python scripts/nlp/batch_backfill.py --limit 1000

    # Dry run (build + validate, don't submit)
    python scripts/nlp/batch_backfill.py --dry-run --limit 20

    # Skip schema verification (faster, use if you're sure)
    python scripts/nlp/batch_backfill.py --skip-verify

    # Custom output directory
    python scripts/nlp/batch_backfill.py --output-dir ./batches

Prefilters Applied (aligned with live parsing):
    - is_bot_command(): Skip messages starting with !, /, etc.
    - is_url_only(): Skip URL-only messages (cannot extract ideas)
    - is_bot_response(): Skip messages from bot users (QBOT, etc.)
    - Empty after clean: Skip messages that become empty after preprocessing

Batch API Notes:
    - Uses /v1/chat/completions (Responses API not supported in batch)
    - Same MessageParseResult schema as live parsing
    - 50% cost discount vs synchronous API
    - Completes within 24 hours (usually much faster)
"""

import argparse
import json
import logging
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Optional

# Add project root to path
sys.path.insert(0, str(__file__).rsplit("scripts", 1)[0].rstrip("/\\"))

# Bootstrap AWS secrets FIRST, before any other src imports
from src.env_bootstrap import bootstrap_env

bootstrap_env()

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def verify_schema(verbose: bool = False) -> bool:
    """
    Verify database schema is ready for batch processing.

    Checks:
    - discord_messages table exists
    - discord_parsed_ideas table exists
    - Required columns present (parse_status, etc.)

    Returns:
        True if schema is valid
    """
    logger.info("Verifying database schema...")

    try:
        from src.db import execute_sql

        # Check discord_messages table
        result = execute_sql(
            """
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = 'discord_messages'
            AND column_name IN ('message_id', 'content', 'author', 'parse_status')
            """,
            fetch_results=True,
        )
        dm_cols = {row[0] for row in result} if result else set()
        required_dm = {"message_id", "content", "author", "parse_status"}
        if not required_dm.issubset(dm_cols):
            missing = required_dm - dm_cols
            logger.error(f"discord_messages missing columns: {missing}")
            return False

        # Check discord_parsed_ideas table
        result = execute_sql(
            """
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = 'discord_parsed_ideas'
            AND column_name IN ('message_id', 'idea_index', 'soft_chunk_index', 'local_idea_index')
            """,
            fetch_results=True,
        )
        dpi_cols = {row[0] for row in result} if result else set()
        required_dpi = {
            "message_id",
            "idea_index",
            "soft_chunk_index",
            "local_idea_index",
        }
        if not required_dpi.issubset(dpi_cols):
            missing = required_dpi - dpi_cols
            logger.error(f"discord_parsed_ideas missing columns: {missing}")
            return False

        # Check pending message count
        pending_result = execute_sql(
            "SELECT COUNT(*) FROM discord_messages WHERE parse_status = 'pending'",
            fetch_results=True,
        )
        pending_count = pending_result[0][0] if pending_result else 0
        logger.info(f"Schema verified. Pending messages: {pending_count}")

        return True

    except Exception as e:
        logger.error(f"Schema verification failed: {e}")
        return False


def get_pending_stats() -> Dict[str, int]:
    """Get current parse_status distribution."""
    from src.db import execute_sql

    result = execute_sql(
        """
        SELECT parse_status, COUNT(*) 
        FROM discord_messages 
        GROUP BY parse_status
        """,
        fetch_results=True,
    )

    stats = {}
    if result:
        for row in result:
            status = row[0] or "null"
            stats[status] = row[1]

    return stats


def run_build_batch(
    output_path: Path,
    limit: Optional[int],
    mark_skipped: bool = True,
) -> Dict[str, Any]:
    """
    Build batch JSONL file.

    Args:
        output_path: Path to write JSONL file
        limit: Maximum messages to include
        mark_skipped: Update parse_status for filtered messages

    Returns:
        Build stats dict
    """
    logger.info(f"Building batch file: {output_path}")

    from scripts.nlp.build_batch import get_pending_messages, build_batch_file

    # Fetch pending messages
    messages = get_pending_messages(limit=limit)
    logger.info(f"Fetched {len(messages)} pending messages")

    if not messages:
        return {"messages_processed": 0, "chunks_generated": 0}

    # Build batch file
    stats = build_batch_file(
        messages=messages,
        output_path=output_path,
        skip_triage=False,
        mark_skipped_in_db=mark_skipped,
    )

    return stats


def run_batch_job(
    input_path: Path,
    output_dir: Path,
    poll_seconds: int = 30,
    dry_run: bool = False,
) -> Optional[Dict[str, Any]]:
    """
    Upload, run, and download batch job results.

    Args:
        input_path: Path to input JSONL
        output_dir: Directory for output files
        poll_seconds: Seconds between status polls
        dry_run: If True, skip actual submission

    Returns:
        Batch result dict or None if dry run
    """
    if dry_run:
        logger.info("[DRY RUN] Would submit batch job")
        return None

    from openai import OpenAI
    from scripts.nlp.run_batch import (
        upload_batch_file,
        create_batch,
        poll_batch_status,
        download_batch_output,
    )

    client = OpenAI()

    # Upload
    file_id = upload_batch_file(client, input_path)

    # Create batch
    batch_id = create_batch(
        client,
        file_id,
        description=f"Discord backfill {datetime.now(timezone.utc).isoformat()}",
    )

    # Poll until complete
    result = poll_batch_status(client, batch_id, poll_seconds=poll_seconds)

    if result["status"] != "completed":
        logger.error(f"Batch failed with status: {result['status']}")
        return result

    # Download output
    if result.get("output_file_id"):
        output_path = output_dir / f"batch_output_{batch_id}.jsonl"
        download_batch_output(client, result["output_file_id"], output_path)
        result["output_path"] = str(output_path)
        logger.info(f"Downloaded output to: {output_path}")

    # Download errors if present
    if result.get("error_file_id"):
        error_path = output_dir / f"batch_errors_{batch_id}.jsonl"
        download_batch_output(client, result["error_file_id"], error_path)
        result["error_path"] = str(error_path)
        logger.warning(f"Downloaded errors to: {error_path}")

    return result


def run_ingestion(
    output_path: Path,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """
    Ingest batch results into database.

    Args:
        output_path: Path to batch output JSONL
        dry_run: If True, don't write to database

    Returns:
        Ingestion stats
    """
    logger.info(f"Ingesting results from: {output_path}")

    from scripts.nlp.ingest_batch import load_batch_output, process_batch_output

    responses = load_batch_output(output_path)
    logger.info(f"Loaded {len(responses)} responses")

    if not responses:
        return {"total_responses": 0, "ideas_extracted": 0}

    stats = process_batch_output(responses, dry_run=dry_run)

    return stats


def run_integrity_checks() -> Dict[str, Any]:
    """
    Run post-ingestion integrity checks.

    Checks:
    - No duplicate ideas (same message_id, soft_chunk_index, local_idea_index)
    - parse_status distribution is sane
    - Orphan ideas check (ideas without matching message)

    Returns:
        Check results dict
    """
    logger.info("Running integrity checks...")

    from src.db import execute_sql

    checks = {
        "passed": True,
        "duplicate_ideas": 0,
        "orphan_ideas": 0,
        "parse_status_counts": {},
    }

    # Check for duplicate ideas
    dup_result = execute_sql(
        """
        SELECT message_id, soft_chunk_index, local_idea_index, COUNT(*) as cnt
        FROM discord_parsed_ideas
        GROUP BY message_id, soft_chunk_index, local_idea_index
        HAVING COUNT(*) > 1
        LIMIT 10
        """,
        fetch_results=True,
    )
    if dup_result:
        checks["duplicate_ideas"] = len(dup_result)
        checks["passed"] = False
        logger.error(f"Found {len(dup_result)} duplicate idea combinations!")
        for row in dup_result[:3]:
            logger.error(
                f"  Duplicate: msg={row[0]}, chunk={row[1]}, local={row[2]}, count={row[3]}"
            )

    # Check parse_status distribution
    status_result = execute_sql(
        """
        SELECT parse_status, COUNT(*) 
        FROM discord_messages 
        GROUP BY parse_status
        ORDER BY COUNT(*) DESC
        """,
        fetch_results=True,
    )
    if status_result:
        for row in status_result:
            status = row[0] or "null"
            checks["parse_status_counts"][status] = row[1]

    # Check for orphan ideas (ideas without matching message)
    orphan_result = execute_sql(
        """
        SELECT COUNT(*) 
        FROM discord_parsed_ideas dpi
        LEFT JOIN discord_messages dm ON dpi.message_id = dm.message_id
        WHERE dm.message_id IS NULL
        """,
        fetch_results=True,
    )
    if orphan_result and orphan_result[0][0] > 0:
        checks["orphan_ideas"] = orphan_result[0][0]
        logger.warning(
            f"Found {checks['orphan_ideas']} orphan ideas (no matching message)"
        )

    return checks


def print_summary(
    build_stats: Dict[str, Any],
    batch_result: Optional[Dict[str, Any]],
    ingest_stats: Optional[Dict[str, Any]],
    integrity: Dict[str, Any],
    dry_run: bool,
) -> None:
    """Print comprehensive summary."""
    print("\n" + "=" * 60)
    print("BATCH BACKFILL SUMMARY")
    print("=" * 60)

    # Build stats
    print("\n📦 BUILD PHASE:")
    print(f"  Messages processed: {build_stats.get('messages_processed', 0)}")
    print(f"  Chunks generated: {build_stats.get('chunks_generated', 0)}")
    print(f"  Bot commands skipped: {build_stats.get('bot_commands_skipped', 0)}")
    print(f"  URL-only skipped: {build_stats.get('url_only_skipped', 0)}")
    print(f"  Bot responses skipped: {build_stats.get('bot_response_skipped', 0)}")
    print(f"  Empty after clean: {build_stats.get('empty_after_clean_skipped', 0)}")

    # Batch job stats
    if batch_result:
        print("\n🚀 BATCH JOB:")
        print(f"  Status: {batch_result.get('status', 'N/A')}")
        counts = batch_result.get("request_counts", {})
        print(f"  Total requests: {counts.get('total', 0)}")
        print(f"  Completed: {counts.get('completed', 0)}")
        print(f"  Failed: {counts.get('failed', 0)}")
    elif dry_run:
        print("\n🚀 BATCH JOB: [DRY RUN - Not submitted]")

    # Ingestion stats
    if ingest_stats:
        print("\n💾 INGESTION:")
        print(f"  Total responses: {ingest_stats.get('total_responses', 0)}")
        print(f"  Successful: {ingest_stats.get('successful', 0)}")
        print(f"  Failed: {ingest_stats.get('failed', 0)}")
        print(f"  Ideas extracted: {ingest_stats.get('ideas_extracted', 0)}")
        print(f"  Messages updated: {ingest_stats.get('messages_updated', 0)}")
    elif dry_run:
        print("\n💾 INGESTION: [DRY RUN - Not executed]")

    # Integrity checks
    print("\n✅ INTEGRITY CHECKS:")
    print(f"  Passed: {'Yes' if integrity.get('passed', False) else 'NO'}")
    print(f"  Duplicate ideas: {integrity.get('duplicate_ideas', 0)}")
    print(f"  Orphan ideas: {integrity.get('orphan_ideas', 0)}")
    print("\n  Parse status distribution:")
    for status, count in integrity.get("parse_status_counts", {}).items():
        print(f"    {status}: {count}")

    print("\n" + "=" * 60)


def main():
    parser = argparse.ArgumentParser(description="Unified batch backfill orchestrator")
    parser.add_argument(
        "--limit",
        type=int,
        default=500,
        help="Maximum messages to process (default: 500)",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="./batch_output",
        help="Directory for batch files (default: ./batch_output)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Build and validate only, don't submit batch",
    )
    parser.add_argument(
        "--skip-verify",
        action="store_true",
        help="Skip schema verification",
    )
    parser.add_argument(
        "--poll-seconds",
        type=int,
        default=30,
        help="Seconds between status polls (default: 30)",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose logging",
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Create output directory
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    batch_input_path = output_dir / f"batch_input_{timestamp}.jsonl"

    print("\n" + "=" * 60)
    print("BATCH BACKFILL ORCHESTRATOR")
    print("=" * 60)
    print(f"Limit: {args.limit} messages")
    print(f"Output dir: {output_dir}")
    print(f"Dry run: {args.dry_run}")
    print("=" * 60)

    # Step 1: Verify schema
    if not args.skip_verify:
        if not verify_schema(verbose=args.verbose):
            logger.error("Schema verification failed. Aborting.")
            sys.exit(1)
    else:
        logger.info("Skipping schema verification (--skip-verify)")

    # Get initial stats
    initial_stats = get_pending_stats()
    logger.info(f"Initial parse_status distribution: {initial_stats}")

    # Step 2: Build batch file
    build_stats = run_build_batch(
        output_path=batch_input_path,
        limit=args.limit,
        mark_skipped=not args.dry_run,  # Only mark in DB if not dry run
    )

    if build_stats.get("chunks_generated", 0) == 0:
        logger.info("No chunks to process. Done.")
        # Create proper integrity structure for early exit
        early_integrity = {
            "passed": True,
            "duplicate_ideas": 0,
            "orphan_ideas": 0,
            "parse_status_counts": get_pending_stats(),
        }
        print_summary(build_stats, None, None, early_integrity, args.dry_run)
        return

    logger.info(f"Built batch file with {build_stats['chunks_generated']} chunks")

    # Step 3: Run batch job
    batch_result = None
    ingest_stats = None

    if args.dry_run:
        logger.info("[DRY RUN] Skipping batch submission and ingestion")
        # Validate the JSONL file
        with open(batch_input_path, "r") as f:
            lines = f.readlines()
            logger.info(f"Batch file has {len(lines)} lines")
            if lines:
                # Check first line is valid JSON
                try:
                    first_req = json.loads(lines[0])
                    custom_id = first_req.get("custom_id", "")
                    logger.info(f"Sample custom_id: {custom_id}")
                    # Verify custom_id format
                    if not custom_id.startswith("msg-") or "-chunk-" not in custom_id:
                        logger.warning(f"Unexpected custom_id format: {custom_id}")
                except json.JSONDecodeError as e:
                    logger.error(f"Invalid JSON in batch file: {e}")
    else:
        batch_result = run_batch_job(
            input_path=batch_input_path,
            output_dir=output_dir,
            poll_seconds=args.poll_seconds,
            dry_run=args.dry_run,
        )

        if batch_result and batch_result.get("status") == "completed":
            # Step 4: Ingest results
            output_path = batch_result.get("output_path")
            if output_path:
                ingest_stats = run_ingestion(
                    output_path=Path(output_path),
                    dry_run=False,
                )

    # Step 5: Integrity checks
    integrity = run_integrity_checks()

    # Step 6: Print summary
    print_summary(build_stats, batch_result, ingest_stats, integrity, args.dry_run)


if __name__ == "__main__":
    main()
