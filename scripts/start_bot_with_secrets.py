#!/usr/bin/env python3
"""
Bot Startup Wrapper with AWS Secrets Manager

This script loads secrets from AWS Secrets Manager before starting the Discord bot.
Used by PM2 and systemd to ensure secrets are available as environment variables.

Usage:
    # Via PM2 (ecosystem.config.js points to this script)
    pm2 start ecosystem.config.js

    # Via systemd (discord-bot.service ExecStart points to this script)
    sudo systemctl start discord-bot

    # Direct execution (for testing)
    python scripts/start_bot_with_secrets.py

Environment Variables:
    USE_AWS_SECRETS: Set to "1" to load secrets from AWS Secrets Manager
    AWS_REGION: AWS region (default: us-east-1)
    AWS_SECRETS_PREFIX: Secret name prefix (default: llm-portfolio)
    AWS_SECRETS_ENV: Environment name (default: production)
"""

import logging
import os
import sys
from pathlib import Path

# Configure logging early
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("bot_startup")

# Add project root to path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))


def load_secrets() -> int:
    """
    Load secrets from AWS Secrets Manager if configured.

    Returns:
        Number of secrets loaded
    """
    use_aws_secrets = os.environ.get("USE_AWS_SECRETS", "").lower()

    if use_aws_secrets not in ("1", "true", "yes"):
        logger.info("USE_AWS_SECRETS not set, using .env file or existing environment")
        # Fall back to loading from .env if it exists
        try:
            from dotenv import load_dotenv

            env_file = BASE_DIR / ".env"
            if env_file.exists():
                load_dotenv(env_file)
                logger.info(f"Loaded environment from {env_file}")
        except ImportError:
            pass
        return 0

    # Load secrets from AWS Secrets Manager
    try:
        from src.aws_secrets import load_secrets_to_env

        count = load_secrets_to_env()
        logger.info("✅ Loaded secrets from AWS Secrets Manager")
        return count
    except ImportError as e:
        logger.error(f"❌ Could not import aws_secrets module: {e}")
        logger.error("   Make sure boto3 is installed: pip install boto3")
        sys.exit(1)
    except Exception as e:
        logger.error(f"❌ Failed to load secrets from AWS Secrets Manager: {e}")
        sys.exit(1)


def verify_required_secrets() -> bool:
    """
    Verify that required environment variables are set.

    Returns:
        True if all required secrets are present
    """
    required = [
        "DISCORD_BOT_TOKEN",
        "DATABASE_URL",
    ]

    missing = []
    for key in required:
        if not os.environ.get(key):
            missing.append(key)

    if missing:
        logger.error(f"❌ Missing required environment variables: {missing}")
        logger.error("   Check your AWS Secrets Manager secret or .env file")
        return False

    # Log what's configured (without values)
    optional = [
        "OPENAI_API_KEY",
        "SNAPTRADE_CLIENT_ID",
        "TWITTER_BEARER_TOKEN",
        "DATABENTO_API_KEY",
    ]

    logger.info("Environment configuration:")
    for key in required + optional:
        status = "✅" if os.environ.get(key) else "❌"
        logger.info(f"   {status} {key}")

    return True


def main():
    """Main entry point - load secrets and start the bot."""
    logger.info("=" * 60)
    logger.info("LLM Portfolio Journal - Discord Bot Startup")
    logger.info("=" * 60)

    # Step 1: Load secrets
    load_secrets()

    # Step 2: Verify required secrets
    if not verify_required_secrets():
        sys.exit(1)

    # Step 3: Import and run the bot
    logger.info("Starting Discord bot...")
    try:
        from src.bot.bot import main as bot_main

        bot_main()
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Bot crashed: {e}")
        raise


if __name__ == "__main__":
    main()
