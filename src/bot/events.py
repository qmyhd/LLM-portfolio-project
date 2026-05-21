from discord.ext import commands

from src.config import settings
from src.logging_utils import log_message_to_database

# Channel-name → channel-type mapping.
#
# Order matters: the FIRST pattern whose substring is present in the
# (lowercased) channel name wins. The list is ordered most-specific →
# least-specific so e.g. "trading-picks" lands on `trading` instead of
# being snagged by a vaguer "chat" pattern.
#
# We keep the typed value down to three buckets the rest of the app
# already understands (`trading`, `market`, `general`); narrower channel
# variants (picks, signals, news, etc.) get folded in but stay
# distinguishable via the raw `channel` column.
CHANNEL_NAME_TO_TYPE: tuple[tuple[str, str], ...] = (
    # ---- trading bucket -----------------------------------------------------
    ("trading-picks", "trading"),
    ("trade-picks", "trading"),
    ("trading-signals", "trading"),
    ("trade-signals", "trading"),
    ("trading-ideas", "trading"),
    ("trade-ideas", "trading"),
    ("trading-alerts", "trading"),
    ("trade-alerts", "trading"),
    ("picks", "trading"),
    ("signals", "trading"),
    ("alerts", "trading"),
    ("trading", "trading"),
    ("trades", "trading"),
    # ---- market bucket ------------------------------------------------------
    ("market-news", "market"),
    ("news", "market"),
    ("market-chat", "market"),
    ("market", "market"),
    ("macro", "market"),
    ("earnings", "market"),
    # ---- general bucket -----------------------------------------------------
    ("general", "general"),
    ("chat", "general"),
    ("off-topic", "general"),
)


def get_channel_type(channel_name: str | None) -> str:
    """Map a Discord channel name to one of {trading, market, general}.

    The match is ordered: the first ``(pattern, type)`` whose pattern is a
    substring of the lowercased name wins. Returns ``'general'`` when no
    pattern matches so downstream callers always get a usable label.
    """
    if not channel_name:
        return "general"
    name_lower = channel_name.lower()
    for pattern, channel_type in CHANNEL_NAME_TO_TYPE:
        if pattern in name_lower:
            return channel_type
    return "general"


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
