"""
Discord data processing command for the bot.
Allows users to trigger channel-specific data processing.
"""

from discord.ext import commands

from src.channel_processor import get_channel_stats
from src.channel_processor import process_channel_data as process_channel


def register(bot: commands.Bot):
    @bot.command(name="process")
    async def process_channel_data(ctx, channel_type: str = "general"):
        """
        Process Discord messages for the current channel into cleaned database.
        
        Usage: !process [channel_type]
        - channel_type: 'general' or 'trading' (default: general)
        """
        try:
            await ctx.send(f"🔄 Processing Discord data for #{ctx.channel.name} as {channel_type} channel...")
            
            # Process the current channel
            processing_result = process_channel(ctx.channel.name, channel_type)
            
            if processing_result["success"]:
                if processing_result["processed_count"] > 0:
                    await ctx.send(f"✅ **Processing Complete**\n"
                                 f"• Channel: #{ctx.channel.name}\n"
                                 f"• Type: {channel_type}\n"
                                 f"• Processed: {processing_result['processed_count']} messages")
                else:
                    await ctx.send(f"ℹ️ **No New Messages**\n"
                                 f"• Channel: #{ctx.channel.name}\n"
                                 f"• All messages are already processed")
            else:
                await ctx.send(f"❌ **Processing Failed**\n"
                             f"• Channel: #{ctx.channel.name}\n"
                             f"• Error: {processing_result.get('error', 'Unknown error')}")
                             
        except Exception as e:
            await ctx.send(f"❌ **Error processing channel data**\n"
                         f"• Error: {str(e)}\n"
                         f"• Please check logs and try again")

    @bot.command(name="stats")
    async def channel_stats_cmd(ctx):
        """
        Show statistics for the current Discord channel.
        
        Usage: !stats
        """
        try:
            await ctx.send("📊 Fetching channel statistics...")
            
            stats = get_channel_stats(ctx.channel.name)
            
            if not stats or all(v == 0 for v in stats.values()):
                await ctx.send("ℹ️ No processed channel data found. Use `!process` to process current channel first.")
                return
            
            await ctx.send(f"📊 **Channel Statistics: #{ctx.channel.name}**\n"
                         f"• Raw Messages: {stats['raw_messages']}\n"
                         f"• General Processed: {stats['general_processed']}\n"
                         f"• Trading Processed: {stats['trading_processed']}\n"
                         f"• Twitter Data: {stats['twitter_data']}")
                         
        except Exception as e:
            await ctx.send(f"❌ **Error fetching statistics**\n"
                         f"• Error: {str(e)}\n"
                         f"• Please check logs and try again")

    @bot.command(name="globalstats")
    async def global_stats_cmd(ctx):
        """
        Show statistics for all processed Discord channels.
        
        Usage: !globalstats
        """
        try:
            await ctx.send("📊 Fetching global statistics...")
            
            stats = get_channel_stats()  # No specific channel = global stats
            
            if not stats or all(v == 0 for v in stats.values()):
                await ctx.send("ℹ️ No processed data found. Use `!process` to process channels first.")
                return
            
            await ctx.send(f"📊 **Global Statistics**\n"
                         f"• Total Raw Messages: {stats['raw_messages']}\n"
                         f"• Total General Processed: {stats['general_processed']}\n"
                         f"• Total Trading Processed: {stats['trading_processed']}\n"
                         f"• Total Twitter Data: {stats['twitter_data']}")
                         
        except Exception as e:
            await ctx.send(f"❌ **Error fetching global statistics**\n"
                         f"• Error: {str(e)}\n"
                         f"• Please check logs and try again")
