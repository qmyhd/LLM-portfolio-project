#
import discord
from discord.ext import commands
import os
import re
from pathlib import Path
import csv
from dotenv import load_dotenv
from datetime import datetime, timedelta
import pandas as pd
import tweepy
import time
import logging
from textblob import TextBlob  # Add TextBlob for sentiment analysis
import yfinance as yf
import mplfinance as mpf
import numpy as np
import sqlite3  # Import SQLite for database connectivity
# --- OUTPUT PATHS (relative to project root) ------------------------------
# …/llm_portfolio_project
BASE_DIR = Path(__file__).resolve().parents[1]
RAW_DIR = BASE_DIR / "data" / "raw"
PROCESSED_DIR = BASE_DIR / "data" / "processed"
DB_DIR = BASE_DIR / "data" / "database"

# Create directories if they don't exist
RAW_DIR.mkdir(parents=True, exist_ok=True)
PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
DB_DIR.mkdir(parents=True, exist_ok=True)

DISCORD_CSV = RAW_DIR / "discord_msgs.csv"
TWEET_CSV = RAW_DIR / "x_posts_log.csv"
PRICE_DB = DB_DIR / "price_history.db"

if DISCORD_CSV.exists():
    # 1) read all columns, skip spaces after commas
    df = pd.read_csv(DISCORD_CSV, skipinitialspace=True)
    # 2) strip any stray whitespace on column names
    df.columns = df.columns.str.strip()
    # 3) if we see a literal message_id column, use it; otherwise assume it's column 0
    if "message_id" in df.columns:
        _seen = set(df["message_id"])
    else:
        _seen = set(df.iloc[:, 0])
else:
    _seen = set()

SEEN_IDS = _seen

# Set up logging
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')
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
BEARER = os.getenv("TWITTER_BEARER_TOKEN")
if BEARER:
    twitter_client = tweepy.Client(
        bearer_token=BEARER,
        wait_on_rate_limit=True
    )
else:
    twitter_client = None
    logger.warning("No TWITTER_BEARER_TOKEN—tweet fetching disabled")
# Initialize Twitter API client
try:
    twitter_client = tweepy.Client(
        bearer_token=TWITTER_BEARER_TOKEN,
        wait_on_rate_limit=True,
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

TWEET_URL_RE = re.compile(
    r"https?://(?:www\.)?(?:x\.com|twitter\.com)/([A-Za-z0-9_]+)/status/(\d+)"
)


def detect_twitter_links(text: str) -> list[str]:
    return list({m.group(0) for m in TWEET_URL_RE.finditer(text)})


def extract_tweet_meta(url: str):
    m = TWEET_URL_RE.search(url)
    return (m.group(1), m.group(2)) if m else (None, None)


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

def detect_twitter_links(text: str) -> list[str]:
    # return the *whole* URL so you can log it
    return re.findall(
        r'https?://(?:www\.)?(?:x\.com|twitter\.com)/\w+/status/\d+',
        text
    )


def extract_tweet_id(url):
    m = TWEET_URL_RE.search(url)
    return m.group(1) if m else None


def fetch_tweet_data(tweet_id: str):
    """Fetch tweet data using Twitter API."""
    if not twitter_client:
        logger.error(
            "Twitter client not initialized. Cannot fetch tweet data.")
        return None

    try:
        # Get tweet with user information
        tweet_id = int(tweet_id)  # Ensure tweet_id is an integer
        logger.info(f"Fetching tweet data for ID: {tweet_id}")
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
            user = tweet.includes['users'][0] if tweet.includes and tweet.includes.get(
                'users') else None

        # Create tweet data dictionary
        tweet_data = {
            'tweet_id': tweet_id,
            'source_url': f"https://x.com/{tweet.data.author_id}/status/{tweet_id}",
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
    if message.id in SEEN_IDS:
        logger.info(f"Message {message.id} already logged. Skipping.")
        return

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

    SEEN_IDS.add(message.id)

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
    if str(message.channel.id) in os.getenv("LOG_CHANNEL_IDS", "").split(","):
        print(
            f"[LIVE] #{message.channel} | {message.author}: {message.content}")
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

# ——— Insert chart/EOD/compare/bollinger commands here ——————
# TODO:Make sure the functions work


class trade:
    def __init__(self):
        self.name = 'default'
        self.db_path = PRICE_DB

    def _get_db_connection(self):
        """Get a database connection"""
        try:
            return sqlite3.connect(self.db_path)
        except Exception as e:
            logger.error(f"Error connecting to database: {e}")
            return None

    def get_realtime_price(self, symbol):
        """Get the most recent price from the database"""
        conn = self._get_db_connection()
        if not conn:
            return None

        try:
            # Get the most recent price data for the symbol
            query = """
            SELECT * FROM realtime_prices 
            WHERE symbol = ? 
            ORDER BY timestamp DESC 
            LIMIT 1
            """

            df = pd.read_sql_query(query, conn, params=(symbol,))

            if not df.empty:
                return df.iloc[0]
            return None
        except Exception as e:
            logger.error(f"Error getting realtime price for {symbol}: {e}")
            return None
        finally:
            if conn:
                conn.close()

    def get_historical_prices(self, symbol, days=1):
        """Get historical prices from the database"""
        conn = self._get_db_connection()
        if not conn:
            return None

        try:
            # Get historical price data for the symbol
            query = """
            SELECT * FROM daily_prices 
            WHERE symbol = ? 
            ORDER BY date DESC 
            LIMIT ?
            """

            df = pd.read_sql_query(query, conn, params=(symbol, days))

            if not df.empty:
                # Convert date string to datetime index
                df['date'] = pd.to_datetime(df['date'])
                df.set_index('date', inplace=True)
                return df
            return None
        except Exception as e:
            logger.error(f"Error getting historical prices for {symbol}: {e}")
            return None        
        finally:
            if conn:
                conn.close()
                
    def get_position_for_symbol(self, symbol):
        """Get a specific position from the database"""
        conn = self._get_db_connection()
        if not conn:
            return None

        try:
            # Get position data for the symbol
            query = "SELECT * FROM positions WHERE symbol = ?"
            df = pd.read_sql_query(query, conn, params=(symbol,))

            if not df.empty:
                return df.iloc[0]
            return None
        except Exception as e:
            logger.error(f"Error getting position for {symbol}: {e}")
            return None
        finally:
            if conn:
                conn.close()
                
    def get_user_positions(self):
        """Get user's portfolio positions from the database"""
        conn = self._get_db_connection()
        if not conn:
            return None

        try:
            # Get position data
            query = "SELECT * FROM positions ORDER BY equity DESC"
            df = pd.read_sql_query(query, conn)
            if not df.empty:
                return df
            return None
        except Exception as e:
            logger.error(f"Error getting positions: {e}")
            return None
        finally:
            if conn:
                conn.close()

    def create_charts(self, stockName):
        """Create candlestick chart for a stock, checking database first"""
        # Try to get data from the database first
        data = None

        # Create SQL connection
        conn = self._get_db_connection()
        if conn:
            try:
                # Try to get real-time price data from the last day
                query = """
                SELECT timestamp as Date, price as Close, price as Open, 
                       price as High, price as Low, 0 as Volume
                FROM realtime_prices 
                WHERE symbol = ? 
                AND timestamp > datetime('now', '-1 day')
                ORDER BY timestamp
                """

                df = pd.read_sql_query(query, conn, params=(stockName,))

                if not df.empty and len(df) > 10:
                    # Set the index to datetime
                    df['Date'] = pd.to_datetime(df['Date'])
                    data = df.set_index('Date')
                    logger.info(f"Using database data for {stockName} chart")
            except Exception as e:
                logger.error(
                    f"Error getting chart data from database for {stockName}: {e}")
            finally:
                conn.close()

        # If we couldn't get data from database or not enough data points, use yfinance
        if data is None or (isinstance(data, pd.DataFrame) and (data.empty or len(data) < 10)):
            data = yf.download(
                tickers=f'{stockName}', period='1d', interval='5m')
            logger.info(f"Using yfinance data for {stockName} chart")

        # Check if we got any data
        if isinstance(data, pd.DataFrame) and data.empty:
            logger.error(f"No data available for {stockName}")
            return False

        # customize style on matplotlib finance
        customstyle = mpf.make_mpf_style(base_mpf_style='yahoo',
                                         y_on_right=False,
                                         facecolor='w')

        # Add portfolio position details if available
        portfolio_info = ""
        position_data = self.get_position_for_symbol(stockName)

        if position_data is not None:
            portfolio_info = f"Portfolio: {position_data['quantity']} shares, ${position_data['equity']:.2f}"

        # Get volume data if available, otherwise use a placeholder
        volume_data = None
        if 'Volume' in data.columns:
            if (data['Volume'].sum() if isinstance(data['Volume'].sum(), (int, float)) else 0) > 0:
                volume_data = data['Volume']

        # Plot with volume if available
        if volume_data is not None:
            mpf.plot(data,
                     type='candle',
                     title=f'${stockName} price {portfolio_info}',
                     ylabel='Price ($USD)',
                     xlabel='Time',
                     addplot=mpf.make_addplot(
                         volume_data, type='bar', panel=1, ylabel='Volume', y_on_right=False),
                     tight_layout=True,
                     style=customstyle,
                     savefig='chart.png')
        else:
            # Plot without volume
            mpf.plot(data,
                     type='candle',
                     title=f'${stockName} price {portfolio_info}',
                     ylabel='Price ($USD)',
                     xlabel='Time',
                     tight_layout=True,
                     style=customstyle,
                     savefig='chart.png')

        return True

    def compare_stocks(self, stockName1, stockName2):
        """Compare two stocks, using database data if available"""
        stock1_data = None
        stock2_data = None

        # Try to get data from database first
        conn = self._get_db_connection()
        if conn:
            try:
                # Try to get real-time price data for first stock
                query = """
                SELECT timestamp as Date, price as Close, price as Open, 
                       price as High, price as Low, 0 as Volume
                FROM realtime_prices 
                WHERE symbol = ? 
                AND timestamp > datetime('now', '-1 day')
                ORDER BY timestamp
                """

                df1 = pd.read_sql_query(query, conn, params=(stockName1,))
                if not df1.empty and len(df1) > 10:
                    df1['Date'] = pd.to_datetime(df1['Date'])
                    stock1_data = df1.set_index('Date')
                    logger.info(f"Using database data for {stockName1}")

                # Try to get data for second stock
                df2 = pd.read_sql_query(query, conn, params=(stockName2,))
                if not df2.empty and len(df2) > 10:
                    df2['Date'] = pd.to_datetime(df2['Date'])
                    stock2_data = df2.set_index('Date')
                    logger.info(f"Using database data for {stockName2}")
            except Exception as e:
                logger.error(
                    f"Error getting comparison data from database: {e}")
            finally:
                conn.close()

        # If we don't have data from database, use yfinance
        if stock1_data is None:
            stock1_data = yf.download(
                f'{stockName1}', period='1d', interval='1m')
            logger.info(f"Using yfinance data for {stockName1}")

        if stock2_data is None:
            stock2_data = yf.download(
                f'{stockName2}', period='1d', interval='1m')
            logger.info(f"Using yfinance data for {stockName2}")

        # Check if we got valid data
        if isinstance(stock1_data, pd.DataFrame) and stock1_data.empty or isinstance(stock2_data, pd.DataFrame) and stock2_data.empty:
            logger.error(
                f"Missing data for comparison: {stockName1}={not (isinstance(stock1_data, pd.DataFrame) and stock1_data.empty)}, {stockName2}={not (isinstance(stock2_data, pd.DataFrame) and stock2_data.empty)}")
            return False

        # Custom style
        customstyle = mpf.make_mpf_style(base_mpf_style='yahoo',
                                         y_on_right=False,
                                         facecolor='w')

        # Get position information if available
        position1 = self.get_position_for_symbol(stockName1)
        position2 = self.get_position_for_symbol(stockName2)

        pos1_info = ""
        pos2_info = ""

        if position1 is not None:
            pos1_info = f" (Own: {position1['quantity']} @ ${position1['average_buy_price']:.2f})"

        if position2 is not None:
            pos2_info = f" (Own: {position2['quantity']} @ ${position2['average_buy_price']:.2f})"

        # Check if we have Volume data for both stocks
        volume1 = stock1_data.Volume if 'Volume' in stock1_data.columns and stock1_data.Volume.sum() > 0 else None
        volume2 = stock2_data.Volume if 'Volume' in stock2_data.columns and stock2_data.Volume.sum() > 0 else None

        # Create additional plots
        adds = []

        # Add volume for stock1 if available
        if volume1 is not None:
            adds.append(mpf.make_addplot(stock1_data.Volume,
                        type='bar', panel=1, ylabel='Volume', y_on_right=False))

        # Add stock2 price data
        adds.append(mpf.make_addplot(stock2_data, type='candle', panel=2,
                                     ylabel=f'${stockName2}{pos2_info} ($USD)'))

        # Add volume for stock2 if available
        if volume2 is not None:
            adds.append(mpf.make_addplot(stock2_data.Volume,
                        type='bar', panel=3, ylabel='Volume', y_on_right=False))

        # Create comparison plot
        mpf.plot(stock1_data,
                 type='candle',
                 title=f'${stockName1}{pos1_info} vs ${stockName2}{pos2_info}',
                 ylabel=f'${stockName1} ($USD)',
                 xlabel='Time',
                 addplot=adds,
                 tight_layout=True,
                 style=customstyle,
                 savefig='chart.png')

        return True

    def EOD(self, stockName):
        """Get end-of-day information for a stock, checking database first"""
        # Try to get data from database
        conn = self._get_db_connection()
        data = None

        if conn:
            try:
                # Check daily_prices table first
                query = """
                SELECT * FROM daily_prices 
                WHERE symbol = ? 
                ORDER BY date DESC 
                LIMIT 1
                """

                daily_df = pd.read_sql_query(query, conn, params=(stockName,))

                if not daily_df.empty:
                    # Use data from daily_prices table
                    daily_data = daily_df.iloc[0]

                    # Get position information if available
                    position_info = ""
                    query = "SELECT * FROM positions WHERE symbol = ?"
                    pos_df = pd.read_sql_query(
                        query, conn, params=(stockName,))

                    if not pos_df.empty:
                        position = pos_df.iloc[0]
                        position_info = f"\n-Your Position: {position['quantity']} shares @ ${position['average_buy_price']:.2f}\n-Current Value: ${position['equity']:.2f}"

                    # Format with database data
                    return (f"EOD update on ${stockName} (from database)\n"
                            f"-Date: {daily_data['date']}\n"
                            f"-Open: {daily_data['open']}\n"
                            f"-High: {daily_data['high']}\n"
                            f"-Low: {daily_data['low']}\n"
                            f"-Close: {daily_data['close']}\n"
                            f"-Volume: {daily_data['volume']}{position_info}")

                # Check realtime_prices as backup
                query = """
                SELECT * FROM realtime_prices 
                WHERE symbol = ? 
                ORDER BY timestamp DESC 
                LIMIT 1
                """

                realtime_df = pd.read_sql_query(
                    query, conn, params=(stockName,))

                if not realtime_df.empty:
                    # Use data from realtime_prices table
                    rt_data = realtime_df.iloc[0]

                    # Get position information if available
                    position_info = ""
                    query = "SELECT * FROM positions WHERE symbol = ?"
                    pos_df = pd.read_sql_query(
                        query, conn, params=(stockName,))

                    if not pos_df.empty:
                        position = pos_df.iloc[0]
                        position_info = f"\n-Your Position: {position['quantity']} shares @ ${position['average_buy_price']:.2f}\n-Current Value: ${position['equity']:.2f}"                    # Format with realtime data
                    change = rt_data['change']
                    percent = rt_data['change_percent']
                    change_text = f"{change:.2f} ({percent:.2f}%)"
                    
                    return (f"Latest price for ${stockName} (from database)\n"
                            f"-Time: {rt_data['timestamp']}\n"
                            f"-Price: ${rt_data['price']:.2f}\n"
                            f"-Previous Close: ${rt_data['previous_close']:.2f}\n"
                            f"-Change: {change_text}{position_info}"
                    )
            except Exception as e:
                logger.error(f"Error getting EOD data from database for {stockName}: {e}")
            finally:
                conn.close()

        # If we couldn't get data from database, use yfinance
        try:
            data = yf.download(tickers=f'{stockName}', period='1d')
            if data.empty:
                return f"Could not find data for ${stockName}"
                
            df = pd.DataFrame(data)
            adj = df['Adj Close'][0]
            
            # Get position information if available
            position_info = ""
            position_data = self.get_position_for_symbol(stockName)

            if position_data is not None:
                position_info = f"\n-Your Position: {position_data['quantity']} shares @ ${position_data['average_buy_price']:.2f}\n-Current Value: ${position_data['equity']:.2f}"
                
            # Return EOD of stock
            return f'EOD update on ${stockName} (from yfinance)\n-Date: {df.index[0].date()}\n-Open: {df.Open[0]:.2f}\n-High: {df.High[0]:.2f}\n-Low: {df.Low[0]:.2f}\n-Close: {df.Close[0]:.2f}\n-Adj Close: {adj:.2f}\n-Volume: {df.Volume[0]}{position_info}'
        except Exception as e:
            logger.error(f"Error getting EOD data from yfinance for {stockName}: {e}")
            return f"Error getting data for ${stockName}"
            
    # Bollinger related methods removed
    # These methods have been removed as part of cleaning up the Bollinger bands functionality:
    # - calcBollAndRsi
    # - bollingerBandRsiStrategy
    # - calcProfits
    # - bollinger


@bot.command(name="chart")
async def create_chart(ctx):
    await ctx.send("Enter a stock:")

    def check(msg):
        return msg.author == ctx.author and msg.channel == ctx.channel
    try:
        msg = await bot.wait_for("message", check=check, timeout=30)
        stock = trade()
        success = stock.create_charts(msg.content)
        if success:
            await ctx.send(file=discord.File("chart.png"))
        else:
            await ctx.send(f"Could not create chart for {msg.content}")
    except Exception as e:
        logger.error(f"Error creating chart: {e}")
        await ctx.send("Error creating chart. Please try again later.")


@bot.command(name="EOD")
async def eod_info(ctx):
    await ctx.send("Enter a stock:")

    def check(msg):
        return msg.author == ctx.author and msg.channel == ctx.channel
    try:
        msg = await bot.wait_for("message", check=check, timeout=30)
        stock = trade()
        info = stock.EOD(msg.content)
        await ctx.send(info)
    except Exception as e:
        logger.error(f"Error getting EOD data: {e}")
        await ctx.send("Error getting stock data. Please try again later.")


@bot.command(name="compare")
async def compare(ctx):
    await ctx.send("Enter first stock:")

    def check(msg):
        return msg.author == ctx.author and msg.channel == ctx.channel
    try:
        msg1 = await bot.wait_for("message", check=check, timeout=30)
        await ctx.send("Enter second stock:")
        msg2 = await bot.wait_for("message", check=check, timeout=30)
        stock = trade()
        success = stock.compare_stocks(msg1.content, msg2.content)
        if success:
            await ctx.send(file=discord.File("chart.png"))
        else:
            await ctx.send(f"Could not compare {msg1.content} and {msg2.content}")
    except Exception as e:
        logger.error(f"Error comparing stocks: {e}")
        await ctx.send("Error comparing stocks. Please try again later.")

# Bollinger command removed


# === Start the bot ===
bot.run(TOKEN)
