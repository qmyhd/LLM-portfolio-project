import discord
from discord.ext import commands
import subprocess
import os
import sys


def register(bot: commands.Bot, twitter_client=None):
    @bot.command(name="arb")
    async def arb(ctx):
        """
        Launch the local Arbitrage Dashboard website.
        """
        try:
            # Path to the script
            script_path = os.path.join("scripts", "run_arb_site.py")

            # Check if script exists
            if not os.path.exists(script_path):
                await ctx.send(f"❌ Error: Could not find script at `{script_path}`")
                return

            # Launch the script as a subprocess
            # We use Popen to let it run in the background/independent of the bot process
            subprocess.Popen([sys.executable, script_path], cwd=os.getcwd())

            await ctx.send(
                "🚀 **Arbitrage Dashboard Launching...**\n"
                "The dashboard should open in your browser shortly.\n"
                "If it doesn't, visit: http://localhost:5173"
            )

        except Exception as e:
            await ctx.send(f"❌ Failed to launch dashboard: {str(e)}")
