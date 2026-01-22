# LLM Portfolio Journal - AI Advisor Complete Technical Guide

> **Generated:** December 9, 2025  
> **Purpose:** Complete technical reference for AI coding assistants to understand, debug, and extend the codebase  
> **Database:** PostgreSQL (Supabase) - 19 active tables, RLS enabled

---

## 🎯 Quick Reference

### System Overview
A sophisticated portfolio tracking system that:
1. **Collects Data** from SnapTrade (brokerage), Discord (social), Twitter (sentiment), yfinance (market)
2. **Processes** messages to extract tickers, calculate sentiment, track positions
3. **Generates** AI-powered journal entries using Gemini/OpenAI LLMs
4. **Provides** Discord bot interface for real-time interaction and commands

### Critical Entry Points
```bash
# Main operations
python generate_journal.py --force    # Generate trading journal
python -m src.bot.bot                  # Run Discord bot
python scripts/bootstrap.py           # Full setup/health check

# Database operations
python scripts/deploy_database.py     # Deploy schema changes
python scripts/verify_database.py     # Validate schema alignment
python scripts/schema_parser.py --output expected  # Regenerate expected_schemas.py
```

---

## 📊 Database Schema Reference

### Connection Configuration
```python
# Environment Variables Required:
DATABASE_URL=postgresql://postgres.project:sb_secret_KEY@aws-0-us-east-1.pooler.supabase.com:6543/postgres
SUPABASE_URL=https://project.supabase.co
SUPABASE_SERVICE_ROLE_KEY=sb_secret_...

# Usage:
from src.db import execute_sql, get_sync_engine
from src.config import get_database_url
```

### Tables with Row Counts (as of Dec 9, 2025)

| Table | Rows | Primary Key | Purpose |
|-------|------|-------------|---------|
| **accounts** | 2 | `id` | Brokerage accounts from SnapTrade |
| **account_balances** | 4 | `account_id, currency_code, snapshot_date` | Cash/buying power snapshots |
| **positions** | 178 | `symbol, account_id` | Current holdings |
| **orders** | 703 | `brokerage_order_id` | Trade history |
| **symbols** | 180 | `id` | Ticker reference data |
| **discord_messages** | 226 | `message_id` | Raw Discord messages |
| **discord_market_clean** | 25 | `message_id` | Processed general messages |
| **discord_trading_clean** | 165 | `message_id` | Processed trading messages |
| **twitter_data** | 7 | `tweet_id` | Extracted tweet data |
| **event_contract_trades** | 207 | `trade_id` | Event contract trades |
| **event_contract_positions** | 33 | `position_id` | Event contract positions |
| **schema_migrations** | 26 | `version` | Migration tracking |
| **processing_status** | 211 | `message_id, channel` | Message processing flags |
| **daily_prices** | 1 | `date, symbol` | Historical OHLCV |
| **realtime_prices** | 7 | `timestamp, symbol` | Intraday prices |
| **stock_metrics** | 2 | `date, symbol` | Fundamental metrics |
| **chart_metadata** | 0 | `symbol, period, interval, theme` | Chart configs |
| **discord_processing_log** | 0 | `message_id, channel` | Processing history |
| **institutional_holdings** | 0 | `id` | 13F filing data |

### Key Relationships
```
accounts.id ← positions.account_id
accounts.id ← orders.account_id
accounts.id ← account_balances.account_id
discord_messages.message_id ← twitter_data.discord_message_id
discord_messages.message_id ← processing_status.message_id
```

### Database Operations Pattern
```python
# ALWAYS use named placeholders (:param) with dict parameters
from src.db import execute_sql

# SELECT with results
result = execute_sql(
    "SELECT * FROM positions WHERE symbol = :symbol",
    params={"symbol": "AAPL"},
    fetch_results=True
)

# INSERT/UPDATE (auto-commits)
execute_sql(
    "INSERT INTO daily_prices (symbol, date, close) VALUES (:symbol, :date, :price)",
    params={"symbol": "AAPL", "date": "2025-12-09", "price": 150.00}
)
```

---

## 📁 File Structure & Purposes

### Core Application (`src/`)

| File | Purpose | Key Functions |
|------|---------|---------------|
| `db.py` | Database engine with SQLAlchemy 2.0 | `execute_sql()`, `get_sync_engine()`, `get_connection()` |
| `config.py` | Pydantic settings from .env | `settings()`, `get_database_url()` |
| `data_collector.py` | Market data ingestion | `fetch_realtime_prices()`, `update_all_data()` |
| `snaptrade_collector.py` | SnapTrade ETL operations | `SnapTradeCollector.collect_all_data()` |
| `message_cleaner.py` | Text processing & ticker extraction | `extract_ticker_symbols()`, `calculate_sentiment()` |
| `journal_generator.py` | LLM integration | `generate_journal_entry()`, `create_enhanced_journal_prompt()` |
| `channel_processor.py` | Discord channel processing | `process_channel_data()`, `parse_messages_with_llm()` |
| `twitter_analysis.py` | Twitter/X data extraction | Tweet fetching and sentiment |
| `retry_utils.py` | Retry decorators | `@hardened_retry`, `@database_retry` |
| `position_analysis.py` | Portfolio analytics | Position tracking, P/L calculation |
| `chart_enhancements.py` | Enhanced charting | Position overlays on charts |
| `market_data.py` | Market data queries | Portfolio queries |
| `logging_utils.py` | Logging with Twitter | `log_message_with_twitter()` |
| `expected_schemas.py` | Schema definitions | `EXPECTED_SCHEMAS` dict for validation |

### Bot Infrastructure (`src/bot/`)

| File | Purpose |
|------|---------|
| `bot.py` | Entry point, bot creation |
| `__init__.py` | `create_bot()` factory function |
| `events.py` | Message event handlers, ticker detection |
| `help.py` | Custom help command with dropdowns |

### Bot Commands (`src/bot/commands/`)

| Command | File | Usage |
|---------|------|-------|
| `!chart SYMBOL` | `chart.py` | Generate price charts with position tracking |
| `!history [limit]` | `history.py` | Fetch channel message history |
| `!process [type]` | `process.py` | Process channel messages for tickers/sentiment |
| `!portfolio` | `snaptrade_cmd.py` | Show current positions |
| `!orders` | `snaptrade_cmd.py` | Show recent orders |
| `!movers` | `snaptrade_cmd.py` | Top gainers/losers |
| `!twitter [SYMBOL]` | `twitter_cmd.py` | Twitter sentiment analysis |
| `!EOD` | `eod.py` | End-of-day stock lookup |

### Bot UI (`src/bot/ui/`)

| File | Purpose |
|------|---------|
| `embed_factory.py` | Standardized embed builder with color coding |
| `pagination.py` | Base class for paginated views |
| `portfolio_view.py` | Interactive portfolio with filter buttons |
| `help_view.py` | Dropdown-based help navigation |

### Scripts (`scripts/`)

| Script | Purpose | When to Use |
|--------|---------|-------------|
| `bootstrap.py` | Full setup automation | Initial setup, health checks |
| `deploy_database.py` | Schema deployment | After creating migrations |
| `verify_database.py` | Schema validation | Verify DB matches expected |
| `schema_parser.py` | Generate expected_schemas.py | After SQL changes |
| `check_system_status.py` | Quick health check | Debugging connectivity |
| `fetch_discord_history_improved.py` | Discord backfill | Historical data import |

### Tests (`tests/`)

| Test File | Coverage |
|-----------|----------|
| `test_integration.py` | Ticker extraction, import consolidation |
| `test_core_functions.py` | Unit tests: ticker, sentiment, prompts |
| `test_safe_response_handling.py` | API response parsing |
| `validate_deployment.py` | Pre-deployment validation |

### ETL (`src/etl/`)

| File | Purpose |
|------|---------|
| `sec_13f_parser.py` | Parse SEC 13F filings (standalone tool) |

---

## 🔄 Process Flows

### 1. SnapTrade Data Sync
```
SnapTrade API → snaptrade_collector.py → PostgreSQL
                      ↓
               accounts, positions, orders, symbols tables
```

### 2. Discord Message Processing
```
Discord Channel → bot events.py → discord_messages table
                        ↓
              message_cleaner.py (extract tickers, sentiment)
                        ↓
         discord_trading_clean OR discord_market_clean table
```

### 3. Journal Generation
```
positions + orders + discord_messages → journal_generator.py
                                             ↓
                                    Gemini API (primary)
                                             ↓
                                    OpenAI API (fallback)
                                             ↓
                                    Markdown + Text output
```

### 4. Schema Management
```
schema/*.sql → schema_parser.py → src/expected_schemas.py
                                         ↓
                              verify_database.py (validate)
```

---

## 🤖 Discord Bot Commands Reference

### Portfolio Commands
```
!portfolio              # Show all positions with P/L
!portfolio winners      # Filter to profitable positions
!portfolio losers       # Filter to losing positions
!orders [limit]         # Show recent orders (default: 10)
!movers                 # Top gainers and losers
```

### Chart Commands
```
!chart AAPL             # Default 1-month chart
!chart AAPL 3mo         # 3-month period
!chart AAPL 1y candle   # 1-year candlestick
!chart AAPL 6mo line    # 6-month line chart
```

### Data Processing Commands
```
!history 100            # Fetch last 100 messages
!process trading        # Process as trading channel
!process market         # Process as market channel
!stats                  # Show channel statistics
```

### Twitter Commands
```
!twitter                # Recent Twitter data
!twitter AAPL           # Twitter data for specific ticker
```

---

## 🔧 Common Operations

### Adding a New Database Column

1. **Create migration file:**
```sql
-- schema/030_add_new_column.sql
ALTER TABLE positions ADD COLUMN IF NOT EXISTS new_field TEXT;
```

2. **Deploy:**
```bash
python scripts/deploy_database.py
```

3. **Regenerate schemas:**
```bash
python scripts/schema_parser.py --output expected
```

4. **Verify:**
```bash
python scripts/verify_database.py
```

### Adding a New Bot Command

1. **Create command file:** `src/bot/commands/new_cmd.py`
```python
def register(bot, twitter_client=None):
    @bot.command(name="newcmd")
    async def new_command(ctx, arg: str = "default"):
        await ctx.send(f"Response: {arg}")
```

2. **Register in:** `src/bot/commands/__init__.py`
```python
from .new_cmd import register as register_new_cmd
# Add to register_commands function
register_new_cmd(bot, twitter_client)
```

### Testing Ticker Extraction
```python
from src.message_cleaner import extract_ticker_symbols

# Test cases
assert extract_ticker_symbols("I bought $AAPL") == ["$AAPL"]
assert extract_ticker_symbols("$BRK.B is up") == ["$BRK.B"]
assert extract_ticker_symbols("No tickers here") == []
```

### Manual Database Query
```python
from src.db import execute_sql

# Get position summary
result = execute_sql("""
    SELECT symbol, quantity, equity, open_pnl 
    FROM positions 
    WHERE quantity > 0 
    ORDER BY equity DESC
""", fetch_results=True)
```

---

## ⚠️ Critical Rules

### DO
- ✅ Use `execute_sql()` with named placeholders (`:param`)
- ✅ Use `pathlib.Path` for file paths
- ✅ Use retry decorators for external API calls
- ✅ Regenerate expected_schemas.py after SQL changes
- ✅ Test ticker extraction with edge cases

### DON'T
- ❌ Modify `db.py` connection logic without understanding pooling
- ❌ Manually edit `expected_schemas.py` (regenerate from SQL)
- ❌ Skip schema verification after migrations
- ❌ Use string formatting for SQL queries (SQL injection risk)

---

## 🐛 Troubleshooting

### Database Connection Issues
```python
# Test connection
from src.db import test_connection
print(test_connection())  # Should return True

# Check URL format
from src.config import get_database_url
print(get_database_url())  # Should contain sb_secret_
```

### Schema Mismatch Errors
```bash
# Regenerate and verify
python scripts/schema_parser.py --output expected
python scripts/verify_database.py --verbose
```

### Bot Not Responding
1. Check `DISCORD_BOT_TOKEN` in `.env`
2. Verify channel is in `LOG_CHANNEL_IDS`
3. Check bot has message content intent enabled

### Missing Ticker Detection
```python
# Debug ticker extraction
from src.message_cleaner import extract_ticker_symbols
text = "your message here"
print(f"Tickers: {extract_ticker_symbols(text)}")
```

---

## 📚 Environment Variables Reference

### Required
| Variable | Purpose |
|----------|---------|
| `DATABASE_URL` | PostgreSQL connection string |
| `DISCORD_BOT_TOKEN` | Bot authentication |
| `GEMINI_API_KEY` | Primary LLM API |

### Optional
| Variable | Purpose |
|----------|---------|
| `OPENAI_API_KEY` | Fallback LLM API |
| `SNAPTRADE_CLIENT_ID` | Brokerage integration |
| `SNAPTRADE_CONSUMER_KEY` | Brokerage integration |
| `TWITTER_BEARER_TOKEN` | Twitter API access |
| `LOG_CHANNEL_IDS` | Discord channels to monitor |

---

## 📈 Data Flow Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                        DATA SOURCES                                  │
├─────────────────────────────────────────────────────────────────────┤
│  SnapTrade API    Discord Bot    Twitter API    yfinance            │
│       │               │              │              │               │
│       ▼               ▼              ▼              ▼               │
│  snaptrade_      events.py      twitter_      data_collector        │
│  collector.py                   analysis.py      .py                │
└───────┬───────────────┬──────────────┬──────────────┬───────────────┘
        │               │              │              │
        ▼               ▼              ▼              ▼
┌─────────────────────────────────────────────────────────────────────┐
│                     POSTGRESQL (SUPABASE)                            │
├─────────────────────────────────────────────────────────────────────┤
│  accounts  │ positions │ orders │ discord_messages │ twitter_data   │
│  symbols   │ balances  │ prices │ *_clean tables   │ processing_*   │
└─────────────────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────────────┐
│                        PROCESSING                                    │
├─────────────────────────────────────────────────────────────────────┤
│  message_cleaner.py → Ticker extraction, sentiment analysis          │
│  position_analysis.py → Portfolio metrics, P/L calculation           │
│  journal_generator.py → LLM prompt construction                      │
└───────┬─────────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────────────┐
│                        OUTPUT                                        │
├─────────────────────────────────────────────────────────────────────┤
│  Gemini/OpenAI API → Markdown Journal + Text Summary                 │
│  Discord Bot → Real-time responses, charts, portfolio views          │
└─────────────────────────────────────────────────────────────────────┘
```

---

*This guide should provide everything needed to understand, debug, and extend the LLM Portfolio Journal system.*
