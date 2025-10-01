import logging
from pathlib import Path

from src.message_cleaner import extract_ticker_symbols
from src.db import mark_message_processed, execute_sql
from src.twitter_analysis import (
    analyze_sentiment,
    detect_twitter_links,
    extract_tweet_id,
    fetch_tweet_data,
)

logger = logging.getLogger(__name__)


def log_message_to_database(message, twitter_client=None):
    """Persist a Discord message to database using unified execute_sql approach."""
    try:
        from src.db import execute_sql, get_sync_engine
        from src.twitter_analysis import detect_twitter_links, fetch_tweet_data
        from src.message_cleaner import extract_ticker_symbols

        # Use single transaction for all message-related database operations
        engine = get_sync_engine()
        with engine.begin() as conn:
            # 1. Insert Discord message with named placeholders and dict parameters
            message_data = {
                "message_id": str(message.id),
                "author": message.author.name,
                "content": message.content,
                "channel": message.channel.name,
                "timestamp": message.created_at.isoformat(),
            }

            execute_sql(
                """
                INSERT INTO discord_messages 
                (message_id, author, content, channel, timestamp)
                VALUES (:message_id, :author, :content, :channel, :timestamp)
                ON CONFLICT (message_id) DO UPDATE SET
                    author = EXCLUDED.author,
                    content = EXCLUDED.content,
                    channel = EXCLUDED.channel,
                    timestamp = EXCLUDED.timestamp
                """,
                message_data,
            )

            # 2. Process Twitter links if found
            twitter_links = detect_twitter_links(message.content)
            if twitter_links:
                for url in twitter_links:
                    tweet_id = extract_tweet_id(url)
                    if tweet_id and twitter_client:
                        tweet_data = fetch_tweet_data(
                            tweet_id, twitter_client=twitter_client
                        )
                        if tweet_data:
                            # Extract stock mentions from tweet content
                            stock_tags = extract_ticker_symbols(
                                tweet_data.get("content", "")
                            )

                            twitter_data = {
                                "message_id": str(message.id),
                                "discord_date": message.created_at.isoformat(),
                                "tweet_date": tweet_data.get("created_at", ""),
                                "content": tweet_data.get("content", ""),
                                "stock_tags": (
                                    ", ".join(stock_tags) if stock_tags else ""
                                ),
                                "author": message.author.name,
                                "channel": message.channel.name,
                            }

                            execute_sql(
                                """
                                INSERT INTO twitter_data 
                                (message_id, discord_date, tweet_date, content, stock_tags, author, channel)
                                VALUES (:message_id, :discord_date, :tweet_date, :content, :stock_tags, :author, :channel)
                                ON CONFLICT (message_id) DO UPDATE SET
                                    discord_date = EXCLUDED.discord_date,
                                    tweet_date = EXCLUDED.tweet_date,
                                    content = EXCLUDED.content,
                                    stock_tags = EXCLUDED.stock_tags
                                """,
                                twitter_data,
                            )

                            # 3. Mark message as processed for Twitter
                            from src.db import mark_message_processed

                            mark_message_processed(
                                str(message.id), message.channel.name, "twitter"
                            )

        logger.info(
            f"✅ Successfully logged message {message.id} to database with all related data"
        )

    except Exception as e:
        logger.error(f"❌ Error logging message to database: {e}")
        raise  # Re-raise for proper error surfacing


def log_message_to_file(message, log_file: Path, tweet_log: Path, twitter_client=None):
    """Legacy function - now redirects to database logging.

    This function is maintained for backward compatibility but now primarily
    uses the database-first approach instead of CSV files.
    """
    # Primary: Log to database (Supabase)
    log_message_to_database(message, twitter_client)

    # Note: CSV logging has been deprecated in favor of database storage.
    # Database provides better consistency, deduplication, and query capabilities.


# log_tweet_to_csv() function removed - CSV logging deprecated in favor of database storage
