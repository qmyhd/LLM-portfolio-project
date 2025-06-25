from discord.ext import commands

from . import history, chart, eod, compare


def register_commands(bot: commands.Bot, twitter_client=None):
    history.register(bot, twitter_client)
    chart.register(bot)
    eod.register(bot)
    compare.register(bot)
