# LLM Portfolio Journal - Canonical AI Contributor Guide

> **📖 This is the authoritative guide for AI coding agents working with the LLM Portfolio Journal codebase.**  
> **🏗️ For pure architecture documentation, see [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)**

## 🚀 Quick Start for AI Coding Agents

### System Overview
Sophisticated data-driven portfolio journal system with integrated LLM generation:
- **Data Sources**: SnapTrade API + Discord bot

## 🚨 CRITICAL FIXES & TROUBLESHOOTING

### **Recently Resolved Issues (Sept 2025)**

#### **1. Supabase Connection & RLS Policy Issues**
**Problem**: Database operations failing with RLS policy blocks or transaction issues  
**Root Cause**: Using direct PostgreSQL password instead of Supabase service role key  
**Solution**: Update `.env` DATABASE_URL to use `SUPABASE_SERVICE_ROLE_KEY`:  
```bash
# ❌ Wrong (direct password): 
DATABASE_URL=postgresql://postgres.project:directpassword@...

# ✅ Correct (service role key):
DATABASE_URL=postgresql://postgres.project:sb_secret_YOUR_KEY@...
```
**Verification**: `python -c "from src.config import get_database_url; print('✅' if 'sb_secret_' in get_database_url() else '❌')"`

#### **2. INSERT Operations Not Persisting** 
**Problem**: `execute_sql()` INSERT operations returning success but data not persisting (COUNT = 0)  
**Root Cause**: `execute_query()` only auto-committed DDL operations, not DML (INSERT/UPDATE/DELETE)  
**Solution**: Modified `src/db.py` to auto-commit both DDL and DML write operations  
**Fix Applied**: Added `is_dml_write` check for INSERT/UPDATE/DELETE operations

#### **3. Schema Mismatches in SnapTrade Integration**
**Problem**: Orders table insert failing with "column does not exist" errors  
**Root Cause**: Code attempting to insert `universal_symbol`, `extracted_symbol` columns not in actual schema  
**Solution**: Removed non-existent column references from `src/snaptrade_collector.py`  
**Tables Affected**: Orders table (32 actual columns vs 36 expected)

#### **4. Account-Position Relationship Failures**
**Problem**: 165/166 positions linked to fake "default_account" instead of real accounts  
**Root Cause**: `extract_position_data()` method not receiving `account_id` parameter  
**Solution**: Modified method signature and propagated `account_id` from `get_positions()` call  
**Result**: All positions now correctly linked to real Robinhood account

#### **5. Symbol Table Population Failures**
**Problem**: Symbols table empty despite positions containing valid tickers  
**Root Cause**: Case-sensitive filtering (`!= "Unknown"` vs `"UNKNOWN"` in data)  
**Solution**: Changed to case-insensitive comparison (`symbol_val.lower() != "unknown"`)  
**Result**: 177 symbols successfully extracted from positions + orders

### **Critical Verification Commands**
```bash
# 1. Verify Supabase service role key usage
python -c "from src.config import get_database_url; print('Service role:' if 'sb_secret_' in get_database_url() else 'Direct password')"

# 2. Test data operations work end-to-end
python -c "from src.snaptrade_collector import SnapTradeCollector; print(f'Success: {SnapTradeCollector().collect_all_data(write_parquet=False)[\"success\"]}')"

# 3. Verify data integrity
python -c "from src.db import execute_sql; r=execute_sql('SELECT COUNT(*) FROM positions p JOIN accounts a ON p.account_id=a.id', fetch_results=True); print(f'Linked positions: {r[0][0]}')"
```

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
Twitter/X API + yfinance → Real-time market sentiment & brokerage data
- **Storage**: PostgreSQL/Supabase with connection pooling and real-time capabilities
- **Processing**: Advanced ETL pipelines with ticker extraction, sentiment analysis, and position tracking
- **Intelligence**: LLM-powered journal generation (Gemini primary, OpenAI fallback) with dual output formats
- **Interface**: Discord bot with modular commands, interactive charts, and real-time data collection

### Current Architecture (2025)
- **Database Engine**: PostgreSQL-only with SQLAlchemy 2.0, Supabase pooler optimization (port 6543)
- **Configuration**: Pydantic-based settings with comprehensive environment variable mapping
- **Error Handling**: Hardened retry patterns with intelligent exception filtering
- **Bot System**: Modular Discord commands with Twitter integration, advanced charting, and centralized UI design system
- **UI System**: Standardized embed factory with color coding, interactive views (portfolio filters, help dropdown), and pagination
- **NLP Pipeline**: OpenAI structured outputs for semantic parsing (triage → main → escalation model routing)
- **Schema**: Modern PostgreSQL schema (000_baseline.sql → 048_drop_unused_nlp_indexes.sql, 24 tables)

## 📁 Project Map & Service Purposes

### Entry Points
```bash
generate_journal.py                    # CLI wrapper → src.journal_generator.main()
src/bot/bot.py                        # Discord bot entry point with Twitter integration
notebooks/01_generate_journal.ipynb   # Interactive development workflow
```

### Core Services
```
src/
├── 📊 Data Collection Layer
│   ├── data_collector.py             # Primary data ingestion: SnapTrade + yfinance + dual DB persistence
│   ├── snaptrade_collector.py        # Dedicated SnapTrade ETL with enhanced field extraction
│   ├── market_data.py                # Market data utilities and price fetching
│   └── twitter_analysis.py           # Twitter/X integration and sentiment analysis
│
├── 💾 Database Management  
│   ├── db.py                         # Advanced SQLAlchemy engine: get_connection() → PostgreSQL with pooling
│   └── config.py                     # Unified configuration: Pydantic settings with field mapping
│
├── 🧠 Processing Engine
│   ├── journal_generator.py          # LLM orchestration: prompt engineering, API calls, dual output formats
│   ├── message_cleaner.py            # Text processing & robust ticker symbol extraction
│   ├── position_analysis.py          # Advanced position tracking and analytics
│   └── chart_enhancements.py         # Enhanced charting with position overlays
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
├── 000_baseline.sql                  # SSOT baseline schema with 18 confirmed tables
├── 015-026_*.sql                     # Core migrations (RLS, timestamps, cleanup, Twitter)
├── 027_institutional_holdings.sql    # Institutional holdings table
├── 028_add_raw_symbol_to_positions.sql # Raw symbol column
├── 029_fix_account_balances_pk.sql   # Account balances PK fix
├── 030-038_*.sql                     # Discord chunks, stock mentions, LLM tagging columns
├── 039_add_parse_status_to_discord_messages.sql # NLP parse status tracking
├── 040_create_discord_parsed_ideas.sql # Core NLP parsed ideas table
├── 041_fix_parsed_ideas_message_id_type.sql # Fix message_id type to bigint
└── 042_add_chunk_indexing_columns.sql # Add soft_chunk_index, local_idea_index, unique constraint

scripts/
├── bootstrap.py                      # Comprehensive database setup and migration
├── deploy_database.py                # Unified database deployment system
├── schema_parser.py                  # Schema parsing and dataclass generation
├── verify_database.py                # Unified schema validation (24 tables, FKs, constraints)
└── nlp/                              # NLP processing scripts
    ├── parse_messages.py             # Live message parsing with OpenAI
    ├── build_batch.py                # Batch API request builder
    ├── run_batch.py                  # Submit batch jobs to OpenAI
    └── ingest_batch.py               # Ingest batch results to database
```

### Data Conventions
- **PostgreSQL-only**: All data persists to Supabase PostgreSQL with CSV backup for historical data
- **Database requirement**: PostgreSQL/Supabase connection required via `get_database_url()` (no SQLite fallback)
- **Symbol extraction**: Robust regex patterns for `$TICKER` format, handles complex API responses
- **Sentiment scoring**: TextBlob integration with numerical values (-1.0 to 1.0)

## ⚡ Essential Setup Commands

### 🚨 Step 1: Pre-Setup Validation (ALWAYS RUN FIRST)
```bash
# CRITICAL: Run this before any setup to validate deployment readiness
python validate_deployment.py

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
# - pgloader-based SQLite → PostgreSQL migration
# - Comprehensive health checks (DB, config, size)
# - Complete orchestration with cleanup
```

### 🔧 Step 3: Manual Environment Setup (If Bootstrap Fails)
```bash
# Complete development setup
python -m venv .venv
.venv\Scripts\Activate.ps1  # Windows PowerShell
pip install -r requirements.txt && pip install -e .

# Alternative: Use Makefile (if available)
make setup

# Environment configuration
cp .env.example .env  # Edit with your API keys
```

### 💾 Step 4: Database Setup
```bash
# Database initialization and migration
make init-db      # Create tables + enable RLS policies
make verify-migration  # Check migration status

# Manual database operations (if Makefile unavailable)
python scripts/deploy_database.py       # Deploy schema to Supabase PostgreSQL

# pgloader migration (requires pgloader installed)
# Bootstrap handles this automatically, but for manual:
# apt-get install pgloader (Ubuntu) or brew install pgloader (macOS)
```

## 🎯 Key Development Commands

### Journal Generation (Primary Use Case)
```bash
# Generate journal (auto-updates data)
python generate_journal.py --force
make journal  # Alternative via Makefile

# Custom output directory
python generate_journal.py --output custom/path

# Interactive workflow
# Use notebooks/01_generate_journal.ipynb
```

### Discord Bot (Real-time Data Collection)
```bash
# Run Discord bot for real-time data collection
python -m src.bot.bot
make bot  # Alternative via Makefile

# Bot requires DISCORD_BOT_TOKEN in .env
```

### Development Workflow
```bash
make test         # Run test suite
make lint         # Code linting
make clean        # Clean up temp files

# Manual testing
pytest tests/ --maxfail=1 --disable-warnings -v
python test_integration.py  # Comprehensive integration tests
```

## 🔧 Essential Environment Variables

Based on `.env.example`, configure these for full functionality:

### 🚨 Critical Dependencies (27+ packages)
```bash
# Core Data & Database (ESSENTIAL)
pandas>=2.3.1, sqlalchemy>=2.0.29, psycopg2-binary>=2.9.0
python-dotenv>=1.0.1, pydantic-settings>=2.2, pydantic==2.11.7

# Financial APIs (CORE FUNCTIONALITY)  
yfinance>=0.2.65, snaptrade-python-sdk>=11.0.98

# LLM APIs (JOURNAL GENERATION)
openai>=1.98.0, google-generativeai>=0.8.0, langchain>=0.3.27

# Social Media (SENTIMENT ANALYSIS)
discord.py>=2.5.2, tweepy>=4.14, textblob>=0.17

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

# LLM APIs (choose one)
GOOGLE_API_KEY=your_gemini_api_key      # Primary (free tier)
OPENAI_API_KEY=your_openai_key          # Fallback
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

### Key Tables (20+ confirmed)
```sql
-- SnapTrade Integration (5 core tables) 
accounts, account_balances, positions, orders, symbols

-- Market Data & Analytics
daily_prices, realtime_prices, stock_metrics

-- Discord/Social Integration
discord_messages, discord_market_clean, discord_trading_clean, discord_processing_log

-- NLP Parsed Ideas (NEW)
discord_parsed_ideas  -- Unique constraint: (message_id, soft_chunk_index, local_idea_index)

-- Twitter/X Integration  
twitter_data

-- System Configuration
processing_status, schema_migrations

-- Event Contracts & Institutional
event_contract_trades, event_contract_positions, institutional_holdings
```

### Schema Validation
```bash
# Verify database schema compliance
python scripts/verify_database.py --verbose

# Validate post-migration status
python scripts/validate_post_migration.py
```

### pgloader Migration System (Advanced)
The project includes automated pgloader-based migration:

```bash
# pgloader installation (required for automated migration)
# Ubuntu/Debian: apt-get install pgloader  
# macOS: brew install pgloader
# Windows: Use WSL or Docker

# Migration is handled automatically by bootstrap.py:
# 1. Detects existing SQLite database with data (>1KB)
# 2. Runs pgloader-based migration to PostgreSQL
# 3. Creates .migration_completed flag to prevent re-migration
# 4. Provides detailed migration verification

# Manual migration verification:
python -c "from pathlib import Path; print('Migration completed:', Path('.migration_completed').exists())"
```

## 🤖 LLM Integration Patterns

### Journal Generation Workflow
```python
# Entry point: generate_journal.py → src.journal_generator.main()
from src.journal_generator import main

# Force refresh all data and generate journal
result = main(force_update=True, output_dir=None)
```

### LLM API Integration
- **Primary**: Gemini API (free tier, high rate limits)
- **Fallback**: OpenAI API (paid, reliable)
- **Token limits**: Max 200 tokens for journal entries (~120 words)
- **Retry logic**: `@hardened_retry(max_retries=3, delay=2)` for API calls

### Prompt Engineering
```python
# Basic prompt builder
from src.journal_generator import create_journal_prompt

# Enhanced prompt with full context
from src.journal_generator import create_enhanced_journal_prompt

# Both functions expect: positions_df, messages_df, prices_df
```

## 🧪 Testing & Validation

### 🏥 Comprehensive Health Checks
```bash
# Pre-deployment validation (run first)
python validate_deployment.py

# Bootstrap validation (full system check)
python scripts/bootstrap.py

# Core integration test
python tests/test_integration.py

# Complete test suite  
pytest tests/ --maxfail=1 --disable-warnings -v
```

### 🔬 Unit Testing Framework
The project uses `unittest` with comprehensive test coverage:

```bash
# Test Structure:
tests/
├── test_integration.py      # Ticker extraction & import consolidation
├── test_core_functions.py   # Unit tests with edge cases
└── test_safe_response_handling.py  # Data handling validation

# Key Test Patterns:
python -m unittest tests.test_core_functions.TestTickerExtraction
python -m unittest tests.test_core_functions.TestMessageAppend  
python -m unittest tests.test_core_functions.TestPromptBuilder
```

### 🔍 Individual Module Testing
```bash
# Database connectivity
python -c "from src.db import execute_sql; print(execute_sql('SELECT COUNT(*) FROM positions', fetch_results=True))"

# Configuration validation
python -c "from src.config import settings; print(settings().model_dump())"

# Schema validation (validated all 24 tables including foreign keys and constraints)
python scripts/verify_database.py --verbose
```

### 📊 Health Monitoring & System Checks
```bash
# Database health and size monitoring
python -c "from src.db import healthcheck, get_database_size; print(f'Health: {healthcheck()}, Size: {get_database_size()}')"

# Migration status verification
python scripts/validate_post_migration.py

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
conn = get_connection()  # Should return SQLite connection
```

## 🔍 Symbol Extraction & Data Processing

### Ticker Symbol Pattern
- **Regex**: `r'\$[A-Z]{1,6}(?:\.[A-Z]+)?'` matches `$AAPL`, `$BRK.B`, handles 1-6 character symbols
- **SnapTrade parsing**: `extract_symbol_from_data()` walks nested dicts, handles "Unknown" symbols gracefully
- **Fallback hierarchy**: `raw_symbol` → `symbol` → `ticker` → short `id` values (no UUIDs)

### Data Processing Pipeline
1. **Collection**: `data_collector.py` fetches market data + SnapTrade positions
2. **Cleaning**: `message_cleaner.py` extracts tickers + sentiment from Discord messages
3. **Analysis**: `position_analysis.py` calculates portfolio metrics
4. **Output**: `journal_generator.py` creates LLM summaries in text + markdown formats

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

# Access database URL with fallback logic
from src.config import get_database_url
db_url = get_database_url()  # Returns PostgreSQL or SQLite URL
```

### Database Operations
```python
# Universal database interface (works with both PostgreSQL and SQLite)
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
1. **ALWAYS run `python validate_deployment.py` FIRST** - validates environment readiness
2. **Use `python scripts/bootstrap.py` for automated setup** - handles dependencies, environment, database, migration
3. **Virtual environment is REQUIRED** - bootstrap warns if not detected
4. **pgloader required for PostgreSQL migration** - install before running bootstrap
5. **Environment variables must be configured** - copy .env.example to .env with your keys

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
- **Database files**: `data/database/price_history.db` (SQLite)
- **Journal outputs**: `data/processed/` with timestamped filenames
- **Environment**: `.env` (git-ignored), `.env.example` (template)

### DEVELOPMENT WORKFLOW
1. Always run `python test_integration.py` after changes
2. Test ticker extraction with edge cases (numbers, special characters)  
3. Maintain dual output formats (text summary + detailed markdown)
4. Follow the retry pattern for external API calls
5. Handle missing `.env` variables gracefully

## 📚 Key Functions Reference

### Data Collection
```python
from src.data_collector import update_all_data, get_account_positions
from src.snaptrade_collector import SnapTradeCollector
from src.market_data import get_positions, get_recent_trades
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

### LLM Integration
```python
from src.journal_generator import generate_journal_entry, create_enhanced_journal_prompt, main
```

This guide provides everything needed for effective development on the LLM Portfolio Journal system. Follow these patterns and you'll be able to extend and maintain the codebase successfully!