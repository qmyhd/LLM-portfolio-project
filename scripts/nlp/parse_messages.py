#!/usr/bin/env python3
"""
Parse Discord messages using OpenAI structured outputs.

This script processes messages from the database through the LLM parsing pipeline
and stores extracted ideas in discord_parsed_ideas.

Usage:
    # Parse all pending messages
    python scripts/nlp/parse_messages.py

    # Parse specific message
    python scripts/nlp/parse_messages.py --message-id 123456789

    # Parse with limit
    python scripts/nlp/parse_messages.py --limit 100

    # Dry run (don't save to database)
    python scripts/nlp/parse_messages.py --dry-run --limit 10

    # Skip triage (faster but more LLM calls)
    python scripts/nlp/parse_messages.py --skip-triage

    # Force long context model
    python scripts/nlp/parse_messages.py --long-context

    # Use context window for continuation messages
    python scripts/nlp/parse_messages.py --context-window 5 --context-minutes 30
"""

import argparse
import json
import logging
import re
import sys
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional, Tuple

# Add project root to path
sys.path.insert(0, str(__file__).rsplit("scripts", 1)[0].rstrip("/\\"))

from src.db import execute_sql, transaction
from sqlalchemy import text
from src.nlp.openai_parser import (
    process_message,
    estimate_cost,
    set_debug_openai,
    CURRENT_PROMPT_VERSION,
)
from src.nlp.schemas import CURRENT_PROMPT_VERSION
from src.nlp.preclean import (
    merge_short_ideas,
    is_valid_short_action,
    MIN_IDEA_LENGTH,
    should_skip_message,  # SSOT prefilter
)

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# =============================================================================
# CONTINUATION DETECTION
# =============================================================================

# Patterns that suggest a message is a continuation of previous conversation
CONTINUATION_STARTERS = re.compile(
    r"^(but|also|agreed|yeah|same|this|that|and|or|plus|exactly|yep|yup|true|"
    r"right|correct|definitely|absolutely|for sure|totally|indeed|however|"
    r"although|still|anyway|btw|fwiw|imo|imho|tbh|ngl)\b",
    re.IGNORECASE,
)

# Ticker pattern for entity density check
TICKER_PATTERN = re.compile(r"\$[A-Z]{1,6}(?:\.[A-Z]+)?")

# Options keywords that suggest trading context (calls, puts, strike, expiry)
OPTIONS_KEYWORDS = re.compile(
    r"\b(calls?|puts?|strike|expiry|exp\b|0dte|dte\b|premium|spread|straddle|strangle|iron\s?condor)\b",
    re.IGNORECASE,
)


def is_low_entity_density(text: str, threshold: int = 1) -> bool:
    """
    Check if message has low ticker/entity density.

    Args:
        text: Message content
        threshold: Minimum tickers to NOT be considered low density

    Returns:
        True if message has fewer tickers than threshold
    """
    tickers = TICKER_PATTERN.findall(text)
    return len(tickers) < threshold


def is_continuation_message(text: str) -> bool:
    """
    Check if message appears to be a continuation of previous conversation.

    Args:
        text: Message content

    Returns:
        True if message starts with continuation patterns
    """
    text = text.strip()
    return bool(CONTINUATION_STARTERS.match(text))


def has_options_without_ticker(text: str) -> bool:
    """
    Check if message has options keywords but no ticker symbols.

    These messages likely refer to a ticker mentioned in prior context.

    Args:
        text: Message content

    Returns:
        True if options keywords present without ticker
    """
    has_options = bool(OPTIONS_KEYWORDS.search(text))
    has_ticker = not is_low_entity_density(text, threshold=1)
    return has_options and not has_ticker


def needs_context(text: str) -> bool:
    """
    Determine if a message needs context from previous messages.

    A message needs context if:
    - It has low entity density (few/no tickers) AND is short, OR
    - It starts with continuation words, OR
    - It has options keywords (call, put, strike) but no ticker

    Args:
        text: Message content

    Returns:
        True if message would benefit from context
    """
    is_short = len(text) < 200
    low_density = is_low_entity_density(text)
    is_continuation = is_continuation_message(text)
    options_no_ticker = has_options_without_ticker(text)

    return (low_density and is_short) or is_continuation or options_no_ticker


def fetch_context_messages(
    channel: str,
    before_timestamp: str,
    window_size: int = 5,
    window_minutes: int = 30,
) -> List[Dict[str, Any]]:
    """
    Fetch previous messages from same channel within time window.

    Args:
        channel: Channel ID to fetch from
        before_timestamp: ISO timestamp of current message
        window_size: Maximum number of previous messages
        window_minutes: Maximum age of context messages in minutes

    Returns:
        List of message dicts, oldest first
    """
    if not channel or not before_timestamp:
        return []

    # Parse timestamp and calculate window (ensure timezone aware)
    try:
        ts = before_timestamp.replace("Z", "+00:00")
        current_time = datetime.fromisoformat(ts)
        # Ensure timezone aware
        if current_time.tzinfo is None:
            current_time = current_time.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return []

    min_time = current_time - timedelta(minutes=window_minutes)

    query = """
        SELECT message_id, content, author, created_at
        FROM discord_messages
        WHERE channel = :channel
        AND created_at < :before_time
        AND created_at > :min_time
        AND content IS NOT NULL
        AND LENGTH(content) > 5
        ORDER BY created_at DESC
        LIMIT :limit
    """

    params = {
        "channel": str(channel),
        "before_time": current_time,
        "min_time": min_time,
        "limit": window_size,
    }

    result = execute_sql(query, params=params, fetch_results=True)

    if not result:
        return []

    # Reverse to get oldest first
    messages = [
        {
            "message_id": row[0],
            "content": row[1],
            "author": row[2],
            "created_at": row[3].isoformat() if row[3] else None,
        }
        for row in result
    ]
    return list(reversed(messages))


def build_context_enhanced_input(
    current_content: str,
    context_messages: List[Dict[str, Any]],
) -> Tuple[str, List[str]]:
    """
    Build LLM input with context from previous messages.

    Args:
        current_content: Current message content
        context_messages: List of previous messages (oldest first)

    Returns:
        Tuple of (enhanced_input, context_message_ids)
    """
    if not context_messages:
        return current_content, []

    context_parts = []
    context_ids = []

    for msg in context_messages:
        author = msg.get("author", "unknown")
        content = msg.get("content", "")
        context_parts.append(f"[{author}]: {content}")
        context_ids.append(msg["message_id"])

    context_text = "\n".join(context_parts)

    enhanced_input = f"""CONTEXT (previous messages):
{context_text}
---
CURRENT MESSAGE:
{current_content}"""

    return enhanced_input, context_ids


# =============================================================================
# POST-PARSE CLEANUP - Short idea handling imported from preclean.py
# merge_short_ideas() and is_valid_short_action() are imported at top
# =============================================================================


def count_bullet_lines(text: str) -> int:
    """
    Count bullet lines in message (lines starting with - or •).

    Args:
        text: The message text

    Returns:
        Number of bullet lines detected
    """
    lines = text.split("\n")
    bullet_count = sum(1 for line in lines if line.strip().startswith(("-", "•")))
    return bullet_count


def get_pending_messages(
    limit: Optional[int] = None,
    message_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Fetch messages pending parsing from the database.

    Args:
        limit: Maximum number of messages to fetch
        message_id: Specific message ID to fetch (always string)

    Returns:
        List of message dicts
    """
    # Normalize message_id to string (belt + suspenders)
    if message_id is not None:
        message_id = str(message_id).strip()
        if not message_id:
            message_id = None

    if message_id:
        query = """
            SELECT 
                message_id,
                content,
                author,
                channel,
                created_at
            FROM discord_messages
            WHERE message_id = CAST(:message_id AS text)
        """
        params = {"message_id": str(message_id)}
    else:
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
            AND LENGTH(content) > 10
            ORDER BY created_at DESC
        """
        if limit:
            query += f" LIMIT {limit}"
        params = {}

    result = execute_sql(query, params=params, fetch_results=True)

    if not result:
        return []

    return [
        {
            "message_id": row[0],
            "content": row[1],
            "author": row[2],
            "channel": (
                str(row[3]) if row[3] else None
            ),  # Column is 'channel', not 'channel_id'
            "created_at": row[4].isoformat() if row[4] else None,
        }
        for row in result
    ]


def get_candidate_messages_by_size() -> Dict[str, Optional[Dict[str, Any]]]:
    """
    Find 3 candidate messages by content size: short, medium, mega.

    Returns pending messages at different length thresholds for testing:
    - short: A message near minimum length (~50-200 chars)
    - medium: A message around ~2000 chars
    - mega: The largest pending message

    Usage:
        candidates = get_candidate_messages_by_size()
        print(f"Short: {candidates['short']}")
        print(f"Medium: {candidates['medium']}")
        print(f"Mega: {candidates['mega']}")

    Returns:
        Dict with keys 'short', 'medium', 'mega', each containing message dict or None
    """
    candidates = {"short": None, "medium": None, "mega": None}

    # Query for short message (smallest pending, min 20 chars)
    short_query = """
        SELECT 
            message_id,
            content,
            LENGTH(content) as content_length,
            author,
            channel,
            created_at
        FROM discord_messages
        WHERE parse_status = 'pending'
        AND content IS NOT NULL
        AND LENGTH(content) BETWEEN 20 AND 200
        ORDER BY LENGTH(content) ASC
        LIMIT 1
    """
    short_result = execute_sql(short_query, fetch_results=True)
    if short_result:
        row = short_result[0]
        candidates["short"] = {
            "message_id": row[0],
            "content": row[1],
            "content_length": row[2],
            "author": row[3],
            "channel": str(row[4]) if row[4] else None,
            "created_at": row[5].isoformat() if row[5] else None,
        }

    # Query for medium message (~2000 chars, allow range 1500-2500)
    medium_query = """
        SELECT 
            message_id,
            content,
            LENGTH(content) as content_length,
            author,
            channel,
            created_at
        FROM discord_messages
        WHERE parse_status = 'pending'
        AND content IS NOT NULL
        AND LENGTH(content) BETWEEN 1500 AND 2500
        ORDER BY ABS(LENGTH(content) - 2000) ASC
        LIMIT 1
    """
    medium_result = execute_sql(medium_query, fetch_results=True)
    if medium_result:
        row = medium_result[0]
        candidates["medium"] = {
            "message_id": row[0],
            "content": row[1],
            "content_length": row[2],
            "author": row[3],
            "channel": str(row[4]) if row[4] else None,
            "created_at": row[5].isoformat() if row[5] else None,
        }

    # Query for mega message (largest pending)
    mega_query = """
        SELECT 
            message_id,
            content,
            LENGTH(content) as content_length,
            author,
            channel,
            created_at
        FROM discord_messages
        WHERE parse_status = 'pending'
        AND content IS NOT NULL
        ORDER BY LENGTH(content) DESC
        LIMIT 1
    """
    mega_result = execute_sql(mega_query, fetch_results=True)
    if mega_result:
        row = mega_result[0]
        candidates["mega"] = {
            "message_id": row[0],
            "content": row[1],
            "content_length": row[2],
            "author": row[3],
            "channel": str(row[4]) if row[4] else None,
            "created_at": row[5].isoformat() if row[5] else None,
        }

    return candidates


def print_candidate_messages():
    """
    Print candidate messages by size for manual testing.

    CLI helper to quickly identify test messages:
        python -c "from scripts.nlp.parse_messages import print_candidate_messages; print_candidate_messages()"
    """
    candidates = get_candidate_messages_by_size()

    print("\n" + "=" * 60)
    print("📊 CANDIDATE MESSAGES BY SIZE (pending parse)")
    print("=" * 60)

    for size_label, msg in candidates.items():
        print(f"\n🔹 {size_label.upper()}:")
        if msg:
            print(f"   message_id: {msg['message_id']}")
            print(f"   length: {msg['content_length']} chars")
            print(f"   author: {msg['author']}")
            preview = msg["content"][:100].replace("\n", " ")
            print(f"   preview: {preview}...")
        else:
            print("   (no matching message found)")

    print("\n" + "=" * 60)


def save_parsed_ideas_with_cleanup(
    message_id: str,
    ideas: List[Dict[str, Any]],
    status: str,
    error_reason: Optional[str] = None,
) -> int:
    """
    Save parsed ideas with reparse safety - delete existing, then insert ATOMICALLY.

    CRITICAL: This function implements the "reparse safety" rule using a SINGLE transaction:
    - Acquires advisory lock on message_id (pg_advisory_xact_lock)
    - Deletes ALL existing ideas for this message_id
    - Inserts fresh ideas
    - Updates parse_status on discord_messages
    - Lock is released when transaction commits

    All operations happen in the SAME transaction, ensuring:
    - Two concurrent parses of the same message_id never interleave
    - No orphaned ideas if process crashes mid-operation
    - Automatic rollback on any error

    Args:
        message_id: The message ID being parsed
        ideas: List of idea dicts from process_message()
        status: Parse status (ok, error, noise, skipped)
        error_reason: Error message if status='error'

    Returns:
        Number of ideas inserted
    """
    if not message_id:
        return 0

    # Convert message_id to a numeric lock key (hash for non-numeric IDs)
    try:
        lock_key = int(message_id)
    except ValueError:
        # Hash string message_id to int64 range
        lock_key = hash(message_id) & 0x7FFFFFFFFFFFFFFF

    inserted = 0

    try:
        # Use transaction context to ensure atomicity
        with transaction() as conn:
            # Step 0: Acquire advisory lock (held until transaction ends)
            conn.execute(
                text("SELECT pg_advisory_xact_lock(:lock_key)"), {"lock_key": lock_key}
            )
            logger.debug(f"Acquired advisory lock for message {message_id}")

            # Step 1: Delete existing ideas for this message
            conn.execute(
                text(
                    "DELETE FROM discord_parsed_ideas WHERE message_id = CAST(:message_id AS text)"
                ),
                {"message_id": str(message_id)},
            )
            logger.debug(f"Deleted existing ideas for message {message_id}")

            # Step 2: Insert fresh ideas (if any)
            for idea in ideas:
                try:
                    insert_query = text(
                        """
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
                    )

                    # For live parsing, soft_chunk_index=0, local_idea_index=idea_index
                    params = {
                        "message_id": str(idea["message_id"]),
                        "idea_index": idea["idea_index"],
                        "soft_chunk_index": idea.get("soft_chunk_index", 0),
                        "local_idea_index": idea.get(
                            "local_idea_index", idea["idea_index"]
                        ),
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

                    conn.execute(insert_query, params)
                    inserted += 1

                except Exception as e:
                    logger.error(f"Failed to insert idea: {e}")
                    raise  # Re-raise to rollback entire transaction

            # Step 3: Update message status (inside same transaction)
            conn.execute(
                text(
                    """
                    UPDATE discord_messages
                    SET parse_status = :status,
                        prompt_version = :prompt_version,
                        error_reason = :error_reason
                    WHERE message_id = CAST(:message_id AS text)
                """
                ),
                {
                    "message_id": str(message_id),
                    "status": status,
                    "prompt_version": CURRENT_PROMPT_VERSION,
                    "error_reason": error_reason,
                },
            )

        # Transaction committed, lock released
        return inserted

    except Exception as e:
        logger.error(f"Failed to save ideas for message {message_id}: {e}")
        raise


def save_parsed_ideas(ideas: List[Dict[str, Any]]) -> int:
    """
    Save parsed ideas to discord_parsed_ideas table.

    DEPRECATED: Use save_parsed_ideas_with_cleanup() for reparse safety.
    This function is kept for backwards compatibility but uses UPSERT
    which can leave stale rows on reparse.

    Args:
        ideas: List of idea dicts from process_message()

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
                ON CONFLICT (message_id, soft_chunk_index, local_idea_index) DO UPDATE SET
                    idea_index = EXCLUDED.idea_index,
                    idea_text = EXCLUDED.idea_text,
                    idea_summary = EXCLUDED.idea_summary,
                    context_summary = EXCLUDED.context_summary,
                    primary_symbol = EXCLUDED.primary_symbol,
                    symbols = EXCLUDED.symbols,
                    instrument = EXCLUDED.instrument,
                    direction = EXCLUDED.direction,
                    action = EXCLUDED.action,
                    time_horizon = EXCLUDED.time_horizon,
                    trigger_condition = EXCLUDED.trigger_condition,
                    levels = EXCLUDED.levels,
                    option_type = EXCLUDED.option_type,
                    strike = EXCLUDED.strike,
                    expiry = EXCLUDED.expiry,
                    premium = EXCLUDED.premium,
                    labels = EXCLUDED.labels,
                    label_scores = EXCLUDED.label_scores,
                    is_noise = EXCLUDED.is_noise,
                    model = EXCLUDED.model,
                    prompt_version = EXCLUDED.prompt_version,
                    confidence = EXCLUDED.confidence,
                    raw_json = EXCLUDED.raw_json,
                    parsed_at = NOW()
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

            execute_sql(query, params=params)
            inserted += 1

        except Exception as e:
            logger.error(f"Failed to insert idea: {e}")

    return inserted


def update_message_status(
    message_id: str, status: str, error_reason: Optional[str] = None
) -> None:
    """
    Update the parse_status on discord_messages.

    Args:
        message_id: Message ID to update (string)
        status: New status (ok, error, skipped, noise)
        error_reason: Error message if status='error'
    """
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


def parse_single_message(
    message: Dict[str, Any],
    skip_triage: bool = False,
    force_long_context: bool = False,
    dry_run: bool = False,
    context_window: int = 0,
    context_minutes: int = 30,
) -> Dict[str, Any]:
    """
    Parse a single message and optionally save results.

    Args:
        message: Message dict from get_pending_messages()
        skip_triage: Skip the triage step
        force_long_context: Use long context model
        dry_run: Don't save to database
        context_window: Number of previous messages to include (0=disabled)
        context_minutes: Maximum age of context messages in minutes

    Returns:
        Result dict with status, ideas count, etc.
    """
    message_id = message["message_id"]
    content = message["content"]
    channel = message.get("channel")
    created_at = message.get("created_at")

    # ==========================================================================
    # PRE-FILTER: SINGLE SOURCE OF TRUTH (from preclean.should_skip_message)
    # ==========================================================================
    # Build message_meta for bot detection
    message_meta = {
        "author": message.get("author"),
        "is_bot": message.get("is_bot", False),
    }

    should_skip, skip_reason = should_skip_message(content, message_meta)
    if should_skip:
        logger.info(f"Skipping message {message_id}: {skip_reason}")
        if not dry_run:
            execute_sql(
                "UPDATE discord_messages SET parse_status = 'skipped', error_reason = :reason WHERE message_id = :mid",
                params={"mid": str(message_id), "reason": skip_reason},
            )
        return {"status": "skipped", "ideas_count": 0, "reason": skip_reason}

    # Check if message needs context enhancement
    context_ids = []
    llm_input = content

    if context_window > 0 and needs_context(content):
        context_messages = fetch_context_messages(
            channel=channel,
            before_timestamp=created_at,
            window_size=context_window,
            window_minutes=context_minutes,
        )

        if context_messages:
            llm_input, context_ids = build_context_enhanced_input(
                content, context_messages
            )
            logger.info(f"  Added {len(context_ids)} context messages")

    logger.info(f"Processing message {message_id} ({len(content)} chars)")

    try:
        # Pass message_meta for double-checking in process_message
        result = process_message(
            text=llm_input,  # Use context-enhanced input
            message_id=message_id,
            author_id=message.get("author"),
            channel_id=channel,
            created_at=created_at,
            skip_triage=skip_triage,
            force_long_context=force_long_context,
            message_meta=message_meta,
        )

        status = result["status"]
        ideas = result["ideas"]
        model = result["model"]
        error_reason = result.get("error_reason")

        # Post-parse cleanup: merge short idea fragments
        if ideas and len(ideas) > 1:
            original_count = len(ideas)
            ideas = merge_short_ideas(ideas)
            if len(ideas) != original_count:
                logger.info(f"  Merged short ideas: {original_count} → {len(ideas)}")

        # Add context_message_ids to raw_json for each idea
        if context_ids:
            for idea in ideas:
                raw_json = idea.get("raw_json", {})
                if isinstance(raw_json, str):
                    try:
                        raw_json = json.loads(raw_json)
                    except json.JSONDecodeError:
                        raw_json = {}
                raw_json["context_message_ids"] = context_ids
                idea["raw_json"] = raw_json

        logger.info(f"  Status: {status}, Ideas: {len(ideas)}, Model: {model}")

        if not dry_run:
            # Use the reparse-safe cleanup function (delete + insert + status update)
            inserted = save_parsed_ideas_with_cleanup(
                message_id=message_id,
                ideas=ideas,
                status=status,
                error_reason=error_reason,
            )
            logger.info(f"  Inserted {inserted} ideas (deleted old ideas first)")
        else:
            logger.info(f"  [DRY RUN] Would insert {len(ideas)} ideas")
            if ideas:
                for idea in ideas[:3]:  # Show first 3
                    symbol = idea.get("primary_symbol", "N/A")
                    instrument = idea.get("instrument", "equity")
                    logger.info(
                        f"    - {symbol} ({instrument}): {idea['idea_text'][:70]}..."
                    )

        return {
            "message_id": message_id,
            "status": status,
            "ideas_count": len(ideas),
            "model": model,
            "error_reason": error_reason,
        }

    except Exception as e:
        logger.error(f"  Error: {e}")
        if not dry_run:
            update_message_status(message_id, "error", str(e))
        return {
            "message_id": message_id,
            "status": "error",
            "ideas_count": 0,
            "model": None,
            "error_reason": str(e),
        }


def main():
    parser = argparse.ArgumentParser(
        description="Parse Discord messages using OpenAI structured outputs"
    )
    parser.add_argument(
        "--message-id", type=str, help="Parse a specific message by ID (string)"
    )
    parser.add_argument(
        "--limit", type=int, default=None, help="Maximum number of messages to process"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Don't save results to database"
    )
    parser.add_argument(
        "--skip-triage",
        action="store_true",
        help="Skip the triage step (faster but more LLM calls)",
    )
    parser.add_argument(
        "--long-context", action="store_true", help="Force use of long context model"
    )
    parser.add_argument(
        "--estimate-cost", action="store_true", help="Only estimate cost, don't process"
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Enable verbose logging"
    )
    parser.add_argument(
        "--debug-openai",
        action="store_true",
        help="Enable OpenAI response debugging (logs raw response structure on parse failures)",
    )
    # Context window arguments
    parser.add_argument(
        "--context-window",
        type=int,
        default=0,
        help="Number of previous messages to include for context (0=disabled)",
    )
    parser.add_argument(
        "--context-minutes",
        type=int,
        default=30,
        help="Maximum age of context messages in minutes (default: 30)",
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    if args.debug_openai:
        set_debug_openai(True)
        logger.info("OpenAI debug mode enabled")

    # Log context window settings if enabled
    if args.context_window > 0:
        logger.info(
            f"Context window enabled: {args.context_window} messages within {args.context_minutes} minutes"
        )

    # Fetch messages
    logger.info("Fetching messages...")
    messages = get_pending_messages(
        limit=args.limit,
        message_id=args.message_id,
    )

    if not messages:
        logger.info("No pending messages found")
        return

    logger.info(f"Found {len(messages)} messages to process")

    # Cost estimation mode
    if args.estimate_cost:
        total_cost = 0.0
        total_chunks = 0
        for msg in messages:
            est = estimate_cost(msg["content"], include_triage=not args.skip_triage)
            total_cost += est["cost_usd"]
            total_chunks += est["num_chunks"]

        logger.info(f"Estimated cost: ${total_cost:.4f}")
        logger.info(f"Total chunks: {total_chunks}")
        logger.info(f"Avg chunks/message: {total_chunks / len(messages):.1f}")
        return

    # Process messages
    results = {
        "ok": 0,
        "noise": 0,
        "skipped": 0,
        "error": 0,
    }
    total_ideas = 0

    for i, message in enumerate(messages, 1):
        logger.info(f"\n[{i}/{len(messages)}]")

        result = parse_single_message(
            message,
            skip_triage=args.skip_triage,
            force_long_context=args.long_context,
            dry_run=args.dry_run,
            context_window=args.context_window,
            context_minutes=args.context_minutes,
        )

        results[result["status"]] += 1
        total_ideas += result["ideas_count"]

    # Summary
    logger.info("\n" + "=" * 50)
    logger.info("SUMMARY")
    logger.info("=" * 50)
    logger.info(f"Messages processed: {len(messages)}")
    logger.info(f"  OK: {results['ok']}")
    logger.info(f"  Noise: {results['noise']}")
    logger.info(f"  Skipped: {results['skipped']}")
    logger.info(f"  Error: {results['error']}")
    logger.info(f"Total ideas extracted: {total_ideas}")
    if results["ok"] > 0:
        logger.info(f"Avg ideas per message: {total_ideas / results['ok']:.1f}")


if __name__ == "__main__":
    main()
