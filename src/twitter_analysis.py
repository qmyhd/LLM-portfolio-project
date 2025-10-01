import csv
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import pandas as pd

try:
    from textblob import TextBlob

    TEXTBLOB_AVAILABLE = True
except ImportError:
    TEXTBLOB_AVAILABLE = False

# Import message cleaning functions
from src.message_cleaner import extract_ticker_symbols, clean_text

logger = logging.getLogger(__name__)

TWEET_URL_RE = re.compile(
    r"https?://(?:www\.)?(?:x\.com|twitter\.com)/([A-Za-z0-9_]+)/status/(\d+)"
)


def detect_twitter_links(text: str) -> list[str]:
    if not text:
        return []
    return list({m.group(0) for m in TWEET_URL_RE.finditer(text)})


def extract_tweet_id(url: str):
    m = TWEET_URL_RE.search(url)
    return m.group(2) if m else None


def analyze_sentiment(text: str) -> float:
    if not text or not TEXTBLOB_AVAILABLE:
        return 0.0
    try:
        blob = TextBlob(text)
        # Type ignore for TextBlob sentiment property access
        return float(blob.sentiment.polarity)  # type: ignore
    except Exception as e:
        logger.error(f"Error analyzing sentiment: {e}")
        return 0.0


def fetch_tweet_data(tweet_id: str, twitter_client=None):
    """Fetch tweet data using tweepy.Client if provided."""
    if not twitter_client:
        logger.debug("No twitter_client provided, skipping fetch.")
        return None
    try:
        tid = int(tweet_id)
        tweet = twitter_client.get_tweet(
            tid,
            expansions=["author_id"],
            tweet_fields=["created_at", "public_metrics", "text"],
            user_fields=["name", "username"],
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
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
        }
        return data
    except Exception as e:
        logger.error(f"Error fetching tweet {tweet_id}: {e}")
        return None


def log_tweet_to_file(tweet_data: dict, discord_message_id: int, csv_path: Path):
    """Log tweet data to both CSV (for backward compatibility) and database."""
    if not tweet_data:
        return

    # Log to CSV file (existing functionality)
    file_exists = csv_path.exists()
    row = dict(tweet_data)
    row["discord_message_id"] = discord_message_id
    with open(csv_path, "a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=row.keys())
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)

    # Also log to database
    log_tweet_to_database(tweet_data, discord_message_id)


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
        }

        execute_sql(
            """
            INSERT INTO twitter_data 
            (tweet_id, message_id, content, author, channel, discord_message_id,
             discord_sent_date, discord_date, tweet_date, tweet_created_date, tweet_content, author_username, 
             author_name, retweet_count, like_count, reply_count, quote_count, 
             stock_tags, source_url, retrieved_at)
            VALUES (:tweet_id, :message_id, :content, :author, :channel, :discord_message_id,
                   :discord_sent_date, :discord_date, :tweet_date, :tweet_created_date, :tweet_content, :author_username, 
                   :author_name, :retweet_count, :like_count, :reply_count, :quote_count, 
                   :stock_tags, :source_url, :retrieved_at)
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
                retrieved_at = EXCLUDED.retrieved_at
            """,
            tweet_record,
        )

        logger.info(
            f"✅ Logged tweet {tweet_data.get('tweet_id')} to database with {len(stock_tags)} stock tags"
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


def upsert_x_posts_db(df: pd.DataFrame, db_url: Optional[str] = None) -> bool:
    """
    Upsert X/Twitter posts to database with conflict resolution.

    Args:
        df: DataFrame with X/Twitter posts
        db_url: Database URL (optional, will use default if not provided)

    Returns:
        True if successful, False otherwise
    """
    if df.empty:
        logger.info("Empty DataFrame provided to upsert_x_posts_db")
        return True

    try:
        from src.db import execute_sql

        # Prepare DataFrame for database insertion
        db_df = df.copy()

        # PostgreSQL: keep tickers as list for TEXT[] column
        db_df["tickers"] = db_df["tickers"].apply(
            lambda x: x if isinstance(x, list) else []
        )

        # Convert timestamps to appropriate format for PostgreSQL
        # PostgreSQL: keep as timezone-aware timestamps (pandas handles this correctly)

        # PostgreSQL upsert with ON CONFLICT using execute_sql
        for _, row in db_df.iterrows():
            execute_sql(
                """
                INSERT INTO twitter_data.x_posts_log 
                (tweet_id, tweet_time, discord_message_time, tweet_text, 
                 tickers, author_id, conversation_id)
                VALUES (:tweet_id, :tweet_time, :discord_message_time, :tweet_text, 
                       :tickers, :author_id, :conversation_id)
                ON CONFLICT (tweet_id) DO NOTHING
            """,
                {
                    "tweet_id": row["tweet_id"],
                    "tweet_time": row["tweet_time"],
                    "discord_message_time": row["discord_message_time"],
                    "tweet_text": row["tweet_text"],
                    "tickers": row["tickers"],
                    "author_id": row["author_id"],
                    "conversation_id": row["conversation_id"],
                },
            )

        logger.info(f"✅ Upserted {len(db_df)} tweets to PostgreSQL")
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
