import discord
from discord.ext import commands

from .events import register_events
from .commands import register_commands

__all__ = ["create_bot"]


def create_bot(command_prefix: str = "!", twitter_client=None) -> commands.Bot:
    intents = discord.Intents.default()
    intents.message_content = True
    bot = commands.Bot(command_prefix=command_prefix, intents=intents)
    register_events(bot, twitter_client)
    register_commands(bot, twitter_client)
    return bot
