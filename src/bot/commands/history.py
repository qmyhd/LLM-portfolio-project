from pathlib import Path

import pandas as pd
from discord.ext import commands

from src.database import execute_sql
from src.logging_utils import log_message_to_database

BASE_DIR = Path(__file__).resolve().parents[3]
RAW_DIR = BASE_DIR / "data" / "raw"
RAW_DIR.mkdir(parents=True, exist_ok=True)
DISCORD_CSV = RAW_DIR / "discord_msgs.csv"
TWEET_CSV = RAW_DIR / "x_posts_log.csv"


def register(bot: commands.Bot, twitter_client=None):
    @bot.command(name="history")
    async def fetch_history(ctx, limit: int = 100):
        await ctx.send(f"📥 Fetching last {limit} messages from #{ctx.channel}…")

        # --- de-dupe guard - check for existing message IDs in database ---
        existing_message_ids = set()
        try:
            results = execute_sql("SELECT message_id FROM discord_messages WHERE channel = ?", (ctx.channel.name,), fetch_results=True)
            existing_message_ids = {row[0] for row in results}
        except Exception as e:
            print(f"Database error: {e}")
            # Fallback to CSV check if database fails
            if DISCORD_CSV.exists():
                try:
                    df = pd.read_csv(DISCORD_CSV)
                    ch_df = df[df["channel"] == ctx.channel.name]
                    if not ch_df.empty:
                        existing_message_ids = set(ch_df["message_id"].astype(str))
                except pd.errors.EmptyDataError:           # handles blank file
                    pass

        # --- pull messages ---
        count = 0
        async for msg in ctx.channel.history(limit=limit, oldest_first=True):
            if msg.author == ctx.bot.user:
                continue
            if str(msg.id) in existing_message_ids:
                continue  # Skip messages that are already logged
            
            # Log to database (preferred method)
            log_message_to_database(msg, twitter_client)
            count += 1
            
        await ctx.send(f"✅ Logged {count} fresh messages from #{ctx.channel} to database.")

