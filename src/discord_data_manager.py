"""
Discord Data Management Module

Handles channel-specific data processing, deduplication, and database operations.
Ensures that Discord messages are efficiently processed without duplicates.
"""

import logging
import re
from datetime import datetime
from pathlib import Path

import pandas as pd
from textblob import TextBlob


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
        result = execute_sql("SELECT message_id FROM discord_processing_log", fetch_results=True)
        processed_ids = {row[0] for row in result} if result else set()
        return processed_ids
    except Exception as e:
        logger.warning(f"Could not fetch processed message IDs: {e}")
        return set()


def mark_messages_as_processed(message_ids, channel, processed_file):
    """Mark messages as processed in the tracking table."""
    try:
        # Use unified database layer instead of direct SQLite
        from src.database import execute_sql
        
        processed_date = datetime.now().isoformat()
        
        # Insert records using unified database layer
        for msg_id in message_ids:
            execute_sql('''
                INSERT OR REPLACE INTO discord_processing_log 
                (message_id, channel, processed_date, processed_file) 
                VALUES (?, ?, ?, ?)
            ''', (msg_id, channel, processed_date, processed_file))
        
        logger.info(f"Marked {len(message_ids)} messages as processed for channel {channel}")
    except Exception as e:
        logger.error(f"Error marking messages as processed: {e}")


def extract_stock_symbols_from_text(text):
    """Extract stock symbols from text content."""
    if not isinstance(text, str):
        return []
    
    # Find ticker patterns like $AAPL, $MSFT, etc.
    tickers = re.findall(r'\$[A-Z]{2,6}', text)
    # Also look for common stock mentions without $ 
    word_tickers = re.findall(r'\b[A-Z]{2,6}\b', text)
    
    # Combine and deduplicate
    all_tickers = list(set(tickers + [f'${t}' for t in word_tickers if len(t) <= 5]))
    return all_tickers


def clean_discord_messages_for_channel(channel_name, force_reprocess=False):
    """
    Clean and process Discord messages for a specific channel.
    
    Args:
        channel_name: Name of the Discord channel
        force_reprocess: If True, reprocess all messages regardless of processing status
        
    Returns:
        Path to the processed parquet file
    """
    try:
        # Load raw Discord data
        if not DISCORD_CSV.exists():
            logger.warning(f"Raw Discord data file not found: {DISCORD_CSV}")
            return None
            
        df = pd.read_csv(DISCORD_CSV)
        logger.info(f"Loaded {len(df)} total Discord messages")
        
        # Filter for the specific channel
        channel_df = df[df['channel'] == channel_name].copy()
        if channel_df.empty:
            logger.warning(f"No messages found for channel: {channel_name}")
            return None
            
        logger.info(f"Found {len(channel_df)} messages for channel {channel_name}")
        
        # Get already processed message IDs if not forcing reprocess
        processed_ids = set() if force_reprocess else get_processed_message_ids()
        
        # Filter to only unprocessed messages
        if not force_reprocess:
            channel_df = channel_df[~channel_df['message_id'].astype(str).isin(processed_ids)]
            logger.info(f"Found {len(channel_df)} unprocessed messages for channel {channel_name}")
        
        if channel_df.empty:
            logger.info(f"No new messages to process for channel {channel_name}")
            return None
        
        # Data cleaning and feature engineering
        channel_df['created_at'] = pd.to_datetime(channel_df['created_at'], utc=True)
        channel_df = channel_df.sort_values('created_at')
        channel_df = channel_df.drop_duplicates('message_id')
        
        # Feature engineering
        channel_df['char_len'] = channel_df['content'].str.len()
        channel_df['word_len'] = channel_df['content'].str.split().str.len()
        
        # Extract tickers as list
        channel_df['tickers'] = channel_df['tickers_detected'].fillna('').apply(
            lambda s: re.findall(r'\$[A-Z]{2,6}', s)
        )
        
        # Parse tweet URLs
        channel_df['tweet_urls'] = channel_df['tweet_urls'].fillna('').str.split(',\\s*')
        
        # Sentiment analysis with type ignore for TextBlob
        channel_df['sentiment'] = channel_df['content'].apply(
            lambda t: TextBlob(str(t)).sentiment.polarity if pd.notna(t) else 0.0  # type: ignore
        )
        
        # Command flag
        channel_df['is_command'] = channel_df['content'].str.startswith('!', na=False)
        
        # Keep useful columns
        keep_columns = [
            'message_id', 'created_at', 'channel', 'author_name',
            'content', 'tickers', 'tweet_urls', 'char_len', 'word_len', 
            'sentiment', 'is_command'
        ]
        
        # Only keep columns that exist in the dataframe
        available_columns = [col for col in keep_columns if col in channel_df.columns]
        clean_df = channel_df[available_columns].copy()
        
        # Save to channel-specific parquet file
        output_file = PROCESSED_DIR / f"discord_msgs_clean_{channel_name}.parquet"
        
        # If file exists and we're not forcing reprocess, append to existing data
        if output_file.exists() and not force_reprocess:
            try:
                existing_df = pd.read_parquet(output_file)
                # Combine with existing data and remove duplicates
                combined_df = pd.concat([existing_df, clean_df]).drop_duplicates('message_id')
                combined_df.to_parquet(output_file, index=False)
                logger.info(f"Appended {len(clean_df)} new messages to existing file: {output_file}")
            except Exception as e:
                logger.error(f"Error appending to existing file, creating new: {e}")
                clean_df.to_parquet(output_file, index=False)
        else:
            clean_df.to_parquet(output_file, index=False)
            logger.info(f"Created new processed file: {output_file}")
        
        # Mark messages as processed
        message_ids = clean_df['message_id'].astype(str).tolist()
        mark_messages_as_processed(message_ids, channel_name, str(output_file))
        
        logger.info(f"Successfully processed {len(clean_df)} messages for channel {channel_name}")
        logger.info(f"Saved to: {output_file}")
        
        return output_file
        
    except Exception as e:
        logger.error(f"Error processing Discord messages for channel {channel_name}: {e}")
        return None


def process_all_channels(force_reprocess=False):
    """Process messages for all channels found in the raw data."""
    try:
        if not DISCORD_CSV.exists():
            logger.warning(f"Raw Discord data file not found: {DISCORD_CSV}")
            return []
        
        df = pd.read_csv(DISCORD_CSV)
        channels = df['channel'].unique()
        
        processed_files = []
        for channel in channels:
            if pd.notna(channel):  # Skip NaN channel names
                output_file = clean_discord_messages_for_channel(channel, force_reprocess)
                if output_file:
                    processed_files.append(output_file)
        
        return processed_files
        
    except Exception as e:
        logger.error(f"Error processing all channels: {e}")
        return []


def get_channel_stats():
    """Get statistics about processed channels."""
    try:
        stats = {}
        
        # Get stats from processed files
        for file_path in PROCESSED_DIR.glob("discord_msgs_clean_*.parquet"):
            channel_name = file_path.stem.replace("discord_msgs_clean_", "")
            try:
                df = pd.read_parquet(file_path)
                stats[channel_name] = {
                    'total_messages': len(df),
                    'date_range': {
                        'start': df['created_at'].min().isoformat() if len(df) > 0 else None,
                        'end': df['created_at'].max().isoformat() if len(df) > 0 else None
                    },
                    'avg_sentiment': df['sentiment'].mean() if 'sentiment' in df.columns else None,
                    'total_tickers': sum(len(tickers) for tickers in df['tickers'] if isinstance(tickers, list)),
                    'file_path': str(file_path)
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
        print(f"  Avg Sentiment: {channel_stats['avg_sentiment']:.3f}" if channel_stats['avg_sentiment'] else "  Avg Sentiment: N/A")
        print(f"  Total Tickers: {channel_stats['total_tickers']}")
