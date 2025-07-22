import csv
import logging
from pathlib import Path

from .data_collector import extract_ticker_symbols
from .twitter_analysis import (
    detect_twitter_links,
    extract_tweet_id,
    analyze_sentiment,
    fetch_tweet_data,
    log_tweet_to_file,
)

logger = logging.getLogger(__name__)


def log_message_to_file(message, log_file: Path, tweet_log: Path, twitter_client=None):
    """Persist a Discord message to CSV and optionally log any linked tweets."""
    file_exists = log_file.exists()
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

    for url in twitter_links:
        tweet_id = extract_tweet_id(url)
        if tweet_id:
            tweet_data = fetch_tweet_data(tweet_id, twitter_client=twitter_client)
            if tweet_data:
                log_tweet_to_file(tweet_data, message.id, tweet_log)
