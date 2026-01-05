from pathlib import Path

from discord.ext import commands

from src.config import settings
from src.logging_utils import log_message_to_file

BASE_DIR = Path(__file__).resolve().parents[2]
RAW_DIR = BASE_DIR / "data" / "raw"
RAW_DIR.mkdir(parents=True, exist_ok=True)
DISCORD_CSV = RAW_DIR / "discord_msgs.csv"
TWEET_CSV = RAW_DIR / "x_posts_log.csv"


def register_events(bot: commands.Bot, twitter_client=None):
    @bot.event
    async def on_ready():
        print(f"✅ Bot is online and logged in as {bot.user}")

    @bot.event
    async def on_message(message):
        # Skip bot's own messages
        if message.author == bot.user:
            return

        # Skip messages from other bots (prevents logging bot responses)
        if message.author.bot:
            await bot.process_commands(message)
            return

        # Skip command messages (messages starting with bot command prefix)
        # These are processed by the bot, not logged as user messages
        content = message.content.strip() if message.content else ""
        command_prefix = getattr(bot, "command_prefix", "!")

        # Handle both string and list/tuple prefixes
        if isinstance(command_prefix, (list, tuple)):
            is_command = any(content.startswith(prefix) for prefix in command_prefix)
        else:
            is_command = content.startswith(str(command_prefix))

        config = settings()
        if str(message.channel.id) in config.log_channel_ids_list:
            # Only log non-command messages from real users
            if not is_command:
                log_message_to_file(message, DISCORD_CSV, TWEET_CSV, twitter_client)

        # Always process commands to handle user commands
        await bot.process_commands(message)
