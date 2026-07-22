import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def log_message_to_database(
    message,
    is_bot: bool = False,
    is_command: bool = False,
    channel_type: str = None,
    content_hash: str = None,
):
    """Persist a Discord message to database using unified execute_sql approach.

    Deduplication & Safety Features:
    - ON CONFLICT (message_id): Handles duplicate inserts safely (idempotent)
    - Primary key: Discord message_id (globally unique)
    - No deletion: Messages are never deleted from discord_messages
    - Processing flags: Messages marked as processed in processing_status table

    Pipeline Integration:
    - Insert stage: This function inserts raw messages into discord_messages
    - Processing stage: get_unprocessed_messages() finds messages to clean
    - Marking stage: mark_message_processed() sets processed_for_cleaning flag
    - Resumable: If interrupted, raw messages remain for later processing

    Message Flags:
    - is_bot: TRUE if message author is a Discord bot
    - is_command: TRUE if message starts with command prefix (!, /, etc.)
    - channel_type: Channel category ('trading', 'market', 'general')
    - Bot/command messages are stored but excluded from NLP parsing downstream

    ON CONFLICT Behavior:
    - If message_id already exists: Updates all fields with new values
    - Ensures latest data is always stored
    - Safe for re-runs and concurrent operations

    Simplified to avoid transaction conflicts - each operation manages its own transaction.
    Shared X/Twitter content is captured via tweet_urls + Discord embeds, not
    a live Twitter API call (the API tier no longer permits tweet reads).

    Args:
        message: Discord message object from discord.py
        is_bot: Whether the message author is a bot
        is_command: Whether the message is a bot command
        channel_type: The channel type ('trading', 'market', 'general')
    """
    try:
        from src.db import execute_sql
        from src.message_cleaner import extract_ticker_symbols
        import json

        # 1. Insert Discord message (primary operation - always succeeds)
        # Auto-compute content_hash if not provided
        if content_hash is None and message.content:
            from src.discord_ingest import compute_content_hash
            content_hash = compute_content_hash(message.content)

        content = message.content or ""
        tickers = extract_ticker_symbols(content)

        # Capture attachments as JSON array
        attachments_json = None
        if message.attachments:
            attachments_data = [
                {
                    "url": att.url,
                    "filename": att.filename,
                    "size": att.size,
                    "content_type": att.content_type,
                }
                for att in message.attachments
            ]
            attachments_json = json.dumps(attachments_data)

        # Capture embeds — for shared X/Twitter links Discord unfurls the tweet
        # text into an embed description, so this preserves the tweet content
        # without any Twitter API call.
        embeds_json = None
        if getattr(message, "embeds", None):
            embeds_data = []
            for emb in message.embeds:
                author_name = getattr(getattr(emb, "author", None), "name", None)
                embeds_data.append(
                    {
                        "type": getattr(emb, "type", None),
                        "title": getattr(emb, "title", None),
                        "description": getattr(emb, "description", None),
                        "url": getattr(emb, "url", None),
                        "author": author_name,
                    }
                )
            if embeds_data:
                embeds_json = json.dumps(embeds_data)

        # Extract shared tweet URLs from the message text (the live path
        # previously never populated tweet_urls).
        from src.message_cleaner import extract_tweet_urls

        tweet_url_list = extract_tweet_urls(content)
        tweet_urls_str = ", ".join(tweet_url_list) if tweet_url_list else None

        # Deterministic parse pre-classification so non-content never sits in
        # 'pending' forever: bot/command/empty/too-short -> 'skipped' up front.
        # A shared tweet/link carries its content in the embed even when the
        # message text is short, so messages with embeds or tweet URLs stay
        # parseable. On re-ingest we do NOT overwrite an existing parse_status,
        # so an already-parsed message keeps its result.
        has_shareable = bool(embeds_json) or bool(tweet_urls_str)
        if is_bot or is_command:
            initial_parse_status = "skipped"
        elif has_shareable or len(content.strip()) > 10:
            initial_parse_status = "pending"
        else:
            initial_parse_status = "skipped"

        message_data = {
            "message_id": str(message.id),
            "author": message.author.name,
            "author_id": message.author.id,
            "content": message.content,
            "channel": message.channel.name,
            "timestamp": message.created_at.isoformat(),
            "user_id": str(message.author.id),
            "num_chars": len(content),
            "num_words": len(content.split()),
            "tickers_detected": ", ".join(tickers) if tickers else None,
            "tweet_urls": tweet_urls_str,
            "is_reply": bool(message.reference and message.reference.message_id),
            "reply_to_id": message.reference.message_id if message.reference else None,
            "mentions": (
                ", ".join([u.name for u in message.mentions])
                if message.mentions
                else None
            ),
            "attachments": attachments_json,
            "embeds": embeds_json,
            "is_bot": is_bot,
            "is_command": is_command,
            "channel_type": channel_type,
            "content_hash": content_hash,
            "parse_status": initial_parse_status,
        }

        execute_sql(
            """
            INSERT INTO discord_messages
            (message_id, author, author_id, content, channel, timestamp,
             user_id, num_chars, num_words, tickers_detected, tweet_urls,
             is_reply, reply_to_id, mentions, attachments, embeds,
             is_bot, is_command, channel_type, content_hash, parse_status)
            VALUES (:message_id, :author, :author_id, :content, :channel, :timestamp,
                    :user_id, :num_chars, :num_words, :tickers_detected, :tweet_urls,
                    :is_reply, :reply_to_id, :mentions, :attachments, :embeds,
                    :is_bot, :is_command, :channel_type, :content_hash, :parse_status)
            ON CONFLICT (message_id) DO UPDATE SET
                author = EXCLUDED.author,
                author_id = EXCLUDED.author_id,
                content = EXCLUDED.content,
                channel = EXCLUDED.channel,
                timestamp = EXCLUDED.timestamp,
                num_chars = EXCLUDED.num_chars,
                num_words = EXCLUDED.num_words,
                tickers_detected = EXCLUDED.tickers_detected,
                tweet_urls = EXCLUDED.tweet_urls,
                is_reply = EXCLUDED.is_reply,
                reply_to_id = EXCLUDED.reply_to_id,
                mentions = EXCLUDED.mentions,
                attachments = EXCLUDED.attachments,
                embeds = EXCLUDED.embeds,
                is_bot = EXCLUDED.is_bot,
                is_command = EXCLUDED.is_command,
                channel_type = EXCLUDED.channel_type,
                content_hash = EXCLUDED.content_hash
            """,
            message_data,
        )

        logger.info(f"✅ Logged message {message.id} to discord_messages")

        # Note: shared X/Twitter content is captured via `tweet_urls` +
        # Discord `embeds` (unfurled tweet text) above — the live Twitter API
        # fetch path was removed because the API tier no longer allows tweet
        # reads. Historical tweet text is backfilled by
        # scripts/backfill_tweet_text.py (free fxtwitter unfurler).

    except Exception as e:
        logger.error(f"❌ Error logging message to database: {e}")
        raise  # Re-raise for proper error surfacing
