"""
Twitter analysis command for the bot.
Allows users to get Twitter data from the database.

Uses the centralized UI system for consistent embed styling.
"""

import discord
from discord.ext import commands

from src.db import execute_sql
from src.bot.ui import EmbedFactory, build_embed, EmbedCategory


def register(bot: commands.Bot):
    @bot.command(name="twitter")
    async def twitter_data(ctx, symbol: str | None = None):
        """Show Twitter data for a specific stock symbol or overview.

        Usage:
            !twitter       - Show overall Twitter data stats
            !twitter AAPL  - Show tweets mentioning AAPL
        """
        try:
            if symbol:
                symbol = symbol.upper().replace("$", "")
                rows = execute_sql(
                    """
                    SELECT discord_date, tweet_date, content, stock_tags, author, channel
                    FROM twitter_data
                    WHERE stock_tags LIKE :symbol_pattern
                    ORDER BY discord_date DESC
                    LIMIT 10
                """,
                    {"symbol_pattern": f"%{symbol}%"},
                    fetch_results=True,
                )

                if not rows:
                    await ctx.send(
                        embed=EmbedFactory.warning(
                            title=f"Twitter Data: ${symbol}",
                            description="No tweets found for this symbol.",
                        )
                    )
                    return

                embed = build_embed(
                    category=EmbedCategory.TWITTER,
                    title=f"Twitter Data: ${symbol}",
                    description=f"Last **{len(rows)}** tweets mentioning ${symbol}",
                )

                for i, row in enumerate(rows[:5]):  # Show max 5 in embed
                    discord_date, tweet_date, content, stock_tags, author, channel = row
                    display_content = (
                        content[:100] + "..." if len(content) > 100 else content
                    )
                    date_str = str(discord_date)[:10] if discord_date else "N/A"
                    embed.add_field(
                        name=f"@{author} in #{channel}",
                        value=f"{display_content}\n📅 {date_str}",
                        inline=False,
                    )

                if len(rows) > 5:
                    embed.set_footer(text=f"+{len(rows) - 5} more tweets found")

                await ctx.send(embed=embed)

            else:
                # Show general Twitter stats
                stats_rows = execute_sql(
                    """
                    SELECT COUNT(*) as total,
                           COUNT(DISTINCT stock_tags) as unique_stocks,
                           COUNT(DISTINCT channel) as channels
                    FROM twitter_data
                    WHERE stock_tags IS NOT NULL AND stock_tags != ''
                """,
                    fetch_results=True,
                )

                if not stats_rows or not stats_rows[0][0]:
                    await ctx.send(
                        embed=EmbedFactory.warning(
                            title="Twitter Data",
                            description="No Twitter data found in database.",
                        )
                    )
                    return

                total, unique_stocks, channels = stats_rows[0]

                # Get top mentioned stocks
                top_stocks = execute_sql(
                    """
                    SELECT stock_tags, COUNT(*) as mentions
                    FROM twitter_data
                    WHERE stock_tags IS NOT NULL AND stock_tags != ''
                    GROUP BY stock_tags
                    ORDER BY mentions DESC
                    LIMIT 5
                """,
                    fetch_results=True,
                )

                embed = build_embed(
                    category=EmbedCategory.TWITTER,
                    title="Twitter Data Overview",
                )
                embed.add_field(name="📝 Total Tweets", value=f"{total:,}", inline=True)
                embed.add_field(
                    name="📊 Unique Stocks", value=f"{unique_stocks:,}", inline=True
                )
                embed.add_field(name="📢 Channels", value=f"{channels:,}", inline=True)

                if top_stocks:
                    top_list = "\n".join(
                        [f"• **{stock}**: {count}" for stock, count in top_stocks]
                    )
                    embed.add_field(
                        name="🔥 Top Mentioned Stocks",
                        value=top_list or "None",
                        inline=False,
                    )

                await ctx.send(embed=embed)

        except Exception as e:
            await ctx.send(
                embed=EmbedFactory.error(
                    title="Twitter Data Error", error_details=str(e)[:200]
                )
            )

    @bot.command(name="tweets")
    async def recent_tweets(ctx, symbol: str | None = None, count: int = 5):
        """Get recent tweets for a stock symbol.

        Usage:
            !tweets         - Last 5 tweets (all symbols)
            !tweets AAPL    - Last 5 tweets for AAPL
            !tweets AAPL 10 - Last 10 tweets for AAPL
        """
        try:
            count = min(max(count, 1), 10)  # Clamp between 1 and 10

            if symbol:
                symbol = symbol.upper().replace("$", "")
                rows = execute_sql(
                    """
                    SELECT discord_date, tweet_date, content, author, channel, stock_tags
                    FROM twitter_data
                    WHERE stock_tags LIKE :symbol_pattern
                    ORDER BY discord_date DESC
                    LIMIT :count
                """,
                    {"symbol_pattern": f"%{symbol}%", "count": count},
                    fetch_results=True,
                )
                title = f"Recent Tweets: ${symbol}"
            else:
                rows = execute_sql(
                    """
                    SELECT discord_date, tweet_date, content, author, channel, stock_tags
                    FROM twitter_data
                    ORDER BY discord_date DESC
                    LIMIT :count
                """,
                    {"count": count},
                    fetch_results=True,
                )
                title = f"Recent Tweets (Last {count})"

            if not rows:
                await ctx.send(
                    embed=EmbedFactory.warning(
                        title=title,
                        description="No tweets found."
                        + (f" for ${symbol}" if symbol else ""),
                    )
                )
                return

            embed = build_embed(
                category=EmbedCategory.TWITTER,
                title=title,
            )

            for row in rows:
                discord_date, tweet_date, content, author, channel, stock_tags = row
                display_content = (
                    content[:120] + "..." if len(content) > 120 else content
                )
                date_str = (
                    str(tweet_date)[:10] if tweet_date else str(discord_date)[:10]
                )
                stocks = f" | {stock_tags}" if stock_tags else ""

                embed.add_field(
                    name=f"@{author} • {date_str}",
                    value=f"{display_content}{stocks}",
                    inline=False,
                )

            await ctx.send(embed=embed)

        except Exception as e:
            await ctx.send(
                embed=EmbedFactory.error(
                    title="Tweets Error", error_details=str(e)[:200]
                )
            )

    @bot.command(name="twitter_stats")
    async def twitter_stats(ctx, channel_name: str | None = None):
        """Show detailed Twitter statistics.

        Usage:
            !twitter_stats           - Overall stats
            !twitter_stats general   - Stats for #general channel
        """
        try:
            if channel_name:
                stats_rows = execute_sql(
                    """
                    SELECT COUNT(*) as total_tweets,
                           COUNT(DISTINCT stock_tags) as unique_stocks,
                           COUNT(DISTINCT author) as unique_authors
                    FROM twitter_data
                    WHERE channel = :channel AND stock_tags IS NOT NULL AND stock_tags != ''
                """,
                    {"channel": channel_name},
                    fetch_results=True,
                )
                title = f"Twitter Stats: #{channel_name}"
            else:
                stats_rows = execute_sql(
                    """
                    SELECT COUNT(*) as total_tweets,
                           COUNT(DISTINCT stock_tags) as unique_stocks,
                           COUNT(DISTINCT author) as unique_authors,
                           COUNT(DISTINCT channel) as unique_channels
                    FROM twitter_data
                    WHERE stock_tags IS NOT NULL AND stock_tags != ''
                """,
                    fetch_results=True,
                )
                title = "Twitter Statistics"

            if not stats_rows or not stats_rows[0][0]:
                await ctx.send(
                    embed=EmbedFactory.warning(
                        title=title, description="No Twitter data found."
                    )
                )
                return

            embed = build_embed(
                category=EmbedCategory.TWITTER,
                title=title,
            )

            if channel_name:
                total_tweets, unique_stocks, unique_authors = stats_rows[0]
            else:
                total_tweets, unique_stocks, unique_authors, unique_channels = (
                    stats_rows[0]
                )
                embed.add_field(
                    name="📢 Channels", value=f"{unique_channels:,}", inline=True
                )

            embed.add_field(
                name="📝 Total Tweets", value=f"{total_tweets:,}", inline=True
            )
            embed.add_field(
                name="📊 Unique Stocks", value=f"{unique_stocks:,}", inline=True
            )
            embed.add_field(
                name="👥 Unique Authors", value=f"{unique_authors:,}", inline=True
            )

            # Get recent activity (PostgreSQL syntax)
            recent_activity = execute_sql(
                """
                SELECT COUNT(*) as recent_tweets
                FROM twitter_data
                WHERE discord_date >= NOW() - INTERVAL '7 days'
                AND stock_tags IS NOT NULL AND stock_tags != ''
            """,
                fetch_results=True,
            )

            if recent_activity and recent_activity[0][0]:
                embed.add_field(
                    name="⏰ Last 7 Days",
                    value=f"{recent_activity[0][0]:,} tweets",
                    inline=True,
                )

            await ctx.send(embed=embed)

        except Exception as e:
            await ctx.send(
                embed=EmbedFactory.error(
                    title="Twitter Stats Error", error_details=str(e)[:200]
                )
            )

    @bot.command(name="twitter_backfill")
    async def twitter_backfill(ctx, action: str = "status"):
        """Backfill Twitter data from Discord messages with rate limit protection.

        Usage:
            !twitter_backfill status  - Show pipeline status
            !twitter_backfill dry     - Preview what would be processed
            !twitter_backfill run     - Process tweets (max 5 per run)
            !twitter_backfill fix     - Reprocess incomplete tweets
        """
        try:
            # Import the backfill functions
            from src.twitter_analysis import (
                backfill_tweets_from_discord,
                reprocess_incomplete_tweets,
                get_twitter_pipeline_status,
            )

            action = action.lower()

            if action == "status":
                # Show current pipeline status
                status = get_twitter_pipeline_status()

                if status.get("success"):
                    embed = build_embed(
                        category=EmbedCategory.TWITTER,
                        title="Twitter Pipeline Status",
                    )
                else:
                    embed = EmbedFactory.error(
                        title="Twitter Pipeline Status",
                        description="Failed to get status",
                    )

                embed.add_field(
                    name="📊 Total Tweets",
                    value=f"{status.get('total_tweets', 0):,}",
                    inline=True,
                )
                embed.add_field(
                    name="✅ Complete",
                    value=f"{status.get('complete_tweets', 0):,}",
                    inline=True,
                )
                embed.add_field(
                    name="⚠️ Incomplete",
                    value=f"{status.get('incomplete_tweets', 0):,}",
                    inline=True,
                )
                embed.add_field(
                    name="💬 Discord Messages",
                    value=f"{status.get('discord_messages_with_links', 0):,} with Twitter links",
                    inline=False,
                )

                rate_limit = status.get("rate_limit", {})
                if rate_limit.get("is_limited"):
                    wait_secs = rate_limit.get("wait_seconds", 0)
                    embed.add_field(
                        name="🚫 Rate Limited",
                        value=f"Wait {wait_secs:.0f}s ({wait_secs/60:.1f}min)",
                        inline=False,
                    )
                else:
                    embed.add_field(
                        name="✅ Rate Limit",
                        value="OK - Ready to process",
                        inline=False,
                    )

                await ctx.send(embed=embed)

            elif action == "dry":
                # Dry run - show what would be processed
                status_msg = await ctx.send(
                    embed=EmbedFactory.loading(
                        title="Dry Run",
                        description="Scanning Discord messages for Twitter links...",
                    )
                )

                result = backfill_tweets_from_discord(dry_run=True, max_tweets=20)

                embed = build_embed(
                    category=EmbedCategory.TWITTER,
                    title="Dry Run Results",
                    description=result.get("message", "Scan complete"),
                )

                tweet_ids = result.get("tweet_ids", [])
                if tweet_ids:
                    embed.add_field(
                        name="Tweet IDs Found",
                        value="\n".join(tweet_ids[:10])
                        + (
                            f"\n... and {len(tweet_ids) - 10} more"
                            if len(tweet_ids) > 10
                            else ""
                        ),
                        inline=False,
                    )

                await status_msg.edit(embed=embed)

            elif action == "run":
                # Actually process tweets (with rate limit protection)
                status_msg = await ctx.send(
                    embed=EmbedFactory.loading(
                        title="Processing Tweets",
                        description="Processing tweets from Discord messages (max 5)...",
                    )
                )

                result = backfill_tweets_from_discord(max_tweets=5)

                if result.get("rate_limited"):
                    embed = EmbedFactory.warning(
                        title="Rate Limited",
                        description=result.get("message", "Processing complete"),
                    )
                elif result.get("success"):
                    embed = EmbedFactory.success(
                        title="Backfill Complete",
                        description=result.get("message", "Processing complete"),
                    )
                else:
                    embed = EmbedFactory.error(
                        title="Backfill Failed",
                        description=result.get("message", "Processing failed"),
                    )

                embed.add_field(
                    name="✅ Processed",
                    value=str(result.get("processed_count", 0)),
                    inline=True,
                )
                embed.add_field(
                    name="⏭️ Skipped",
                    value=str(result.get("skipped_count", 0)),
                    inline=True,
                )
                embed.add_field(
                    name="❌ Errors",
                    value=str(result.get("error_count", 0)),
                    inline=True,
                )

                if result.get("wait_seconds"):
                    wait = result["wait_seconds"]
                    embed.add_field(
                        name="⏰ Wait Time",
                        value=f"{wait:.0f}s ({wait/60:.1f}min)",
                        inline=False,
                    )

                await status_msg.edit(embed=embed)

            elif action == "fix":
                # Reprocess incomplete tweets
                status_msg = await ctx.send(
                    embed=EmbedFactory.loading(
                        title="Reprocessing",
                        description="Reprocessing incomplete tweets...",
                    )
                )

                result = reprocess_incomplete_tweets(max_tweets=5)

                if result.get("rate_limited"):
                    embed = EmbedFactory.warning(
                        title="Rate Limited",
                        description=result.get("message", "Reprocessing complete"),
                    )
                elif result.get("success"):
                    embed = EmbedFactory.success(
                        title="Reprocessing Complete",
                        description=result.get("message", "Reprocessing complete"),
                    )
                else:
                    embed = EmbedFactory.error(
                        title="Reprocessing Failed",
                        description=result.get("message", "Reprocessing failed"),
                    )

                embed.add_field(
                    name="✅ Fixed",
                    value=str(result.get("processed_count", 0)),
                    inline=True,
                )
                embed.add_field(
                    name="❌ Errors",
                    value=str(result.get("error_count", 0)),
                    inline=True,
                )

                if result.get("tweet_ids"):
                    embed.add_field(
                        name="Tweet IDs",
                        value=", ".join(result["tweet_ids"][:5]),
                        inline=False,
                    )

                await status_msg.edit(embed=embed)

            else:
                await ctx.send(
                    embed=EmbedFactory.warning(
                        title="Unknown Action",
                        description=f"Unknown action: `{action}`\n\nValid options: `status`, `dry`, `run`, `fix`",
                    )
                )

        except Exception as e:
            await ctx.send(
                embed=EmbedFactory.error(
                    title="Backfill Error", error_details=str(e)[:200]
                )
            )
