import csv
import logging
import re
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import pandas as pd

from src.nlp.sentiment import sentiment_score

# Import message cleaning functions
from src.message_cleaner import extract_ticker_symbols, clean_text

logger = logging.getLogger(__name__)

TWEET_URL_RE = re.compile(
    r"https?://(?:www\.)?(?:x\.com|twitter\.com)/([A-Za-z0-9_]+)/status/(\d+)"
)

# Rate limit tracking for Twitter API (Free tier: ~1 request per 15 min)
_last_api_call_time: Optional[datetime] = None
_rate_limit_reset_time: Optional[datetime] = None
TWITTER_RATE_LIMIT_SECONDS = 900  # 15 minutes between requests for Free tier


def get_twitter_client():
    """Create and return a tweepy.Client using TWITTER_BEARER_TOKEN from environment.

    Returns:
        tweepy.Client instance or None if token not configured
    """
    try:
        import tweepy
        from src.config import settings

        config = settings()
        bearer_token = config.TWITTER_BEARER_TOKEN

        if not bearer_token:
            logger.warning("TWITTER_BEARER_TOKEN not configured")
            return None

        # Create client with wait_on_rate_limit=False since we handle it manually
        client = tweepy.Client(bearer_token=bearer_token, wait_on_rate_limit=False)
        return client

    except ImportError:
        logger.error("tweepy not installed. Run: pip install tweepy")
        return None
    except Exception as e:
        logger.error(f"Error creating Twitter client: {e}")
        return None


def is_rate_limited() -> bool:
    """Check if we're currently rate limited by Twitter API."""
    global _last_api_call_time, _rate_limit_reset_time

    now = datetime.now(timezone.utc)

    # Check if we hit a rate limit that hasn't reset
    if _rate_limit_reset_time and now < _rate_limit_reset_time:
        return True

    # Check if we made a call too recently (Free tier: 1 per 15 min)
    if _last_api_call_time:
        elapsed = (now - _last_api_call_time).total_seconds()
        if elapsed < TWITTER_RATE_LIMIT_SECONDS:
            return True

    return False


def get_rate_limit_wait_time() -> float:
    """Get seconds until we can make another Twitter API call."""
    global _last_api_call_time, _rate_limit_reset_time

    now = datetime.now(timezone.utc)

    if _rate_limit_reset_time and now < _rate_limit_reset_time:
        return (_rate_limit_reset_time - now).total_seconds()

    if _last_api_call_time:
        elapsed = (now - _last_api_call_time).total_seconds()
        remaining = TWITTER_RATE_LIMIT_SECONDS - elapsed
        return max(0, remaining)

    return 0


def _record_api_call():
    """Record that an API call was made."""
    global _last_api_call_time
    _last_api_call_time = datetime.now(timezone.utc)


def _handle_rate_limit_response(response):
    """Handle rate limit information from API response."""
    global _rate_limit_reset_time

    # Check for rate limit headers in tweepy response
    if hasattr(response, "headers"):
        reset_time = response.headers.get("x-rate-limit-reset")
        if reset_time:
            _rate_limit_reset_time = datetime.fromtimestamp(
                int(reset_time), tz=timezone.utc
            )


def detect_twitter_links(text: str) -> list[str]:
    if not text:
        return []
    return list({m.group(0) for m in TWEET_URL_RE.finditer(text)})


def extract_tweet_id(url: str):
    m = TWEET_URL_RE.search(url)
    return m.group(2) if m else None


def analyze_sentiment(text: str) -> float:
    if not text:
        return 0.0
    try:
        return sentiment_score(text)
    except Exception as e:
        logger.error(f"Error analyzing sentiment: {e}")
        return 0.0


def fetch_tweet_data(
    tweet_id: str, twitter_client=None, respect_rate_limit: bool = True
):
    """Fetch tweet data including media attachments using tweepy.Client.

    Args:
        tweet_id: The Twitter/X post ID
        twitter_client: tweepy.Client instance
        respect_rate_limit: If True, skip fetch when rate limited (default: True)

    Returns:
        Dict with tweet data or None if rate limited/error
    """
    global _rate_limit_reset_time

    if not twitter_client:
        logger.debug("No twitter_client provided, skipping fetch.")
        return None

    # Check rate limit before making request
    if respect_rate_limit and is_rate_limited():
        wait_time = get_rate_limit_wait_time()
        logger.warning(
            f"⚠️ Twitter API rate limited. Wait {wait_time:.0f}s before next request."
        )
        return None

    try:
        tid = int(tweet_id)

        # Record that we're making an API call
        _record_api_call()

        tweet = twitter_client.get_tweet(
            tid,
            expansions=["author_id", "attachments.media_keys"],
            tweet_fields=["created_at", "public_metrics", "text", "attachments"],
            user_fields=["name", "username"],
            media_fields=["url", "preview_image_url", "type", "alt_text"],
        )
        if not tweet or not tweet.data:
            return None
        user = (
            tweet.includes["users"][0]
            if tweet.includes and tweet.includes.get("users")
            else None
        )
        metrics = (
            tweet.data.public_metrics if hasattr(tweet.data, "public_metrics") else {}
        )

        # Extract media URLs from includes
        media_urls = []
        if tweet.includes and tweet.includes.get("media"):
            for media in tweet.includes["media"]:
                # For photos, use url; for videos/gifs, use preview_image_url
                media_url = getattr(media, "url", None) or getattr(
                    media, "preview_image_url", None
                )
                if media_url:
                    media_urls.append(
                        {
                            "url": media_url,
                            "type": getattr(media, "type", "unknown"),
                            "alt_text": getattr(media, "alt_text", None),
                        }
                    )

        data = {
            "tweet_id": tid,
            "source_url": f"https://x.com/{user.username if user else 'unknown'}/status/{tid}",
            "created_at": tweet.data.created_at,
            "text": tweet.data.text,
            "author_id": tweet.data.author_id,
            "author_name": user.name if user else None,
            "author_username": user.username if user else None,
            "retweet_count": metrics.get("retweet_count", 0),
            "like_count": metrics.get("like_count", 0),
            "reply_count": metrics.get("reply_count", 0),
            "quote_count": metrics.get("quote_count", 0),
            "media": media_urls,  # List of media attachments
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
        }
        return data
    except Exception as e:
        error_str = str(e).lower()
        # Handle rate limit errors (429 Too Many Requests)
        if (
            "429" in str(e)
            or "rate limit" in error_str
            or "too many requests" in error_str
        ):
            logger.warning(
                f"⚠️ Twitter API rate limited for tweet {tweet_id}. Will retry later."
            )
            # Set rate limit reset to 15 minutes from now
            _rate_limit_reset_time = datetime.now(timezone.utc) + timedelta(
                seconds=TWITTER_RATE_LIMIT_SECONDS
            )
        else:
            logger.error(f"Error fetching tweet {tweet_id}: {e}")
        return None


def extract_stock_symbols_from_tweet(tweet_text):
    """Extract stock symbols from tweet content."""
    if not tweet_text:
        return []

    import re

    # Find ticker patterns like $AAPL, $MSFT, etc.
    tickers = re.findall(r"\$[A-Z]{2,6}", tweet_text)
    # Also look for common stock mentions without $ (but be more conservative)
    word_tickers = re.findall(r"\b[A-Z]{2,5}\b", tweet_text)

    # Filter out common words that aren't likely to be stocks
    common_words = {
        "THE",
        "AND",
        "OR",
        "BUT",
        "FOR",
        "NOR",
        "YET",
        "SO",
        "AT",
        "IN",
        "ON",
        "TO",
        "BY",
        "UP",
        "IF",
        "IT",
        "IS",
        "AS",
        "WE",
        "HE",
        "SHE",
        "YOU",
        "ALL",
        "ANY",
        "CAN",
        "HAD",
        "HAS",
        "WAS",
        "NOT",
        "ARE",
        "BUT",
        "DAY",
        "GET",
        "HIM",
        "HIS",
        "HOW",
        "ITS",
        "MAY",
        "NEW",
        "NOW",
        "OLD",
        "ONE",
        "OUR",
        "OUT",
        "SEE",
        "TWO",
        "WHO",
        "BOY",
        "DID",
        "HER",
        "LET",
        "MAN",
        "PUT",
        "RUN",
        "SHE",
        "TRY",
        "WAY",
        "WHY",
        "WIN",
        "YES",
        "YET",
        "YOU",
        "BIG",
        "BOX",
        "FUN",
        "GUN",
        "JOB",
        "LOT",
        "MEN",
        "MOM",
        "POP",
        "RED",
        "SUN",
        "TOP",
        "WAR",
        "WIN",
        "USE",
        "USA",
        "USD",
        "CEO",
        "CFO",
        "CTO",
        "IPO",
        "ESG",
    }

    filtered_word_tickers = [
        t for t in word_tickers if t not in common_words and len(t) >= 2
    ]

    # Combine and deduplicate, prefer $ format
    all_tickers = list(set(tickers + [f"${t}" for t in filtered_word_tickers]))
    return all_tickers


def log_tweet_to_database(tweet_data: dict, discord_message_id: int):
    """Log tweet data to PostgreSQL database using named placeholders."""
    try:
        from datetime import datetime, timezone
        from src.db import execute_sql

        # Extract stock symbols from tweet content (handles both 'text' and 'tweet_content' keys)
        tweet_text = tweet_data.get("tweet_content") or tweet_data.get("text", "")
        stock_tags = extract_stock_symbols_from_tweet(tweet_text)
        stock_tags_str = ", ".join(stock_tags) if stock_tags else None

        # Handle timestamp fields - ensure valid timezone-aware datetime objects
        now = datetime.now(timezone.utc)  # Use datetime object, not isoformat string

        # Get tweet_created_date with fallbacks and validation
        tweet_created = tweet_data.get("tweet_created_date") or tweet_data.get(
            "created_at"
        )
        if not tweet_created or tweet_created == "":
            tweet_created = now  # Default to current time if missing
        elif isinstance(tweet_created, str):
            # Convert string timestamps to datetime objects
            try:
                from datetime import datetime as dt

                if "T" in tweet_created:
                    tweet_created = dt.fromisoformat(
                        tweet_created.replace("Z", "+00:00")
                    )
                    if tweet_created.tzinfo is None:
                        tweet_created = tweet_created.replace(tzinfo=timezone.utc)
                else:
                    tweet_created = now
            except (ValueError, AttributeError):
                tweet_created = now

        # Get retrieved_at with validation
        retrieved_at = tweet_data.get("retrieved_at")
        if not retrieved_at or retrieved_at == "":
            retrieved_at = now
        elif isinstance(retrieved_at, str):
            # Convert string timestamps to datetime objects
            try:
                from datetime import datetime as dt

                if "T" in retrieved_at:
                    retrieved_at = dt.fromisoformat(retrieved_at.replace("Z", "+00:00"))
                    if retrieved_at.tzinfo is None:
                        retrieved_at = retrieved_at.replace(tzinfo=timezone.utc)
                else:
                    retrieved_at = now
            except (ValueError, AttributeError):
                retrieved_at = (
                    now  # PostgreSQL upsert with named placeholders and dict parameters
                )

        # Handle media URLs - convert to JSON string for JSONB column
        import json

        media_urls = tweet_data.get("media", [])
        media_urls_json = json.dumps(media_urls) if media_urls else "[]"

        # Map to actual database schema with required NOT NULL fields
        tweet_record = {
            "tweet_id": str(tweet_data.get("tweet_id", "")),
            "message_id": str(discord_message_id),  # Required NOT NULL field
            "content": tweet_text[
                :500
            ],  # Required NOT NULL field (truncate if too long)
            "author": tweet_data.get(
                "author_username", "unknown"
            ),  # Required NOT NULL field
            "channel": "twitter",  # Required NOT NULL field
            "discord_message_id": str(discord_message_id),  # Optional field
            "discord_sent_date": (
                tweet_data.get("discord_sent_date", now)
                if not isinstance(tweet_data.get("discord_sent_date"), str)
                else now
            ),
            "discord_date": now,  # Add missing discord_date field (timestamptz)
            "tweet_date": tweet_created,  # Add missing tweet_date field (timestamptz)
            "tweet_created_date": tweet_created,
            "tweet_content": tweet_text,
            "author_username": tweet_data.get("author_username", ""),
            "author_name": tweet_data.get("author_name", ""),
            "retweet_count": int(
                tweet_data.get("retweet_count", 0)
            ),  # Ensure integer type
            "like_count": int(tweet_data.get("like_count", 0)),  # Ensure integer type
            "reply_count": int(tweet_data.get("reply_count", 0)),  # Ensure integer type
            "quote_count": int(tweet_data.get("quote_count", 0)),  # Ensure integer type
            "stock_tags": stock_tags_str,
            "source_url": tweet_data.get("source_url", ""),
            "retrieved_at": (
                str(retrieved_at.isoformat())
                if hasattr(retrieved_at, "isoformat")
                else str(retrieved_at)
            ),  # Convert to text as per schema
            "media_urls": media_urls_json,  # JSONB column for media attachments
        }

        execute_sql(
            """
            INSERT INTO twitter_data
            (tweet_id, message_id, content, author, channel, discord_message_id,
             discord_sent_date, discord_date, tweet_date, tweet_created_date, tweet_content, author_username,
             author_name, retweet_count, like_count, reply_count, quote_count,
             stock_tags, source_url, retrieved_at, media_urls)
            VALUES (:tweet_id, :message_id, :content, :author, :channel, :discord_message_id,
                   :discord_sent_date, :discord_date, :tweet_date, :tweet_created_date, :tweet_content, :author_username,
                   :author_name, :retweet_count, :like_count, :reply_count, :quote_count,
                   :stock_tags, :source_url, :retrieved_at, :media_urls::jsonb)
            ON CONFLICT (tweet_id) DO UPDATE SET
                message_id = EXCLUDED.message_id,
                content = EXCLUDED.content,
                author = EXCLUDED.author,
                channel = EXCLUDED.channel,
                discord_message_id = EXCLUDED.discord_message_id,
                discord_sent_date = EXCLUDED.discord_sent_date,
                discord_date = EXCLUDED.discord_date,
                tweet_date = EXCLUDED.tweet_date,
                tweet_created_date = EXCLUDED.tweet_created_date,
                tweet_content = EXCLUDED.tweet_content,
                author_username = EXCLUDED.author_username,
                author_name = EXCLUDED.author_name,
                retweet_count = EXCLUDED.retweet_count,
                like_count = EXCLUDED.like_count,
                reply_count = EXCLUDED.reply_count,
                quote_count = EXCLUDED.quote_count,
                stock_tags = EXCLUDED.stock_tags,
                source_url = EXCLUDED.source_url,
                retrieved_at = EXCLUDED.retrieved_at,
                media_urls = EXCLUDED.media_urls
            """,
            tweet_record,
        )

        logger.info(
            f"✅ Logged tweet {tweet_data.get('tweet_id')} to database with {len(stock_tags)} stock tags and {len(media_urls)} media attachments"
        )

    except Exception as e:
        logger.error(f"❌ Error logging tweet to database: {e}")
        raise  # Re-raise for proper error surfacing


def get_tweets_by_stock_symbol(symbol, days_back=30):
    """Get tweets mentioning a specific stock symbol from the database."""
    try:
        from datetime import datetime, timedelta

        from src.db import execute_sql

        cutoff_date = (
            datetime.now(timezone.utc) - timedelta(days=days_back)
        ).isoformat()

        results = execute_sql(
            """
            SELECT tweet_id, discord_sent_date, tweet_created_date, tweet_content,
                   author_username, like_count, retweet_count, source_url
            FROM twitter_data
            WHERE stock_tags LIKE :symbol_pattern AND discord_sent_date > :cutoff_date
            ORDER BY discord_sent_date DESC
        """,
            {"symbol_pattern": f"%{symbol}%", "cutoff_date": cutoff_date},
        )

        return [
            dict(
                zip(
                    [
                        "tweet_id",
                        "discord_sent_date",
                        "tweet_created_date",
                        "tweet_content",
                        "author_username",
                        "like_count",
                        "retweet_count",
                        "source_url",
                    ],
                    row,
                )
            )
            for row in results
        ]

    except Exception as e:
        logger.error(f"Error fetching tweets for symbol {symbol}: {e}")
        return []


def get_twitter_sentiment_for_symbol(symbol, days_back=7):
    """Get aggregated Twitter sentiment for a stock symbol."""
    try:
        tweets = get_tweets_by_stock_symbol(symbol, days_back)
        if not tweets:
            return None

        # Calculate sentiment for each tweet
        sentiments = []
        for tweet in tweets:
            sentiment = analyze_sentiment(tweet["tweet_content"])
            sentiments.append(sentiment)

        return {
            "symbol": symbol,
            "tweet_count": len(tweets),
            "avg_sentiment": sum(sentiments) / len(sentiments) if sentiments else 0,
            "positive_tweets": len([s for s in sentiments if s > 0.1]),
            "negative_tweets": len([s for s in sentiments if s < -0.1]),
            "neutral_tweets": len([s for s in sentiments if -0.1 <= s <= 0.1]),
            "recent_tweets": tweets[:5],  # Most recent 5 tweets
        }

    except Exception as e:
        logger.error(f"Error calculating Twitter sentiment for {symbol}: {e}")
        return None


# ============================================================================
# NEW X/TWITTER PIPELINE FUNCTIONS
# ============================================================================


def build_x_posts_df(
    raw_tweets: List[Dict[str, Any]], discord_message_time: Optional[datetime] = None
) -> pd.DataFrame:
    """
    Build a standardized DataFrame for X/Twitter posts.

    Args:
        raw_tweets: List of raw tweet dictionaries from Twitter API
        discord_message_time: UTC timezone-aware datetime when shared in Discord

    Returns:
        DataFrame with columns: tweet_id, tweet_time, discord_message_time,
        tweet_text, tickers, author_id, conversation_id
    """
    if not raw_tweets:
        return pd.DataFrame()

    processed_tweets = []

    for tweet_data in raw_tweets:
        try:
            # Extract core tweet information
            tweet_id = str(tweet_data.get("tweet_id", tweet_data.get("id", "")))
            if not tweet_id:
                logger.warning("Tweet missing ID, skipping")
                continue

            # Handle tweet text
            raw_text = tweet_data.get("text", tweet_data.get("tweet_text", ""))
            cleaned_text = clean_text(raw_text) if raw_text else ""

            # Extract tickers using message_cleaner logic
            tickers = extract_ticker_symbols(raw_text)

            # Handle timestamps
            tweet_time = tweet_data.get("created_at", tweet_data.get("tweet_time"))
            if isinstance(tweet_time, str):
                try:
                    tweet_time = pd.to_datetime(tweet_time, utc=True)
                except Exception:
                    tweet_time = pd.Timestamp.now(tz="UTC")
            elif tweet_time is None:
                tweet_time = pd.Timestamp.now(tz="UTC")

            # Ensure discord_message_time is timezone-aware
            discord_time = discord_message_time
            if discord_time and discord_time.tzinfo is None:
                discord_time = discord_time.replace(tzinfo=pd.Timestamp.now().tz)
            elif discord_time is None:
                discord_time = pd.NaT

            processed_tweet = {
                "tweet_id": tweet_id,
                "tweet_time": tweet_time,
                "discord_message_time": discord_time,
                "tweet_text": cleaned_text,
                "tickers": tickers,  # List of strings like ['$AAPL', '$MSFT']
                "author_id": str(
                    tweet_data.get("author_id", tweet_data.get("user_id", ""))
                ),
                "conversation_id": str(tweet_data.get("conversation_id", "")),
            }

            processed_tweets.append(processed_tweet)

        except Exception as e:
            logger.error(
                f"Error processing tweet {tweet_data.get('id', 'unknown')}: {e}"
            )
            continue

    if not processed_tweets:
        return pd.DataFrame()

    # Create DataFrame and drop duplicates by tweet_id
    df = pd.DataFrame(processed_tweets)
    df = df.drop_duplicates(subset=["tweet_id"], keep="first")

    # Sort by tweet_time
    df = df.sort_values("tweet_time")

    logger.info(f"Built DataFrame with {len(df)} unique tweets")
    return df


def write_x_posts_parquet(
    df: pd.DataFrame, root: Union[str, Path] = "data/twitter/x_posts_log"
) -> Path:
    """
    Write X/Twitter posts DataFrame to Parquet with date partitioning.

    Args:
        df: DataFrame with X/Twitter posts
        root: Root directory for Parquet files

    Returns:
        Path to the written Parquet file
    """
    if df.empty:
        logger.warning("Empty DataFrame provided to write_x_posts_parquet")
        return Path(root)

    root_path = Path(root)
    root_path.mkdir(parents=True, exist_ok=True)

    # Drop duplicates again before writing
    df_clean = df.drop_duplicates(subset=["tweet_id"], keep="first")

    # Group by date for partitioning
    if "tweet_time" in df_clean.columns:
        df_clean["date"] = df_clean["tweet_time"].dt.strftime("%Y-%m-%d")
    else:
        df_clean["date"] = pd.Timestamp.now().strftime("%Y-%m-%d")

    written_files = []

    for date, group_df in df_clean.groupby("date"):
        # Remove the temporary date column
        group_df = group_df.drop("date", axis=1)

        # Create date partition directory
        partition_dir = root_path / f"date={date}"
        partition_dir.mkdir(exist_ok=True)

        # Write to Parquet file
        file_path = partition_dir / f"tweets_{date}.parquet"

        # If file exists, load and merge to avoid duplicates
        if file_path.exists():
            try:
                existing_df = pd.read_parquet(file_path)
                # Combine and deduplicate
                combined_df = pd.concat([existing_df, group_df], ignore_index=True)
                combined_df = combined_df.drop_duplicates(
                    subset=["tweet_id"], keep="last"
                )
                combined_df = combined_df.sort_values("tweet_time")
                group_df = combined_df
            except Exception as e:
                logger.warning(f"Error reading existing Parquet file {file_path}: {e}")

        # Write with pyarrow engine and snappy compression
        group_df.to_parquet(
            file_path, engine="pyarrow", compression="snappy", index=False
        )

        written_files.append(file_path)
        logger.info(f"Wrote {len(group_df)} tweets to {file_path}")

    return root_path


def upsert_x_posts_db(
    df: pd.DataFrame, db_url: Optional[str] = None, batch_size: int = 1000
) -> bool:
    """
    Upsert X/Twitter posts to database with conflict resolution.

    OPTIMIZED: Uses bulk executemany for reduced round-trips (~100x faster for batches).

    Args:
        df: DataFrame with X/Twitter posts
        db_url: Database URL (optional, will use default if not provided)
        batch_size: Number of records to process per batch (default: 1000)

    Returns:
        True if successful, False otherwise
    """
    if df.empty:
        logger.info("Empty DataFrame provided to upsert_x_posts_db")
        return True

    try:
        import time
        from src.db import execute_sql

        start_time = time.time()

        # Prepare DataFrame for database insertion
        db_df = df.copy()

        # PostgreSQL: keep tickers as list for TEXT[] column
        db_df["tickers"] = db_df["tickers"].apply(
            lambda x: x if isinstance(x, list) else []
        )

        # Convert DataFrame rows to list of parameter dictionaries for bulk operation
        params_list = []
        for _, row in db_df.iterrows():
            params_list.append(
                {
                    "tweet_id": row["tweet_id"],
                    "tweet_time": row["tweet_time"],
                    "discord_message_time": row["discord_message_time"],
                    "tweet_text": row["tweet_text"],
                    "tickers": row["tickers"],
                    "author_id": row["author_id"],
                    "conversation_id": row["conversation_id"],
                }
            )

        # BULK UPSERT: Process in batches to avoid memory/timeout issues
        total_batches = (len(params_list) + batch_size - 1) // batch_size
        logger.info(
            f"Starting bulk upsert of {len(params_list)} tweets in {total_batches} batch(es) (batch_size={batch_size})"
        )

        for i in range(0, len(params_list), batch_size):
            batch = params_list[i : i + batch_size]
            batch_num = i // batch_size + 1

            db_start = time.time()
            execute_sql(
                """
                INSERT INTO twitter_data
                (tweet_id, tweet_time, discord_message_time, tweet_text,
                 tickers, author_id, conversation_id)
                VALUES (:tweet_id, :tweet_time, :discord_message_time, :tweet_text,
                       :tickers, :author_id, :conversation_id)
                ON CONFLICT (tweet_id) DO NOTHING
                """,
                batch,  # Pass list of dicts for bulk operation
            )
            db_elapsed = time.time() - db_start

            if total_batches > 1:
                logger.debug(
                    f"Batch {batch_num}/{total_batches}: {len(batch)} tweets in {db_elapsed:.3f}s"
                )

        total_elapsed = time.time() - start_time
        throughput = len(db_df) / total_elapsed if total_elapsed > 0 else 0

        logger.info(
            f"✅ Bulk upserted {len(db_df)} tweets to PostgreSQL in {total_elapsed:.3f}s "
            f"({throughput:.1f} tweets/sec)"
        )
        return True

    except Exception as e:
        logger.error(f"Error upserting tweets to database: {e}")
        return False


def process_twitter_urls_from_discord(
    twitter_urls: List[str],
    discord_message_time: Optional[datetime] = None,
    twitter_client=None,
    write_parquet: bool = True,
    write_database: bool = True,
) -> Dict[str, Any]:
    """
    Complete pipeline for processing Twitter URLs from Discord messages.

    Args:
        twitter_urls: List of X/Twitter URLs
        discord_message_time: When the Discord message was sent
        twitter_client: Twitter API client for fetching tweet data
        write_parquet: Whether to write to Parquet files
        write_database: Whether to write to database

    Returns:
        Dictionary with processing results
    """
    if not twitter_urls:
        return {"success": True, "processed_count": 0, "message": "No URLs to process"}

    try:
        # Extract tweet IDs and fetch data
        raw_tweets = []
        for url in twitter_urls:
            tweet_id = extract_tweet_id(url)
            if tweet_id:
                tweet_data = fetch_tweet_data(tweet_id, twitter_client)
                if tweet_data:
                    raw_tweets.append(tweet_data)

        if not raw_tweets:
            return {
                "success": True,
                "processed_count": 0,
                "message": "No valid tweets found",
            }

        # Build DataFrame
        df = build_x_posts_df(raw_tweets, discord_message_time)

        if df.empty:
            return {
                "success": True,
                "processed_count": 0,
                "message": "No tweets processed",
            }

        results = {
            "success": True,
            "processed_count": len(df),
            "parquet_written": False,
            "database_written": False,
        }

        # Write to Parquet
        if write_parquet:
            try:
                parquet_path = write_x_posts_parquet(df)
                results["parquet_written"] = True
                results["parquet_path"] = str(parquet_path)
            except Exception as e:
                logger.error(f"Error writing to Parquet: {e}")
                results["parquet_error"] = str(e)

        # Write to database
        if write_database:
            try:
                db_success = upsert_x_posts_db(df)
                results["database_written"] = db_success
                if not db_success:
                    results["database_error"] = "Database upsert failed"
            except Exception as e:
                logger.error(f"Error writing to database: {e}")
                results["database_error"] = str(e)

        # Add summary statistics
        results["unique_tickers"] = len(
            set(ticker for tickers in df["tickers"] for ticker in tickers)
        )
        results["total_tickers"] = sum(len(tickers) for tickers in df["tickers"])

        logger.info(
            f"Processed {len(df)} tweets with {results['total_tickers']} total tickers"
        )
        return results

    except Exception as e:
        logger.error(f"Error in Twitter processing pipeline: {e}")
        return {"success": False, "error": str(e), "processed_count": 0}


# ============================================================================
# BATCH BACKFILL FUNCTIONS WITH RATE LIMIT PROTECTION
# ============================================================================


def backfill_tweets_from_discord(
    twitter_client: Optional[Any] = None,
    max_tweets: int = 10,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """
    Backfill tweet data from Discord messages containing Twitter/X links.

    This function queries discord_messages for Twitter links, fetches tweet data
    with rate limit protection, and updates the twitter_data table.

    Args:
        twitter_client: Tweepy client (uses default if None)
        max_tweets: Maximum number of tweets to process in this batch
        dry_run: If True, only report what would be processed without making API calls

    Returns:
        Dictionary with processing results including:
        - processed_count: Number of tweets successfully processed
        - skipped_count: Number skipped due to rate limits
        - error_count: Number of errors encountered
        - rate_limited: Whether processing stopped due to rate limits
        - tweet_ids: List of tweet IDs processed
    """
    results = {
        "success": True,
        "processed_count": 0,
        "skipped_count": 0,
        "error_count": 0,
        "rate_limited": False,
        "tweet_ids": [],
        "errors": [],
    }

    try:
        from src.db import execute_sql

        # Query Discord messages for Twitter/X links
        query = """
            SELECT message_id, content, created_at
            FROM discord_messages
            WHERE content LIKE '%twitter.com%' OR content LIKE '%x.com%'
            ORDER BY created_at DESC NULLS LAST
            LIMIT :limit
        """

        messages = execute_sql(
            query, params={"limit": max_tweets * 2}, fetch_results=True
        )

        if not messages:
            results["message"] = "No Discord messages with Twitter links found"
            return results

        logger.info(f"Found {len(messages)} Discord messages with Twitter links")

        if dry_run:
            # Just report what we found
            tweet_ids_found = []
            for msg in messages:
                msg_id, content, sent_at = msg
                urls = detect_twitter_links(content)
                for url in urls:
                    tweet_id = extract_tweet_id(url)
                    if tweet_id:
                        tweet_ids_found.append(tweet_id)

            results["dry_run"] = True
            results["tweet_ids"] = list(set(tweet_ids_found))
            results["message"] = (
                f"Dry run: Found {len(results['tweet_ids'])} unique tweet IDs to process"
            )
            return results

        # Create Twitter client if not provided
        if not twitter_client:
            twitter_client = get_twitter_client()
            if not twitter_client:
                results["success"] = False
                results["error"] = (
                    "Failed to create Twitter client. Check TWITTER_BEARER_TOKEN."
                )
                return results

        # Check rate limit before starting
        if is_rate_limited():
            wait_time = get_rate_limit_wait_time()
            results["rate_limited"] = True
            results["message"] = f"Rate limited. Try again in {wait_time:.0f} seconds"
            results["wait_seconds"] = wait_time
            return results

        # Process each message
        processed_tweet_ids = set()

        for msg in messages:
            # Check if we've hit our batch limit
            if results["processed_count"] >= max_tweets:
                results["message"] = f"Batch limit of {max_tweets} reached"
                break

            # Check rate limit before each API call
            if is_rate_limited():
                wait_time = get_rate_limit_wait_time()
                results["rate_limited"] = True
                results["message"] = (
                    f"Rate limited after {results['processed_count']} tweets. Wait {wait_time:.0f}s"
                )
                results["wait_seconds"] = wait_time
                break

            msg_id, content, sent_at = msg
            urls = detect_twitter_links(content)

            for url in urls:
                tweet_id = extract_tweet_id(url)

                if not tweet_id:
                    continue

                # Skip if already processed in this batch
                if tweet_id in processed_tweet_ids:
                    continue

                try:
                    # Fetch tweet data with rate limit respect
                    tweet_data = fetch_tweet_data(
                        tweet_id, twitter_client=twitter_client, respect_rate_limit=True
                    )

                    if tweet_data:
                        # Check if this is a rate limit response
                        if tweet_data.get("rate_limited"):
                            results["rate_limited"] = True
                            results["wait_seconds"] = tweet_data.get(
                                "wait_seconds", 900
                            )
                            results["message"] = (
                                f"Rate limited. Processed {results['processed_count']} tweets"
                            )
                            break

                        # Log to database
                        success = log_tweet_to_database(tweet_data, msg_id)

                        if success:
                            results["processed_count"] += 1
                            processed_tweet_ids.add(tweet_id)
                            results["tweet_ids"].append(tweet_id)
                            logger.info(f"Successfully backfilled tweet {tweet_id}")
                        else:
                            results["error_count"] += 1
                            results["errors"].append(f"Failed to save tweet {tweet_id}")
                    else:
                        results["skipped_count"] += 1

                except Exception as e:
                    results["error_count"] += 1
                    results["errors"].append(
                        f"Error processing tweet {tweet_id}: {str(e)}"
                    )
                    logger.error(f"Error processing tweet {tweet_id}: {e}")

            # Break outer loop if rate limited
            if results.get("rate_limited"):
                break

        if not results.get("message"):
            results["message"] = (
                f"Backfill complete: {results['processed_count']} processed, {results['skipped_count']} skipped, {results['error_count']} errors"
            )

        return results

    except Exception as e:
        logger.error(f"Error in backfill_tweets_from_discord: {e}")
        results["success"] = False
        results["error"] = str(e)
        return results


def reprocess_incomplete_tweets(
    twitter_client: Optional[Any] = None,
    max_tweets: int = 5,
) -> Dict[str, Any]:
    """
    Reprocess tweets that have incomplete data (null content/author).

    Args:
        twitter_client: Tweepy client (uses default if None)
        max_tweets: Maximum number of tweets to reprocess

    Returns:
        Dictionary with processing results
    """
    results = {
        "success": True,
        "processed_count": 0,
        "error_count": 0,
        "tweet_ids": [],
    }

    try:
        from src.db import execute_sql

        # Find tweets with null/empty content or author
        query = """
            SELECT tweet_id, message_id
            FROM twitter_data
            WHERE author_username IS NULL
               OR author_username = ''
               OR content IS NULL
               OR content = ''
            ORDER BY retrieved_at DESC NULLS LAST
            LIMIT :limit
        """

        incomplete_tweets = execute_sql(
            query, params={"limit": max_tweets}, fetch_results=True
        )

        if not incomplete_tweets:
            results["message"] = "No incomplete tweets found to reprocess"
            return results

        logger.info(f"Found {len(incomplete_tweets)} incomplete tweets to reprocess")

        # Create Twitter client if not provided
        if not twitter_client:
            twitter_client = get_twitter_client()
            if not twitter_client:
                results["success"] = False
                results["error"] = (
                    "Failed to create Twitter client. Check TWITTER_BEARER_TOKEN."
                )
                return results

        # Check rate limit
        if is_rate_limited():
            wait_time = get_rate_limit_wait_time()
            results["rate_limited"] = True
            results["message"] = f"Rate limited. Try again in {wait_time:.0f} seconds"
            results["wait_seconds"] = wait_time
            return results

        for tweet_id, message_id in incomplete_tweets:
            if is_rate_limited():
                wait_time = get_rate_limit_wait_time()
                results["rate_limited"] = True
                results["message"] = (
                    f"Rate limited after {results['processed_count']} tweets"
                )
                results["wait_seconds"] = wait_time
                break

            try:
                tweet_data = fetch_tweet_data(
                    tweet_id, twitter_client=twitter_client, respect_rate_limit=True
                )

                if tweet_data and not tweet_data.get("rate_limited"):
                    success = log_tweet_to_database(tweet_data, message_id)
                    if success:
                        results["processed_count"] += 1
                        results["tweet_ids"].append(tweet_id)
                        logger.info(f"Reprocessed tweet {tweet_id}")
                    else:
                        results["error_count"] += 1
                elif tweet_data and tweet_data.get("rate_limited"):
                    results["rate_limited"] = True
                    break

            except Exception as e:
                results["error_count"] += 1
                logger.error(f"Error reprocessing tweet {tweet_id}: {e}")

        if not results.get("message"):
            results["message"] = (
                f"Reprocessed {results['processed_count']} tweets, {results['error_count']} errors"
            )

        return results

    except Exception as e:
        logger.error(f"Error in reprocess_incomplete_tweets: {e}")
        results["success"] = False
        results["error"] = str(e)
        return results


def get_twitter_pipeline_status() -> Dict[str, Any]:
    """
    Get the current status of the Twitter data pipeline.

    Returns:
        Dictionary with pipeline status including:
        - total_tweets: Total tweets in database
        - complete_tweets: Tweets with full data
        - incomplete_tweets: Tweets missing content/author
        - discord_messages_with_links: Discord messages containing Twitter links
        - rate_limit_status: Current rate limit state
    """
    status = {
        "rate_limit": {
            "is_limited": is_rate_limited(),
            "wait_seconds": get_rate_limit_wait_time() if is_rate_limited() else 0,
        }
    }

    try:
        from src.db import execute_sql

        # Count total tweets
        total = execute_sql("SELECT COUNT(*) FROM twitter_data", fetch_results=True)
        status["total_tweets"] = total[0][0] if total else 0

        # Count complete tweets
        complete = execute_sql(
            """SELECT COUNT(*) FROM twitter_data
               WHERE author_username IS NOT NULL
               AND author_username != ''
               AND content IS NOT NULL
               AND content != ''""",
            fetch_results=True,
        )
        status["complete_tweets"] = complete[0][0] if complete else 0

        # Count incomplete tweets
        status["incomplete_tweets"] = status["total_tweets"] - status["complete_tweets"]

        # Count Discord messages with Twitter links
        discord_links = execute_sql(
            """SELECT COUNT(*) FROM discord_messages
               WHERE content LIKE '%twitter.com%' OR content LIKE '%x.com%'""",
            fetch_results=True,
        )
        status["discord_messages_with_links"] = (
            discord_links[0][0] if discord_links else 0
        )

        status["success"] = True

    except Exception as e:
        logger.error(f"Error getting pipeline status: {e}")
        status["success"] = False
        status["error"] = str(e)

    return status
