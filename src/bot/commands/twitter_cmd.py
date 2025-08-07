"""
Twitter analysis command for the bot.
Allows users to get Twitter data from the database.
"""

from discord.ext import commands

from src.database import execute_sql


def register(bot: commands.Bot):
    @bot.command(name="twitter")
    async def twitter_data(ctx, symbol: str | None = None):
        """Show Twitter data for a specific stock symbol or all data."""
        try:
            if symbol:
                # Show data for specific symbol
                rows = execute_sql("""
                    SELECT discord_date, tweet_date, content, stock_tags, author, channel
                    FROM twitter_data 
                    WHERE stock_tags LIKE ?
                    ORDER BY discord_date DESC
                    LIMIT 10
                """, (f"%{symbol.upper()}%",), fetch_results=True)
                
                if not rows:
                    await ctx.send(f"📊 No Twitter data found for **${symbol.upper()}**")
                    return
                
                response = f"📊 **Twitter Data for ${symbol.upper()}** (Last 10)\n\n"
                
                for row in rows:
                    discord_date, tweet_date, content, stock_tags, author, channel = row
                    # Truncate content if too long
                    display_content = content[:100] + "..." if len(content) > 100 else content
                    response += f"**@{author}** in #{channel}\n"
                    response += f"• {display_content}\n"
                    response += f"• Discord: {discord_date[:10]} | Tweet: {tweet_date[:10] if tweet_date else 'N/A'}\n"
                    response += f"• Stocks: {stock_tags}\n\n"
                    
                    # Check if response is getting too long
                    if len(response) > 1500:
                        await ctx.send(response)
                        response = ""
                
                if response:
                    await ctx.send(response)
                    
            else:
                # Show general Twitter stats
                stats_rows = execute_sql("""
                    SELECT COUNT(*) as total,
                           COUNT(DISTINCT stock_tags) as unique_stocks,
                           COUNT(DISTINCT channel) as channels
                    FROM twitter_data 
                    WHERE stock_tags IS NOT NULL AND stock_tags != ''
                """, fetch_results=True)
                
                if stats_rows:
                    try:
                        total, unique_stocks, channels = stats_rows[0]  # type: ignore
                    except (IndexError, TypeError):
                        await ctx.send("❌ Error retrieving Twitter data statistics")
                        return
                    
                    # Get most mentioned stocks
                    top_stocks = execute_sql("""
                        SELECT stock_tags, COUNT(*) as mentions
                        FROM twitter_data 
                        WHERE stock_tags IS NOT NULL AND stock_tags != ''
                        GROUP BY stock_tags
                        ORDER BY mentions DESC
                        LIMIT 5
                    """, fetch_results=True)
                    
                    response = "📊 **Twitter Data Summary**\n"
                    response += f"• Total Tweets: {total}\n"
                    response += f"• Unique Stocks: {unique_stocks}\n"
                    response += f"• Channels: {channels}\n\n"
                    
                    if top_stocks:
                        response += "**Top Mentioned Stocks:**\n"
                        for stock, count in top_stocks:
                            response += f"• {stock}: {count} mentions\n"
                    
                    await ctx.send(response)
                else:
                    await ctx.send("📊 No Twitter data found in database")
                    
        except Exception as e:
            await ctx.send(f"❌ **Error fetching Twitter data**: {str(e)}")

    @bot.command(name="tweets")
    async def recent_tweets(ctx, symbol: str | None = None, count: int = 5):
        """
        Get recent tweets for a stock symbol from database.
        
        Usage: !tweets [AAPL] [count]
        - symbol: Stock symbol (optional)
        - count: Number of tweets to show (default: 5, max: 10)
        """
        try:
            if count > 10:
                count = 10
            elif count < 1:
                count = 5
            
            if symbol:
                # Show tweets for specific symbol
                symbol = symbol.upper().replace('$', '')
                rows = execute_sql("""
                    SELECT discord_date, tweet_date, content, author, channel, stock_tags
                    FROM twitter_data 
                    WHERE stock_tags LIKE ?
                    ORDER BY discord_date DESC
                    LIMIT ?
                """, (f"%{symbol}%", count), fetch_results=True)
                
                header = f"🐦 **Recent Tweets for ${symbol}**"
            else:
                # Show recent tweets for all symbols
                rows = execute_sql("""
                    SELECT discord_date, tweet_date, content, author, channel, stock_tags
                    FROM twitter_data 
                    ORDER BY discord_date DESC
                    LIMIT ?
                """, (count,), fetch_results=True)
                
                header = f"🐦 **Recent Tweets (Last {count})**"
            
            if not rows:
                if symbol:
                    await ctx.send(f"🐦 No tweets found for **${symbol}**")
                else:
                    await ctx.send("🐦 No tweets found in database")
                return
            
            response = header + "\n\n"
            
            for row in rows:
                discord_date, tweet_date, content, author, channel, stock_tags = row
                
                # Truncate content if too long
                display_content = content[:150] + "..." if len(content) > 150 else content
                
                response += f"**@{author}** in #{channel}\n"
                response += f"• {display_content}\n"
                
                if tweet_date:
                    response += f"• Posted: {tweet_date[:10]}"
                else:
                    response += f"• Discord: {discord_date[:10]}"
                    
                if stock_tags:
                    response += f" | Stocks: {stock_tags}\n\n"
                else:
                    response += "\n\n"
                
                # Check if response is getting too long
                if len(response) > 1500:
                    await ctx.send(response)
                    response = ""
            
            if response:
                await ctx.send(response)
                
        except Exception as e:
            await ctx.send(f"❌ **Error fetching tweets**: {str(e)}")

    @bot.command(name="twitter_stats")
    async def twitter_stats(ctx, channel_name: str | None = None):
        """
        Show detailed Twitter statistics.
        
        Usage: !twitter_stats [channel_name]
        """
        try:
            if channel_name:
                # Stats for specific channel
                stats_rows = execute_sql("""
                    SELECT COUNT(*) as total_tweets,
                           COUNT(DISTINCT stock_tags) as unique_stocks,
                           COUNT(DISTINCT author) as unique_authors
                    FROM twitter_data 
                    WHERE channel = ? AND stock_tags IS NOT NULL AND stock_tags != ''
                """, (channel_name,), fetch_results=True)
                
                header = f"📊 **Twitter Stats for #{channel_name}**"
            else:
                # Overall stats
                stats_rows = execute_sql("""
                    SELECT COUNT(*) as total_tweets,
                           COUNT(DISTINCT stock_tags) as unique_stocks,
                           COUNT(DISTINCT author) as unique_authors,
                           COUNT(DISTINCT channel) as unique_channels
                    FROM twitter_data 
                    WHERE stock_tags IS NOT NULL AND stock_tags != ''
                """, fetch_results=True)
                
                header = "📊 **Overall Twitter Statistics**"
            
            if not stats_rows:
                await ctx.send("📊 No Twitter data found")
                return
                
            try:
                if channel_name:
                    total_tweets, unique_stocks, unique_authors = stats_rows[0]  # type: ignore
                    response = header + "\n"
                    response += f"• Total Tweets: {total_tweets}\n"
                    response += f"• Unique Stocks: {unique_stocks}\n"
                    response += f"• Unique Authors: {unique_authors}\n"
                else:
                    total_tweets, unique_stocks, unique_authors, unique_channels = stats_rows[0]  # type: ignore
                    response = header + "\n"
                    response += f"• Total Tweets: {total_tweets}\n"
                    response += f"• Unique Stocks: {unique_stocks}\n"
                    response += f"• Unique Authors: {unique_authors}\n"
                    response += f"• Unique Channels: {unique_channels}\n"
            except (IndexError, TypeError):
                await ctx.send("❌ Error parsing Twitter statistics data")
                return
            
            # Get recent activity (last 7 days)
            recent_activity = execute_sql("""
                SELECT COUNT(*) as recent_tweets
                FROM twitter_data 
                WHERE discord_date >= datetime('now', '-7 days')
                AND stock_tags IS NOT NULL AND stock_tags != ''
            """, fetch_results=True)
            
            if recent_activity:
                try:
                    recent_count = recent_activity[0][0]  # type: ignore
                    response += f"• Recent Activity (7 days): {recent_count} tweets\n"
                except (IndexError, TypeError):
                    response += "• Recent Activity (7 days): 0 tweets\n"
            
            await ctx.send(response)
            
        except Exception as e:
            await ctx.send(f"❌ **Error fetching Twitter stats**: {str(e)}")
