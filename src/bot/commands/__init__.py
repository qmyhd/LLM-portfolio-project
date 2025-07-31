from discord.ext import commands

from . import chart, eod, history, process, twitter_cmd


def register_commands(bot: commands.Bot, twitter_client=None):
    history.register(bot, twitter_client)
    chart.register(bot)
    eod.register(bot)
    process.register(bot)
    twitter_cmd.register(bot)
