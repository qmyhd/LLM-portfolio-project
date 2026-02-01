# LLM Portfolio Journal - AI Coding Agent Instructions

> **📖 For comprehensive guidance, see [AGENTS.md](../AGENTS.md) - the canonical AI contributor guide**  
> **🏗️ For architecture details, see [docs/ARCHITECTURE.md](../docs/ARCHITECTURE.md) - the canonical architecture reference**

## 🚨 Critical Setup Sequence

**ALWAYS follow this order before any development:**

1. **Pre-validation**: `python tests/validate_deployment.py` - validates environment readiness
2. **Automated setup**: `python scripts/bootstrap.py` - handles dependencies, database, migration
3. **Environment config**: Copy `.env.example` to `.env` with your API keys

## ⚡ Essential Commands

```bash
# Core workflow
python -m src.bot.bot                  # Run Discord bot
python scripts/bootstrap.py           # Complete setup

# Development & debugging
pytest tests/ -v                       # Run pytest test suite
pytest tests/ -v --cov=src             # Run tests with coverage
python tests/test_integration.py      # Core integration tests
python scripts/verify_database.py     # Database schema validation

# OHLCV data backfill
python scripts/backfill_ohlcv.py --daily  # Databento OHLCV
```

## 🧰 Copilot Toolsets

Leverage the curated Copilot tool palettes to stay efficient:

- **reader** → Scout recent diffs, open diagnostics, and trace symbol usage before editing anything.
- **semantic_search** → Ask deeper questions; pair semantic queries with the sequential thinking tool to reason across files.
- **codebase** → Map the repo fast by combining global search, change history, and usage lookups.
- **editing** → Open precise editors, add new files, and keep diffs tight while you iterate.
- **execution** → Launch commands, tests, or notebooks and watch diagnostics for fast validation cycles.
- **research** → Pull external docs, upstream repos, or quick reference pages without leaving the editor.

## 🎯 Critical Architecture Patterns

### Database Engine (PostgreSQL/Supabase Only)

```python
# ALWAYS use these patterns for database operations:
from src.db import execute_sql, get_connection, get_sync_engine

# Universal query execution with named placeholders (REQUIRED)
result = execute_sql(
    "SELECT * FROM positions WHERE symbol = :symbol",
    params={'symbol': 'AAPL'},
    fetch_results=True
)

# Connection management with pooling/health checks
with get_connection() as conn:
    # Your database operations

# Direct engine access for SQLAlchemy operations
engine = get_sync_engine()

# CRITICAL: Must use service role key in DATABASE_URL to bypass RLS policies
# Format: postgresql://postgres.project:sb_secret_YOUR_KEY@...
```

### Retry & Error Handling (Required for all external calls)

```python
from src.retry_utils import hardened_retry, database_retry

@hardened_retry(max_retries=3, delay=2)  # API calls
def api_operation(): pass

@database_retry(max_retries=3)  # Database operations
def db_operation(): pass
```

### File Operations (Path-based, not strings)

```python
from pathlib import Path
# ALWAYS use Path objects, never string concatenation
BASE_DIR = Path(__file__).resolve().parent.parent
data_file = BASE_DIR / "data" / "raw" / "positions.csv"
```

### Ticker Symbol Extraction (Core business logic)

```python
from src.message_cleaner import extract_ticker_symbols
# Handles $AAPL, $BRK.B format with 1-6 character limit
symbols = extract_ticker_symbols("Text with $AAPL and $MSFT")
```

## 🔧 Key Integration Points

### NLP Pipeline (OpenAI Structured Outputs)

```python
from src.nlp.openai_parser import process_message
from src.nlp.schemas import MessageParseResult, ParsedIdea

# Process a message (includes triage + parsing + escalation)
result = process_message(text, message_id=123, channel_id=456)
if result and result.ideas:
    for idea in result.ideas:
        # Each idea has: primary_symbol, labels, direction, confidence, levels
        print(f"{idea.primary_symbol}: {idea.labels} ({idea.confidence})")

# Model routing via environment variables:
# OPENAI_MODEL_TRIAGE, OPENAI_MODEL_MAIN, OPENAI_MODEL_ESCALATION
# OPENAI_MODEL_LONG (high symbol density), OPENAI_MODEL_SUMMARY
```

### Discord Bot (Modular Command Pattern)

```python
# Commands located in src/bot/commands/
# Registration pattern in each command file:
def register(bot: commands.Bot, twitter_client=None):
    @bot.command(name="command_name")
    async def command_func(ctx, param: str = "default"):
        # Command implementation - can use twitter_client if needed
        pass

# Bot initialization with Twitter integration:
from src.bot import create_bot
bot = create_bot(command_prefix="!", twitter_client=twitter_client)
```

### Configuration (Pydantic + Environment)

```python
from src.config import settings, get_database_url
config = settings()  # Auto-loads from .env with validation
db_url = get_database_url()  # Returns PostgreSQL URL only (no SQLite fallback)

# Channel-to-table mapping for Discord messages:
from src.message_cleaner import CHANNEL_TYPE_TO_TABLE
table_name = CHANNEL_TYPE_TO_TABLE["trading"]  # -> "discord_trading_clean"
```

### NLP Pipeline (OpenAI Structured Outputs)

```python
# Parse Discord messages into structured idea units
from src.nlp.openai_parser import process_message
from src.nlp.schemas import MessageParseResult, ParsedIdea

# Process a single message (includes triage + parsing + escalation)
result = process_message(text, message_id=123, channel_id=456)
if result and result.ideas:
    for idea in result.ideas:
        # Each idea has: primary_symbol, labels, direction, confidence, levels
        print(f"{idea.primary_symbol}: {idea.labels} ({idea.confidence})")

# Model routing via environment variables:
# OPENAI_MODEL_TRIAGE, OPENAI_MODEL_MAIN, OPENAI_MODEL_ESCALATION
# OPENAI_MODEL_LONG (high symbol density), OPENAI_MODEL_SUMMARY
```

### Ticker Accuracy (preclean.py)

```python
# Deterministic ticker extraction before LLM + post-validation
from src.nlp.preclean import (
    extract_candidate_tickers,      # Pre-LLM deterministic extraction
    validate_llm_tickers,           # Post-validate LLM output against candidates
    is_reserved_signal_word,        # Check if word is trading terminology
    RESERVED_SIGNAL_WORDS,          # 80+ terms: tgt, pt, target, support, etc.
    ALIAS_MAP,                      # Company names → tickers (~100 entries)
)

# Example: prevent "price target $50" from becoming "$TGT $50"
candidates = extract_candidate_tickers("price target $50 for AAPL")
# Returns: {'AAPL'} (not TGT - "target" is in RESERVED_SIGNAL_WORDS)
```

### Concurrency Guards (Advisory Locks)

```python
# REQUIRED for delete+insert patterns on discord_parsed_ideas
# Prevents race conditions when multiple workers process same message
lock_key = int(message_id) if str(message_id).isdigit() else hash(str(message_id)) & 0x7FFFFFFFFFFFFFFF
execute_sql("SELECT pg_advisory_xact_lock(:lock_key)", params={"lock_key": lock_key})
# Then safely: DELETE existing ideas → INSERT new ideas
```

## 🔍 Development Workflow

### Before Making Changes

```bash
# 1. Validate current state
python tests/validate_deployment.py
# 2. Run integration tests
python test_integration.py
# 3. Check database health
python -c "from src.db import test_connection; print(test_connection())"
```

### Schema Management & Migrations

```bash
# Deploy latest schema changes
python scripts/deploy_database.py
# Verify schema compliance
python scripts/verify_database.py --verbose
# Run timestamp migrations (if needed)
python scripts/run_timestamp_migration.py
```

### Testing Patterns

- **Integration**: `python tests/test_integration.py` - tests ticker extraction, imports
- **Unit tests**: `pytest tests/ --maxfail=1 --disable-warnings -v`
- **Database**: Use `execute_sql("SELECT COUNT(*) FROM table_name", fetch_results=True)`
- **Schema validation**: `python scripts/verify_database.py --verbose`

### File Structure Context

- **Entry points**: `src/bot/bot.py`
- **Price data**: `src/price_service.py` (RDS ohlcv_daily), `src/snaptrade_collector.py` (brokerage)
- **OHLCV pipeline**: `src/databento_collector.py` → RDS/S3/Supabase
- **NLP processing**: `src/nlp/` (OpenAI parser, schemas, soft splitter, preclean)
- **NLP scripts**: `scripts/nlp/` (parse_messages, build_batch, run_batch, ingest_batch)
- **Database**: `src/db.py` (engine with unified real-time writes)
- **Bot commands**: `src/bot/commands/` (modular structure with `register()` functions)

### Data Flow Architecture

```
SnapTrade + Discord + Twitter → PostgreSQL (Supabase) → NLP Parser → discord_parsed_ideas
```

**NLP Pipeline Stage**:

1. Discord messages stored in `discord_messages`
2. `scripts/nlp/parse_messages.py` processes pending messages
3. OpenAI structured outputs extract idea units with labels, symbols, levels
4. Ideas stored in `discord_parsed_ideas` with unique constraint `(message_id, soft_chunk_index, local_idea_index)`

## ⚠️ Critical Rules

- **PostgreSQL-only**: No SQLite fallback - all database operations use Supabase PostgreSQL
- **Always use retry patterns** for external APIs (SnapTrade, OpenAI, Databento)
- **Always use `pathlib.Path`** - never string concatenation for file paths
- **Test ticker extraction** with edge cases (`$BRK.B`, mixed text, duplicates)
- **Database operations**: Use `execute_sql()` or connection patterns with PostgreSQL syntax
- **Advisory locks required** for delete+insert patterns on `discord_parsed_ideas` (use `pg_advisory_xact_lock`)
- **NLP structured outputs**: Use Pydantic schemas from `src.nlp.schemas` for OpenAI Responses API
- **Virtual environment required** - bootstrap validates this automatically
- **Environment variables mandatory** - see requirements.txt for dependencies

**📚 For complete setup instructions, architecture deep-dives, and advanced patterns, see [AGENTS.md](../AGENTS.md)**
