from discord.ext import commands

from . import chart, eod, history, process, snaptrade_cmd, twitter_cmd, sports_arb


def register_commands(bot: commands.Bot, twitter_client=None):
    history.register(bot, twitter_client)
    chart.register(bot)
    eod.register(bot)
    process.register(bot, twitter_client)
    twitter_cmd.register(bot)
    snaptrade_cmd.register(bot, twitter_client)
    sports_arb.register(bot, twitter_client)
