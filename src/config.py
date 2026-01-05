"""Centralised settings object – importable from anywhere."""

import logging
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

# Track first-time database URL logging
_db_url_logged = False
logger = logging.getLogger(__name__)

# Auto-load .env from repo root
load_dotenv(Path(__file__).resolve().parents[1] / ".env")


class _Settings(BaseSettings):
    # === Required Database Configuration ===========================
    DATABASE_URL: str = ""  # Transaction Pooler connection string
    DATABASE_DIRECT_URL: str = ""  # Direct connection string (non-pooling)

    # === Supabase Configuration ====================================
    SUPABASE_URL: str = ""  # Project REST API URL
    SUPABASE_SERVICE_ROLE_KEY: str = ""  # Secret key (sb_secret_…)
    SUPABASE_ANON_KEY: str = ""  # Publishable key (sb_publishable_…)

    # === JWT Configuration =========================================
    JWT_PUBLIC_KEY: str = ""  # Public key from ECC (P-256) entry
    JWT_SECRET: str = ""  # JWT secret for token signing
    JWT_PRIVATE_KEY: str = ""  # Private key for server-side token signing

    # === SnapTrade API ================================================
    SNAPTRADE_CLIENT_ID: str = ""
    SNAPTRADE_CONSUMER_KEY: str = ""
    SNAPTRADE_USER_ID: str = ""
    SNAPTRADE_USER_SECRET: str = ""
    ROBINHOOD_ACCOUNT_ID: str = ""

    # === LLM API Keys ================================================
    GEMINI_API_KEY: str = ""
    OPENAI_API_KEY: str = ""

    # === Discord Configuration ======================================
    DISCORD_BOT_TOKEN: str = ""
    DISCORD_CLIENT_ID: str = ""
    DISCORD_CLIENT_SECRET: str = ""

    # === Twitter API Configuration ==================================
    TWITTER_BEARER_TOKEN: str = ""
    TWITTER_API_KEY: str = ""
    TWITTER_API_SECRET_KEY: str = ""
    TWITTER_ACCESS_TOKEN: str = ""
    TWITTER_ACCESS_TOKEN_SECRET: str = ""

    # === System Configuration =======================================
    LOG_CHANNEL_IDS: str = ""  # Comma-separated channel IDs for Discord bot
    SPORTS_CHANNEL_IDS: str = ""  # Comma-separated channel IDs for Sports Arb bot

    model_config = SettingsConfigDict(
        env_file=".env", case_sensitive=False, extra="ignore"
    )

    @property
    def log_channel_ids_list(self) -> list[str]:
        """Parse comma-separated LOG_CHANNEL_IDS into a list."""
        if not self.LOG_CHANNEL_IDS:
            return []
        return [cid.strip() for cid in self.LOG_CHANNEL_IDS.split(",") if cid.strip()]

    @property
    def sports_channel_ids_list(self) -> list[str]:
        """Parse comma-separated SPORTS_CHANNEL_IDS into a list."""
        if not self.SPORTS_CHANNEL_IDS:
            return []
        return [
            cid.strip() for cid in self.SPORTS_CHANNEL_IDS.split(",") if cid.strip()
        ]

    def get(self, key: str, default=None):
        """Get configuration value by key with optional default."""
        return getattr(self, key, default)

    def get_primary_llm_key(self) -> str:
        """Get primary LLM API key, prioritizing Gemini over OpenAI."""
        # Check for Gemini API key first (free tier)
        gemini_key = getattr(self, "GEMINI_API_KEY", "") or getattr(
            self, "gemini_api_key", ""
        )
        if gemini_key:
            return gemini_key

        # Fallback to OpenAI
        openai_key = getattr(self, "OPENAI_API_KEY", "") or getattr(
            self, "openai_api_key", ""
        )
        if openai_key:
            return openai_key

        return ""


@lru_cache
def settings() -> _Settings:
    s = _Settings()

    # Apply field mapping from environment variables for backward compatibility
    import os

    # Legacy Supabase ID mapping
    supabase_id = os.getenv("Supabase_ID")
    if not s.SUPABASE_URL and supabase_id:
        s.SUPABASE_URL = f"https://{supabase_id}.supabase.co"

    # Legacy anon_public key mapping to new SUPABASE_ANON_KEY
    anon_public = os.getenv("anon_public")
    if not s.SUPABASE_ANON_KEY and anon_public:
        s.SUPABASE_ANON_KEY = anon_public

    # Legacy service_role key mapping to new SUPABASE_SERVICE_ROLE_KEY
    service_role = os.getenv("service_role")
    if not s.SUPABASE_SERVICE_ROLE_KEY and service_role:
        s.SUPABASE_SERVICE_ROLE_KEY = service_role

    # JWT Secret key mapping (handle both new and legacy names)
    jwt_secret_key = os.getenv("JWT_Secret_Key")
    if not s.JWT_SECRET and jwt_secret_key:
        s.JWT_SECRET = jwt_secret_key

    # Database Direct URL support
    database_direct_url = os.getenv("DATABASE_DIRECT_URL")
    if not s.DATABASE_DIRECT_URL and database_direct_url:
        s.DATABASE_DIRECT_URL = database_direct_url

    # JWT Public Key support
    jwt_public_key = os.getenv("JWT_PUBLIC_KEY")
    if not s.JWT_PUBLIC_KEY and jwt_public_key:
        s.JWT_PUBLIC_KEY = jwt_public_key

    return s


def get_database_url(use_direct: bool = False) -> str:
    """
    Get database URL for PostgreSQL connection.
    Requires explicit DATABASE_URL configuration - no building from other variables.

    Args:
        use_direct: If True, prefer DATABASE_DIRECT_URL over DATABASE_URL

    Returns:
        Database connection string (PostgreSQL only)

    Raises:
        RuntimeError: If DATABASE_URL is not explicitly configured
    """
    global _db_url_logged
    config = settings()

    # Prefer DATABASE_DIRECT_URL if specifically requested and available
    if use_direct and config.DATABASE_DIRECT_URL:
        source_used = "DATABASE_DIRECT_URL"
        url_to_return = config.DATABASE_DIRECT_URL
    # Check if Transaction Pooler URL (primary) is configured
    elif config.DATABASE_URL:
        source_used = "DATABASE_URL"
        url_to_return = config.DATABASE_URL
    # Fallback to Direct URL if Transaction Pooler not available
    elif config.DATABASE_DIRECT_URL:
        source_used = "DATABASE_DIRECT_URL (fallback)"
        url_to_return = config.DATABASE_DIRECT_URL
    else:
        raise RuntimeError("DATABASE_URL required")

    # One-time masked logging of source used
    if not _db_url_logged:
        masked_url = (
            url_to_return[:25] + "***" + url_to_return[-10:]
            if len(url_to_return) > 35
            else "***"
        )
        logger.info("Database source: %s (%s)", source_used, masked_url)
        _db_url_logged = True

    return url_to_return


def get_migration_database_url() -> str:
    """
    Get database URL optimized for migration operations.
    Prefers direct connection for better performance during bulk operations.
    """
    return get_database_url(use_direct=True)
