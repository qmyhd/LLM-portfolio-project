# Bootstrap AWS secrets FIRST, before any other src imports
from src.env_bootstrap import bootstrap_env

bootstrap_env()

import logging
import discord
from discord.ext import commands
from dotenv import load_dotenv
from src.config import settings
from . import create_bot

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def main():
    load_dotenv()
    config = settings()

    token = config.DISCORD_BOT_TOKEN
    if not token:
        raise RuntimeError("DISCORD_BOT_TOKEN not set")

    bot = create_bot()
    bot.run(token)


if __name__ == "__main__":
    main()
