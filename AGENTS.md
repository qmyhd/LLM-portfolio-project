# LLM Portfolio Journal - Canonical AI Contributor Guide

> **📖 This is the authoritative guide for AI coding agents working with the LLM Portfolio Journal codebase.**  
> **🏗️ For pure architecture documentation, see [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)**

## 🚀 Quick Start for AI Coding Agents

### System Overview

Sophisticated data-driven portfolio analytics system:

- **Data Sources**: SnapTrade API + Discord bot + Twitter/X API + Databento OHLCV

## ⚠️ Important Notes for Agents

### Copilot Toolsets & MCP Helpers

- **reader** – Inspect fresh diffs, diagnostics, and symbol usage before touching code.
- **semantic_search** – Pair semantic queries with the sequential thinking tool for cross-file reasoning.
- **codebase** – Combine global search, change history, and usages to orient quickly.
- **editing** – Open targeted editors, add new files, and track diffs on the fly.
- **execution** – Run commands, notebooks, and tests while monitoring diagnostics.
- **research** – Fetch external docs, browse upstream repos, or launch lightweight references.
- **Advanced MCP** – Use Supabase commands for schema checks, sequential thinking for complex plans, memory/context7 for durable notes and live documentation.

### SETUP SEQUENCE (CRITICAL)

- **Storage**: PostgreSQL/Supabase with connection pooling and real-time capabilities
- **Processing**: Advanced ETL pipelines with ticker extraction, sentiment analysis, and position tracking
- **NLP Intelligence**: OpenAI structured outputs for semantic parsing (triage → main → escalation model routing)
- **Interface**: Discord bot with modular commands, interactive charts, and real-time data collection

### Current Architecture (2026)

- **Database Engine**: PostgreSQL-only with SQLAlchemy 2.0, Supabase pooler optimization (port 6543)
- **Configuration**: Pydantic-based settings with comprehensive environment variable mapping
- **Error Handling**: Hardened retry patterns with intelligent exception filtering
- **Bot System**: Modular Discord commands with Twitter integration, advanced charting, and centralized UI design system
- **UI System**: Standardized embed factory with color coding, interactive views (portfolio filters, help dropdown), and pagination
- **NLP Pipeline**: OpenAI structured outputs for semantic parsing (triage → main → escalation model routing)
- **OHLCV Pipeline**: Databento Historical API → Supabase `ohlcv_daily`
- **Schema**: Modern PostgreSQL schema (060_baseline_current.sql + incremental migrations, 19 Supabase tables)

## 📁 Project Map & Service Purposes

### Entry Points

```bash
src/bot/bot.py                        # Discord bot entry point with Twitter integration
app/main.py                           # FastAPI backend entry point
scripts/deploy_ec2.sh                 # EC2 deploy (called by GitHub Actions on push to main)
scripts/doctor_ec2.sh                 # EC2 environment health check
scripts/backfill_ohlcv.py             # Databento OHLCV backfill CLI for EC2
scripts/nlp/parse_messages.py         # NLP parsing pipeline entry point
```

### Core Services

```
src/
├── 📊 Data Collection Layer
│   ├── price_service.py              # Centralized OHLCV data access (Supabase ohlcv_daily) - sole price source
│   ├── snaptrade_collector.py        # Dedicated SnapTrade ETL with enhanced field extraction
│   ├── databento_collector.py        # Databento OHLCV daily bars → Supabase
│   └── twitter_analysis.py           # Twitter/X integration and sentiment analysis
│
├── 💾 Database Management
│   ├── db.py                         # Advanced SQLAlchemy engine: get_connection() → PostgreSQL with pooling
│   └── config.py                     # Unified configuration: Pydantic settings with field mapping
│
├── 🧠 Processing Engine
│   ├── message_cleaner.py            # Text processing & robust ticker symbol extraction
│   └── position_analysis.py          # Advanced position tracking and analytics
│
├── 🧪 NLP Pipeline (OpenAI Structured Outputs)
│   └── nlp/
│       ├── openai_parser.py          # LLM parser with model routing (triage → main → escalation)
│       │                              # Includes candidate_tickers hint + post-validation
│       ├── schemas.py                # Pydantic schemas: ParsedIdea, MessageParseResult, 13 TradingLabels
│       ├── soft_splitter.py          # Deterministic message splitting for long content
│       └── preclean.py               # Ticker accuracy: ALIAS_MAP, RESERVED_SIGNAL_WORDS (80+ terms)
│                                      # extract_candidate_tickers(), validate_llm_tickers()
│
└── 🤖 Bot Infrastructure
    └── bot/
        ├── bot.py                     # Discord bot entry point
        ├── events.py                  # Event handlers in events.py
        ├── help.py                    # Interactive help with dropdown categories
        ├── commands/                  # Commands in commands/ subdirectory
        │   ├── chart.py               # Advanced charting with FIFO position tracking
        │   ├── history.py             # Message history fetching with deduplication
        │   ├── process.py             # Channel data processing and statistics
        │   ├── snaptrade_cmd.py       # Portfolio, orders, movers, and brokerage status
        │   ├── twitter_cmd.py         # Twitter data analysis commands
        │   └── eod.py                 # End-of-day stock data queries
        └── ui/                        # Centralized UI design system
            ├── embed_factory.py       # Standardized embed builder with color coding
            ├── pagination.py          # Base class for paginated views
            ├── portfolio_view.py      # Interactive portfolio with filters
            └── help_view.py           # Dropdown-based help navigation
```

### Schemas & Migration

```
schema/
├── 060_baseline_current.sql           # Complete schema snapshot (fresh installs)
├── 061_cleanup_migration_ledger.sql   # Ledger consolidation
├── 06N_*.sql                          # Future incremental migrations
└── archive/                           # Retired migrations (000-059), reference only
    ├── 000_baseline.sql
    ├── 015-059_*.sql
    └── README.md

scripts/
├── deploy_ec2.sh                     # Canonical deploy: pull, install, doctor, restart, health check
├── doctor_ec2.sh                     # Environment health check (venv, DB, API, systemd, nginx)
├── bootstrap.py                      # Comprehensive database setup and validation
├── deploy_database.py                # Unified database deployment system
├── schema_parser.py                  # Schema parsing and dataclass generation
├── verify_database.py                # Unified schema validation (20 tables, FKs, constraints)
├── backfill_ohlcv.py                 # Databento OHLCV backfill CLI for EC2
└── nlp/                              # NLP processing scripts
    ├── parse_messages.py             # Live message parsing with OpenAI
    ├── build_batch.py                # Batch API request builder
    ├── run_batch.py                  # Submit batch jobs to OpenAI
    ├── ingest_batch.py               # Ingest batch results to database
    └── batch_backfill.py             # Unified orchestrator for batch pipeline
```

### Data Conventions

- **PostgreSQL-only**: All data persists to Supabase PostgreSQL with CSV backup for historical data
- **Database requirement**: PostgreSQL/Supabase connection required via `get_database_url()` (no SQLite fallback)
- **Symbol extraction**: Robust regex patterns for `$TICKER` format, handles complex API responses
- **Sentiment scoring**: vaderSentiment rule-based scoring with numerical values (-1.0 to 1.0)

## ⚡ Essential Setup Commands

### 🚨 Step 1: Pre-Setup Validation (ALWAYS RUN FIRST)

```bash
# CRITICAL: Run this before any setup to validate deployment readiness
python tests/validate_deployment.py

# This validates:
# - Critical files and Python syntax
# - Directory structure and entry points
# - Core module imports and dependencies
# - .gitignore patterns and git readiness
# - Returns deployment readiness status
```

### 🎯 Step 2: Automated Bootstrap Setup (RECOMMENDED)

```bash
# COMPREHENSIVE: Fully automated setup with health checks
python scripts/bootstrap.py

# This handles:
# - Dependency installation with virtual environment detection
# - Module loading and validation
# - Environment configuration loading
# - Database connectivity testing with detailed info
# - Comprehensive health checks (DB, config, size)
# - Complete orchestration with cleanup
```

### 🔧 Step 3: Manual Environment Setup (If Bootstrap Fails)

```bash
# Complete development setup
python -m venv .venv
.venv\Scripts\Activate.ps1  # Windows PowerShell
pip install -r requirements.txt && pip install -e .

# Environment configuration
cp .env.example .env  # Edit with your API keys
```

### 💾 Step 4: Database Setup

```bash
# Database initialization and migration
python scripts/deploy_database.py       # Deploy schema to Supabase PostgreSQL
python scripts/verify_database.py       # Verify migration status
```

## 🎯 Key Development Commands

### Discord Bot (Real-time Data Collection)

```bash
# Run Discord bot for real-time data collection
python -m src.bot.bot

# Bot requires DISCORD_BOT_TOKEN in .env
```

### Development Workflow

```bash
# Run tests
pytest tests/ -v                       # Full test suite
pytest tests/ -v --cov=src             # Tests with coverage
pytest tests/ -v -m "not openai"       # Skip API tests

# Individual tests
python tests/test_integration.py       # Integration tests
```

## 🔧 Essential Environment Variables

Based on `.env.example`, configure these for full functionality:

### 🚨 Critical Dependencies (27+ packages)

```bash
# Core Data & Database (ESSENTIAL)
pandas>=2.3.1, sqlalchemy>=2.0.29, psycopg2-binary>=2.9.0
python-dotenv>=1.0.1, pydantic-settings>=2.2, pydantic==2.12.3

# Brokerage API (CORE FUNCTIONALITY)
snaptrade-python-sdk>=11.0.98

# LLM APIs (NLP PARSING)
openai>=1.98.0

# Social Media (SENTIMENT ANALYSIS)
discord.py>=2.5.2, tweepy>=4.14, vaderSentiment>=3.3

# Development & Testing (VALIDATION)
pytest>=8.2, coverage>=7.5, jupyterlab>=4.2, ipykernel>=6.29

# Visualization & Charts (UI)
matplotlib>=3.9, mplfinance==0.12.10b0, plotly==6.2.0, dash==3.1.1
```

### Required for Core Features

```bash
# Database (choose one)
SUPABASE_URL=your_supabase_project_url
SUPABASE_KEY=your_supabase_anon_key
# OR
DATABASE_URL=postgresql://user:pass@host:port/db

# LLM API (required for NLP parsing)
OPENAI_API_KEY=your_openai_key
```

### Optional Integrations

```bash
# SnapTrade (brokerage data)
SNAPTRADE_CLIENT_ID=your_client_id
SNAPTRADE_CONSUMER_KEY=your_consumer_key

# Discord Bot (social data)
DISCORD_BOT_TOKEN=your_bot_token
LOG_CHANNEL_IDS=channel_id1,channel_id2  # Comma-separated

# Twitter/X (sentiment analysis)
TWITTER_BEARER_TOKEN=your_bearer_token
```

## 🗄️ Database Architecture

### PostgreSQL-Only Architecture (Unified Supabase)

- **Primary & Only**: PostgreSQL/Supabase via `src/db.py` (advanced connection pooling, health checks)
- **Database engine**: `src/db.py` with SQLAlchemy 2.0, unified `execute_sql()` interface, auto-commit for DML operations
- **Real-time writes**: All operations use `execute_sql()` → Supabase PostgreSQL with connection pooling
- **🚨 KEY REQUIREMENT**: Must use `SUPABASE_SERVICE_ROLE_KEY` in connection string to bypass RLS policies

### Key Tables (17 Supabase tables as of migration 057)

```sql
-- SnapTrade Integration (5 tables)
accounts, account_balances, positions, orders, symbols

-- Discord/Social Integration (4 tables)
discord_messages, discord_market_clean, discord_trading_clean, discord_parsed_ideas

-- Twitter/X Integration (1 table)
twitter_data

-- Institutional (1 table)
institutional_holdings

-- Symbol Management (1 table)
symbol_aliases

-- Market Data (1 table)
ohlcv_daily  -- Databento OHLCV source

-- Stock Analytics (2 tables)
stock_profile_current, stock_profile_history  -- Derived metrics for dashboard

-- System Configuration (2 tables)
processing_status, schema_migrations

-- DROPPED in migration 049-057:
-- discord_processing_log, chart_metadata, discord_message_chunks, discord_idea_units, stock_mentions
-- daily_prices, realtime_prices, stock_metrics (replaced by ohlcv_daily)
-- event_contract_trades, event_contract_positions, trade_history (no runtime usage)
```

### Schema Validation

```bash
# Verify database schema compliance
python scripts/verify_database.py --verbose
```

## 🤖 NLP Pipeline & LLM Integration

### NLP Parsing Pipeline

```python
# Process a single message with OpenAI structured outputs
from src.nlp.openai_parser import process_message
from src.nlp.schemas import MessageParseResult, ParsedIdea

# Process a message (includes triage + parsing + escalation)
result = process_message(text, message_id=123, channel_id=456)
if result and result.ideas:
    for idea in result.ideas:
        # Each idea has: primary_symbol, labels, direction, confidence, levels
        print(f"{idea.primary_symbol}: {idea.labels} ({idea.confidence})")
```

### Batch Processing (50% cost savings)

```bash
# Build batch → submit → ingest results
python scripts/nlp/batch_backfill.py --limit 500
```

### LLM API Integration

- **Primary**: OpenAI API for structured outputs (NLP parsing)
- **Model routing**: Triage → Main → Escalation models based on message complexity
- **Retry logic**: `@hardened_retry(max_retries=3, delay=2)` for API calls

## 🧪 Testing & Validation

### 🏥 Comprehensive Health Checks

```bash
# Pre-deployment validation (run first)
python tests/validate_deployment.py

# Bootstrap validation (full system check)
python scripts/bootstrap.py

# Core integration test
python tests/test_integration.py

# Complete test suite
pytest tests/ --maxfail=1 --disable-warnings -v
```

### 🔬 Unit Testing Framework

The project uses `pytest` with comprehensive test coverage:

```bash
# Test Structure:
tests/
├── conftest.py              # Shared fixtures and pytest configuration
├── test_integration.py      # Import validation
├── test_preclean.py         # Ticker extraction & alias mapping
├── test_core_functions.py   # Prompt builder tests
└── fixtures/                # Test fixture data (JSONL)

# Run tests:
pytest tests/ -v                       # Full suite
pytest tests/test_preclean.py -v       # Single file
pytest tests/ -v -m "not openai"       # Skip API tests
pytest tests/ -v --cov=src             # With coverage
```

### 🔍 Individual Module Testing

```bash
# Database connectivity
python -c "from src.db import execute_sql; print(execute_sql('SELECT COUNT(*) FROM positions', fetch_results=True))"

# Configuration validation
python -c "from src.config import settings; print(settings().model_dump())"

# Schema validation (validates 20 tables including foreign keys and constraints)
python scripts/verify_database.py --verbose
```

### 📊 Health Monitoring & System Checks

```bash
# Database health and size monitoring
python -c "from src.db import healthcheck, get_database_size; print(f'Health: {healthcheck()}, Size: {get_database_size()}')"

# Complete system validation
python scripts/verify_database.py
```

### Data Validation Patterns

```python
# Test ticker extraction
from src.message_cleaner import extract_ticker_symbols
symbols = extract_ticker_symbols("I bought $AAPL and $MSFT today")

# Test sentiment analysis
from src.message_cleaner import calculate_sentiment
sentiment = calculate_sentiment("Great earnings from $TSLA!")

# Test database connectivity
from src.db import get_connection
conn = get_connection()  # Returns PostgreSQL connection
```

## 🔍 Symbol Extraction & Data Processing

### Ticker Symbol Pattern

- **Regex**: `r'\$[A-Z]{1,6}(?:\.[A-Z]+)?'` matches `$AAPL`, `$BRK.B`, handles 1-6 character symbols
- **SnapTrade parsing**: `extract_symbol_from_data()` walks nested dicts, handles "Unknown" symbols gracefully
- **Fallback hierarchy**: `raw_symbol` → `symbol` → `ticker` → short `id` values (no UUIDs)

### Data Processing Pipeline

1. **OHLCV Data**: `price_service.py` queries Supabase `ohlcv_daily` (Databento source)
2. **Brokerage Data**: `snaptrade_collector.py` fetches positions, orders, accounts
3. **Cleaning**: `message_cleaner.py` extracts tickers + sentiment from Discord messages
4. **Analysis**: `position_analysis.py` calculates portfolio metrics
5. **NLP Parsing**: OpenAI structured outputs → `discord_parsed_ideas` table

## 🎛️ Discord Bot Operations

### Bot Commands (once running)

```bash
# In Discord channels:
!history [limit]              # Fetch message history with deduplication
!process [channel_type]       # Process current channel messages (raw ingestion + cleaning)
!backfill [channel_type]      # One-time historical data collection
!chart SYMBOL [period] [type] # Generate advanced charts with position tracking
!twitter [SYMBOL]             # Show Twitter data and sentiment analysis
!EOD                          # Interactive end-of-day stock data lookup
!peekraw [limit]              # Debug: Show raw message JSON
```

### Data Flow: !process vs NLP Parsing

```
!process command:     Discord → discord_messages → discord_*_clean (ticker extraction, sentiment)
                      ↓ (Raw ingestion + basic cleaning)

parse_messages.py:    discord_messages → OpenAI LLM → discord_parsed_ideas (structured ideas)
                      ↓ (Advanced NLP parsing)
```

Both are needed! `!process` populates `discord_messages`, which NLP parsing then consumes.

### Bot Architecture

- **Command registration**: Each command file in `commands/` has `register(bot)` function
- **Event handling**: Centralized in `events.py` with Twitter client dependency injection
- **Message logging**: Real-time ticker detection and sentiment analysis via `on_message` handler
- **Channel filtering**: Only logs messages from channels in `LOG_CHANNEL_IDS` environment variable

## ⚠️ Critical Development Patterns

### Error Handling & Retries

```python
# Use established retry decorators
from src.retry_utils import hardened_retry, database_retry

@hardened_retry(max_retries=3, delay=1)
def api_call_function():
    # API integration code
    pass

@database_retry(max_retries=3)
def database_function():
    # Database operations
    pass
```

### Configuration Management

```python
# Always use centralized config
from src.config import settings
config = settings()

# Access database URL
from src.config import get_database_url
db_url = get_database_url()  # Returns PostgreSQL URL only (no SQLite fallback)
```

### Database Operations

```python
# PostgreSQL database interface
from src.db import execute_sql

# Query with results using named placeholders
results = execute_sql("SELECT * FROM positions WHERE symbol = :symbol",
                     params={'symbol': 'AAPL'}, fetch_results=True)

# Execute without results using named placeholders
execute_sql("UPDATE positions SET price = :price WHERE symbol = :symbol",
           params={'price': 150.00, 'symbol': 'AAPL'})
```

## 🚨 Important Notes for Agents

### SETUP SEQUENCE (CRITICAL)

1. **ALWAYS run `python tests/validate_deployment.py` FIRST** - validates environment readiness
2. **Use `python scripts/bootstrap.py` for automated setup** - handles dependencies, environment, database
3. **Virtual environment is REQUIRED** - bootstrap warns if not detected
4. **Environment variables must be configured** - copy .env.example to .env with your keys

### DO NOT MODIFY

- Database connection logic in `db.py`
- Core retry mechanisms in `retry_utils.py`
- Configuration loading in `config.py`
- Schema migration files in `schema/` (create new ones instead)

### ALWAYS USE

- `execute_sql()` for database operations with named placeholders (:param) and dict parameters
- Retry decorators for external API calls
- `pathlib.Path` for file operations (not string concatenation)
- Type hints for function signatures
- Comprehensive error handling with graceful degradation

### FILE NAMING CONVENTIONS

- **CSV files**: `data/raw/` for source data, `data/processed/` for cleaned data
- **Environment**: `.env` (git-ignored), `.env.example` (template)

### DEVELOPMENT WORKFLOW

1. Always run `python tests/test_integration.py` after changes
2. Test ticker extraction with edge cases (numbers, special characters)
3. Follow the retry pattern for external API calls
4. Handle missing `.env` variables gracefully

## 📚 Key Functions Reference

### Price Data (OHLCV)

```python
from src.price_service import get_ohlcv, get_latest_close, get_previous_close
# get_ohlcv(symbol, start, end) → pd.DataFrame (mplfinance compatible)
# get_latest_close(symbol) → Optional[float]
# get_previous_close(symbol, before_date) → Optional[float]
```

### Brokerage Data

```python
from src.snaptrade_collector import SnapTradeCollector
```

### Text Processing

```python
from src.message_cleaner import extract_ticker_symbols, calculate_sentiment, clean_text
```

### NLP Pipeline (Ticker Accuracy)

```python
from src.nlp.preclean import (
    extract_candidate_tickers,      # Deterministic pre-LLM ticker extraction
    validate_llm_tickers,           # Post-validate LLM output against candidates
    is_reserved_signal_word,        # Check if word is trading terminology
    apply_alias_mapping,            # Company names → ticker symbols
    is_bot_command,                 # Detect bot commands (!help, !!chart, etc.)
    RESERVED_SIGNAL_WORDS,          # 80+ trading terms that never become tickers
    ALIAS_MAP,                      # ~100 company→ticker mappings
)

from src.nlp.openai_parser import process_message, parse_message
from src.nlp.schemas import ParsedIdea, MessageParseResult, TradingLabels
```

### Database Operations

```python
from src.db import execute_sql, get_connection
from src.db import get_database_url
```

This guide provides everything needed for effective development on the LLM Portfolio Journal system. Follow these patterns and you'll be able to extend and maintain the codebase successfully!

<!-- opensrc:start -->

## Source Code Reference

Source code for dependencies is available in `opensrc/` for deeper understanding of implementation details.

See `opensrc/sources.json` for the list of available packages and their versions.

Use this source code when you need to understand how a package works internally, not just its types/interface.

### Fetching Additional Source Code

To fetch source code for a package or repository you need to understand, run:

```bash
npx opensrc <package>           # npm package (e.g., npx opensrc zod)
npx opensrc pypi:<package>      # Python package (e.g., npx opensrc pypi:requests)
npx opensrc crates:<package>    # Rust crate (e.g., npx opensrc crates:serde)
npx opensrc <owner>/<repo>      # GitHub repo (e.g., npx opensrc vercel/ai)
```

<!-- opensrc:end -->