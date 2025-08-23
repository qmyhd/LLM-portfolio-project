"""
Channel-specific data processing module.
Handles cleaning and processing of Discord messages for different channels.
Delegates all cleaning logic to the message_cleaner module.
"""

import logging
from typing import Any, Dict

from src.database import (
    get_connection,
    get_unprocessed_messages,
    mark_message_processed,
    execute_sql,
)
from src.message_cleaner import process_messages_for_channel

logger = logging.getLogger(__name__)


def process_channel_data(
    channel_name: str, channel_type: str = "general"
) -> Dict[str, Any]:
    """Process unprocessed messages for a specific channel using the unified message cleaner.

    Args:
        channel_name: Name of the Discord channel
        channel_type: Type of channel ("trading" or "general")

    Returns:
        Dictionary with processing results and statistics
    """
    try:
        # Get unprocessed messages for the channel
        unprocessed_messages = get_unprocessed_messages(channel_name, "cleaning")

        if not unprocessed_messages:
            return {
                "success": True,
                "channel": channel_name,
                "processed_count": 0,
                "message": "No new messages to process",
            }

        # Convert raw message tuples to list of dicts for the message cleaner
        message_dicts = []
        for message in unprocessed_messages:
            # Expected format: (id, message_id, author, content, channel, timestamp, ...)
            if len(message) >= 6:
                message_dict = {
                    "message_id": message[1],
                    "author": message[2],
                    "content": message[3],
                    "channel": message[4],
                    "created_at": message[5],
                }
                message_dicts.append(message_dict)

        # Process messages using the unified cleaner
        with get_connection() as conn:
            cleaned_df, stats = process_messages_for_channel(
                messages=message_dicts,
                channel_name=channel_name,
                channel_type=channel_type,
                database_connection=conn,
                save_parquet=False,  # We'll handle this elsewhere if needed
                save_database=True,
            )

        # Mark messages as processed
        if not cleaned_df.empty:
            message_ids = cleaned_df["message_id"].tolist()
            for msg_id in message_ids:
                mark_message_processed(msg_id, channel_name, "cleaning")

        logger.info(
            f"Processed {stats['processed_count']} messages for channel {channel_name}"
        )

        return {
            "success": stats["success"],
            "channel": channel_name,
            "channel_type": channel_type,
            "processed_count": stats["processed_count"],
            "message": f"Successfully processed {stats['processed_count']} messages",
            "avg_sentiment": stats.get("avg_sentiment", 0.0),
            "total_tickers": stats.get("total_tickers", 0),
            "unique_tickers": stats.get("unique_tickers", 0),
        }

    except Exception as e:
        logger.error(f"Error processing channel {channel_name}: {e}")
        return {
            "success": False,
            "channel": channel_name,
            "processed_count": 0,
            "error": str(e),
        }


def get_channel_stats(channel_name: str | None = None) -> Dict[str, Any]:
    """Get statistics for processed channels.

    Args:
        channel_name: Optional channel name to filter stats

    Returns:
        Dictionary with channel statistics
    """
    try:
        with get_connection() as conn:
            stats = {}

            # Raw messages count
            if channel_name:
                result = execute_sql(
                    "SELECT COUNT(*) FROM discord_messages WHERE channel = ?",
                    (channel_name,),
                    fetch_results=True,
                )
            else:
                result = execute_sql(
                    "SELECT COUNT(*) FROM discord_messages", fetch_results=True
                )
            stats["raw_messages"] = result[0][0] if result else 0

            # Processed general messages
            if channel_name:
                result = execute_sql(
                    """
                    SELECT COUNT(*) FROM discord_general_clean dgc 
                    JOIN discord_messages dm ON dgc.message_id = dm.message_id 
                    WHERE dm.channel = ?
                """,
                    (channel_name,),
                    fetch_results=True,
                )
            else:
                result = execute_sql(
                    "SELECT COUNT(*) FROM discord_general_clean", fetch_results=True
                )
            stats["general_processed"] = result[0][0] if result else 0

            # Processed trading messages
            if channel_name:
                result = execute_sql(
                    """
                    SELECT COUNT(*) FROM discord_trading_clean dtc 
                    JOIN discord_messages dm ON dtc.message_id = dm.message_id 
                    WHERE dm.channel = ?
                """,
                    (channel_name,),
                    fetch_results=True,
                )
            else:
                result = execute_sql(
                    "SELECT COUNT(*) FROM discord_trading_clean", fetch_results=True
                )
            stats["trading_processed"] = result[0][0] if result else 0

            # Twitter data count
            if channel_name:
                result = execute_sql(
                    "SELECT COUNT(*) FROM twitter_data WHERE channel = ?",
                    (channel_name,),
                    fetch_results=True,
                )
            else:
                result = execute_sql(
                    "SELECT COUNT(*) FROM twitter_data", fetch_results=True
                )
            stats["twitter_data"] = result[0][0] if result else 0

            return stats

    except Exception as e:
        logger.error(f"Error getting channel stats: {e}")
        return {}
