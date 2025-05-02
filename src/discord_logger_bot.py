#
import discord
from discord.ext import commands
import os
import re
from pathlib import Path
import csv
from dotenv import load_dotenv
from datetime import datetime
import pandas as pd
import tweepy
import time
import logging
from textblob import TextBlob  # Add TextBlob for sentiment analysis

# --- OUTPUT PATHS (relative to project root) ------------------------------
BASE_DIR  = Path(__file__).resolve().parents[1]          # …/llm_portfolio_project
RAW_DIR   = BASE_DIR / "data" / "raw"
RAW_DIR.mkdir(parents=True, exist_ok=True)

DISCORD_CSV = RAW_DIR / "discord_msgs.csv"
TWEET_CSV   = RAW_DIR / "x_posts_log.csv"

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Load environment variables from .env file (for bot token security)
load_dotenv()
TOKEN = os.getenv("DISCORD_BOT_TOKEN")

LOG_CHANNEL_IDS = os.getenv("LOG_CHANNEL_IDS", "").split(",")

# Twitter API setup
TWITTER_API_KEY = os.getenv("TWITTER_API_KEY")
TWITTER_API_SECRET_KEY = os.getenv("TWITTER_API_SECRET_KEY")
TWITTER_ACCESS_TOKEN = os.getenv("TWITTER_ACCESS_TOKEN")
TWITTER_ACCESS_TOKEN_SECRET = os.getenv("TWITTER_ACCESS_TOKEN_SECRET")
TWITTER_BEARER_TOKEN = os.getenv("TWITTER_BEARER_TOKEN")

# Initialize Twitter API client
try:
    twitter_client = tweepy.Client(
        bearer_token=TWITTER_BEARER_TOKEN,
        consumer_key=TWITTER_API_KEY, 
        consumer_secret=TWITTER_API_SECRET_KEY,
        access_token=TWITTER_ACCESS_TOKEN, 
        access_token_secret=TWITTER_ACCESS_TOKEN_SECRET
    )
    logger.info("Twitter API client initialized successfully")
except Exception as e:
    logger.error(f"Failed to initialize Twitter API client: {e}")
    twitter_client = None

# Set up Discord intents (what the bot is allowed to see/do)
intents = discord.Intents.default()
intents.message_content = True  # Needed to read actual message text
intents.messages = True
intents.guilds = True

# Create bot with command prefix and the required intents
bot = commands.Bot(command_prefix='!', intents=intents)

def detect_tickers(text):
    # Improved ticker detection regex to match any ticker format $XXXX anywhere in text
    return re.findall(r'\$[A-Z]{1,6}\b', text)

def analyze_sentiment(text):
    """Analyze sentiment of a message text using TextBlob.
    
    Args:
        text: The text to analyze
        
    Returns:
        Float value between -1 (negative) and 1 (positive) representing sentiment
    """
    if not text:
        return 0.0
    
    try:
        # Use TextBlob for sentiment analysis
        analysis = TextBlob(text)
        # Return polarity score (between -1 and 1)
        return analysis.sentiment.polarity
    except Exception as e:
        logger.error(f"Error analyzing sentiment: {e}")
        return 0.0

def detect_twitter_links(text):
    """Extract Twitter/X links from a message text."""
    # Pattern matches twitter.com and x.com URLs
    twitter_pattern = r'https?://(?:www\.)?(twitter\.com|x\.com)/\S+'
    return re.findall(twitter_pattern, text)

TWEET_URL_RE = re.compile(r'https?://(?:www\.)?(?:x\.com|twitter\.com)/\w+/status/(\d+)')
def extract_tweet_id(url):
    m = TWEET_URL_RE.search(url)
    return m.group(1) if m else None

def fetch_tweet_data(tweet_id):
    """Fetch tweet data using Twitter API."""
    if not twitter_client:
        logger.error("Twitter client not initialized. Cannot fetch tweet data.")
        return None
    
    try:
        # Get tweet with user information
        tweet = twitter_client.get_tweet(
            tweet_id, 
            expansions=['author_id'],
            tweet_fields=['created_at', 'public_metrics', 'text'],
            user_fields=['name', 'username']
        )
        
        if not tweet or not tweet.data:
            logger.warning(f"No data found for tweet ID: {tweet_id}")
            return None
        
        # Extract user info from includes
        user = None
        if tweet.includes and 'users' in tweet.includes:
            user = tweet.includes['users'][0]
        
        # Create tweet data dictionary
        tweet_data = {
            'tweet_id': tweet_id,
            'created_at': tweet.data.created_at,
            'text': tweet.data.text,
            'author_id': tweet.data.author_id,
            'author_name': user.name if user else None,
            'author_username': user.username if user else None,
            'retweet_count': tweet.data.public_metrics['retweet_count'] if hasattr(tweet.data, 'public_metrics') else 0,
            'like_count': tweet.data.public_metrics['like_count'] if hasattr(tweet.data, 'public_metrics') else 0,
            'reply_count': tweet.data.public_metrics['reply_count'] if hasattr(tweet.data, 'public_metrics') else 0,
            'quote_count': tweet.data.public_metrics['quote_count'] if hasattr(tweet.data, 'public_metrics') else 0,
            'retrieved_at': datetime.now().isoformat()
        }
        
        return tweet_data
    except Exception as e:
        logger.error(f"Error fetching tweet {tweet_id}: {e}")
        return None

def log_tweet_to_file(tweet_data, discord_message_id):
    """Log tweet data to a CSV file."""
    if not tweet_data:
        return
    
    log_file = TWEET_CSV
    file_exists = log_file.exists()
    
    # Add Discord message reference
    tweet_data['discord_message_id'] = discord_message_id
    
    with open(log_file, mode="a", encoding="utf-8", newline='') as f:
        writer = csv.DictWriter(f, fieldnames=tweet_data.keys())
        if not file_exists:
            writer.writeheader()
        writer.writerow(tweet_data)
    
    logger.info(f"Logged tweet {tweet_data['tweet_id']} to x_posts_log.csv")

def log_message_to_file(message):
    log_file = DISCORD_CSV
    file_exists = log_file.exists()

    tickers = detect_tickers(message.content)
    mentions = [user.name for user in message.mentions]
    
    # Detect Twitter/X links in the message
    twitter_links = detect_twitter_links(message.content)
    tweet_urls = ", ".join(twitter_links) if twitter_links else None
    
    # Analyze sentiment of the message
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
        "tweet_urls": tweet_urls,
        "sentiment_score": sentiment_score  # Now using the result of sentiment analysis
    }

    with open(log_file, mode="a", encoding="utf-8", newline='') as f:
        writer = csv.DictWriter(f, fieldnames=row.keys())
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)
    
    # Process Twitter/X links if any were found
    if twitter_links:
        for url in twitter_links:
            tweet_id = extract_tweet_id(url)
            if tweet_id:
                logger.info(f"Found tweet ID: {tweet_id} from URL: {url}")
                tweet_data = fetch_tweet_data(tweet_id)
                if tweet_data:
                    log_tweet_to_file(tweet_data, message.id)
                else:
                    logger.warning(f"Could not fetch data for tweet: {url}")
            else:
                logger.warning(f"Could not extract tweet ID from URL: {url}")

# === Event: Bot is ready ===
@bot.event
async def on_ready():
    print(f"✅ Bot is online and logged in as {bot.user}")

# === Event: On every new message ===
@bot.event
async def on_message(message):
    # Skip if the bot sent this message
    if message.author == bot.user:
        return

    # Only process messages from channels listed in LOG_CHANNELS
    if str(message.channel.id) in os.getenv("LOG_CHANNEL_IDS","").split(","):
        print(f"[LIVE] #{message.channel} | {message.author}: {message.content}")
        log_message_to_file(message)

    # Allow other commands to work
    await bot.process_commands(message)

# === Command: !history N ===
@bot.command(name="history")
async def fetch_history(ctx, limit: int = 100):
    """Fetch and log the last N messages from the current channel."""
    await ctx.send(f"📥 Fetching the last {limit} messages from #{ctx.channel}...")

    count = 0
    async for msg in ctx.channel.history(limit=limit, oldest_first=True):
        log_message_to_file(msg)
        count += 1

    await ctx.send(f"✅ Logged {count} historical messages from #{ctx.channel} to file.")

# === Start the bot ===
bot.run(TOKEN)