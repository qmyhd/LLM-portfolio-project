import logging
from pathlib import Path

from src.message_cleaner import extract_ticker_symbols
from src.database import mark_message_processed, execute_sql
from src.twitter_analysis import (
    analyze_sentiment,
    detect_twitter_links,
    extract_tweet_id,
    fetch_tweet_data,
)

logger = logging.getLogger(__name__)


def log_message_to_database(message, twitter_client=None):
    """Persist a Discord message to database and optionally log any linked tweets."""
    try:
        # First try direct Supabase write (primary)
        try:
            from src.supabase_writers import DirectSupabaseWriter
            from src.twitter_analysis import detect_twitter_links
            from src.message_cleaner import extract_ticker_symbols

            writer = DirectSupabaseWriter()

            # Convert Discord message to dictionary format
            message_data = {
                "message_id": str(message.id),
                "author": message.author.name,
                "content": message.content,
                "channel": message.channel.name,
                "timestamp": message.created_at.isoformat(),
                "author_id": (
                    str(message.author.id) if hasattr(message.author, "id") else None
                ),
                "tickers_detected": ", ".join(extract_ticker_symbols(message.content)),
                "tweet_urls": ", ".join(detect_twitter_links(message.content)),
                "is_reply": bool(message.reference and message.reference.message_id),
                "reply_to_id": (
                    str(message.reference.message_id) if message.reference else None
                ),
                "mentions": (
                    ", ".join([str(user.id) for user in message.mentions])
                    if message.mentions
                    else ""
                ),
            }

            success = writer.write_discord_message(message_data)
            if success:
                logger.info(f"✅ Successfully logged message {message.id} to Supabase")
                return
            else:
                logger.warning(
                    "⚠️ Failed to log to Supabase, falling back to unified database layer"
                )
                raise Exception("Supabase write failed")
        except Exception as e:
            logger.warning(f"Supabase write failed: {e}, using fallback database")
            # Fallback to unified database layer

            # Check if message already exists
            existing = execute_sql(
                "SELECT message_id FROM discord_messages WHERE message_id = ?",
                (str(message.id),),
                fetch_results=True,
            )
            if existing:
                return  # Message already exists, skip

            # Insert message into discord_messages table
            execute_sql(
                """
                INSERT INTO discord_messages 
                (message_id, author, content, channel, timestamp)
                VALUES (?, ?, ?, ?, ?)
            """,
                (
                    str(message.id),
                    message.author.name,
                    message.content,
                    message.channel.name,
                    message.created_at.isoformat(),
                ),
            )

            # Check for Twitter links and process them
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

                            execute_sql(
                                """
                                INSERT INTO twitter_data 
                                (message_id, discord_date, tweet_date, content, stock_tags, author, channel)
                                VALUES (?, ?, ?, ?, ?, ?, ?)
                            """,
                                (
                                    str(message.id),
                                    message.created_at.isoformat(),
                                    tweet_data.get("created_at", ""),
                                    tweet_data.get("content", ""),
                                    ", ".join(stock_tags) if stock_tags else "",
                                    message.author.name,
                                    message.channel.name,
                                ),
                            )

                            mark_message_processed(
                                str(message.id), message.channel.name, "twitter"
                            )

            logger.info(f"Successfully logged message {message.id} to database")

    except Exception as e:
        logger.error(f"Error logging message to database: {e}")
        import traceback

        logger.error(traceback.format_exc())


def log_message_to_file(message, log_file: Path, tweet_log: Path, twitter_client=None):
    """Legacy function - now redirects to database logging.

    This function is maintained for backward compatibility but now primarily
    uses the database-first approach instead of CSV files.
    """
    # Primary: Log to database (Supabase + fallback)
    log_message_to_database(message, twitter_client)

    # Note: CSV logging has been deprecated in favor of database storage.
    # Database provides better consistency, deduplication, and query capabilities.


def log_tweet_to_csv(tweet_data, discord_message_id, tweet_log: Path):
    """Legacy function - CSV logging deprecated in favor of database storage.

    This function is maintained for API compatibility but no longer writes CSV files.
    Tweet data is now stored in the database through the main logging pipeline.
    """
    # CSV logging has been deprecated - data is now stored in database
    pass
