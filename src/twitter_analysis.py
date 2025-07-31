import csv
import logging
import re
from datetime import datetime
from pathlib import Path

try:
    from textblob import TextBlob
    TEXTBLOB_AVAILABLE = True
except ImportError:
    TEXTBLOB_AVAILABLE = False

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
    """Log tweet data to both CSV (for backward compatibility) and database."""
    if not tweet_data:
        return
    
    # Log to CSV file (existing functionality)
    file_exists = csv_path.exists()
    row = dict(tweet_data)
    row['discord_message_id'] = discord_message_id
    with open(csv_path, 'a', encoding='utf-8', newline='') as f:
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
    tickers = re.findall(r'\$[A-Z]{2,6}', tweet_text)
    # Also look for common stock mentions without $ (but be more conservative)
    word_tickers = re.findall(r'\b[A-Z]{2,5}\b', tweet_text)
    
    # Filter out common words that aren't likely to be stocks
    common_words = {'THE', 'AND', 'OR', 'BUT', 'FOR', 'NOR', 'YET', 'SO', 'AT', 'IN', 'ON', 'TO', 'BY', 'UP', 'IF', 'IT', 'IS', 'AS', 'WE', 'HE', 'SHE', 'YOU', 'ALL', 'ANY', 'CAN', 'HAD', 'HAS', 'WAS', 'NOT', 'ARE', 'BUT', 'DAY', 'GET', 'HIM', 'HIS', 'HOW', 'ITS', 'MAY', 'NEW', 'NOW', 'OLD', 'ONE', 'OUR', 'OUT', 'SEE', 'TWO', 'WHO', 'BOY', 'DID', 'HER', 'LET', 'MAN', 'PUT', 'RUN', 'SHE', 'TRY', 'WAY', 'WHY', 'WIN', 'YES', 'YET', 'YOU', 'BIG', 'BOX', 'FUN', 'GUN', 'JOB', 'LOT', 'MEN', 'MOM', 'POP', 'RED', 'SUN', 'TOP', 'WAR', 'WIN', 'USE', 'USA', 'USD', 'CEO', 'CFO', 'CTO', 'IPO', 'ESG'}
    
    filtered_word_tickers = [t for t in word_tickers if t not in common_words and len(t) >= 2]
    
    # Combine and deduplicate, prefer $ format
    all_tickers = list(set(tickers + [f'${t}' for t in filtered_word_tickers]))
    return all_tickers


def log_tweet_to_database(tweet_data: dict, discord_message_id: int):
    """Log tweet data to the SQLite database."""
    try:
        from datetime import datetime

        from src.database import execute_sql
        
        # Extract stock symbols from tweet content
        stock_tags = extract_stock_symbols_from_tweet(tweet_data.get('text', ''))
        stock_tags_str = ', '.join(stock_tags) if stock_tags else None
        
        # Insert or update tweet data
        execute_sql('''
            INSERT OR REPLACE INTO twitter_data 
            (tweet_id, discord_message_id, discord_sent_date, tweet_created_date, 
             tweet_content, author_username, author_name, retweet_count, like_count, 
             reply_count, quote_count, stock_tags, source_url, retrieved_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            str(tweet_data.get('tweet_id', '')),
            str(discord_message_id),
            datetime.now().isoformat(),  # When it was shared in Discord
            tweet_data.get('created_at', ''),  # Original tweet date
            tweet_data.get('text', ''),
            tweet_data.get('author_username', ''),
            tweet_data.get('author_name', ''),
            tweet_data.get('retweet_count', 0),
            tweet_data.get('like_count', 0),
            tweet_data.get('reply_count', 0),
            tweet_data.get('quote_count', 0),
            stock_tags_str,
            tweet_data.get('source_url', ''),
            tweet_data.get('retrieved_at', datetime.now().isoformat())
        ))
        
        logger.info(f"Logged tweet {tweet_data.get('tweet_id')} to database with {len(stock_tags)} stock tags")
        
    except Exception as e:
        logger.error(f"Error logging tweet to database: {e}")


def get_tweets_by_stock_symbol(symbol, days_back=30):
    """Get tweets mentioning a specific stock symbol from the database."""
    try:
        from datetime import datetime, timedelta

        from src.database import execute_sql
        
        cutoff_date = (datetime.now() - timedelta(days=days_back)).isoformat()
        
        results = execute_sql('''
            SELECT tweet_id, discord_sent_date, tweet_created_date, tweet_content, 
                   author_username, like_count, retweet_count, source_url
            FROM twitter_data 
            WHERE stock_tags LIKE ? AND discord_sent_date > ?
            ORDER BY discord_sent_date DESC
        ''', (f'%{symbol}%', cutoff_date))
        
        return [dict(zip([
            'tweet_id', 'discord_sent_date', 'tweet_created_date', 'tweet_content',
            'author_username', 'like_count', 'retweet_count', 'source_url'
        ], row)) for row in results]
        
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
            sentiment = analyze_sentiment(tweet['tweet_content'])
            sentiments.append(sentiment)
        
        return {
            'symbol': symbol,
            'tweet_count': len(tweets),
            'avg_sentiment': sum(sentiments) / len(sentiments) if sentiments else 0,
            'positive_tweets': len([s for s in sentiments if s > 0.1]),
            'negative_tweets': len([s for s in sentiments if s < -0.1]),
            'neutral_tweets': len([s for s in sentiments if -0.1 <= s <= 0.1]),
            'recent_tweets': tweets[:5]  # Most recent 5 tweets
        }
        
    except Exception as e:
        logger.error(f"Error calculating Twitter sentiment for {symbol}: {e}")
        return None
