#!/usr/bin/env python3
"""
Incremental Discord Message Ingestion

Fetches only messages newer than the last-ingested cursor per channel,
writes them to discord_messages via idempotent upsert, and advances
the cursor on success.

Usage:
    python scripts/ingest_discord.py                    # All channels, incremental
    python scripts/ingest_discord.py --dry-run           # Fetch + count only
    python scripts/ingest_discord.py --max-pages 10      # Limit pages per channel
    python scripts/ingest_discord.py --channel 123456    # Single channel
    python scripts/ingest_discord.py --status            # Show cursor state
    python scripts/ingest_discord.py --verbose           # Debug logging
"""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

# ── Project root setup ───────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from src.env_bootstrap import bootstrap_env  # noqa: E402

bootstrap_env()

# ── Logging ──────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("discord_ingest")


def show_status():
    """Print current ingestion cursor state for all channels."""
    from src.discord_ingest import get_ingestion_status

    rows = get_ingestion_status()
    if not rows:
        print("No ingestion state found — run an ingestion first.")
        return

    print(f"\n{'Channel':<25} {'Status':<10} {'Cursor':<22} {'Total':>8} {'Last New':>9} {'Last Run'}")
    print("-" * 100)
    for r in rows:
        last_run = r["last_run_at"].strftime("%Y-%m-%d %H:%M") if r["last_run_at"] else "never"
        print(
            f"{(r['channel_name'] or r['channel_id']):<25} "
            f"{r['status']:<10} "
            f"{(r['last_message_id'] or 'none'):<22} "
            f"{r['messages_total'] or 0:>8} "
            f"{r['last_run_new'] or 0:>9} "
            f"{last_run}"
        )
        if r["error_message"]:
            print(f"  ERROR: {r['error_message']}")
    print()


async def run_ingestion(args):
    """Start the bot, run ingestion in on_ready, then close."""
    from src.config import settings
    from src.bot import create_bot
    from src.discord_ingest import ingest_all_channels, ingest_channel

    config = settings()

    if not config.DISCORD_BOT_TOKEN:
        logger.error("DISCORD_BOT_TOKEN not set")
        sys.exit(1)

    if not args.channel and not config.log_channel_ids_list:
        logger.error("LOG_CHANNEL_IDS not set and --channel not provided")
        sys.exit(1)

    bot = create_bot()

    @bot.event
    async def on_ready():
        logger.info("Bot connected as %s", bot.user)

        try:
            if args.channel:
                results = [
                    await ingest_channel(
                        bot,
                        args.channel,
                        dry_run=args.dry_run,
                        max_pages=args.max_pages,
                    )
                ]
            else:
                results = await ingest_all_channels(
                    bot,
                    dry_run=args.dry_run,
                    max_pages=args.max_pages,
                )

            # Print summary
            print("\n" + "=" * 70)
            print("  INGESTION SUMMARY" + (" [DRY RUN]" if args.dry_run else ""))
            print("=" * 70)
            for r in results:
                status = "OK" if not r.error else f"ERROR: {r.error}"
                print(
                    f"  {r.channel_name or r.channel_id}: "
                    f"fetched={r.messages_fetched} new={r.messages_new} "
                    f"dupes={r.messages_duplicate} bot_skip={r.messages_skipped_bot} "
                    f"({r.duration_seconds:.1f}s) [{status}]"
                )

            total_new = sum(r.messages_new for r in results)
            total_errors = sum(1 for r in results if r.error)
            print(f"\n  Total new: {total_new}  Errors: {total_errors}")
            print("=" * 70)

        except Exception:
            logger.exception("Ingestion failed")
        finally:
            await bot.close()

    try:
        await bot.start(config.DISCORD_BOT_TOKEN)
    except Exception as exc:
        logger.error("Bot startup failed: %s", exc)
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="Incremental Discord message ingestion",
    )
    parser.add_argument("--dry-run", action="store_true", help="Fetch and count only, no DB writes")
    parser.add_argument("--max-pages", type=int, default=None, help="Max pages per channel (100 msgs/page)")
    parser.add_argument("--channel", type=str, default=None, help="Single channel ID to ingest")
    parser.add_argument("--status", action="store_true", help="Show cursor state and exit")
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    if args.status:
        show_status()
        return

    asyncio.run(run_ingestion(args))


if __name__ == "__main__":
    main()
