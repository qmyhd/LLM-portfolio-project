import logging
import discord
from discord.ext import commands
from dotenv import load_dotenv
from src.config import settings
from . import create_bot

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def main():
    load_dotenv()
    config = settings()

    token = config.DISCORD_BOT_TOKEN
    if not token:
        raise RuntimeError("DISCORD_BOT_TOKEN not set")

    # Twitter client configuration (optional)
    twitter_client = None
    try:
        import tweepy

        bearer = config.TWITTER_BEARER_TOKEN
        if bearer:
            twitter_client = tweepy.Client(bearer_token=bearer, wait_on_rate_limit=True)
    except Exception as e:
        logger.warning(f"Twitter client not configured: {e}")

    bot = create_bot(twitter_client=twitter_client)
    bot.run(token)


if __name__ == "__main__":
    main()
