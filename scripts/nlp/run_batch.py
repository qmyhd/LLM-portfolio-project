#!/usr/bin/env python3
"""
End-to-end Batch API orchestration for OpenAI parsing.

This script handles the complete batch processing workflow:
1. Upload JSONL input file to OpenAI
2. Create batch job
3. Poll until terminal status (completed/failed/cancelled/expired)
4. Download output JSONL (and error JSONL if present)
5. Call ingest_batch logic to save to database

Usage:
    # Run full batch workflow
    python scripts/nlp/run_batch.py --input batch_requests.jsonl

    # Resume an existing batch (skip upload/create)
    python scripts/nlp/run_batch.py --resume-batch-id batch_abc123

    # Custom poll interval (default: 30 seconds)
    python scripts/nlp/run_batch.py --input batch.jsonl --poll-seconds 60

    # Dry run (don't ingest to database)
    python scripts/nlp/run_batch.py --input batch.jsonl --dry-run

    # Verbose output
    python scripts/nlp/run_batch.py --input batch.jsonl --verbose

Batch API Notes:
    - Batch jobs complete within 24 hours (usually faster)
    - 50% cost discount vs synchronous API
    - Terminal states: completed, failed, cancelled, expired
    - Output files auto-deleted after 24 hours
"""

import argparse
import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Add project root to path
sys.path.insert(0, str(__file__).rsplit("scripts", 1)[0].rstrip("/\\"))

from openai import OpenAI

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Terminal batch statuses
TERMINAL_STATUSES = {"completed", "failed", "cancelled", "expired"}


def upload_batch_file(client: OpenAI, input_path: Path) -> str:
    """
    Upload JSONL file to OpenAI for batch processing.

    Args:
        client: OpenAI client
        input_path: Path to input JSONL file

    Returns:
        File ID of uploaded file
    """
    logger.info(f"Uploading {input_path} to OpenAI...")

    with open(input_path, "rb") as f:
        file_obj = client.files.create(file=f, purpose="batch")

    logger.info(f"Uploaded file: {file_obj.id}")
    return file_obj.id


def create_batch(
    client: OpenAI,
    input_file_id: str,
    description: str = "Discord message parsing batch",
) -> str:
    """
    Create a new batch job.

    Args:
        client: OpenAI client
        input_file_id: ID of uploaded input file
        description: Description for the batch

    Returns:
        Batch ID
    """
    # BATCH API ENDPOINT DECISION:
    # We use /v1/chat/completions because OpenAI Batch API only supports:
    # - /v1/chat/completions (Chat Completions)
    # - /v1/embeddings (Embeddings)
    #
    # The Responses API (/v1/responses) is NOT supported for batch processing.
    # Our live parser uses Responses API for structured outputs, but batch must
    # use Chat Completions with JSON schema in response_format.
    # Both produce identical MessageParseResult output.
    BATCH_ENDPOINT = "/v1/chat/completions"

    logger.info(f"Creating batch job with input file {input_file_id}...")
    logger.info(f"Using batch endpoint: {BATCH_ENDPOINT}")

    batch = client.batches.create(
        input_file_id=input_file_id,
        endpoint=BATCH_ENDPOINT,
        completion_window="24h",
        metadata={
            "description": description,
            "created_at": datetime.now(timezone.utc).isoformat(),
        },
    )

    logger.info(f"Created batch: {batch.id} (status: {batch.status})")
    return batch.id


def poll_batch_status(
    client: OpenAI,
    batch_id: str,
    poll_seconds: int = 30,
    verbose: bool = False,
) -> dict:
    """
    Poll batch status until terminal state.

    Args:
        client: OpenAI client
        batch_id: Batch ID to poll
        poll_seconds: Seconds between polls
        verbose: Print detailed progress

    Returns:
        Final batch object as dict
    """
    logger.info(f"Polling batch {batch_id} every {poll_seconds} seconds...")

    while True:
        batch = client.batches.retrieve(batch_id)

        status = batch.status
        counts = batch.request_counts

        if verbose:
            logger.info(
                f"Status: {status} | "
                f"Total: {counts.total} | "
                f"Completed: {counts.completed} | "
                f"Failed: {counts.failed}"
            )
        else:
            # Progress bar style
            if counts.total > 0:
                pct = (counts.completed + counts.failed) / counts.total * 100
                logger.info(f"Batch {batch_id}: {status} ({pct:.1f}% done)")
            else:
                logger.info(f"Batch {batch_id}: {status}")

        if status in TERMINAL_STATUSES:
            logger.info(f"Batch reached terminal status: {status}")
            return {
                "id": batch.id,
                "status": batch.status,
                "input_file_id": batch.input_file_id,
                "output_file_id": batch.output_file_id,
                "error_file_id": batch.error_file_id,
                "request_counts": {
                    "total": counts.total,
                    "completed": counts.completed,
                    "failed": counts.failed,
                },
                "created_at": batch.created_at,
                "completed_at": getattr(batch, "completed_at", None),
                "failed_at": getattr(batch, "failed_at", None),
                "cancelled_at": getattr(batch, "cancelled_at", None),
                "expired_at": getattr(batch, "expired_at", None),
            }

        time.sleep(poll_seconds)


def download_batch_output(
    client: OpenAI,
    file_id: str,
    output_path: Path,
) -> Path:
    """
    Download batch output file.

    Args:
        client: OpenAI client
        file_id: File ID to download
        output_path: Path to save file

    Returns:
        Path to downloaded file
    """
    logger.info(f"Downloading file {file_id} to {output_path}...")

    content = client.files.content(file_id)

    with open(output_path, "wb") as f:
        f.write(content.read())

    logger.info(f"Downloaded {output_path.stat().st_size} bytes")
    return output_path


def run_ingest(
    output_path: Path,
    error_path: Optional[Path] = None,
    dry_run: bool = False,
    verbose: bool = False,
) -> dict:
    """
    Run ingestion on batch output.

    Args:
        output_path: Path to output JSONL
        error_path: Path to error JSONL (optional)
        dry_run: If True, don't save to database
        verbose: Print detailed output

    Returns:
        Ingestion statistics
    """
    # Import here to avoid circular imports
    from scripts.nlp.ingest_batch import (
        load_batch_output,
        process_batch_responses,
    )

    logger.info(f"Ingesting batch output from {output_path}...")

    # Load responses
    responses = load_batch_output(output_path)
    logger.info(f"Loaded {len(responses)} responses")

    if not responses:
        return {"success": True, "ideas_inserted": 0, "messages_updated": 0}

    # Process responses
    stats = process_batch_responses(
        responses=responses,
        dry_run=dry_run,
        verbose=verbose,
    )

    # Report errors if present
    if error_path and error_path.exists():
        with open(error_path, "r") as f:
            error_count = sum(1 for _ in f)
        if error_count > 0:
            logger.warning(f"Batch had {error_count} errors (see {error_path})")
            stats["error_count"] = error_count

    return stats


def main():
    parser = argparse.ArgumentParser(
        description="End-to-end OpenAI Batch API orchestration",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--input",
        type=Path,
        help="Path to input JSONL file (from build_batch.py)",
    )
    parser.add_argument(
        "--resume-batch-id",
        type=str,
        help="Resume polling an existing batch (skip upload/create)",
    )
    parser.add_argument(
        "--poll-seconds",
        type=int,
        default=30,
        help="Seconds between status polls (default: 30)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/batch_outputs"),
        help="Directory to save output files (default: data/batch_outputs)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Don't save to database, just download outputs",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Print detailed progress",
    )
    parser.add_argument(
        "--skip-ingest",
        action="store_true",
        help="Skip database ingestion (just poll and download)",
    )

    args = parser.parse_args()

    # Validate args
    if not args.resume_batch_id and not args.input:
        parser.error("Either --input or --resume-batch-id is required")

    if args.input and not args.input.exists():
        parser.error(f"Input file not found: {args.input}")

    # Create output directory
    args.output_dir.mkdir(parents=True, exist_ok=True)

    # Initialize client
    client = OpenAI()

    try:
        # Step 1 & 2: Upload and create batch (or resume)
        if args.resume_batch_id:
            batch_id = args.resume_batch_id
            logger.info(f"Resuming batch: {batch_id}")
        else:
            # Upload input file
            input_file_id = upload_batch_file(client, args.input)

            # Create batch
            batch_id = create_batch(
                client,
                input_file_id,
                description=f"Parse {args.input.name}",
            )

        # Step 3: Poll until done
        batch_result = poll_batch_status(
            client,
            batch_id,
            poll_seconds=args.poll_seconds,
            verbose=args.verbose,
        )

        # Check status
        if batch_result["status"] != "completed":
            logger.error(
                f"Batch did not complete successfully: {batch_result['status']}"
            )
            if batch_result["status"] == "failed":
                logger.error("Check error file for details")
            sys.exit(1)

        # Step 4: Download outputs
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = args.output_dir / f"batch_output_{timestamp}.jsonl"
        error_path = args.output_dir / f"batch_errors_{timestamp}.jsonl"

        # Download main output
        if batch_result["output_file_id"]:
            download_batch_output(client, batch_result["output_file_id"], output_path)
        else:
            logger.error("No output file available")
            sys.exit(1)

        # Download errors if present
        if batch_result["error_file_id"]:
            download_batch_output(client, batch_result["error_file_id"], error_path)

        # Step 5: Ingest to database
        if not args.skip_ingest:
            stats = run_ingest(
                output_path,
                error_path if error_path.exists() else None,
                dry_run=args.dry_run,
                verbose=args.verbose,
            )

            logger.info("=== Batch Complete ===")
            logger.info(f"Batch ID: {batch_id}")
            logger.info(f"Status: {batch_result['status']}")
            logger.info(f"Total requests: {batch_result['request_counts']['total']}")
            logger.info(f"Completed: {batch_result['request_counts']['completed']}")
            logger.info(f"Failed: {batch_result['request_counts']['failed']}")
            logger.info(f"Ideas inserted: {stats.get('ideas_inserted', 0)}")
            logger.info(f"Messages updated: {stats.get('messages_updated', 0)}")
            if args.dry_run:
                logger.info("(dry run - no database changes)")
        else:
            logger.info("=== Batch Download Complete ===")
            logger.info(f"Output: {output_path}")
            if error_path.exists():
                logger.info(f"Errors: {error_path}")

    except KeyboardInterrupt:
        logger.warning("Interrupted by user")
        logger.info(
            f"To resume: python scripts/nlp/run_batch.py --resume-batch-id {batch_id}"
        )
        sys.exit(130)

    except Exception as e:
        logger.error(f"Batch processing failed: {e}")
        raise


if __name__ == "__main__":
    main()
