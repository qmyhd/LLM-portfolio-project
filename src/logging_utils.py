import csv
import logging
from pathlib import Path

from src.data_collector import extract_ticker_symbols
from src.database import get_connection, mark_message_processed, execute_sql
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
        # Check if message already exists
        existing = execute_sql("SELECT message_id FROM discord_messages WHERE message_id = ?", (str(message.id),), fetch_results=True)
        if existing:
            return  # Message already exists, skip
        
        # Insert message into discord_messages table
        execute_sql("""
            INSERT INTO discord_messages 
            (message_id, author, content, channel, timestamp)
            VALUES (?, ?, ?, ?, ?)
        """, (
            str(message.id),
            message.author.name,
            message.content,
            message.channel.name,
            message.created_at.isoformat()
        ))
        
        # Check for Twitter links and process them
        twitter_links = detect_twitter_links(message.content)
        if twitter_links:
            for url in twitter_links:
                tweet_id = extract_tweet_id(url)
                if tweet_id and twitter_client:
                    tweet_data = fetch_tweet_data(tweet_id, twitter_client=twitter_client)
                    if tweet_data:
                        # Extract stock mentions from tweet content
                        stock_tags = extract_ticker_symbols(tweet_data.get('content', ''))
                        
                        execute_sql("""
                            INSERT INTO twitter_data 
                            (message_id, discord_date, tweet_date, content, stock_tags, author, channel)
                            VALUES (?, ?, ?, ?, ?, ?, ?)
                        """, (
                            str(message.id),
                            message.created_at.isoformat(),
                            tweet_data.get('created_at', ''),
                            tweet_data.get('content', ''),
                            ', '.join(stock_tags) if stock_tags else '',
                            message.author.name,
                            message.channel.name
                        ))
                        
                        mark_message_processed(str(message.id), message.channel.name, "twitter")
        
        logger.info(f"Successfully logged message {message.id} to database")
        
    except Exception as e:
        logger.error(f"Error logging message to database: {e}")


def log_message_to_file(message, log_file: Path, tweet_log: Path, twitter_client=None):
    """Legacy function - now redirects to database logging."""
    log_message_to_database(message, twitter_client)
    
    # Keep CSV logging for backward compatibility if needed
    file_exists = log_file.exists()
    if file_exists:
        try:
            with open(log_file, newline='', encoding="utf-8") as f:
                existing_ids = {row["message_id"] for row in csv.DictReader(f)}
            if str(message.id) in existing_ids:
                return                     # ---> early-exit, nothing to do
        except Exception:
            # Corrupted/empty CSV?  Swallow and keep going.
            pass
    
    tickers = extract_ticker_symbols(message.content)
    mentions = [user.name for user in getattr(message, 'mentions', [])]
    twitter_links = detect_twitter_links(message.content)
    sentiment_score = analyze_sentiment(message.content)

    row = {
        "message_id": message.id,
        "created_at": message.created_at.isoformat(),
        "channel": message.channel.name,
        "author_name": message.author.name,
        "author_id": message.author.id,
        "content": message.content,
        "is_reply": message.reference is not None,
        "reply_to_id": getattr(message.reference, 'message_id', None) if message.reference else None,
        "mentions": ", ".join(mentions),
        "num_chars": len(message.content),
        "num_words": len(message.content.split()),
        "tickers_detected": ", ".join(tickers),
        "tweet_urls": ", ".join(twitter_links) if twitter_links else None,
        "sentiment_score": sentiment_score,
    }

    with open(log_file, 'a', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=row.keys())
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)

    # Process Twitter links and log to database
    for url in twitter_links:
        tweet_id = extract_tweet_id(url)
        if tweet_id and twitter_client:
            tweet_data = fetch_tweet_data(tweet_id, twitter_client=twitter_client)
            if tweet_data:
                # Also log to CSV for backward compatibility
                log_tweet_to_csv(tweet_data, message.id, tweet_log)


def log_tweet_to_csv(tweet_data, discord_message_id, tweet_log: Path):
    """Log tweet data to CSV file for backward compatibility."""
    file_exists = tweet_log.exists()
    
    row = {
        "discord_message_id": discord_message_id,
        "tweet_id": tweet_data.get('id', ''),
        "tweet_content": tweet_data.get('content', ''),
        "tweet_created_at": tweet_data.get('created_at', ''),
        "discord_logged_at": tweet_data.get('discord_date', ''),
        "stock_tags": tweet_data.get('stock_tags', ''),
    }
    
    with open(tweet_log, 'a', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=row.keys())
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)
