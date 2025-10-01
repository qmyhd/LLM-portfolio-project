"""
Discord Message Cleaning Module

Centralized module for cleaning Discord messages with ticker extraction,
sentiment analysis, and deduplication. Supports both Parquet and database output.
"""

import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union, Literal

import pandas as pd
from textblob import TextBlob

from sqlalchemy import text

logger = logging.getLogger(__name__)


# Centralized table mapping for channel types
CHANNEL_TYPE_TO_TABLE = {
    "general": "discord_market_clean",
    "trading": "discord_trading_clean",
    "market": "discord_market_clean",  # Alternative name
}


def get_table_name_for_channel_type(channel_type: str) -> str:
    """Get the database table name for a given channel type.

    Args:
        channel_type: The type of Discord channel

    Returns:
        Database table name for the channel type

    Raises:
        ValueError: If channel_type is not recognized
    """
    normalized_type = channel_type.lower().strip()

    if normalized_type not in CHANNEL_TYPE_TO_TABLE:
        raise ValueError(
            f"Unknown channel type '{channel_type}'. "
            f"Valid types: {list(CHANNEL_TYPE_TO_TABLE.keys())}"
        )

    return CHANNEL_TYPE_TO_TABLE[normalized_type]


def extract_ticker_symbols(text: str | None) -> List[str]:
    """Extract ticker symbols from text, matching $TICKER format anywhere in the text.

    Args:
        text: The text to extract ticker symbols from

    Returns:
        List of unique ticker symbols in order of appearance
    """
    if not text:
        return []

    # Use a simpler regex pattern that matches $TICKER format
    # Find tickers like $AAPL, $MSFT, etc.
    pattern = r"\$[A-Z]{1,6}(?=[^A-Z]|$)"
    matches = re.findall(pattern, text)

    # Remove duplicates while preserving order
    unique_tickers = []
    for ticker in matches:
        if ticker not in unique_tickers:
            unique_tickers.append(ticker)

    return unique_tickers


def clean_text(text: str) -> str:
    """Clean and normalize text content.

    Args:
        text: Raw text content to clean

    Returns:
        Cleaned text with URLs, mentions, and extra whitespace removed
    """
    if not isinstance(text, str):
        return ""

    # Remove URLs
    text = re.sub(
        r"http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+",
        "",
        text,
    )

    # Remove Discord mentions and channels
    text = re.sub(r"<@!?\d+>", "", text)
    text = re.sub(r"<#\d+>", "", text)

    # Remove extra whitespace
    text = " ".join(text.split())

    return text.strip()


def calculate_sentiment(text: str) -> float:
    """Calculate sentiment score for text using TextBlob.

    Args:
        text: Text to analyze sentiment for

    Returns:
        Sentiment polarity score (-1.0 to 1.0)
    """
    if not isinstance(text, str) or not text.strip():
        return 0.0

    try:
        blob = TextBlob(text)
        # Type ignore for TextBlob sentiment property access
        return float(blob.sentiment.polarity)  # type: ignore
    except Exception as e:
        logger.warning(f"Error calculating sentiment for text '{text[:50]}...': {e}")
        return 0.0


def extract_tweet_urls(text: str) -> List[str]:
    """Extract Twitter/X URLs from text.

    Args:
        text: Text containing potential tweet URLs

    Returns:
        List of found tweet URLs
    """
    if not isinstance(text, str):
        return []

    # Pattern for Twitter/X URLs
    twitter_pattern = r"https?://(?:twitter\.com|x\.com)/\w+/status/\d+"
    urls = re.findall(twitter_pattern, text)
    return urls


def clean_messages(
    messages: Union[pd.DataFrame, List[Dict[str, Any]]],
    channel_type: str = "general",
    deduplication_key: str = "message_id",
) -> pd.DataFrame:
    """Clean a list or DataFrame of Discord messages.

    Args:
        messages: Raw messages as DataFrame or list of dicts
        channel_type: Type of channel ("trading" or "general") for specialized processing
        deduplication_key: Column name to use for deduplication

    Returns:
        Cleaned DataFrame with standardized columns
    """
    # Convert to DataFrame if needed
    if isinstance(messages, list):
        df = pd.DataFrame(messages)
    else:
        df = messages.copy()

    if df.empty:
        logger.info("No messages to clean")
        return pd.DataFrame()

    logger.info(f"Starting to clean {len(df)} messages for {channel_type} channel")

    # Ensure required columns exist
    required_columns = ["message_id", "content", "author", "channel", "created_at"]
    missing_columns = [col for col in required_columns if col not in df.columns]
    if missing_columns:
        logger.error(f"Missing required columns: {missing_columns}")
        raise ValueError(f"Missing required columns: {missing_columns}")

    # Deduplication by message_id - ensure DataFrame return
    original_count = len(df)
    df = df.drop_duplicates(subset=[deduplication_key]).copy()
    if len(df) < original_count:
        logger.info(f"Removed {original_count - len(df)} duplicate messages")

    # Parse timestamp
    if "timestamp" not in df.columns and "created_at" in df.columns:
        df["timestamp"] = df["created_at"]

    try:
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    except Exception as e:
        logger.warning(f"Error parsing timestamps: {e}")
        df["timestamp"] = pd.Timestamp.now(tz="UTC")

    # Text cleaning
    df["cleaned_content"] = df["content"].fillna("").astype(str).apply(clean_text)

    # Sentiment analysis
    df["sentiment"] = df["cleaned_content"].apply(calculate_sentiment)

    # Ticker symbol extraction
    df["tickers"] = df["content"].fillna("").astype(str).apply(extract_ticker_symbols)
    df["tickers_str"] = df["tickers"].apply(lambda x: ", ".join(x) if x else "")

    # Tweet URL extraction
    df["tweet_urls"] = df["content"].fillna("").astype(str).apply(extract_tweet_urls)
    df["tweet_urls_str"] = df["tweet_urls"].apply(lambda x: ", ".join(x) if x else "")

    # Additional features
    df["char_len"] = df["content"].fillna("").astype(str).str.len()
    df["word_len"] = df["content"].fillna("").astype(str).str.split().str.len()
    df["is_command"] = (
        df["content"].fillna("").astype(str).str.startswith("!", na=False)
    )

    # Channel-specific processing
    if channel_type.lower() == "trading":
        # Additional trading-specific features could go here
        df["has_tickers"] = df["tickers"].apply(lambda x: len(x) > 0)
        df["ticker_count"] = df["tickers"].apply(len)

    # Sort by timestamp - ensure DataFrame return
    df = df.sort_values("timestamp").copy()

    # Standardize column names for output
    standard_columns = [
        "message_id",
        "timestamp",
        "channel",
        "author",
        "content",
        "cleaned_content",
        "sentiment",
        "tickers",
        "tickers_str",
        "tweet_urls",
        "tweet_urls_str",
        "char_len",
        "word_len",
        "is_command",
    ]

    # Add trading-specific columns if applicable
    if channel_type.lower() == "trading":
        standard_columns.extend(["has_tickers", "ticker_count"])

    # Only keep columns that exist - ensure DataFrame return
    available_columns = [col for col in standard_columns if col in df.columns]

    # Ensure we always return a DataFrame, never a Series
    if available_columns:
        # Use double brackets to ensure DataFrame return even with single column
        result_df = df[available_columns].copy()
    else:
        # If no columns available, return empty DataFrame with proper structure
        result_df = pd.DataFrame()

    # Final safeguard: ensure we're returning a DataFrame
    if not isinstance(result_df, pd.DataFrame):
        logger.warning("Converting non-DataFrame result to DataFrame")
        result_df = pd.DataFrame(result_df)

    logger.info(f"Successfully cleaned {len(result_df)} messages")
    return result_df


def save_to_parquet(
    df: pd.DataFrame,
    file_path: Union[str, Path],
    compression: Literal["snappy", "gzip", "brotli", "lz4", "zstd"] = "snappy",
) -> bool:
    """Save cleaned DataFrame to Parquet file.

    Args:
        df: Cleaned DataFrame to save
        file_path: Path to save the Parquet file
        compression: Compression method to use

    Returns:
        True if successful, False otherwise
    """
    try:
        file_path = Path(file_path)
        file_path.parent.mkdir(parents=True, exist_ok=True)

        df.to_parquet(file_path, compression=compression, index=False)
        logger.info(f"Saved {len(df)} messages to {file_path}")
        return True
    except Exception as e:
        logger.error(f"Error saving to Parquet: {e}")
        return False


def append_to_parquet(
    df: pd.DataFrame,
    file_path: Union[str, Path],
    compression: Literal["snappy", "gzip", "brotli", "lz4", "zstd"] = "snappy",
    deduplication_key: str = "message_id",
) -> bool:
    """Append cleaned DataFrame to existing Parquet file with deduplication.

    Args:
        df: New DataFrame to append
        file_path: Path to existing Parquet file
        compression: Compression method to use
        deduplication_key: Column to use for deduplication

    Returns:
        True if successful, False otherwise
    """
    try:
        file_path = Path(file_path)

        if file_path.exists():
            # Load existing data
            existing_df = pd.read_parquet(file_path)
            # Combine and deduplicate
            combined_df = pd.concat([existing_df, df], ignore_index=True)
            combined_df = combined_df.drop_duplicates(
                subset=[deduplication_key], keep="last"
            )
            combined_df = (
                combined_df.sort_values("timestamp")
                if "timestamp" in combined_df.columns
                else combined_df
            )
        else:
            combined_df = df

        return save_to_parquet(combined_df, file_path, compression)
    except Exception as e:
        logger.error(f"Error appending to Parquet: {e}")
        return False


def save_to_database(
    df: pd.DataFrame,
    table_name: str,
    connection,
    if_exists: Literal["append", "replace", "fail"] = "append",
) -> bool:
    """Save cleaned DataFrame to database table using psycopg named parameters.

    Args:
        df: Cleaned DataFrame to save
        table_name: Name of the database table
        connection: Database connection object
        if_exists: How to behave if table exists ('append', 'replace', 'fail')

    Returns:
        True if successful, False otherwise
    """
    try:
        # Prepare DataFrame for database insertion
        db_df = df.copy()

        # Map columns to match database schema
        column_mapping = {
            "tickers_str": "stock_mentions",
            "author": "author_name" if "author_name" not in db_df.columns else "author",
            "tweet_urls_str": "tweet_urls",
        }

        # Rename columns
        for old_col, new_col in column_mapping.items():
            if old_col in db_df.columns:
                db_df = db_df.rename(columns={old_col: new_col})

        # Drop columns that aren't needed for database storage
        columns_to_drop = (
            ["tickers", "tweet_urls"] if "tweet_urls" in db_df.columns else ["tickers"]
        )
        db_df = db_df.drop(
            columns=[col for col in columns_to_drop if col in db_df.columns]
        )

        # Ensure timestamp is properly formatted as string for consistency
        if "timestamp" in db_df.columns:
            # Convert timestamp column to string format safely
            try:
                db_df["timestamp"] = db_df["timestamp"].apply(
                    lambda x: (
                        pd.to_datetime(x, errors="coerce").strftime("%Y-%m-%d %H:%M:%S")
                        if pd.notna(pd.to_datetime(x, errors="coerce"))
                        else str(x)
                    )
                )
            except Exception:
                # Fallback: keep as string if conversion fails
                db_df["timestamp"] = db_df["timestamp"].astype(str)

        # Use proper psycopg named parameters for PostgreSQL
        from src.db import execute_sql
        from sqlalchemy import text

        # Build column list for INSERT statement with named placeholders
        columns = list(db_df.columns)
        columns_str = ", ".join(columns)
        placeholders = ", ".join([f":{col}" for col in columns])

        # Build INSERT with ON CONFLICT for idempotency
        if table_name in ["discord_market_clean", "discord_trading_clean"]:
            insert_sql = f"""
            INSERT INTO {table_name} ({columns_str})
            VALUES ({placeholders})
            ON CONFLICT (message_id) DO UPDATE SET
                {", ".join([f"{col} = EXCLUDED.{col}" for col in columns if col != "message_id"])}
            """
        else:
            insert_sql = f"""
            INSERT INTO {table_name} ({columns_str})
            VALUES ({placeholders})
            ON CONFLICT DO NOTHING
            """

        # Execute bulk insert using named parameters
        records = db_df.to_dict("records")
        execute_sql(insert_sql, records)

        logger.info(f"Saved {len(db_df)} messages to database table {table_name}")
        return True
    except Exception as e:
        logger.error(f"Error saving to database: {e}")
        return False


def process_messages_for_channel(
    messages: Union[pd.DataFrame, List[Dict[str, Any]]],
    channel_name: str,
    channel_type: str = "general",
    output_dir: Optional[Union[str, Path]] = None,
    database_connection=None,
    save_parquet: bool = True,
    save_database: bool = True,
) -> Tuple[pd.DataFrame, Dict[str, Any]]:
    """Complete processing pipeline for Discord messages.

    Args:
        messages: Raw messages to process
        channel_name: Name of the Discord channel
        channel_type: Type of channel ("trading" or "general")
        output_dir: Directory to save Parquet files
        database_connection: Database connection for saving
        save_parquet: Whether to save to Parquet file
        save_database: Whether to save to database

    Returns:
        Tuple of (cleaned DataFrame, processing stats)
    """
    start_time = datetime.now()

    # Clean the messages
    cleaned_df = clean_messages(messages, channel_type)

    if cleaned_df.empty:
        return cleaned_df, {
            "success": True,
            "channel": channel_name,
            "processed_count": 0,
            "message": "No messages to process",
        }

    success_flags = {"parquet": True, "database": True}

    # Save to Parquet if requested
    if save_parquet and output_dir:
        output_dir = Path(output_dir)
        parquet_file = output_dir / f"discord_msgs_clean_{channel_name}.parquet"
        success_flags["parquet"] = append_to_parquet(cleaned_df, parquet_file)

    # Save to database if requested
    if save_database and database_connection:
        # Use centralized table mapping
        table_name = get_table_name_for_channel_type(channel_type)
        success_flags["database"] = save_to_database(
            cleaned_df, table_name, database_connection
        )

    processing_time = datetime.now() - start_time

    stats = {
        "success": all(success_flags.values()),
        "channel": channel_name,
        "channel_type": channel_type,
        "processed_count": len(cleaned_df),
        "processing_time_seconds": processing_time.total_seconds(),
        "parquet_saved": success_flags["parquet"],
        "database_saved": success_flags["database"],
        "avg_sentiment": cleaned_df["sentiment"].mean() if len(cleaned_df) > 0 else 0.0,
        "total_tickers": sum(len(tickers) for tickers in cleaned_df["tickers"]),
        "unique_tickers": len(
            set(ticker for tickers in cleaned_df["tickers"] for ticker in tickers)
        ),
    }

    logger.info(f"Processing complete for {channel_name}: {stats}")
    return cleaned_df, stats


if __name__ == "__main__":
    # Example usage and testing
    logging.basicConfig(level=logging.INFO)

    # Test with sample data
    sample_messages = [
        {
            "message_id": "1",
            "content": "Just bought $AAPL and $MSFT! 🚀",
            "author": "trader1",
            "channel": "trading",
            "created_at": "2025-09-19T10:00:00Z",
        },
        {
            "message_id": "2",
            "content": "Check out this tweet: https://twitter.com/user/status/123456",
            "author": "user2",
            "channel": "general",
            "created_at": "2025-09-19T11:00:00Z",
        },
    ]

    cleaned_df = clean_messages(sample_messages, "trading")
    print(f"Cleaned {len(cleaned_df)} messages")
    print(
        cleaned_df[["message_id", "cleaned_content", "sentiment", "tickers_str"]].head()
    )
