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
python generate_journal.py --force    # Generate journal with data refresh
python -m src.bot.bot                  # Run Discord bot
python scripts/bootstrap.py           # Complete setup + migration

# Development & debugging
make test                              # Run pytest test suite
python test_integration.py            # Core integration tests
python scripts/verify_schemas.py      # Database schema validation
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

# Universal query execution with PostgreSQL
result = execute_sql("SELECT * FROM positions", fetch_results=True)

# Connection management with pooling/health checks
with get_connection() as conn:
    # Your database operations

# Direct engine access for SQLAlchemy operations
engine = get_sync_engine()
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

### LLM Journal Generation
```python
from src.journal_generator import create_enhanced_journal_prompt, generate_journal_entry

# Primary: Gemini API → Fallback: OpenAI API  
prompt = create_enhanced_journal_prompt(positions_df, messages_df, prices_df)
journal = generate_journal_entry(prompt, max_tokens=160)  # ~120 words
```

### Discord Bot (Modular Command Pattern)
```python
# Commands located in src/bot/commands/
# Registration pattern in each command file:
def register(bot: commands.Bot):
    @bot.command(name="command_name")
    async def command_func(ctx, param: str = "default"):
        # Command implementation
```

### Configuration (Pydantic + Environment)
```python
from src.config import settings, get_database_url
config = settings()  # Auto-loads from .env with validation
db_url = get_database_url()  # Returns PostgreSQL URL only (no SQLite fallback)
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

### Testing Patterns
- **Integration**: `python test_integration.py` - tests ticker extraction, imports
- **Unit tests**: `pytest tests/ --maxfail=1 --disable-warnings -v`  
- **Database**: Use `execute_sql("SELECT COUNT(*) FROM table_name", fetch_results=True)`
- **Schema validation**: `python scripts/verify_schemas.py --verbose`

### File Structure Context
- **Entry points**: `generate_journal.py`, `src/bot/bot.py`
- **Data processing**: `src/data_collector.py` (market), `src/snaptrade_collector.py` (brokerage)
- **LLM integration**: `src/journal_generator.py` (dual text/markdown output)
- **Database**: `src/db.py` (engine with unified real-time writes)
- **Bot commands**: `src/bot/commands/` (modular structure with `register()` functions)

### Data Flow Architecture
```
SnapTrade + Discord + Twitter → PostgreSQL (Supabase) → LLM → Journal (text + markdown)
```

## ⚠️ Critical Rules

- **PostgreSQL-only**: No SQLite fallback - all database operations use Supabase PostgreSQL
- **Always use retry patterns** for external APIs (SnapTrade, yfinance, LLM APIs)
- **Always use `pathlib.Path`** - never string concatenation for file paths
- **Test ticker extraction** with edge cases (`$BRK.B`, mixed text, duplicates)
- **Database operations**: Use `execute_sql()` or connection patterns with PostgreSQL syntax
- **Virtual environment required** - bootstrap validates this automatically
- **Environment variables mandatory** - 27+ dependencies, see requirements.txt

**📚 For complete setup instructions, architecture deep-dives, and advanced patterns, see [AGENTS.md](../AGENTS.md)**