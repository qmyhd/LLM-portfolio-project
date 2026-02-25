import logging

from discord.ext import commands

from . import eod, history, process, snaptrade_cmd, twitter_cmd

logger = logging.getLogger(__name__)

try:
    from . import chart
except ModuleNotFoundError:
    chart = None
    logger.info(
        "Chart command is unavailable: charting dependencies not installed. "
        "Install requirements-dev.txt to enable it."
    )


def register_commands(bot: commands.Bot, twitter_client=None):
    history.register(bot, twitter_client)
    if chart is not None:
        chart.register(bot)
    eod.register(bot)
    process.register(bot, twitter_client)
    twitter_cmd.register(bot)
    snaptrade_cmd.register(bot, twitter_client)
