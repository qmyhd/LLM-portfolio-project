import yfinance as yf
from discord.ext import commands


def register(bot: commands.Bot):
    @bot.command(name="EOD")
    async def eod_info(ctx):
        await ctx.send("Enter a stock:")

        def check(msg):
            return msg.author == ctx.author and msg.channel == ctx.channel

        try:
            msg = await bot.wait_for("message", check=check, timeout=30)
            data = yf.download(msg.content, period="1d")
            if data.empty:
                await ctx.send(f"Could not find data for {msg.content}")
                return
            info = data.iloc[0]
            response = (
                f"EOD update on ${msg.content}\n"
                f"-Open: {info['Open']:.2f}\n"
                f"-High: {info['High']:.2f}\n"
                f"-Low: {info['Low']:.2f}\n"
                f"-Close: {info['Close']:.2f}\n"
                f"-Volume: {info['Volume']}"
            )
            await ctx.send(response)
        except Exception:
            await ctx.send("Error getting stock data. Please try again later.")
