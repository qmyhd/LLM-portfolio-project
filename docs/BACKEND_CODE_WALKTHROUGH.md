# Backend Engineer Code Walkthrough

> **Purpose:** A structured walkthrough of the `src/` directory for backend engineers  
> **Focus:** Function signatures, parameters, data flow, and architecture patterns  
> **Audience:** Technical interviews, code reviews, onboarding  
> **Last Updated:** January 2026

---

## Table of Contents

1. [Walkthrough Overview](#1-walkthrough-overview)
2. [Layer 1: Infrastructure & Configuration](#2-layer-1-infrastructure--configuration)
   - [Layer 1b: AWS Secrets Manager](#25-layer-1b-aws-secrets-manager-integration)
3. [Layer 2: Database Operations](#3-layer-2-database-operations)
4. [Layer 3: Data Collection (ETL)](#4-layer-3-data-collection-etl)
5. [Layer 4: NLP Processing Pipeline](#5-layer-4-nlp-processing-pipeline)
6. [Layer 5: Bot Interface](#6-layer-5-bot-interface)
7. [Recommended Walkthrough Script](#7-recommended-walkthrough-script)
8. [Deployment Infrastructure](#8-deployment-infrastructure)
9. [Architecture Summary](#9-architecture-summary)

---

## 1. Walkthrough Overview

### Directory Structure
```
src/
├── config.py              # Configuration management (Pydantic)
├── db.py                  # Database layer (SQLAlchemy 2.0)
├── retry_utils.py         # Resilience patterns
├── price_service.py       # OHLCV data access (RDS)
├── snaptrade_collector.py # Brokerage data ETL
├── databento_collector.py # OHLCV data ETL (Databento)
├── message_cleaner.py     # Text processing
├── twitter_analysis.py    # Social data ETL
├── nlp/                   # NLP pipeline
│   ├── openai_parser.py   # LLM integration
│   ├── schemas.py         # Pydantic models
│   ├── preclean.py        # Text preprocessing
│   └── soft_splitter.py   # Message chunking
└── bot/                   # Discord interface
    ├── commands/          # Bot commands
    └── ui/                # UI components
```

### Key Talking Points

| Layer | Focus | Why It's Interesting |
|-------|-------|---------------------|
| Infrastructure | Config, Retry, DB | Pydantic settings, connection pooling, advisory locks |
| Data Collection | ETL patterns | Multi-API orchestration, rate limiting, resilience |
| NLP Pipeline | LLM Integration | Structured outputs, model routing, cost optimization |
| Bot Interface | Real-time events | Async patterns, message streaming, interactive UI |

---

## 2.5 Layer 1b: AWS Secrets Manager Integration

### 📄 `src/aws_secrets.py` - Production Secrets

**Purpose:** Load secrets from AWS Secrets Manager for EC2 deployment

```python
# Secret key mapping with flexible RDS key names
SECRET_KEY_MAPPING = {
    "DATABASE_URL": "DATABASE_URL",
    "SUPABASE_SERVICE_ROLE_KEY": "SUPABASE_SERVICE_ROLE_KEY",
    "OPENAI_API_KEY": "OPENAI_API_KEY",
    "DISCORD_BOT_TOKEN": "DISCORD_BOT_TOKEN",
    # ... all API keys
}

# RDS secrets may use different key names (AWS RDS format)
RDS_SECRET_KEY_MAPPING = {
    "RDS_HOST": ["host", "RDS_HOST", "hostname"],
    "RDS_PORT": ["port", "RDS_PORT"],
    "RDS_DATABASE": ["dbname", "database", "RDS_DATABASE"],
    "RDS_USER": ["username", "RDS_USER", "user"],
    "RDS_PASSWORD": ["password", "RDS_PASSWORD"],
}
```

#### Core Functions

```python
def load_secrets_to_env(
    secret_name: Optional[str] = None,
    overwrite: bool = False,
) -> int:
    """
    Load secrets from AWS Secrets Manager into environment.
    
    Also loads RDS secrets from separate secret if configured.
    
    Environment Variables:
        USE_AWS_SECRETS: Set to "1" to enable
        AWS_SECRET_NAME: Main secret name (default: {prefix}/{env})
        AWS_RDS_SECRET_NAME: Separate RDS secret (e.g., "RDS/ohlcvdata")
    
    Returns:
        Total number of environment variables set
    """

def load_rds_secrets_to_env(
    rds_secret_name: Optional[str] = None,
    overwrite: bool = False,
) -> int:
    """
    Load RDS secrets from a separate AWS secret.
    
    Handles AWS RDS secret format (host, username, password keys)
    as well as custom formats (RDS_HOST, RDS_USER, etc.)
    
    Returns:
        Number of RDS environment variables set
    """

def build_rds_connection_url(
    host: Optional[str] = None,
    port: Optional[str] = None,
    database: Optional[str] = None,
    user: Optional[str] = None,
    password: Optional[str] = None,
) -> Optional[str]:
    """
    Build PostgreSQL URL from RDS components.
    
    Automatically URL-encodes password for special characters.
    Adds sslmode=require for secure connections.
    """
```

**Usage Pattern:**
```python
# At application startup
import os
os.environ["USE_AWS_SECRETS"] = "1"
os.environ["AWS_SECRET_NAME"] = "qqqAppsecrets"
os.environ["AWS_RDS_SECRET_NAME"] = "RDS/ohlcvdata"

from src.aws_secrets import load_secrets_to_env
count = load_secrets_to_env()  # Loads both main + RDS secrets
```

---

## 2. Layer 1: Infrastructure & Configuration

### 📄 `src/config.py` - Centralized Configuration

**Purpose:** Type-safe environment variable management using Pydantic

```python
# Core class: Pydantic BaseSettings
class _Settings(BaseSettings):
    # Database
    DATABASE_URL: str = ""          # Transaction pooler (port 6543)
    DATABASE_DIRECT_URL: str = ""   # Direct connection (port 5432)
    
    # Supabase
    SUPABASE_URL: str = ""
    SUPABASE_SERVICE_ROLE_KEY: str = ""
    
    # External APIs
    SNAPTRADE_CLIENT_ID: str = ""
    OPENAI_API_KEY: str = ""
    DISCORD_BOT_TOKEN: str = ""
    TWITTER_BEARER_TOKEN: str = ""
    
    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=False,
        extra="ignore"
    )
```

**Key Functions:**

```python
@lru_cache
def settings() -> _Settings:
    """Cached singleton - loads .env once"""
    s = _Settings()
    # Handle legacy field mappings for backward compatibility
    return s

def get_database_url(use_direct: bool = False) -> str:
    """
    Get database URL for PostgreSQL connection.
    
    Args:
        use_direct: If True, prefer direct connection (port 5432)
                   Default False uses pooler (port 6543)
    
    Returns:
        PostgreSQL connection string
    
    Raises:
        RuntimeError: If DATABASE_URL not configured
    """
```

**Why It's Interesting:**
- `@lru_cache` ensures single load
- Handles legacy environment variable names for migration
- Masked URL logging for security

---

### 📄 `src/retry_utils.py` - Resilience Patterns

**Purpose:** Prevent infinite loops on non-retryable errors

```python
# Non-retryable exceptions (immediate failure, no retry)
NON_RETRYABLE_EXCEPTIONS = (
    ValueError,                       # Data format errors
    TypeError,                        # Type mismatches
    KeyError,                         # Missing data
    sqlalchemy.exc.ArgumentError,     # SQL parameter mismatch
    pandas.errors.ParserError,        # CSV parsing failures
)

def hardened_retry(
    max_retries: int = 3,
    delay: float = 1.0,
    backoff_factor: float = 2.0
):
    """
    Retry decorator that prevents infinite loops.
    
    Args:
        max_retries: Maximum retry attempts
        delay: Initial delay between retries (seconds)
        backoff_factor: Multiplier for exponential backoff
    
    Behavior:
        - Immediately raises NON_RETRYABLE_EXCEPTIONS
        - Retries other exceptions with exponential backoff
        - Logs each retry attempt with exception details
    """

def database_retry(max_retries: int = 3, delay: float = 1.0):
    """
    Specialized retry for database operations.
    
    Additional non-retryable exceptions:
        - DisconnectionError (but after connection reset)
        - IntegrityError (constraint violations)
    """
```

**Usage Pattern:**
```python
@hardened_retry(max_retries=3, delay=1)
def call_external_api():
    # If this throws ValueError → immediate failure
    # If this throws HTTPError → retry with backoff
    pass
```

---

## 3. Layer 2: Database Operations

### 📄 `src/db.py` - SQLAlchemy 2.0 Engine

**Purpose:** Resilient async-friendly database layer with connection pooling

#### Engine Creation

```python
def get_sync_engine():
    """
    Create synchronous SQLAlchemy engine with:
    - Connection pooling (size=5, overflow=2)
    - Pool pre-ping (connection validation)
    - Pool recycling (1 hour)
    - Automatic Supabase pooler detection (port 6543)
    
    Connection Options:
        - statement_timeout = 30s
        - lock_timeout = 10s
        - application_name = 'trading-bot-pooler'
    
    Returns:
        SQLAlchemy Engine singleton
    """

async def get_async_engine() -> AsyncEngine:
    """
    Create async engine for async operations.
    Uses asyncpg driver instead of psycopg2.
    """
```

#### Core Query Function

```python
def execute_sql(
    query: str,
    params: Optional[Union[Dict[str, Any], List[Dict[str, Any]]]] = None,
    fetch_results: bool = False,
) -> Union[List[Row[Any]], CursorResult[Any]]:
    """
    Execute SQL query with enhanced type safety.
    
    Args:
        query: SQL with named placeholders (:param_name)
        params: Dict or list of dicts for parameters
        fetch_results: If True, return query results
    
    Returns:
        List[Row] if fetch_results=True
        CursorResult otherwise
    
    Raises:
        TypeError: If params aren't dict/list of dicts
        ValueError: If naive datetime passed for timestamptz fields
    
    Examples:
        # Read query
        rows = execute_sql(
            "SELECT * FROM positions WHERE symbol = :symbol",
            params={"symbol": "AAPL"},
            fetch_results=True
        )
        
        # Write query
        execute_sql(
            "UPDATE positions SET price = :price WHERE symbol = :symbol",
            params={"price": 150.0, "symbol": "AAPL"}
        )
        
        # Bulk insert
        execute_sql(
            "INSERT INTO positions (symbol, price) VALUES (:symbol, :price)",
            params=[{"symbol": "AAPL", "price": 150}, {"symbol": "MSFT", "price": 380}]
        )
    """
```

#### Transaction & Advisory Locks

```python
class transaction:
    """
    Context manager for atomic multi-statement transactions.
    
    Use for:
        - Advisory locks (pg_advisory_xact_lock)
        - DELETE + INSERT patterns
        - Any operation requiring atomicity
    
    Example:
        with transaction() as conn:
            # Acquire lock (held until transaction ends)
            conn.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": 123})
            
            # Atomic operations
            conn.execute(text("DELETE FROM table WHERE id = :id"), {"id": 456})
            conn.execute(text("INSERT INTO table ..."), {...})
        
        # Lock released, transaction committed
    """
    
    def __enter__(self):
        self._engine = get_sync_engine()
        self._conn = self._engine.begin()
        return self._conn.__enter__()
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        return self._conn.__exit__(exc_type, exc_val, exc_tb)
```

#### Atomic Write Helper

```python
def save_parsed_ideas_atomic(
    message_id: str,
    ideas: list,
    status: str,
    prompt_version: str,
    error_reason: str = None,
) -> int:
    """
    CANONICAL atomic helper for saving NLP parsed ideas.
    
    This function handles the critical race condition where multiple
    workers might process the same message simultaneously.
    
    Transaction Flow:
        1. Acquire advisory lock on message_id
        2. DELETE all existing ideas for this message
        3. INSERT fresh ideas
        4. UPDATE parse_status on discord_messages
        5. COMMIT all operations atomically
    
    Args:
        message_id: Discord message ID being processed
        ideas: List of idea dicts (message_id, idea_text, symbols, etc.)
        status: Parse status (ok, error, noise, skipped)
        prompt_version: Version string for schema tracking
        error_reason: Error message if status='error'
    
    Returns:
        Number of ideas inserted
    
    Why This Exists:
        Without atomic writes, separate transactions could:
        - Delete ideas, then crash before insert → data loss
        - Two workers process same message → duplicate ideas
        - Update status before ideas written → inconsistent state
    """
```

---

## 4. Layer 3: Data Collection (ETL)

### 📄 `src/snaptrade_collector.py` - Brokerage ETL

**Purpose:** Extract brokerage data from SnapTrade API with resilient field extraction

```python
class SnapTradeCollector:
    """SnapTrade data collection and ETL operations."""
    
    def __init__(self):
        """
        Initialize with credentials from environment.
        
        Required env vars:
            SNAPTRADE_CLIENT_ID
            SNAPTRADE_CONSUMER_KEY
            SNAPTRADE_USER_ID
            SNAPTRADE_USER_SECRET
        """
```

#### Safe Response Handling

```python
def safely_extract_response_data(
    self,
    response,
    operation_name: str = "API call",
    max_sample_items: int = 3
) -> Tuple[Any, bool]:
    """
    Safely extract data from SnapTrade API response.
    
    The SnapTrade SDK wraps responses in objects with various
    attribute names depending on the endpoint.
    
    Args:
        response: SnapTrade API response object
        operation_name: For logging context
        max_sample_items: Number of sample items to log
    
    Returns:
        Tuple of (data, is_list):
            - data: The extracted content (list or dict)
            - is_list: Whether data is a list
    
    Attribute Priority:
        1. response.parsed
        2. response.body
        3. response.data
        4. response.content
    """
```

#### Symbol Extraction (Complex Nested Payloads)

```python
def extract_symbol_from_data(self, symbol_data) -> Optional[str]:
    """
    Extract clean ticker from SnapTrade symbol payload.
    
    SnapTrade returns symbols in various nested formats:
        - {"symbol": {"raw_symbol": "AAPL"}}
        - {"universal_symbol": {"symbol": "AAPL"}}
        - {"id": "AAPL"}  # Short IDs that look like tickers
    
    Args:
        symbol_data: String or nested dict containing symbol
    
    Returns:
        Clean ticker string or None
    
    Key Priority:
        1. raw_symbol
        2. symbol
        3. ticker
        4. universal_symbol_symbol
        5. id (only if short, non-UUID)
    """
```

#### Data Collection Methods

```python
def get_accounts(self) -> pd.DataFrame:
    """
    Get user accounts with enhanced field extraction.
    
    Returns DataFrame with columns:
        id, name, institution_name, total_equity, 
        last_successful_sync, sync_timestamp
    """

def get_balances(self, account_id: Optional[str] = None) -> pd.DataFrame:
    """
    Get account balances per currency.
    
    Args:
        account_id: Account to fetch (defaults to ROBINHOOD_ACCOUNT_ID)
    
    Returns DataFrame with columns:
        account_id, currency_code, cash, buying_power, snapshot_date
    """

def get_positions(self, account_id: Optional[str] = None) -> pd.DataFrame:
    """
    Get current portfolio positions.
    
    Returns DataFrame with columns:
        symbol, quantity, price, equity, average_buy_price,
        open_pnl, open_pnl_percent, account_id
    """

def get_orders(
    self,
    account_id: Optional[str] = None,
    state: str = "all",
    days: int = 365
) -> pd.DataFrame:
    """
    Get trade orders with comprehensive field extraction.
    
    Args:
        account_id: Account filter
        state: "all", "executed", "pending", "cancelled"
        days: How far back to look
    
    Returns DataFrame with columns:
        brokerage_order_id, symbol, action, status,
        total_quantity, execution_price, filled_at
    """
```

---

### 📄 `src/databento_collector.py` - OHLCV ETL

**Purpose:** Fetch historical price data from Databento with multi-storage targets

```python
class DatabentoCollector:
    """Collect OHLCV daily bars from Databento Historical API."""
    
    def __init__(
        self,
        api_key: str | None = None,
        rds_url: str | None = None,
        s3_bucket: str | None = None,
        supabase_url: str | None = None,
    ):
        """
        Initialize with storage targets.
        
        Args:
            api_key: Databento API key (or DATABENTO_API_KEY env)
            rds_url: PostgreSQL RDS connection URL
            s3_bucket: S3 bucket name (default: qqq-llm-raw-history)
            supabase_url: Optional Supabase sync URL
        """
```

#### Dataset Switching

```python
# Dataset cutoff: EQUS.MINI ends 2024-06-30, EQUS.SUMMARY starts 2024-07-01
DATASET_CUTOFF = date(2024, 7, 1)
DATASET_HISTORICAL = "EQUS.MINI"
DATASET_CURRENT = "EQUS.SUMMARY"

def _select_dataset(self, target_date: date) -> str:
    """
    Select appropriate dataset based on date.
    
    Databento changed their data product naming:
        - Before July 2024: EQUS.MINI
        - After July 2024: EQUS.SUMMARY
    """
    return DATASET_HISTORICAL if target_date < DATASET_CUTOFF else DATASET_CURRENT
```

#### Storage Targets

```python
@hardened_retry(max_retries=3, delay=2)
def save_to_rds(self, df: pd.DataFrame) -> int:
    """
    Save OHLCV data to AWS RDS PostgreSQL.
    
    Uses UPSERT (ON CONFLICT DO UPDATE) for idempotency.
    
    Returns:
        Number of rows inserted/updated
    """

def save_to_s3(self, df: pd.DataFrame, date_str: str) -> str:
    """
    Archive OHLCV data to S3 as Parquet.
    
    Key format: ohlcv/daily/YYYY-MM-DD.parquet
    
    Returns:
        S3 key path
    """

def sync_to_supabase(self, df: pd.DataFrame) -> int:
    """
    Optional sync to Supabase for real-time access.
    
    Returns:
        Number of rows synced
    """
```

---

### 📄 `src/message_cleaner.py` - Text Processing

**Purpose:** Extract tickers and sentiment from Discord messages

```python
# Channel type to database table mapping
CHANNEL_TYPE_TO_TABLE = {
    "general": "discord_trading_clean",
    "trading": "discord_trading_clean",
    "market": "discord_market_clean",
}

def extract_ticker_symbols(text: str | None) -> List[str]:
    """
    Extract $TICKER format symbols from text.
    
    Pattern: r"\\$[A-Z]{1,6}(?:\\.[A-Z]+)?"
    
    Handles:
        - Standard: $AAPL, $MSFT
        - Class shares: $BRK.B, $BRK.A
        - 1-6 character limit
    
    Args:
        text: Text to extract from
    
    Returns:
        List of unique tickers in order of appearance
    
    Examples:
        >>> extract_ticker_symbols("I bought $AAPL and $MSFT!")
        ['$AAPL', '$MSFT']
        >>> extract_ticker_symbols("Check $BRK.B today")
        ['$BRK.B']
    """
```

---

## 5. Layer 4: NLP Processing Pipeline

### 📄 `src/nlp/schemas.py` - Pydantic Models

**Purpose:** Type-safe schemas for LLM structured outputs

```python
class ParseStatus(str, Enum):
    """
    Message parsing lifecycle states.
    
    Transitions:
        pending → ok       : Ideas extracted successfully
        pending → noise    : LLM detected noise (no content)
        pending → error    : Parsing failed (API/validation error)
        pending → skipped  : Pre-filtered (bot command, too short)
    """
    PENDING = "pending"
    OK = "ok"
    NOISE = "noise"
    ERROR = "error"
    SKIPPED = "skipped"

class TradingLabel(str, Enum):
    """
    13-category taxonomy for trading messages.
    
    Categories:
        TRADE_EXECUTION      - Did/doing a trade
        TRADE_PLAN           - Will do / setup / entry plan
        TECHNICAL_ANALYSIS   - Levels, patterns, trend
        FUNDAMENTAL_THESIS   - Business/value thesis
        CATALYST_NEWS        - News, macro event
        EARNINGS             - Earnings-specific
        INSTITUTIONAL_FLOW   - 13F filings, fund moves
        OPTIONS              - Calls/puts/strikes
        RISK_MANAGEMENT      - Stops, sizing, hedges
        SENTIMENT_CONVICTION - High confidence statements
        PORTFOLIO_UPDATE     - Positions, P/L
        QUESTION_REQUEST     - Asking for info
        RESOURCE_LINK        - Chart links, data
    """

class ParsedIdea(BaseModel):
    """
    A single semantic idea unit from a trading message.
    
    Fields:
        idea_text: str          # Exact quote (max 500 chars)
        idea_summary: str       # 1-2 sentence summary
        primary_symbol: str     # Main ticker focus
        symbols: List[str]      # All tickers mentioned
        instrument: InstrumentType
        direction: Direction    # bullish/bearish/neutral/mixed
        action: Action          # buy/sell/trim/add/watch/hold
        time_horizon: TimeHorizon
        levels: List[Level]     # Price levels (entry/target/stop)
        labels: List[TradingLabel]
        confidence: float       # 0.0-1.0
    """
```

---

### 📄 `src/nlp/openai_parser.py` - LLM Integration

**Purpose:** Semantic parsing with OpenAI structured outputs

#### Model Routing Strategy

```python
# Model configuration (env-configurable)
MODEL_TRIAGE = "gpt-5-mini-2025-08-07"     # Quick classification
MODEL_MAIN = "gpt-5.1-2025-11-13"          # Primary parsing
MODEL_ESCALATION = "gpt-5.1-2025-11-13"    # Complex cases
MODEL_LONG_CONTEXT = "gpt-5.1-2025-11-13"  # >2000 chars

# Thresholds
LONG_CONTEXT_THRESHOLD = 2000      # chars
ESCALATION_THRESHOLD = 0.8         # confidence
SYMBOL_DENSITY_THRESHOLD = 10      # ticker count
```

#### Call Tracking (Prevent Explosion)

```python
@dataclass
class CallStats:
    """Track API calls per message for monitoring."""
    
    soft_chunks: int = 0
    triage_calls: int = 0
    main_calls: int = 0
    escalation_calls: int = 0
    noise_chunks: int = 0
    
    @property
    def total_calls(self) -> int:
        return self.triage_calls + self.main_calls + self.escalation_calls
    
    def summary(self) -> str:
        return (
            f"chunks={self.soft_chunks} calls={self.total_calls} "
            f"triage={self.triage_calls} main={self.main_calls}"
        )
```

#### Core Parsing Functions

```python
def _extract_parsed_result(response: Response, result_type: type[T]) -> Optional[T]:
    """
    Safely extract parsed result from OpenAI Response.
    
    Handles the union type complexity of response.output:
        - Reasoning models return: [ResponseReasoningItem, ParsedResponseOutputMessage]
        - Need to iterate through all items to find parsed content
    
    Args:
        response: OpenAI Response object
        result_type: Expected type (ParsedIdea, MessageParseResult, etc.)
    
    Returns:
        Parsed result or None (with diagnostics logged)
    """

def process_message(
    content: str,
    message_id: Optional[str] = None,
    channel_id: Optional[str] = None,
    author_id: Optional[str] = None,
    source_created_at: Optional[datetime] = None,
    context_messages: Optional[List[str]] = None,
    skip_triage: bool = False,
) -> Optional[MessageParseResult]:
    """
    Full parsing pipeline for a Discord message.
    
    Pipeline:
        1. Pre-filter (bot commands, too short, etc.)
        2. Triage (quick noise detection)
        3. Soft-split (chunk long messages)
        4. Parse each chunk
        5. Escalate if low confidence
        6. Aggregate ideas
    
    Args:
        content: Message text to parse
        message_id: For tracking/logging
        channel_id: For metadata
        author_id: For metadata
        source_created_at: Original message timestamp
        context_messages: Recent messages for context
        skip_triage: Skip triage step (for pre-validated content)
    
    Returns:
        MessageParseResult with ideas, or None if filtered/noise
    
    Call Budget:
        - Short (<1500 chars): 2 calls (triage + parse)
        - Medium (1500-2000 chars): 2-4 calls
        - Long (>2000 chars): 1 call (long-context model)
    """
```

#### Instrument Detection Helpers

```python
def detect_instrument_type(text: str, primary_symbol: Optional[str] = None) -> str:
    """
    Detect if text refers to option, crypto, or equity.
    
    Detection patterns:
        Options: "180c", "95p", "calls", "puts", "strike", "expiry"
        Crypto: BTC, ETH, "bitcoin", "ethereum"
        Default: equity
    
    Examples:
        >>> detect_instrument_type("AAPL 180c looking good")
        'option'
        >>> detect_instrument_type("Bitcoin hit ATH")
        'crypto'
    """

def extract_strike_info(text: str) -> Dict[str, Any]:
    """
    Extract strike price, option type, and premium.
    
    Handles multiple formats:
        - "180c", "95p" → strike + type
        - "$180 call", "$95 put" → strike + type
        - "for $1.76", "@ $1.35" → premium
    
    Examples:
        >>> extract_strike_info("AAPL 180c")
        {'strike': 180, 'option_type': 'call'}
        >>> extract_strike_info("$95 put for $1.76")
        {'strike': 95.0, 'option_type': 'put', 'premium': 1.76}
    """

def extract_price_levels(text: str) -> List[Dict[str, Any]]:
    """
    Extract support/resistance/target levels from text.
    
    Uses context keywords to classify:
        Support: "support", "hold", "floor", "bounce", "bottom"
        Resistance: "resistance", "target", "ceiling", "breakout"
    
    Examples:
        >>> extract_price_levels("bounced off $147, needs to hold 150")
        [{'kind': 'support', 'value': 147.0}, {'kind': 'support', 'value': 150.0}]
    """
```

---

### 📄 `src/nlp/preclean.py` - Text Preprocessing

**Purpose:** Ticker accuracy improvement with reserved words and aliases

```python
# Company name → ticker mappings (~100 entries)
ALIAS_MAP = {
    "google": "GOOGL",
    "tesla": "TSLA",
    "nvidia": "NVDA",
    "target corp": "TGT",
    "bitcoin": "BTC",
    "microsoft": "MSFT",
    # ... ~100 more
}

# Trading terms that should NOT become tickers (80+ entries)
RESERVED_SIGNAL_WORDS = {
    "tgt", "pt", "tp", "sl", "be",      # Abbreviations
    "target", "support", "resistance",   # Levels
    "buy", "sell", "trim", "add",        # Actions
    "calls", "puts", "strike", "expiry", # Options
    "gap", "breakout", "reversal",       # Patterns
    # ... 80+ more
}

def extract_candidate_tickers(text: str) -> set[str]:
    """
    Pre-LLM deterministic ticker extraction.
    
    This runs BEFORE the LLM to:
        1. Provide candidate_tickers hint to LLM
        2. Enable post-validation of LLM output
    
    Filters:
        - Reserved signal words (won't extract TGT from "target price")
        - Bot commands
        - URLs
    
    Returns:
        Set of valid ticker candidates
    """

def validate_llm_tickers(
    llm_tickers: List[str],
    candidate_tickers: set[str],
    strict: bool = False
) -> List[str]:
    """
    Post-validate LLM ticker extraction.
    
    Args:
        llm_tickers: Tickers returned by LLM
        candidate_tickers: Pre-extracted candidates
        strict: If True, only allow candidates
    
    Returns:
        Validated ticker list (removes false positives)
    """

def is_reserved_signal_word(word: str) -> bool:
    """Check if word is trading terminology (not a ticker)."""

def is_bot_command(text: str) -> bool:
    """Detect bot commands (!help, !!chart, /roll, etc.)."""
```

---

## 6. Layer 5: Bot Interface

### 📄 `src/bot/bot.py` - Entry Point

```python
# Entry point (40 lines)
def main():
    """
    Discord bot entry point.
    
    1. Load environment via dotenv
    2. Create Twitter client (optional)
    3. Create bot via create_bot()
    4. Run bot with token
    """
    
# Bot factory
def create_bot(command_prefix: str = "!", twitter_client=None):
    """
    Create configured Discord bot.
    
    Args:
        command_prefix: Command prefix (default "!")
        twitter_client: Optional tweepy client for Twitter integration
    
    Registers:
        - All commands from commands/ directory
        - Event handlers from events.py
        - Custom help command
    """
```

### 📄 `src/bot/commands/snaptrade_cmd.py` - Portfolio Commands

```python
def register(bot: commands.Bot, twitter_client=None):
    """Register SnapTrade-related commands."""
    
    @bot.command(name="fetch")
    async def fetch_command(ctx, data_type: str = "all"):
        """
        Sync brokerage data from SnapTrade.
        
        Usage: !fetch [all|positions|orders|balances]
        
        Calls: SnapTradeCollector methods
        Updates: accounts, positions, orders, account_balances tables
        """
    
    @bot.command(name="portfolio")
    async def portfolio_command(ctx, filter_type: str = "all", limit: int = 10):
        """
        Display portfolio with interactive filtering.
        
        Usage: !portfolio [all|winners|losers] [limit]
        
        Features:
            - Paginated view
            - Filter toggles (All/Winners/Losers)
            - P/L display ($/%)
            - Refresh button
        """
    
    @bot.command(name="orders")
    async def orders_command(ctx, limit: int = 10):
        """
        Show recent orders.
        
        Usage: !orders [limit]
        """
    
    @bot.command(name="movers")
    async def movers_command(ctx):
        """
        Show top gainers and losers today.
        
        Usage: !movers
        """
```

---

## 7. Recommended Walkthrough Script

### For a 30-Minute Code Review

```
1. START: Infrastructure (5 min)
   └─ config.py: "Here's how we manage environment variables with Pydantic"
   └─ retry_utils.py: "This prevents infinite loops on non-retryable errors"

2. DATABASE: Core Operations (8 min)
   └─ db.py: get_sync_engine() - "Connection pooling with pre-ping validation"
   └─ db.py: execute_sql() - "Type-safe queries with timezone validation"
   └─ db.py: transaction + save_parsed_ideas_atomic() - "Advisory locks for race conditions"

3. ETL: Data Collection (7 min)
   └─ snaptrade_collector.py: safely_extract_response_data() - "Resilient API parsing"
   └─ snaptrade_collector.py: extract_symbol_from_data() - "Complex nested payloads"
   └─ databento_collector.py: Dataset switching - "Multi-storage targets"

4. NLP: LLM Integration (8 min)
   └─ schemas.py: ParsedIdea, TradingLabel - "Structured output schemas"
   └─ openai_parser.py: Model routing - "Cost optimization with routing"
   └─ preclean.py: RESERVED_SIGNAL_WORDS - "Ticker accuracy system"

5. WRAP-UP: Architecture (2 min)
   └─ "The pipeline flows: Data Collection → NLP Processing → Database → Bot"
```

### Key Points to Emphasize

| Topic | Talking Point |
|-------|--------------|
| **Type Safety** | "Pydantic everywhere - config, schemas, validation" |
| **Resilience** | "Hardened retry prevents infinite loops on SQL errors" |
| **Concurrency** | "Advisory locks solve the reparse race condition" |
| **Cost Control** | "Model routing keeps LLM costs predictable" |
| **Ticker Accuracy** | "80+ reserved words prevent false positives like TGT" |

### Common Interview Questions

1. **"How do you handle API failures?"**
   → `hardened_retry()` with non-retryable exception filtering

2. **"How do you prevent race conditions?"**
   → `save_parsed_ideas_atomic()` with `pg_advisory_xact_lock`

3. **"How do you optimize LLM costs?"**
   → Model routing based on message length and complexity

4. **"How do you handle nested API responses?"**
   → `safely_extract_response_data()` with priority attribute search

5. **"How do you prevent ticker false positives?"**
   → `RESERVED_SIGNAL_WORDS` + `validate_llm_tickers()` post-validation


---

## 8. Architecture Summary

### Data Flow Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                           DATA SOURCES                               │
├──────────────┬─────────────┬──────────────┬─────────────────────────┤
│  SnapTrade   │   Discord   │   Databento  │   Twitter (optional)    │
│   (broker)   │   (social)  │   (OHLCV)    │   (sentiment)           │
└──────┬───────┴──────┬──────┴──────┬───────┴──────────┬──────────────┘
       │              │             │                  │
       ▼              ▼             ▼                  ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      ETL LAYER (Collectors)                          │
├──────────────┬─────────────┬──────────────┬─────────────────────────┤
│SnaptradeColl │ChannelProc  │DatabentoColl │ TwitterAnalysis         │
│ector         │essor        │ector         │                         │
└──────┬───────┴──────┬──────┴──────┬───────┴──────────┬──────────────┘
       │              │             │                  │
       ▼              ▼             ▼                  ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      DATABASE LAYER                                  │
├────────────────────────────────┬────────────────────────────────────┤
│         SUPABASE               │              RDS                    │
│  • accounts, positions, orders │  • ohlcv_daily (1-year rolling)    │
│  • discord_messages            │                                    │
│  • discord_parsed_ideas        │                                    │
└────────────────────────────────┴────────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      NLP PIPELINE                                    │
├─────────────────────────────────────────────────────────────────────┤
│  1. preclean.py → extract_candidate_tickers() + skip detection     │
│  2. soft_splitter.py → chunk long messages                         │
│  3. openai_parser.py → LLM structured output (model routing)       │
│  4. db.py → save_parsed_ideas_atomic() with advisory locks         │
└─────────────────────────────────────────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      INTERFACE LAYER                                 │
├─────────────────────────────────────────────────────────────────────┤
│  Discord Bot (commands/)     │  Analytics (future)                  │
│  • !portfolio, !orders       │  • Dashboard views                   │
│  • !chart, !process          │  • API endpoints                     │
└─────────────────────────────────────────────────────────────────────┘
```

### Key Integration Points

| Component | Input | Output | Database Table |
|-----------|-------|--------|----------------|
| SnapTradeCollector | SnapTrade API | Positions/Orders | accounts, positions, orders |
| ChannelProcessor | Discord API | Raw messages | discord_messages |
| NLP Parser | discord_messages | Parsed ideas | discord_parsed_ideas |
| DatabentoCollector | Databento API | OHLCV bars | ohlcv_daily (RDS) |

---

*This walkthrough covers the core backend patterns. For full function signatures, see the source files directly.*
