import discord
from discord.ext import commands as dpy_cmds  # rename the import

# or rename your local file to bot_commands.py and adjust the import below

__all__ = ["create_bot"]

def create_bot(command_prefix: str = "!", twitter_client=None):
    intents = discord.Intents.default()
    intents.message_content = True

    bot = dpy_cmds.Bot(command_prefix=command_prefix, intents=intents)

    from .commands import register_commands  # ok – this no longer shadows dpy_cmds
    from .events import register_events

    register_events(bot, twitter_client)
    register_commands(bot, twitter_client)
    return bot