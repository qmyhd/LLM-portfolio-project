import discord
from discord.ext import commands
import yfinance as yf
import mplfinance as mpf


def register(bot: commands.Bot):
    @bot.command(name="chart")
    async def create_chart(ctx):
        await ctx.send("Enter a stock:")

        def check(msg):
            return msg.author == ctx.author and msg.channel == ctx.channel

        try:
            msg = await bot.wait_for("message", check=check, timeout=30)
            data = yf.download(msg.content, period="1d", interval="1m")
            if data.empty:
                await ctx.send(f"Could not find data for {msg.content}")
                return
            mpf.plot(data, type='candle', volume=True, style='yahoo', savefig='chart.png')
            await ctx.send(file=discord.File("chart.png"))
        except Exception:
            await ctx.send("Error creating chart. Please try again later.")
