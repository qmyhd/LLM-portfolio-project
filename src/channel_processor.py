"""
Channel-specific data processing module.
Handles cleaning and processing of Discord messages for different channels.
"""

import logging
import re
from typing import Any, Dict

from sqlalchemy import text
from textblob import TextBlob

from src.data_collector import extract_ticker_symbols
from src.database import (
    get_connection,
    get_unprocessed_messages,
    mark_message_processed,
    use_postgres,
)

logger = logging.getLogger(__name__)


def _execute_sql(conn, query: str, params=None):
    """Execute SQL compatible with both SQLite and SQLAlchemy connections."""
    if use_postgres() and hasattr(conn, 'execute'):
        # SQLAlchemy connection
        if params:
            return conn.execute(text(query), params)
        else:
            return conn.execute(text(query))
    else:
        # SQLite connection
        cursor = conn.cursor()
        if params:
            return cursor.execute(query, params)
        else:
            return cursor.execute(query)


def _fetchone(result):
    """Fetch one result compatible with both SQLite and SQLAlchemy."""
    if hasattr(result, 'fetchone'):
        # SQLAlchemy result
        row = result.fetchone()
        return row if row is not None else (0,)
    else:
        # SQLite cursor result  
        row = result.fetchone()
        return row if row is not None else (0,)


def clean_text(text: str) -> str:
    """Clean and normalize text content."""
    # Remove URLs
    text = re.sub(r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+', '', text)
    
    # Remove Discord mentions and channels
    text = re.sub(r'<@!?\d+>', '', text)
    text = re.sub(r'<#\d+>', '', text)
    
    # Remove extra whitespace
    text = ' '.join(text.split())
    
    return text.strip()


def calculate_sentiment(text: str) -> float:
    """Calculate sentiment score for text."""
    try:
        blob = TextBlob(text)
        # Type ignore for TextBlob sentiment property access
        return float(blob.sentiment.polarity)  # type: ignore
    except Exception as e:
        logger.warning(f"Error calculating sentiment: {e}")
        return 0.0


def process_general_channel(messages) -> int:
    """Process messages for general channels."""
    processed_count = 0
    
    with get_connection() as conn:
        for message in messages:
            message_id, author, content, channel, timestamp = message[1:6]  # Skip id field
            
            try:
                # Clean content
                cleaned_content = clean_text(content)
                sentiment = calculate_sentiment(cleaned_content)
                
                # Insert into general clean table using compatible SQL execution
                if use_postgres():
                    _execute_sql(conn, """
                        INSERT INTO discord_general_clean
                        (message_id, author, content, sentiment, cleaned_content, timestamp)
                        VALUES (:message_id, :author, :content, :sentiment, :cleaned_content, :timestamp)
                        ON CONFLICT (message_id) DO NOTHING
                    """, {
                        'message_id': message_id, 
                        'author': author, 
                        'content': content, 
                        'sentiment': sentiment, 
                        'cleaned_content': cleaned_content, 
                        'timestamp': timestamp
                    })
                else:
                    _execute_sql(conn, """
                        INSERT OR IGNORE INTO discord_general_clean
                        (message_id, author, content, sentiment, cleaned_content, timestamp)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (message_id, author, content, sentiment, cleaned_content, timestamp))
                
                mark_message_processed(message_id, channel, "cleaning")
                processed_count += 1
                
            except Exception as e:
                logger.error(f"Error processing message {message_id}: {e}")
        
        conn.commit()
    
    return processed_count


def process_trading_channel(messages) -> int:
    """Process messages for trading channels with stock mention extraction."""
    processed_count = 0
    
    with get_connection() as conn:
        for message in messages:
            message_id, author, content, channel, timestamp = message[1:6]  # Skip id field
            
            try:
                # Clean content
                cleaned_content = clean_text(content)
                sentiment = calculate_sentiment(cleaned_content)
                
                # Extract stock mentions
                stock_mentions = extract_ticker_symbols(content)
                stock_mentions_str = ', '.join(stock_mentions) if stock_mentions else ''
                
                # Insert into trading clean table using compatible SQL execution
                if use_postgres():
                    _execute_sql(conn, """
                        INSERT INTO discord_trading_clean
                        (message_id, author, content, sentiment, cleaned_content, stock_mentions, timestamp)
                        VALUES (:message_id, :author, :content, :sentiment, :cleaned_content, :stock_mentions, :timestamp)
                        ON CONFLICT (message_id) DO NOTHING
                    """, {
                        'message_id': message_id,
                        'author': author,
                        'content': content,
                        'sentiment': sentiment,
                        'cleaned_content': cleaned_content,
                        'stock_mentions': stock_mentions_str,
                        'timestamp': timestamp
                    })
                else:
                    _execute_sql(conn, """
                        INSERT OR IGNORE INTO discord_trading_clean
                        (message_id, author, content, sentiment, cleaned_content, stock_mentions, timestamp)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, (message_id, author, content, sentiment, cleaned_content, stock_mentions_str, timestamp))
                
                mark_message_processed(message_id, channel, "cleaning")
                processed_count += 1
                
            except Exception as e:
                logger.error(f"Error processing message {message_id}: {e}")
        
        conn.commit()
    
    return processed_count


def process_channel_data(channel_name: str, channel_type: str = "general") -> Dict[str, Any]:
    """Process unprocessed messages for a specific channel."""
    try:
        # Get unprocessed messages for the channel
        unprocessed_messages = get_unprocessed_messages(channel_name, "cleaning")
        
        if not unprocessed_messages:
            return {
                "success": True,
                "channel": channel_name,
                "processed_count": 0,
                "message": "No new messages to process"
            }
        
        # Process based on channel type
        if channel_type.lower() == "trading":
            processed_count = process_trading_channel(unprocessed_messages)
        else:
            processed_count = process_general_channel(unprocessed_messages)
        
        logger.info(f"Processed {processed_count} messages for channel {channel_name}")
        
        return {
            "success": True,
            "channel": channel_name,
            "processed_count": processed_count,
            "message": f"Successfully processed {processed_count} messages"
        }
        
    except Exception as e:
        logger.error(f"Error processing channel {channel_name}: {e}")
        return {
            "success": False,
            "channel": channel_name,
            "processed_count": 0,
            "error": str(e)
        }


def get_channel_stats(channel_name: str | None = None) -> Dict[str, Any]:
    """Get statistics for processed channels."""
    with get_connection() as conn:
        stats = {}
        
        # Raw messages count
        if channel_name:
            if use_postgres():
                result = _execute_sql(conn, "SELECT COUNT(*) FROM discord_messages WHERE channel = :channel", {"channel": channel_name})
            else:
                result = _execute_sql(conn, "SELECT COUNT(*) FROM discord_messages WHERE channel = ?", (channel_name,))
        else:
            result = _execute_sql(conn, "SELECT COUNT(*) FROM discord_messages")
        stats['raw_messages'] = _fetchone(result)[0]
        
        # Processed general messages
        if channel_name:
            if use_postgres():
                result = _execute_sql(conn, "SELECT COUNT(*) FROM discord_general_clean dgc JOIN discord_messages dm ON dgc.message_id = dm.message_id WHERE dm.channel = :channel", {"channel": channel_name})
            else:
                result = _execute_sql(conn, "SELECT COUNT(*) FROM discord_general_clean dgc JOIN discord_messages dm ON dgc.message_id = dm.message_id WHERE dm.channel = ?", (channel_name,))
        else:
            result = _execute_sql(conn, "SELECT COUNT(*) FROM discord_general_clean")
        stats['general_processed'] = _fetchone(result)[0]
        
        # Processed trading messages
        if channel_name:
            if use_postgres():
                result = _execute_sql(conn, "SELECT COUNT(*) FROM discord_trading_clean dtc JOIN discord_messages dm ON dtc.message_id = dm.message_id WHERE dm.channel = :channel", {"channel": channel_name})
            else:
                result = _execute_sql(conn, "SELECT COUNT(*) FROM discord_trading_clean dtc JOIN discord_messages dm ON dtc.message_id = dm.message_id WHERE dm.channel = ?", (channel_name,))
        else:
            result = _execute_sql(conn, "SELECT COUNT(*) FROM discord_trading_clean")
        stats['trading_processed'] = _fetchone(result)[0]
        
        # Twitter data count
        if channel_name:
            if use_postgres():
                result = _execute_sql(conn, "SELECT COUNT(*) FROM twitter_data WHERE channel = :channel", {"channel": channel_name})
            else:
                result = _execute_sql(conn, "SELECT COUNT(*) FROM twitter_data WHERE channel = ?", (channel_name,))
        else:
            result = _execute_sql(conn, "SELECT COUNT(*) FROM twitter_data")
        stats['twitter_data'] = _fetchone(result)[0]
        
        return stats
