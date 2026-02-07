from discord.ext import commands

from src.config import settings
from src.logging_utils import log_message_to_database

# Channel name to type mapping
CHANNEL_NAME_TO_TYPE = {
    "trading": "trading",
    "trades": "trading",
    "market": "market",
    "market-chat": "market",
    "general": "general",
    "chat": "general",
}


def get_channel_type(channel_name: str) -> str:
    """Map channel name to channel type.

    Args:
        channel_name: Discord channel name

    Returns:
        Channel type: 'trading', 'market', or 'general'
    """
    name_lower = channel_name.lower()
    for pattern, channel_type in CHANNEL_NAME_TO_TYPE.items():
        if pattern in name_lower:
            return channel_type
    return "general"  # Default to general


def register_events(bot: commands.Bot, twitter_client=None):
    @bot.event
    async def on_ready():
        print(f"✅ Bot is online and logged in as {bot.user}")

    @bot.event
    async def on_message(message):
        # Determine message flags
        is_bot = message.author.bot or message.author == bot.user

        # Detect command messages (starts with command prefix)
        content = message.content.strip() if message.content else ""
        command_prefix = getattr(bot, "command_prefix", "!")

        # Handle both string and list/tuple prefixes
        if isinstance(command_prefix, (list, tuple)):
            is_command = any(content.startswith(prefix) for prefix in command_prefix)
        else:
            is_command = content.startswith(str(command_prefix))

        # Get channel type
        channel_type = get_channel_type(message.channel.name)

        config = settings()
        if str(message.channel.id) in config.log_channel_ids_list:
            # Log ALL messages with flags - let downstream pipeline filter
            # Bot/command messages are stored but flagged for exclusion from NLP
            log_message_to_database(
                message,
                twitter_client=twitter_client,
                is_bot=is_bot,
                is_command=is_command,
                channel_type=channel_type,
            )

        # Always process commands to handle user commands
        await bot.process_commands(message)
