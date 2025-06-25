import re
import csv
import logging
from datetime import datetime
from pathlib import Path
from textblob import TextBlob

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
    if not text:
        return 0.0
    try:
        return TextBlob(text).sentiment.polarity
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
            expansions=['author_id'],
            tweet_fields=['created_at', 'public_metrics', 'text'],
            user_fields=['name', 'username']
        )
        if not tweet or not tweet.data:
            return None
        user = tweet.includes['users'][0] if tweet.includes and tweet.includes.get('users') else None
        metrics = tweet.data.public_metrics if hasattr(tweet.data, 'public_metrics') else {}
        data = {
            'tweet_id': tid,
            'source_url': f"https://x.com/{user.username if user else 'unknown'}/status/{tid}",
            'created_at': tweet.data.created_at,
            'text': tweet.data.text,
            'author_id': tweet.data.author_id,
            'author_name': user.name if user else None,
            'author_username': user.username if user else None,
            'retweet_count': metrics.get('retweet_count', 0),
            'like_count': metrics.get('like_count', 0),
            'reply_count': metrics.get('reply_count', 0),
            'quote_count': metrics.get('quote_count', 0),
            'retrieved_at': datetime.now().isoformat(),
        }
        return data
    except Exception as e:
        logger.error(f"Error fetching tweet {tweet_id}: {e}")
        return None


def log_tweet_to_file(tweet_data: dict, discord_message_id: int, csv_path: Path):
    if not tweet_data:
        return
    file_exists = csv_path.exists()
    row = dict(tweet_data)
    row['discord_message_id'] = discord_message_id
    with open(csv_path, 'a', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=row.keys())
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)
