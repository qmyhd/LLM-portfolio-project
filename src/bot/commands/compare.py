import discord
from discord.ext import commands
import yfinance as yf
import mplfinance as mpf


def register(bot: commands.Bot):
    @bot.command(name="compare")
    async def compare(ctx):
        await ctx.send("Enter first stock:")

        def check(msg):
            return msg.author == ctx.author and msg.channel == ctx.channel

        try:
            msg1 = await bot.wait_for("message", check=check, timeout=30)
            await ctx.send("Enter second stock:")
            msg2 = await bot.wait_for("message", check=check, timeout=30)
            df1 = yf.download(msg1.content, period="1d", interval="1m")
            df2 = yf.download(msg2.content, period="1d", interval="1m")
            if df1.empty or df2.empty:
                await ctx.send("Could not fetch data for comparison")
                return
            adds = [mpf.make_addplot(df2['Close'], panel=1, ylabel=msg2.content)]
            mpf.plot(df1, type='candle', addplot=adds, style='yahoo', savefig='chart.png')
            await ctx.send(file=discord.File("chart.png"))
        except Exception:
            await ctx.send("Error comparing stocks. Please try again later.")
