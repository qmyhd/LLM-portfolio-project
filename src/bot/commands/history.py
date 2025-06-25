from pathlib import Path
from discord.ext import commands

from logging_utils import log_message_to_file

BASE_DIR = Path(__file__).resolve().parents[3]
RAW_DIR = BASE_DIR / "data" / "raw"
DISCORD_CSV = RAW_DIR / "discord_msgs.csv"
TWEET_CSV = RAW_DIR / "x_posts_log.csv"


def register(bot: commands.Bot, twitter_client=None):
    @bot.command(name="history")
    async def fetch_history(ctx, limit: int = 100):
        await ctx.send(f"📥 Fetching the last {limit} messages from #{ctx.channel}...")
        count = 0
        async for msg in ctx.channel.history(limit=limit, oldest_first=True):
            log_message_to_file(msg, DISCORD_CSV, TWEET_CSV, twitter_client)
            count += 1
        await ctx.send(f"✅ Logged {count} messages from #{ctx.channel}.")
