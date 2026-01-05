"""
Discord message history command for the bot.
Fetches and stores historical messages from Discord channels.

Uses the centralized UI system for consistent embed styling.
"""

import asyncio
from pathlib import Path

import discord
from discord.ext import commands

from src.db import execute_sql
from src.logging_utils import log_message_to_database
from src.bot.ui import EmbedFactory, build_embed, EmbedCategory

BASE_DIR = Path(__file__).resolve().parents[3]
RAW_DIR = BASE_DIR / "data" / "raw"
RAW_DIR.mkdir(parents=True, exist_ok=True)


def register(bot: commands.Bot, twitter_client=None):
    @bot.command(name="history")
    async def fetch_history(ctx, limit: int = 100):
        """Fetch message history from the current channel.

        Usage:
            !history      - Fetch last 100 messages
            !history 500  - Fetch last 500 messages
        """
        # Create loading embed
        status_msg = await ctx.send(
            embed=EmbedFactory.loading(
                title="Fetching Message History",
                description=f"Retrieving last **{limit}** messages from #{ctx.channel.name}...",
            )
        )

        # Check for existing message IDs to avoid duplicates
        existing_message_ids = set()
        try:
            results = execute_sql(
                "SELECT message_id FROM discord_messages WHERE channel = :channel",
                {"channel": ctx.channel.name},
                fetch_results=True,
            )
            existing_message_ids = {row[0] for row in results} if results else set()
        except Exception as e:
            await status_msg.edit(
                embed=EmbedFactory.error(
                    title="Database Error", error_details=str(e)[:200]
                )
            )
            return

        # Fetch messages with rate limiting
        count = 0
        skipped_bot = 0
        skipped_duplicate = 0

        try:
            async for msg in ctx.channel.history(limit=limit, oldest_first=True):
                if msg.author == ctx.bot.user:
                    skipped_bot += 1
                    continue
                if str(msg.id) in existing_message_ids:
                    skipped_duplicate += 1
                    continue

                # Log to database
                log_message_to_database(msg, twitter_client)
                count += 1

                # Rate limiting: delay every 50 messages
                if count % 50 == 0:
                    await asyncio.sleep(1)

        except discord.HTTPException as e:
            if e.status == 429:
                retry_after = getattr(e, "retry_after", None)
                wait_time = float(retry_after) if retry_after else 5.0

                embed = EmbedFactory.warning(
                    title="Rate Limited",
                    description=f"Fetched **{count}** messages before rate limit.\n\n"
                    f"Waiting **{wait_time:.1f}s**... Re-run `!history {limit}` to continue.",
                )
                embed.add_field(name="📝 Logged", value=str(count), inline=True)
                embed.add_field(
                    name="🤖 Skipped (bot)", value=str(skipped_bot), inline=True
                )
                embed.add_field(
                    name="🔄 Skipped (dupe)", value=str(skipped_duplicate), inline=True
                )
                await status_msg.edit(embed=embed)
                await asyncio.sleep(wait_time)
                return
            else:
                raise

        # Success embed
        total_scanned = count + skipped_bot + skipped_duplicate
        embed = EmbedFactory.success(
            title="History Fetch Complete",
            description=f"Processed messages from #{ctx.channel.name}",
            footer_hint=f"Total scanned: {total_scanned}",
        )
        embed.add_field(name="📝 Logged", value=str(count), inline=True)
        embed.add_field(name="🤖 Skipped (bot)", value=str(skipped_bot), inline=True)
        embed.add_field(
            name="🔄 Skipped (dupe)", value=str(skipped_duplicate), inline=True
        )

        await status_msg.edit(embed=embed)
