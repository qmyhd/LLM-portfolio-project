"""
Discord data processing command for the bot.
Allows users to trigger channel-specific data processing.

Uses the centralized UI system for consistent embed styling.
"""

import asyncio
import json
from io import BytesIO
import discord
from discord.ext import commands

from src.channel_processor import process_channel_data as process_channel
from src.logging_utils import log_message_to_database
from src.bot.ui import EmbedFactory, build_embed, EmbedCategory


def register(bot: commands.Bot, twitter_client=None):
    @bot.command(name="process")
    async def process_channel_data(ctx, channel_type: str = "trading"):
        """
        Fetch and process the latest 50 Discord messages for the current channel.

        QUICK OPERATION: Designed for frequent use to process recent messages.
        Use !backfill for one-time historical data collection.

        Usage: !process [channel_type]
        - channel_type: 'market' or 'trading' (default: trading)
        - Note: 'general' is redirected to 'trading' for backwards compatibility

        Process (Resumable Pipeline):
        1. Fetch latest 50 messages from Discord
        2. Skip bot messages and duplicates already in database
        3. Insert new messages into discord_messages table (ON CONFLICT safe)
        4. Process new messages through cleaning pipeline
        5. Store cleaned data in discord_market_clean or discord_trading_clean

        Deduplication Strategy:
        - Primary key: Discord message_id (globally unique)
        - Pre-insert check: Query existing message_ids to skip duplicates
        - ON CONFLICT safety: log_message_to_database() handles race conditions
        - Processing flags: Messages marked as processed, never deleted
        - Resumable: Can be re-run safely; already-processed messages are skipped
        """
        try:
            # Create loading embed
            status_msg = await ctx.send(
                embed=EmbedFactory.loading(
                    title="Processing Channel",
                    description=f"Fetching messages from #{ctx.channel.name} as **{channel_type}** channel...",
                )
            )

            # Step 1: Query database for existing message IDs in this channel
            # This prevents duplicate inserts and makes the operation idempotent
            from src.db import execute_sql

            existing_result = execute_sql(
                "SELECT message_id FROM discord_messages WHERE channel = :channel",
                {"channel": ctx.channel.name},
                fetch_results=True,
            )

            # Build set of existing message IDs for fast O(1) lookup
            existing_message_ids = set()
            if existing_result:
                for row in existing_result:
                    if row and len(row) > 0:
                        existing_message_ids.add(str(row[0]))

            # Step 2: Fetch latest 50 messages from Discord
            # Rate limiting: Single batch fetch with 429 error handling
            messages_to_insert = []
            skipped_bot = 0
            skipped_duplicate = 0

            try:
                async for msg in ctx.channel.history(limit=50):
                    # Skip bot's own messages (never process our own output)
                    if msg.author == ctx.bot.user:
                        skipped_bot += 1
                        continue

                    # Skip messages authored by ANY bot
                    if msg.author.bot:
                        skipped_bot += 1
                        continue

                    # Skip bot commands (start with !)
                    if msg.content.strip().startswith("!"):
                        continue

                    # Skip messages already in database (primary deduplication check)
                    # This ensures we never insert the same message_id twice
                    msg_id_str = str(msg.id)
                    if msg_id_str in existing_message_ids:
                        skipped_duplicate += 1
                        continue

                    # Add to insert list
                    messages_to_insert.append(msg)

            except discord.HTTPException as e:
                if e.status == 429:
                    # Handle rate limiting gracefully
                    retry_after = getattr(e, "retry_after", None)
                    wait_time = float(retry_after) if retry_after else 5.0
                    await ctx.send(
                        embed=EmbedFactory.warning(
                            title="Rate Limited",
                            description=f"Waiting **{wait_time:.1f}s**...\nPlease re-run `!process` command after wait.",
                        )
                    )
                    await asyncio.sleep(wait_time)
                    return
                else:
                    # Re-raise other HTTP errors
                    raise

            # Step 3: Insert new messages into discord_messages table
            # Note: log_message_to_database() has ON CONFLICT protection for safety
            inserted_count = 0
            for msg in messages_to_insert:
                try:
                    log_message_to_database(msg, twitter_client=twitter_client)
                    inserted_count += 1
                except Exception as e:
                    # Log error but continue processing other messages
                    # This ensures partial failures don't stop the entire batch
                    print(f"⚠️ Error inserting message {msg.id}: {e}")

            # Step 4: Process the newly inserted messages through cleaning pipeline
            # Uses get_unprocessed_messages() to find messages without processed_for_cleaning flag
            processing_result = process_channel(ctx.channel.name, channel_type)

            # Step 5: Send summary to user
            embed = EmbedFactory.success(
                title="Processing Complete",
                description=f"Channel: **#{ctx.channel.name}** ({channel_type})",
            )
            embed.add_field(name="📥 Fetched", value="50 messages", inline=True)
            embed.add_field(
                name="🤖 Skipped (bot)", value=str(skipped_bot), inline=True
            )
            embed.add_field(
                name="🔄 Skipped (dupe)", value=str(skipped_duplicate), inline=True
            )
            embed.add_field(name="📝 Inserted", value=str(inserted_count), inline=True)
            embed.add_field(
                name="🧹 Cleaned",
                value=str(processing_result.get("processed_count", 0)),
                inline=True,
            )

            if not processing_result.get("success", False):
                embed.add_field(
                    name="⚠️ Warning",
                    value=processing_result.get(
                        "error", "Unknown error during cleaning"
                    )[:100],
                    inline=False,
                )

            await status_msg.edit(embed=embed)

        except Exception as e:
            await ctx.send(
                embed=EmbedFactory.error(
                    title="Processing Error", error_details=str(e)[:200]
                )
            )

    @bot.command(name="backfill")
    async def backfill_channel_history(ctx, channel_type: str = "trading"):
        """
        Backfill entire message history for the current channel (use cautiously).

        HEAVY ONE-TIME OPERATION: Designed for initial historical data collection.
        Use !process for frequent updates of recent messages.

        Usage: !backfill [channel_type]
        - channel_type: 'market' or 'trading' (default: trading)

        ⚠️ WARNING: This fetches ALL historical messages from the channel.
        This is a one-time operation per channel and may take several minutes.

        Process (Resumable & Idempotent):
        1. Fetch all historical messages in batches of 50 (newest to oldest)
        2. Skip bot messages and duplicates already in database
        3. Insert raw messages into discord_messages table (ON CONFLICT safe)
        4. Process all new messages through cleaning pipeline in chunks of 100
        5. Respects Discord rate limits with automatic delays

        Rate Limiting & Safety:
        - Batch size: 50 messages per Discord API call
        - Explicit delay: 1 second pause between batches (asyncio.sleep(1))
        - 429 handling: Automatic retry with Discord's retry_after value
        - Fallback: 5 second default wait if retry_after unavailable

        Deduplication & Safety:
        - Primary key: Discord message_id (globally unique)
        - Pre-insert check: Query existing message_ids before starting
        - Per-batch check: Skip messages already inserted in current run
        - ON CONFLICT safety: log_message_to_database() handles race conditions
        - Processing flags: Messages marked as processed via processing_status table
        - Resumable: If interrupted, re-running will skip already-processed messages
        - No deletion: Raw messages never deleted, only marked as processed
        """
        try:
            # Send initial status embed
            status_msg = await ctx.send(
                embed=build_embed(
                    category=EmbedCategory.DISCORD,
                    title="Starting Historical Backfill",
                    description=(
                        f"**Channel:** #{ctx.channel.name}\n"
                        f"**Type:** {channel_type}\n\n"
                        "⚠️ Fetching entire message history...\n"
                        "This may take several minutes."
                    ),
                )
            )

            from src.db import execute_sql

            # Get existing message IDs to avoid duplicates
            existing_result = execute_sql(
                "SELECT message_id FROM discord_messages WHERE channel = :channel",
                {"channel": ctx.channel.name},
                fetch_results=True,
            )

            existing_message_ids = set()
            if existing_result:
                for row in existing_result:
                    if row and len(row) > 0:
                        existing_message_ids.add(str(row[0]))

            # Statistics tracking
            total_fetched = 0
            total_inserted = 0
            total_skipped_bot = 0
            total_skipped_duplicate = 0
            batch_count = 0
            last_message = None

            # Fetch messages in batches (paginated, newest to oldest)
            while True:
                try:
                    # Fetch batch of 50 messages
                    if last_message is None:
                        # First batch: get latest 50 messages
                        messages = [msg async for msg in ctx.channel.history(limit=50)]
                    else:
                        # Subsequent batches: get 50 messages before the last one
                        messages = [
                            msg
                            async for msg in ctx.channel.history(
                                limit=50, before=last_message
                            )
                        ]

                    # If no messages returned, we've reached the beginning
                    if not messages:
                        break

                    # Increment batch counter only after successful fetch
                    batch_count += 1
                    total_fetched += len(messages)

                    # Process messages in this batch
                    batch_inserted = 0
                    for msg in messages:
                        # Skip bot's own messages
                        if msg.author == ctx.bot.user:
                            total_skipped_bot += 1
                            continue

                        # Skip messages authored by ANY bot
                        if msg.author.bot:
                            total_skipped_bot += 1
                            continue

                        # Skip bot commands (start with !)
                        if msg.content.strip().startswith("!"):
                            continue

                        # Skip messages already in database
                        msg_id_str = str(msg.id)
                        if msg_id_str in existing_message_ids:
                            total_skipped_duplicate += 1
                            continue

                        # Insert new message
                        try:
                            log_message_to_database(msg, twitter_client=twitter_client)
                            batch_inserted += 1
                            total_inserted += 1
                            # Add to existing set to avoid re-checking in same run
                            existing_message_ids.add(msg_id_str)
                        except Exception as e:
                            print(f"⚠️ Error inserting message {msg.id}: {e}")

                    # Update last_message pointer for next iteration
                    last_message = messages[-1]  # Oldest message in this batch

                    # Update status every 5 batches
                    if batch_count % 5 == 0:
                        await status_msg.edit(
                            embed=build_embed(
                                category=EmbedCategory.DISCORD,
                                title="Backfill In Progress",
                                description=(
                                    f"**Channel:** #{ctx.channel.name}\n\n"
                                    f"📦 Batches: **{batch_count}**\n"
                                    f"📥 Fetched: **{total_fetched}**\n"
                                    f"📝 Inserted: **{total_inserted}**\n"
                                    f"🤖 Skipped (bot): {total_skipped_bot}\n"
                                    f"🔄 Skipped (dupe): {total_skipped_duplicate}"
                                ),
                            )
                        )

                    # Rate limiting: explicit 1-second pause between batches
                    # This greatly reduces chance of hitting Discord API rate limits
                    await asyncio.sleep(1.0)

                except discord.HTTPException as e:
                    # Handle rate limiting (429 Too Many Requests)
                    if e.status == 429:
                        # Use Discord's retry_after value if available
                        retry_after = getattr(e, "retry_after", None)
                        if retry_after:
                            wait_time = float(retry_after)
                        else:
                            # Fallback to 5 seconds if retry_after unavailable
                            wait_time = 5.0

                        await ctx.send(
                            embed=EmbedFactory.warning(
                                title="Rate Limited",
                                description=f"Waiting {wait_time:.1f} seconds...",
                            )
                        )
                        await asyncio.sleep(wait_time)
                        # Retry this batch without incrementing batch_count
                        # (batch_count only increments after successful fetch above)
                        continue
                    else:
                        # Re-raise other HTTP exceptions
                        raise
                except Exception as e:
                    # Log unexpected errors and stop processing this channel
                    # Breaking prevents infinite loop on persistent errors
                    await ctx.send(
                        embed=EmbedFactory.error(
                            title="Critical Batch Error",
                            description=f"Stopping backfill. Already fetched: {total_fetched} messages.",
                            error_details=str(e)[:100],
                        )
                    )
                    break  # Exit loop to prevent infinite retry

            # All messages fetched, now process them in chunks
            await status_msg.edit(
                embed=build_embed(
                    category=EmbedCategory.DISCORD,
                    title="Fetch Complete",
                    description=(
                        f"📥 Total fetched: **{total_fetched}**\n"
                        f"📝 Inserted: **{total_inserted}**\n\n"
                        "🧹 Now processing through cleaning pipeline..."
                    ),
                )
            )

            # Process unprocessed messages in chunks of 100
            total_cleaned = 0
            chunk_size = 100

            while True:
                # Get a chunk of unprocessed messages
                from src.db import get_unprocessed_messages

                unprocessed = get_unprocessed_messages(ctx.channel.name, "cleaning")

                # Convert to list if needed
                if unprocessed:
                    unprocessed = list(unprocessed)
                else:
                    break

                if not unprocessed:
                    break

                # Take only chunk_size messages
                chunk = unprocessed[:chunk_size]

                # Convert to message dicts and process
                message_dicts = []
                for message in chunk:
                    if len(message) >= 5:
                        message_dict = {
                            "message_id": message[0],
                            "author": message[1],
                            "content": message[2],
                            "channel": message[3],
                            "created_at": message[4],
                        }
                        message_dicts.append(message_dict)

                if message_dicts:
                    # Process this chunk
                    from src.message_cleaner import process_messages_for_channel
                    from src.db import mark_message_processed

                    cleaned_df, stats = process_messages_for_channel(
                        messages=message_dicts,
                        channel_name=ctx.channel.name,
                        channel_type=channel_type,
                        database_connection=None,
                        save_parquet=False,
                        save_database=True,
                    )

                    # Mark as processed
                    if not cleaned_df.empty:
                        for msg_id in cleaned_df["message_id"].tolist():
                            mark_message_processed(msg_id, ctx.channel.name, "cleaning")

                        total_cleaned += len(cleaned_df)

                    # Update status
                    await status_msg.edit(
                        embed=build_embed(
                            category=EmbedCategory.DISCORD,
                            title="Cleaning In Progress",
                            description=(
                                f"**Channel:** #{ctx.channel.name}\n\n"
                                f"🧹 Cleaned so far: **{total_cleaned}**\n"
                                f"📦 Remaining: ~{len(unprocessed) - len(chunk)}"
                            ),
                        )
                    )

                    # Brief pause between chunks
                    await asyncio.sleep(0.5)

                # If we processed fewer than chunk_size, we're done
                if len(chunk) < chunk_size:
                    break

            # Final summary embed
            embed = EmbedFactory.success(
                title="Backfill Complete!",
                description=f"Channel **#{ctx.channel.name}** ({channel_type}) fully imported!",
                footer_hint="✨ History imported • You can now use !process for updates",
            )
            embed.add_field(name="📦 Batches", value=str(batch_count), inline=True)
            embed.add_field(name="📥 Fetched", value=str(total_fetched), inline=True)
            embed.add_field(name="📝 Inserted", value=str(total_inserted), inline=True)
            embed.add_field(
                name="🤖 Skipped (bot)", value=str(total_skipped_bot), inline=True
            )
            embed.add_field(
                name="🔄 Skipped (dupe)",
                value=str(total_skipped_duplicate),
                inline=True,
            )
            embed.add_field(name="🧹 Cleaned", value=str(total_cleaned), inline=True)

            await status_msg.edit(embed=embed)

        except Exception as e:
            await ctx.send(
                embed=EmbedFactory.error(
                    title="Backfill Error",
                    description="Progress may be partially saved. You can re-run `!backfill` safely.",
                    error_details=str(e)[:200],
                )
            )

    @bot.command(name="peekraw")
    async def peekraw(ctx, limit: int = 5):
        """
        Show the last N raw messages from the current channel (ID, author, content, timestamp, mentions…).
        Usage: !peekraw [limit]
        """
        out = []

        try:
            async for m in ctx.channel.history(limit=limit):
                out.append(
                    {
                        "id": str(m.id),
                        "author": m.author.display_name,
                        "author_id": m.author.id,
                        "content": m.content,
                        "timestamp": m.created_at.isoformat(),
                        "channel": m.channel.name,
                        "is_reply": bool(m.reference and m.reference.message_id),
                        "reply_to_id": (
                            str(m.reference.message_id)
                            if (m.reference and m.reference.message_id)
                            else None
                        ),
                        "mentions": [u.display_name for u in m.mentions],
                        "attachments": [a.url for a in m.attachments],
                        "embeds_count": len(m.embeds),
                    }
                )

        except discord.HTTPException as e:
            if e.status == 429:
                # Handle rate limiting (unlikely with small limits, but possible)
                await ctx.send("⚠️ Rate limited. Please try again in a moment.")
                return
            else:
                # Re-raise other HTTP errors
                raise

        pretty = json.dumps(out, ensure_ascii=False, indent=2)
        if len(pretty) < 1800:
            await ctx.send(f"```json\n{pretty}\n```")
        else:
            buf = BytesIO(pretty.encode("utf-8"))
            await ctx.send(
                file=discord.File(buf, filename=f"peekraw_{ctx.channel.name}.json")
            )
