from pathlib import Path

from discord.ext import commands

from src.config import settings
from src.logging_utils import log_message_to_file

BASE_DIR = Path(__file__).resolve().parents[2]
RAW_DIR = BASE_DIR / "data" / "raw"
RAW_DIR.mkdir(parents=True, exist_ok=True)
DISCORD_CSV = RAW_DIR / "discord_msgs.csv"
TWEET_CSV = RAW_DIR / "x_posts_log.csv"


def register_events(bot: commands.Bot, twitter_client=None):
    @bot.event
    async def on_ready():
        print(f"✅ Bot is online and logged in as {bot.user}")

    @bot.event
    async def on_message(message):
        if message.author == bot.user:
            return
        
        config = settings()
        if str(message.channel.id) in config.log_channel_ids_list:
            log_message_to_file(message, DISCORD_CSV, TWEET_CSV, twitter_client)
        await bot.process_commands(message)
