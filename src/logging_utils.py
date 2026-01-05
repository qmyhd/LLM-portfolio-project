import logging
from pathlib import Path

from src.twitter_analysis import (
    extract_tweet_id,
)

logger = logging.getLogger(__name__)


def log_message_to_database(message, twitter_client=None):
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

    ON CONFLICT Behavior:
    - If message_id already exists: Updates all fields with new values
    - Ensures latest data is always stored
    - Safe for re-runs and concurrent operations

    Simplified to avoid transaction conflicts - each operation manages its own transaction.
    Twitter processing is done as a separate step to avoid blocking message logging.

    Args:
        message: Discord message object from discord.py
        twitter_client: Optional Twitter API client for tweet data extraction
    """
    try:
        from src.db import execute_sql
        from src.message_cleaner import extract_ticker_symbols
        import json

        # 1. Insert Discord message (primary operation - always succeeds)
        tickers = extract_ticker_symbols(message.content)

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

        message_data = {
            "message_id": str(message.id),
            "author": message.author.name,
            "author_id": message.author.id,
            "content": message.content,
            "channel": message.channel.name,
            "timestamp": message.created_at.isoformat(),
            "user_id": str(message.author.id),
            "num_chars": len(message.content),
            "num_words": len(message.content.split()),
            "tickers_detected": ", ".join(tickers) if tickers else None,
            "is_reply": bool(message.reference and message.reference.message_id),
            "reply_to_id": message.reference.message_id if message.reference else None,
            "mentions": (
                ", ".join([u.name for u in message.mentions])
                if message.mentions
                else None
            ),
            "attachments": attachments_json,
        }

        execute_sql(
            """
            INSERT INTO discord_messages 
            (message_id, author, author_id, content, channel, timestamp, 
             user_id, num_chars, num_words, tickers_detected, 
             is_reply, reply_to_id, mentions, attachments)
            VALUES (:message_id, :author, :author_id, :content, :channel, :timestamp,
                    :user_id, :num_chars, :num_words, :tickers_detected,
                    :is_reply, :reply_to_id, :mentions, :attachments)
            ON CONFLICT (message_id) DO UPDATE SET
                author = EXCLUDED.author,
                author_id = EXCLUDED.author_id,
                content = EXCLUDED.content,
                channel = EXCLUDED.channel,
                timestamp = EXCLUDED.timestamp,
                num_chars = EXCLUDED.num_chars,
                num_words = EXCLUDED.num_words,
                tickers_detected = EXCLUDED.tickers_detected,
                is_reply = EXCLUDED.is_reply,
                reply_to_id = EXCLUDED.reply_to_id,
                mentions = EXCLUDED.mentions,
                attachments = EXCLUDED.attachments
            """,
            message_data,
        )

        logger.info(f"✅ Logged message {message.id} to discord_messages")

        # 2. Process Twitter links separately (non-blocking)
        # This is done in a separate transaction to avoid blocking message logging
        try:
            from src.twitter_analysis import (
                detect_twitter_links,
                fetch_tweet_data,
                extract_tweet_id,
                log_tweet_to_database,
            )

            twitter_links = detect_twitter_links(message.content)
            if twitter_links and twitter_client:
                for url in twitter_links:
                    tweet_id = extract_tweet_id(url)
                    if tweet_id:
                        try:
                            tweet_data = fetch_tweet_data(
                                tweet_id, twitter_client=twitter_client
                            )
                            if tweet_data:
                                # Add Discord context to tweet data
                                tweet_data["discord_sent_date"] = message.created_at

                                # Use the comprehensive log_tweet_to_database function
                                # which properly extracts all fields including stock tags
                                log_tweet_to_database(tweet_data, message.id)

                                # Mark as processed for Twitter
                                from src.db import mark_message_processed

                                mark_message_processed(
                                    str(message.id), message.channel.name, "twitter"
                                )

                                logger.info(
                                    f"✅ Logged tweet {tweet_id} from message {message.id}"
                                )
                        except Exception as tweet_error:
                            logger.warning(
                                f"⚠️ Could not fetch tweet {tweet_id}: {tweet_error}"
                            )
                            # Don't fail the entire message logging due to Twitter issues

        except Exception as twitter_error:
            logger.warning(
                f"⚠️ Twitter processing failed for message {message.id}: {twitter_error}"
            )
            # Don't fail the entire message logging due to Twitter issues

    except Exception as e:
        logger.error(f"❌ Error logging message to database: {e}")
        raise  # Re-raise for proper error surfacing


def log_message_to_file(
    message, _log_file: Path, _tweet_log: Path, twitter_client=None
):
    """Legacy function - now redirects to database logging.

    This function is maintained for backward compatibility but now primarily
    uses the database-first approach instead of CSV files.

    Args:
        message: Discord message object
        _log_file: Deprecated - CSV logging path (unused, kept for backwards compatibility)
        _tweet_log: Deprecated - Tweet CSV logging path (unused, kept for backwards compatibility)
        twitter_client: Optional Twitter client for tweet fetching
    """
    # Primary: Log to database (Supabase)
    log_message_to_database(message, twitter_client)

    # Note: CSV logging has been deprecated in favor of database storage.
    # Database provides better consistency, deduplication, and query capabilities.


# log_tweet_to_csv() function removed - CSV logging deprecated in favor of database storage
