"""
Discord Data Management Module

Handles channel-specific data processing, deduplication, and database operations.
Ensures that Discord messages are efficiently processed without duplicates.
Delegates all cleaning logic to the message_cleaner module.
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any

import pandas as pd

from src.message_cleaner import process_messages_for_channel

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parents[1]
RAW_DIR = BASE_DIR / "data" / "raw"
PROCESSED_DIR = BASE_DIR / "data" / "processed"
DB_DIR = BASE_DIR / "data" / "database"

# Ensure directories exist
PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
DB_DIR.mkdir(parents=True, exist_ok=True)

DISCORD_CSV = RAW_DIR / "discord_msgs.csv"


def get_processed_message_ids():
    """Get set of message IDs that have already been processed."""
    try:
        from src.database import execute_sql

        result = execute_sql(
            "SELECT message_id FROM discord_processing_log", fetch_results=True
        )
        processed_ids = {row[0] for row in result} if result else set()
        return processed_ids
    except Exception as e:
        logger.warning(f"Could not fetch processed message IDs: {e}")
        return set()


def mark_messages_as_processed(
    message_ids: List[str], channel: str, processed_file: str
):
    """Mark messages as processed in the tracking table."""
    try:
        from src.database import execute_sql

        processed_date = datetime.now().isoformat()

        # Insert records using unified database layer
        for msg_id in message_ids:
            execute_sql(
                """
                INSERT OR REPLACE INTO discord_processing_log 
                (message_id, channel, processed_date, processed_file) 
                VALUES (?, ?, ?, ?)
            """,
                (msg_id, channel, processed_date, processed_file),
            )

        logger.info(
            f"Marked {len(message_ids)} messages as processed for channel {channel}"
        )
    except Exception as e:
        logger.error(f"Error marking messages as processed: {e}")


def clean_discord_messages_for_channel(
    channel_name: str, force_reprocess: bool = False
) -> Path | None:
    """
    Clean and process Discord messages for a specific channel using the unified message cleaner.

    Args:
        channel_name: Name of the Discord channel
        force_reprocess: If True, reprocess all messages regardless of processing status

    Returns:
        Path to the processed parquet file or None if no processing occurred
    """
    try:
        # Load raw Discord data
        if not DISCORD_CSV.exists():
            logger.warning(f"Raw Discord data file not found: {DISCORD_CSV}")
            return None

        df = pd.read_csv(DISCORD_CSV)
        logger.info(f"Loaded {len(df)} total Discord messages")

        # Filter for the specific channel
        channel_df = df[df["channel"] == channel_name].copy()
        if channel_df.empty:
            logger.warning(f"No messages found for channel: {channel_name}")
            return None

        logger.info(f"Found {len(channel_df)} messages for channel {channel_name}")

        # Get already processed message IDs if not forcing reprocess
        processed_ids = set() if force_reprocess else get_processed_message_ids()

        # Filter to only unprocessed messages
        if not force_reprocess:
            channel_df = channel_df[
                ~channel_df["message_id"].astype(str).isin(processed_ids)
            ]
            logger.info(
                f"Found {len(channel_df)} unprocessed messages for channel {channel_name}"
            )

        if channel_df.empty:
            logger.info(f"No new messages to process for channel {channel_name}")
            return None

        # Convert DataFrame to list of dicts for the message cleaner
        message_dicts = []
        for _, row in channel_df.iterrows():
            message_dict = {
                "message_id": str(row.get("message_id", "")),
                "author": str(row.get("author_name", row.get("author", ""))),
                "content": str(row.get("content", "")),
                "channel": str(row.get("channel", channel_name)),
                "created_at": str(row.get("created_at", row.get("timestamp", ""))),
            }
            message_dicts.append(message_dict)

        # Determine channel type (trading if contains trading-related terms)
        channel_type = (
            "trading"
            if any(
                term in channel_name.lower()
                for term in ["trade", "trading", "stock", "market"]
            )
            else "general"
        )

        # Process messages using the unified cleaner
        output_file = PROCESSED_DIR / f"discord_msgs_clean_{channel_name}.parquet"

        cleaned_df, stats = process_messages_for_channel(
            messages=message_dicts,
            channel_name=channel_name,
            channel_type=channel_type,
            output_dir=PROCESSED_DIR,
            save_parquet=True,
            save_database=False,  # We'll let channel_processor handle database writes
        )

        if not cleaned_df.empty:
            # Mark messages as processed
            message_ids = cleaned_df["message_id"].astype(str).tolist()
            mark_messages_as_processed(message_ids, channel_name, str(output_file))

            logger.info(
                f"Successfully processed {len(cleaned_df)} messages for channel {channel_name}"
            )
            logger.info(f"Processing stats: {stats}")
            return output_file
        else:
            logger.info(f"No messages were processed for channel {channel_name}")
            return None

    except Exception as e:
        logger.error(
            f"Error processing Discord messages for channel {channel_name}: {e}"
        )
        return None


def process_all_channels(force_reprocess: bool = False) -> List[Path]:
    """Process messages for all channels found in the raw data using the unified cleaner."""
    try:
        if not DISCORD_CSV.exists():
            logger.warning(f"Raw Discord data file not found: {DISCORD_CSV}")
            return []

        df = pd.read_csv(DISCORD_CSV)
        channels = df["channel"].unique()

        processed_files = []
        for channel in channels:
            if pd.notna(channel):  # Skip NaN channel names
                output_file = clean_discord_messages_for_channel(
                    channel, force_reprocess
                )
                if output_file:
                    processed_files.append(output_file)

        return processed_files

    except Exception as e:
        logger.error(f"Error processing all channels: {e}")
        return []


def get_channel_stats() -> Dict[str, Any]:
    """Get statistics about processed channels."""
    try:
        stats = {}

        # Get stats from processed files
        for file_path in PROCESSED_DIR.glob("discord_msgs_clean_*.parquet"):
            channel_name = file_path.stem.replace("discord_msgs_clean_", "")
            try:
                df = pd.read_parquet(file_path)
                stats[channel_name] = {
                    "total_messages": len(df),
                    "date_range": {
                        "start": (
                            df["timestamp"].min().isoformat()
                            if len(df) > 0 and "timestamp" in df.columns
                            else None
                        ),
                        "end": (
                            df["timestamp"].max().isoformat()
                            if len(df) > 0 and "timestamp" in df.columns
                            else None
                        ),
                    },
                    "avg_sentiment": (
                        df["sentiment"].mean()
                        if "sentiment" in df.columns and len(df) > 0
                        else None
                    ),
                    "total_tickers": (
                        sum(
                            len(tickers)
                            for tickers in df["tickers"]
                            if isinstance(tickers, list)
                        )
                        if "tickers" in df.columns
                        else 0
                    ),
                    "unique_tickers": (
                        len(
                            set(
                                ticker
                                for tickers in df["tickers"]
                                for ticker in tickers
                                if isinstance(tickers, list)
                            )
                        )
                        if "tickers" in df.columns
                        else 0
                    ),
                    "file_path": str(file_path),
                }
            except Exception as e:
                logger.warning(f"Could not read stats for {file_path}: {e}")

        return stats

    except Exception as e:
        logger.error(f"Error getting channel stats: {e}")
        return {}


if __name__ == "__main__":
    # Example usage
    logging.basicConfig(level=logging.INFO)

    # Process all channels
    processed_files = process_all_channels()
    print(f"Processed {len(processed_files)} channels")

    # Show stats
    stats = get_channel_stats()
    for channel, channel_stats in stats.items():
        print(f"\nChannel: {channel}")
        print(f"  Messages: {channel_stats['total_messages']}")
        print(
            f"  Avg Sentiment: {channel_stats['avg_sentiment']:.3f}"
            if channel_stats["avg_sentiment"]
            else "  Avg Sentiment: N/A"
        )
        print(f"  Total Tickers: {channel_stats['total_tickers']}")
        print(f"  Unique Tickers: {channel_stats['unique_tickers']}")
