"""
Incremental Discord message ingestion with cursor-based tracking.

Fetches only messages newer than the last-ingested snowflake per channel,
writes them via the existing idempotent upsert in logging_utils, and
advances the cursor only after successful writes.

Key features:
- Per-channel cursor stored in discord_ingestion_state
- Content-hash dedup via SHA-256 of normalised text
- Concurrent-run guard with 30-minute staleness override
- Dry-run mode for safe previewing
- Full statistics via IngestResult dataclass
"""

import asyncio
import hashlib
import logging
import re
import time
from dataclasses import dataclass, field

import discord

logger = logging.getLogger(__name__)

# ── Staleness threshold for concurrent-run guard ─────────────────────
STALE_RUN_MINUTES = 30


# ── Dataclass for per-channel results ────────────────────────────────
@dataclass
class IngestResult:
    channel_id: str
    channel_name: str = ""
    messages_fetched: int = 0
    messages_new: int = 0
    messages_duplicate: int = 0
    messages_skipped_bot: int = 0
    cursor_before: str | None = None
    cursor_after: str | None = None
    error: str | None = None
    dry_run: bool = False
    duration_seconds: float = 0.0


# ── Content hashing ──────────────────────────────────────────────────
_WHITESPACE_RE = re.compile(r"\s+")


def compute_content_hash(content: str) -> str:
    """SHA-256 of normalised content (strip, collapse whitespace, lowercase).

    Returns the hex digest.  Empty/whitespace-only content hashes the
    empty string so we always get a deterministic value.
    """
    normalised = _WHITESPACE_RE.sub(" ", content.strip()).lower()
    return hashlib.sha256(normalised.encode("utf-8")).hexdigest()


# ── Cursor helpers ───────────────────────────────────────────────────

def get_cursor(channel_id: str) -> str | None:
    """Load last_message_id from discord_ingestion_state.

    Returns None when no state exists or the cursor is NULL.
    """
    from src.db import execute_sql

    rows = execute_sql(
        "SELECT last_message_id FROM discord_ingestion_state WHERE channel_id = :cid",
        {"cid": channel_id},
        fetch_results=True,
    )
    if rows and rows[0][0]:
        return rows[0][0]
    return None


def set_cursor(
    channel_id: str,
    channel_name: str,
    last_message_id: str,
    last_message_ts,
    new_count: int,
    dupe_count: int,
) -> None:
    """Upsert cursor state after a successful ingestion run."""
    from src.db import execute_sql

    execute_sql(
        """
        INSERT INTO discord_ingestion_state
            (channel_id, channel_name, last_message_id, last_message_ts,
             messages_total, last_run_at, last_run_new, last_run_dupes, status)
        VALUES
            (:cid, :cname, :mid, :mts,
             :new_count, NOW(), :new_count, :dupe_count, 'idle')
        ON CONFLICT (channel_id) DO UPDATE SET
            channel_name    = EXCLUDED.channel_name,
            last_message_id = EXCLUDED.last_message_id,
            last_message_ts = EXCLUDED.last_message_ts,
            messages_total  = discord_ingestion_state.messages_total + EXCLUDED.last_run_new,
            last_run_at     = NOW(),
            last_run_new    = EXCLUDED.last_run_new,
            last_run_dupes  = EXCLUDED.last_run_dupes,
            status          = 'idle',
            error_message   = NULL
        """,
        {
            "cid": channel_id,
            "cname": channel_name,
            "mid": last_message_id,
            "mts": last_message_ts,
            "new_count": new_count,
            "dupe_count": dupe_count,
        },
    )


def _mark_channel_status(channel_id: str, status: str, error_message: str | None = None) -> None:
    """Set channel status (running / error / idle)."""
    from src.db import execute_sql

    execute_sql(
        """
        INSERT INTO discord_ingestion_state (channel_id, status, error_message)
        VALUES (:cid, :status, :err)
        ON CONFLICT (channel_id) DO UPDATE SET
            status = EXCLUDED.status,
            error_message = EXCLUDED.error_message
        """,
        {"cid": channel_id, "status": status, "err": error_message},
    )


def check_channel_not_running(channel_id: str) -> bool:
    """Return True if safe to start a new run for this channel.

    Safe when:
    - No state row exists
    - Status is 'idle' or 'error'
    - Status is 'running' but updated_at is older than STALE_RUN_MINUTES
    """
    from src.db import execute_sql

    rows = execute_sql(
        """
        SELECT status, updated_at,
               EXTRACT(EPOCH FROM (NOW() - updated_at)) / 60 AS age_minutes
        FROM discord_ingestion_state
        WHERE channel_id = :cid
        """,
        {"cid": channel_id},
        fetch_results=True,
    )
    if not rows:
        return True  # No state → safe

    status, _updated_at, age_minutes = rows[0]
    if status != "running":
        return True
    # Running but stale → override
    if age_minutes is not None and age_minutes > STALE_RUN_MINUTES:
        logger.warning(
            "Channel %s has stale 'running' state (%.1f min old) — overriding",
            channel_id,
            age_minutes,
        )
        return True
    return False


# ── Core ingestion ───────────────────────────────────────────────────

async def ingest_channel(
    bot,
    channel_id: str,
    *,
    dry_run: bool = False,
    max_pages: int | None = None,
    page_size: int = 100,
) -> IngestResult:
    """Incrementally fetch new messages for a single channel.

    Args:
        bot: Connected discord.py Bot instance.
        channel_id: Discord channel ID as string.
        dry_run: If True, fetch and count but do not write to DB.
        max_pages: Cap total messages at page_size * max_pages.
        page_size: Messages per Discord API page (max 100).

    Returns:
        IngestResult with full statistics.
    """
    from src.bot.events import get_channel_type
    from src.logging_utils import log_message_to_database

    result = IngestResult(channel_id=channel_id, dry_run=dry_run)
    start = time.monotonic()

    # 1. Resolve channel object
    channel = bot.get_channel(int(channel_id))
    if channel is None:
        try:
            channel = await bot.fetch_channel(int(channel_id))
        except (discord.NotFound, discord.Forbidden) as exc:
            result.error = f"Cannot access channel: {exc}"
            result.duration_seconds = time.monotonic() - start
            logger.error("Channel %s inaccessible: %s", channel_id, exc)
            return result

    result.channel_name = getattr(channel, "name", str(channel_id))

    # 2. Concurrent-run guard
    if not check_channel_not_running(channel_id):
        result.error = "Concurrent run detected — skipping"
        result.duration_seconds = time.monotonic() - start
        logger.warning("Channel %s (%s): concurrent run detected", channel_id, result.channel_name)
        return result

    # 3. Load cursor
    cursor = get_cursor(channel_id)
    result.cursor_before = cursor

    # 4. Mark running (unless dry_run)
    if not dry_run:
        _mark_channel_status(channel_id, "running")

    # 5. Build history kwargs
    limit = (page_size * max_pages) if max_pages else None
    history_kwargs = {"oldest_first": True, "limit": limit}
    if cursor:
        history_kwargs["after"] = discord.Object(id=int(cursor))

    highest_id: str | None = None
    highest_ts = None
    channel_type = get_channel_type(result.channel_name)

    try:
        count = 0
        async for msg in channel.history(**history_kwargs):
            count += 1
            result.messages_fetched += 1

            # Skip bot's own messages
            if msg.author == bot.user:
                result.messages_skipped_bot += 1
                continue

            is_bot = msg.author.bot
            content = msg.content.strip() if msg.content else ""
            command_prefix = getattr(bot, "command_prefix", "!")
            if isinstance(command_prefix, (list, tuple)):
                is_command = any(content.startswith(p) for p in command_prefix)
            else:
                is_command = content.startswith(str(command_prefix))

            c_hash = compute_content_hash(msg.content) if msg.content else None

            if not dry_run:
                log_message_to_database(
                    msg,
                    is_bot=is_bot,
                    is_command=is_command,
                    channel_type=channel_type,
                    content_hash=c_hash,
                )
                result.messages_new += 1
            else:
                result.messages_new += 1

            # Track highest snowflake (monotonically increasing)
            msg_id_str = str(msg.id)
            if highest_id is None or int(msg_id_str) > int(highest_id):
                highest_id = msg_id_str
                highest_ts = msg.created_at

            # Yield control every 50 messages
            if count % 50 == 0:
                await asyncio.sleep(0.1)

    except discord.Forbidden as exc:
        result.error = f"Permission denied: {exc}"
        logger.error("Channel %s: permission denied — cursor NOT advanced", channel_id)
        if not dry_run:
            _mark_channel_status(channel_id, "error", str(exc))
        result.duration_seconds = time.monotonic() - start
        return result

    except discord.HTTPException as exc:
        if exc.status == 429:
            logger.warning("Channel %s: rate limited (429) — advancing cursor for fetched messages", channel_id)
            # Still advance cursor for what we got
        else:
            result.error = f"HTTP error: {exc}"
            logger.error("Channel %s: HTTP error %s", channel_id, exc)
            if not dry_run:
                _mark_channel_status(channel_id, "error", str(exc))
            result.duration_seconds = time.monotonic() - start
            return result

    except Exception as exc:
        result.error = f"Unexpected error: {exc}"
        logger.exception("Channel %s: unexpected error during ingestion", channel_id)
        if not dry_run:
            _mark_channel_status(channel_id, "error", str(exc))
        result.duration_seconds = time.monotonic() - start
        return result

    # 6. Advance cursor
    result.cursor_after = highest_id
    if highest_id and not dry_run:
        set_cursor(
            channel_id=channel_id,
            channel_name=result.channel_name,
            last_message_id=highest_id,
            last_message_ts=highest_ts,
            new_count=result.messages_new,
            dupe_count=result.messages_duplicate,
        )

    result.duration_seconds = time.monotonic() - start
    logger.info(
        "Channel %s (%s): fetched=%d new=%d dupes=%d skipped_bot=%d cursor=%s→%s (%.1fs)%s",
        channel_id,
        result.channel_name,
        result.messages_fetched,
        result.messages_new,
        result.messages_duplicate,
        result.messages_skipped_bot,
        result.cursor_before or "none",
        result.cursor_after or "none",
        result.duration_seconds,
        " [DRY RUN]" if dry_run else "",
    )
    return result


async def ingest_all_channels(
    bot,
    *,
    dry_run: bool = False,
    max_pages: int | None = None,
    channel_ids: list[str] | None = None,
) -> list[IngestResult]:
    """Run incremental ingestion for all configured channels.

    Args:
        bot: Connected discord.py Bot instance.
        dry_run: If True, fetch and count but do not write to DB.
        max_pages: Cap total messages per channel.
        channel_ids: Explicit channel list; defaults to LOG_CHANNEL_IDS from config.

    Returns:
        List of IngestResult, one per channel.
    """
    from src.config import settings

    if channel_ids is None:
        channel_ids = settings().log_channel_ids_list

    if not channel_ids:
        logger.warning("No channel IDs configured — nothing to ingest")
        return []

    results = []
    for cid in channel_ids:
        r = await ingest_channel(bot, cid, dry_run=dry_run, max_pages=max_pages)
        results.append(r)

    total_new = sum(r.messages_new for r in results)
    total_fetched = sum(r.messages_fetched for r in results)
    errors = [r for r in results if r.error]
    logger.info(
        "Ingestion complete: %d channels, %d fetched, %d new, %d errors%s",
        len(results),
        total_fetched,
        total_new,
        len(errors),
        " [DRY RUN]" if dry_run else "",
    )
    return results


def get_ingestion_status() -> list[dict]:
    """Return current cursor state for all channels (for --status CLI flag)."""
    from src.db import execute_sql

    rows = execute_sql(
        """
        SELECT channel_id, channel_name, last_message_id, last_message_ts,
               messages_total, last_run_at, last_run_new, last_run_dupes,
               status, error_message
        FROM discord_ingestion_state
        ORDER BY channel_name
        """,
        fetch_results=True,
    )
    if not rows:
        return []

    return [
        {
            "channel_id": r[0],
            "channel_name": r[1],
            "last_message_id": r[2],
            "last_message_ts": r[3],
            "messages_total": r[4],
            "last_run_at": r[5],
            "last_run_new": r[6],
            "last_run_dupes": r[7],
            "status": r[8],
            "error_message": r[9],
        }
        for r in rows
    ]
