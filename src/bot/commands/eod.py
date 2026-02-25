import asyncio
from datetime import date, timedelta
from discord.ext import commands
from src.bot.ui import EmbedFactory, EmbedCategory
from src.price_service import get_ohlcv


def register(bot: commands.Bot):
    @bot.command(name="EOD")
    async def eod_info(ctx):
        """Interactive End-of-Day stock data lookup.

        Data sourced from Databento (Supabase ohlcv_daily).
        """

        # Initial prompt
        prompt_msg = await ctx.send(
            embed=EmbedFactory.create(
                title="End-of-Day Quote",
                description="Please enter a stock symbol (e.g., AAPL, MSFT):",
                category=EmbedCategory.MARKET,
                footer_hint="Waiting for response...",
            )
        )

        def check(msg):
            return msg.author == ctx.author and msg.channel == ctx.channel

        try:
            msg = await bot.wait_for("message", check=check, timeout=30)
            symbol = msg.content.upper().replace("$", "").strip()

            # Show loading state
            await prompt_msg.edit(
                embed=EmbedFactory.loading(
                    title=f"Fetching Data: {symbol}",
                    description="Retrieving latest market data from Databento...",
                )
            )

            # Fetch data from price_service (last 5 days to get the most recent)
            loop = asyncio.get_event_loop()
            end_date = date.today()
            start_date = end_date - timedelta(days=7)

            data = await loop.run_in_executor(
                None, lambda: get_ohlcv(symbol, start_date, end_date)
            )

            if data.empty:
                await ctx.send(
                    embed=EmbedFactory.warning(
                        title="Data Not Found",
                        description=f"Could not find market data for **{symbol}**.",
                        footer_hint="Check the symbol and ensure OHLCV data has been backfilled.",
                    )
                )
                return

            # Extract latest data (last row)
            info = data.iloc[-1]
            date_str = data.index[-1].strftime("%Y-%m-%d")

            # Create response embed
            embed = EmbedFactory.create(
                title=f"End-of-Day Update: ${symbol}",
                description=f"Latest market data for **{symbol}** (Databento)",
                category=EmbedCategory.MARKET,
            )

            embed.add_field(name="Open", value=f"${info['Open']:.2f}", inline=True)
            embed.add_field(name="High", value=f"${info['High']:.2f}", inline=True)
            embed.add_field(name="Low", value=f"${info['Low']:.2f}", inline=True)
            embed.add_field(name="Close", value=f"${info['Close']:.2f}", inline=True)
            embed.add_field(
                name="Volume", value=f"{int(info['Volume']):,}", inline=True
            )

            embed.set_footer(text=f"Date: {date_str} | Source: Databento")

            await ctx.send(embed=embed)

        except TimeoutError:
            await prompt_msg.edit(
                embed=EmbedFactory.warning(
                    title="Timeout",
                    description="No symbol provided within 30 seconds.",
                )
            )
        except Exception as e:
            await ctx.send(
                embed=EmbedFactory.error(
                    title="Market Data Error", error_details=str(e)
                )
            )
