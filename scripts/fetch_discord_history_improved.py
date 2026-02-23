"""
Improved Discord History Fetcher with Rate Limit Handling

Fetches message history in smaller batches with proper rate limit management.

Usage:
    python scripts/fetch_discord_history_improved.py [--limit 50] [--batch-size 25]
"""

import asyncio
import argparse
from pathlib import Path
import sys
import time

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from src.env_bootstrap import bootstrap_env  # noqa: E402

bootstrap_env()


async def fetch_channel_history_batch(
    bot, channel_id: int, limit: int = 50, batch_size: int = 25
):
    """Fetch history from a specific channel in batches."""
    from src.logging_utils import log_message_to_database

    try:
        channel = bot.get_channel(channel_id)
        if not channel:
            print(f"❌ Could not access channel {channel_id}")
            return 0, 0

        print(
            f"\n📥 Fetching up to {limit} messages from #{channel.name} (batch size: {batch_size})..."
        )

        # Get existing message IDs to avoid duplicates
        from src.db import execute_sql

        existing_ids = set()
        try:
            results = execute_sql(
                "SELECT message_id FROM discord_messages WHERE channel = :channel",
                {"channel": channel.name},
                fetch_results=True,
            )
            if not isinstance(results, list):
                results = list(results) if results else []
            existing_ids = {row[0] for row in results}
            print(f"   Found {len(existing_ids)} existing messages in database")
        except Exception as e:
            print(f"⚠️  Database check failed: {e}")

        total_fetched = 0
        total_logged = 0
        batch_num = 0

        # Fetch in batches to handle rate limits better
        async for msg in channel.history(limit=limit, oldest_first=True):
            if msg.author == bot.user:
                continue

            total_fetched += 1

            if str(msg.id) in existing_ids:
                continue

            # Log to database
            try:
                twitter_client = getattr(bot, "twitter_client", None)
                log_message_to_database(msg, twitter_client)
                total_logged += 1

                # Progress indicator every 10 messages
                if total_logged % 10 == 0:
                    print(f"   ✓ Logged {total_logged} messages...")

                # Batch pause every batch_size messages to avoid rate limits
                # Discord's strict rate limits require ~15 minute pauses between batches
                if total_logged % batch_size == 0:
                    batch_num += 1
                    pause_duration = 900  # 15 minutes = 900 seconds
                    print(f"   ⏸️  Batch {batch_num} complete ({total_logged} logged).")
                    print(
                        f"   ⏸️  Pausing {pause_duration}s (~15 min) to respect Discord rate limits..."
                    )
                    await asyncio.sleep(pause_duration)

            except Exception as e:
                print(f"⚠️  Failed to log message {msg.id}: {e}")

        print(
            f"✅ Fetch complete: {total_fetched} messages scanned, {total_logged} new messages logged"
        )
        return total_fetched, total_logged

    except Exception as e:
        print(f"❌ Error fetching from channel {channel_id}: {e}")
        return 0, 0


async def main():
    """Main execution function."""
    parser = argparse.ArgumentParser(
        description="Fetch Discord message history (improved)"
    )
    parser.add_argument(
        "--limit", type=int, default=50, help="Max messages to fetch per channel"
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=25,
        help="Pause after this many messages to avoid rate limits",
    )
    args = parser.parse_args()

    print("=" * 80)
    print("  IMPROVED DISCORD HISTORY FETCHER")
    print("  (With Rate Limit Protection)")
    print("=" * 80)
    print(f"\nSettings: limit={args.limit}, batch_size={args.batch_size}")

    # Load configuration
    from src.config import settings
    from src.bot import create_bot

    config = settings()

    if not config.DISCORD_BOT_TOKEN:
        print("❌ DISCORD_BOT_TOKEN not set in .env")
        return

    if not config.log_channel_ids_list:
        print("❌ LOG_CHANNEL_IDS not set in .env")
        return

    # Initialize Twitter client (optional)
    twitter_client = None
    try:
        import tweepy

        if config.TWITTER_BEARER_TOKEN:
            twitter_client = tweepy.Client(
                bearer_token=config.TWITTER_BEARER_TOKEN, wait_on_rate_limit=True
            )
            print("✅ Twitter client initialized")
    except Exception as e:
        print(f"⚠️  Twitter client not available: {e}")

    # Create bot
    bot = create_bot(twitter_client=twitter_client)
    bot.twitter_client = twitter_client

    @bot.event
    async def on_ready():
        print(f"\n✅ Bot connected as {bot.user}")
        print(
            f"\n📊 Fetching history from {len(config.log_channel_ids_list)} channels..."
        )

        total_fetched = 0
        total_logged = 0

        for idx, channel_id_str in enumerate(config.log_channel_ids_list, 1):
            try:
                channel_id = int(channel_id_str)
                print(
                    f"\n[{idx}/{len(config.log_channel_ids_list)}] Processing channel {channel_id}..."
                )

                fetched, logged = await fetch_channel_history_batch(
                    bot, channel_id, args.limit, args.batch_size
                )
                total_fetched += fetched
                total_logged += logged

                # Pause between channels to avoid rate limits
                # Allow rate limit window to reset between different channels
                if idx < len(config.log_channel_ids_list):
                    channel_pause = 300  # 5 minutes = 300 seconds
                    print(
                        f"\n⏸️  Pausing {channel_pause}s (~5 min) before next channel..."
                    )
                    print(f"   This allows Discord's rate limit window to reset.")
                    await asyncio.sleep(channel_pause)

            except ValueError:
                print(f"❌ Invalid channel ID: {channel_id_str}")
            except Exception as e:
                print(f"❌ Error processing channel: {e}")

        print(f"\n" + "=" * 80)
        print(f"✅ FETCH COMPLETE")
        print(f"   Total messages scanned: {total_fetched}")
        print(f"   New messages logged: {total_logged}")
        print("=" * 80)

        # Close bot
        await bot.close()

    # Run bot
    try:
        await bot.start(config.DISCORD_BOT_TOKEN)
    except Exception as e:
        print(f"❌ Bot error: {e}")


if __name__ == "__main__":
    asyncio.run(main())
