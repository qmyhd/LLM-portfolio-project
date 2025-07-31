"""Centralised settings object – importable from anywhere."""
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

# Auto-load .env from repo root
load_dotenv(Path(__file__).resolve().parents[1] / ".env")

class _Settings(BaseSettings):
    # === Required (with fallbacks for compatibility) ================
    DATABASE_URL: str = ""
    SUPABASE_SERVICE_ROLE_KEY: str = ""
    
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
    
    # === Derived/Optional ============================================
    SUPABASE_URL: str = ""
    SUPABASE_ANON_KEY: str = ""  
    JWT_SECRET: str = ""
    ALLOW_SQLITE_FALLBACK: bool = True
    LOG_CHANNEL_IDS: str = ""  # Comma-separated channel IDs for Discord bot
    SQLITE_PATH: str = "data/database/price_history.db"  # SQLite database path for migration and fallback
    
    # === User's actual .env field names ============================
    anon_public: str = ""
    JWT_Secret_Key: str = ""
    Supabase_ID: str = ""

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False, extra="ignore")
    
    @property
    def log_channel_ids_list(self) -> list[str]:
        """Parse comma-separated LOG_CHANNEL_IDS into a list."""
        if not self.LOG_CHANNEL_IDS:
            return []
        return [cid.strip() for cid in self.LOG_CHANNEL_IDS.split(",") if cid.strip()]
    
    def get(self, key: str, default=None):
        """Get configuration value by key with optional default."""
        return getattr(self, key, default)
    
    def get_primary_llm_key(self) -> str:
        """Get primary LLM API key, prioritizing Gemini over OpenAI."""
        # Check for Gemini API key first (free tier)
        gemini_key = getattr(self, 'GEMINI_API_KEY', '') or getattr(self, 'gemini_api_key', '')
        if gemini_key:
            return gemini_key
            
        # Fallback to OpenAI
        openai_key = getattr(self, 'OPENAI_API_KEY', '') or getattr(self, 'openai_api_key', '')
        if openai_key:
            return openai_key
            
        return ""

@lru_cache
def settings() -> _Settings:
    s = _Settings()
    
    # Apply field mapping after creation
    if not s.SUPABASE_URL and s.Supabase_ID:
        s.SUPABASE_URL = f"https://{s.Supabase_ID}.supabase.co"
    
    if not s.SUPABASE_ANON_KEY and s.anon_public:
        s.SUPABASE_ANON_KEY = s.anon_public
        
    if not s.JWT_SECRET and s.JWT_Secret_Key:
        s.JWT_SECRET = s.JWT_Secret_Key
        
    return s


def get_database_url() -> str:
    """
    Get database URL with automatic fallback to SQLite if PostgreSQL not configured.
    Supports Supabase pooler detection for prepared statement auto-disable.
    """
    config = settings()
    
    # Check if PostgreSQL/Supabase is configured
    if config.DATABASE_URL:
        return config.DATABASE_URL
    
    # Build Supabase URL if components are available
    if config.SUPABASE_URL and config.SUPABASE_SERVICE_ROLE_KEY:
        # Check for Supabase pooler (port 6543) and disable prepared statements
        if ":6543" in config.SUPABASE_URL:
            # Pooler detected - disable prepared statements for compatibility
            pooler_url = config.SUPABASE_URL.replace("https://", "").replace("http://", "")
            return f"postgresql://postgres:{config.SUPABASE_SERVICE_ROLE_KEY}@{pooler_url}/postgres?prepared_statement_cache_size=0"
        else:
            # Direct connection - use port 5432 with prepared statements enabled
            direct_url = config.SUPABASE_URL.replace("https://", "").replace("http://", "")
            return f"postgresql://postgres:{config.SUPABASE_SERVICE_ROLE_KEY}@{direct_url}:5432/postgres"
    
    # Fallback to SQLite if enabled
    if config.ALLOW_SQLITE_FALLBACK:
        from pathlib import Path
        db_path = Path(__file__).resolve().parents[1] / "data" / "database" / "price_history.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        return f"sqlite:///{db_path}"
    
    raise ValueError("No database configuration found. Set DATABASE_URL or configure Supabase settings.")
