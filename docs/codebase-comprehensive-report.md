# LLM Portfolio Journal - Comprehensive Codebase Report

> **Generated:** January 23, 2026  
> **Scope:** Complete file-by-file analysis of the entire repository  
> **Database:** PostgreSQL/Supabase with 20 active tables  
> **Python Version:** 3.11+

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Directory Structure](#2-directory-structure)
3. [Core Source Files (src/)](#3-core-source-files-src)
4. [NLP Pipeline (src/nlp/)](#4-nlp-pipeline-srcnlp)
5. [Discord Bot Infrastructure (src/bot/)](#5-discord-bot-infrastructure-srcbot)
6. [Scripts (scripts/)](#6-scripts-scripts)
7. [Database Schema (schema/)](#7-database-schema-schema)
8. [Tests (tests/)](#8-tests-tests)
9. [Database Tables & Interactions](#9-database-tables--interactions)
10. [External API Integrations](#10-external-api-integrations)
11. [AWS Services Integration](#11-aws-services-integration)
12. [Data Flow Architecture](#12-data-flow-architecture)
13. [Configuration Files](#13-configuration-files)

---

## 1. Project Overview

The **LLM Portfolio Journal** is a sophisticated data-driven portfolio analytics system that integrates:

- **Brokerage Data**: SnapTrade API for real-time positions, orders, and account balances
- **Social Sentiment**: Discord bot for real-time message collection and Twitter/X API integration
- **Market Data**: yfinance for stock prices, Databento for OHLCV historical data
- **NLP Intelligence**: OpenAI structured outputs for semantic parsing of trading messages
- **Visualization**: Advanced charting with mplfinance and interactive Discord embeds

### Key Technologies

| Component | Technology |
|-----------|------------|
| Language | Python 3.11+ |
| Database | PostgreSQL (Supabase) with SQLAlchemy 2.0 |
| Configuration | Pydantic Settings |
| Discord | discord.py |
| NLP | OpenAI API (Responses API with structured outputs) |
| Market Data | yfinance, Databento |
| Cloud | AWS (RDS, S3, EC2) |

---

## 2. Directory Structure

```
llm-portfolio/
├── .github/                    # GitHub configuration
│   ├── agents/                 # AI coding agent instructions
│   └── copilot-instructions.md # Copilot guidelines
├── batch_output/               # OpenAI Batch API output files
├── charts/                     # Generated chart images
├── data/
│   ├── database/              # Local SQLite backups (legacy)
│   ├── models/                # ML model artifacts
│   ├── processed/             # Processed data files
│   ├── raw/                   # Raw data files (CSV, Parquet)
│   ├── Robinhood_official_Reports/  # Brokerage reports
│   └── testing/               # Test data fixtures
├── docker/                     # Docker configuration
│   └── discord-bot.service    # Systemd service file
├── docs/                       # Documentation
├── schema/                     # SQL migration files (000-050)
├── scripts/                    # Operational scripts
│   ├── nlp/                   # NLP processing scripts
│   └── testing/               # Test utilities
├── src/                        # Main source code
│   ├── bot/                   # Discord bot
│   │   ├── commands/          # Bot commands
│   │   ├── formatting/        # Output formatting
│   │   └── ui/                # UI components
│   ├── etl/                   # ETL utilities
│   └── nlp/                   # NLP pipeline
├── tests/                      # Test suite
│   └── fixtures/              # Test fixtures
└── tmp/                        # Temporary files
```

---

## 3. Core Source Files (src/)

### 3.1 Database Layer

#### `src/db.py` (1,051 lines)
**Purpose:** Advanced SQLAlchemy 2.0 engine with connection pooling and resilience

**Main Components:**
- `get_sync_engine()`: Creates synchronous engine with connection pooling
- `get_async_engine()`: Creates async engine for async operations
- `execute_sql(query, params, fetch_results)`: Universal query execution
- `get_connection()`: Context manager for database connections
- `transaction`: Context manager for atomic transactions with advisory locks
- `save_parsed_ideas_atomic()`: Atomic helper for NLP idea storage
- `healthcheck()`: Database connectivity validation
- `test_connection()`: Detailed connection info retrieval

**Key Features:**
- Automatic Supabase pooler detection (port 6543)
- Statement timeout: 30s, Lock timeout: 10s
- Connection pool: size=5, max_overflow=2
- Pool pre-ping for connection validation

**Interacts With:**
- Supabase PostgreSQL (all 20 tables)
- Environment variables via `src/config.py`

---

#### `src/config.py` (200 lines)
**Purpose:** Centralized Pydantic-based settings management

**Main Components:**
- `_Settings` class: Pydantic BaseSettings with all environment variables
- `settings()`: Cached singleton returning settings object
- `get_database_url(use_direct)`: Returns PostgreSQL connection URL
- `get_migration_database_url()`: Optimized URL for migrations

**Configuration Categories:**
| Category | Variables |
|----------|-----------|
| Database | DATABASE_URL, DATABASE_DIRECT_URL |
| Supabase | SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, SUPABASE_ANON_KEY |
| Discord | DISCORD_BOT_TOKEN, LOG_CHANNEL_IDS |
| Twitter | TWITTER_BEARER_TOKEN, TWITTER_API_KEY |
| LLM | OPENAI_API_KEY, GEMINI_API_KEY |
| SnapTrade | SNAPTRADE_CLIENT_ID, SNAPTRADE_USER_ID |

---

### 3.2 Data Collection Layer

#### `src/data_collector.py` (1,266 lines)
**Purpose:** Market data collection with yfinance integration

**Main Components:**
- `rate_limit_delay()`: Enforces ~60 requests/minute for Yahoo Finance
- `exponential_backoff_retry()`: Decorator for API failure handling
- `validate_period_interval()`: Validates yfinance period/interval combos
- `get_cached_price()`: Falls back to database when API fails
- `fetch_realtime_prices()`: Batch downloads current prices
- `update_position_prices()`: Updates positions table with current prices
- `append_discord_message_to_csv()`: Legacy CSV logging

**Interacts With:**
- **APIs:** yfinance
- **Tables:** realtime_prices, daily_prices, positions

---

#### `src/snaptrade_collector.py` (1,252 lines)
**Purpose:** SnapTrade API ETL with enhanced field extraction

**Main Components:**
- `SnapTradeCollector` class: Main collector with all operations
- `safely_extract_response_data()`: Handles nested API responses
- `extract_symbol_from_data()`: Extracts ticker from complex payloads
- `get_accounts()`, `get_positions()`, `get_orders()`: Data fetchers
- `get_balances()`: Account balance retrieval
- `write_to_database()`: Upsert data to Supabase
- `collect_all_data()`: Full ETL orchestration

**Interacts With:**
- **APIs:** SnapTrade API (via snaptrade-python-sdk)
- **Tables:** accounts, positions, orders, account_balances, symbols

---

#### `src/databento_collector.py` (720 lines)
**Purpose:** OHLCV daily bars from Databento Historical API

**Main Components:**
- `DatabentoCollector` class: Main collector
- `get_portfolio_symbols()`: Gets symbols from positions table
- `_select_dataset()`: Routes to EQUS.MINI (pre-July 2024) or EQUS.SUMMARY
- `_fetch_segment()`: Fetches data for date range segment
- `save_to_rds()`: Saves to AWS RDS PostgreSQL
- `save_to_s3()`: Archives to S3 as Parquet
- `sync_to_supabase()`: Optional Supabase sync
- `prune_rds_data()`: Removes data older than 1 year

**Dataset Cutoff:** July 1, 2024
- Before: EQUS.MINI
- After: EQUS.SUMMARY

**Interacts With:**
- **APIs:** Databento Historical API
- **AWS:** RDS PostgreSQL, S3 bucket (qqq-llm-raw-history)
- **Tables:** ohlcv_daily (Supabase), RDS ohlcv_daily

---

#### `src/twitter_analysis.py` (1,288 lines)
**Purpose:** Twitter/X integration and sentiment analysis

**Main Components:**
- `get_twitter_client()`: Creates tweepy.Client with bearer token
- `is_rate_limited()`: Checks rate limit status (Free tier: 1/15min)
- `detect_twitter_links()`: Regex extraction of tweet URLs
- `fetch_tweet_data()`: Fetches tweet with media attachments
- `analyze_sentiment()`: TextBlob sentiment analysis (-1.0 to 1.0)
- `log_tweet_to_database()`: Persists tweet data

**Interacts With:**
- **APIs:** Twitter API v2 (via tweepy)
- **Tables:** twitter_data

---

#### `src/message_cleaner.py` (1,201 lines)
**Purpose:** Discord message cleaning with ticker extraction

**Main Components:**
- `CHANNEL_TYPE_TO_TABLE`: Maps channel types to database tables
- `extract_ticker_symbols()`: Regex for $TICKER format (1-6 chars, supports .B suffix)
- `extract_unprefixed_tickers()`: Detects AAPL without $ in trading context
- `calculate_sentiment()`: TextBlob integration
- `clean_text()`: Text normalization
- `process_messages_for_channel()`: Full cleaning pipeline
- `deduplicate_messages()`: Message deduplication

**Pattern:** `r"\$[A-Z]{1,6}(?:\.[A-Z]+)?"`

**Interacts With:**
- **Tables:** discord_trading_clean, discord_market_clean

---

#### `src/channel_processor.py` (445 lines)
**Purpose:** Channel processing orchestrator with LLM integration

**Main Components:**
- `process_channel_data()`: Resumable processing pipeline
- `parse_messages_with_llm()`: OpenAI NLP parsing
- `get_unprocessed_messages()`: Queries pending messages

**Pipeline:**
1. Query messages without `processed_for_cleaning` flag
2. Process through cleaning pipeline
3. Mark as processed (never deletes raw messages)

**Interacts With:**
- **Tables:** discord_messages, processing_status, discord_parsed_ideas

---

### 3.3 Utility Modules

#### `src/retry_utils.py` (327 lines)
**Purpose:** Hardened retry decorators preventing infinite loops

**Main Components:**
- `hardened_retry()`: General retry with non-retryable exception filtering
- `database_retry()`: Specialized for database operations
- `NON_RETRYABLE_EXCEPTIONS`: ValueError, TypeError, KeyError, AttributeError, SQLAlchemy errors

**Usage:**
```python
@hardened_retry(max_retries=3, delay=1)
def api_call(): pass

@database_retry(max_retries=3)
def db_operation(): pass
```

---

#### `src/logging_utils.py` (185 lines)
**Purpose:** Message logging to database

**Main Components:**
- `log_message_to_database()`: Persists Discord messages
- ON CONFLICT handling for deduplication
- Captures attachments as JSON
- Processes Twitter links separately

**Interacts With:**
- **Tables:** discord_messages, twitter_data

---

#### `src/position_analysis.py` (362 lines)
**Purpose:** Enhanced position tracking for charts

**Main Components:**
- `analyze_position_history()`: Comprehensive position analysis
- `get_current_position_size()`: Current position from database
- `get_current_price()`: Current price from realtime_prices
- `create_enhanced_chart_annotations()`: Chart overlays
- `generate_position_report()`: Position summary

**Interacts With:**
- **Tables:** positions, orders, realtime_prices

---

#### `src/market_data.py` (150 lines)
**Purpose:** Market data queries

**Main Components:**
- `get_recent_executed_orders()`: Recent EXECUTED orders
- `get_executed_orders_for_symbol()`: Symbol-specific orders
- `get_portfolio_summary()`: Total equity, position count

**Interacts With:**
- **Tables:** orders, positions

---

#### `src/expected_schemas.py` (402 lines)
**Purpose:** Generated schema definitions for validation

**Generated From:** schema_parser.py from SQL DDL files

**Contains:** EXPECTED_SCHEMAS dict with all 20 table definitions including:
- Required fields with types
- Primary keys
- Table descriptions

---

---

## 4. NLP Pipeline (src/nlp/)

### 4.1 `src/nlp/openai_parser.py` (1,719 lines)
**Purpose:** LLM-based semantic parsing with OpenAI structured outputs

**Model Routing:**
| Model | Purpose | Default |
|-------|---------|---------|
| MODEL_TRIAGE | Quick classification | gpt-5-mini |
| MODEL_MAIN | Primary parsing | gpt-5.1 |
| MODEL_ESCALATION | Complex cases | gpt-5.1 |
| MODEL_LONG | Long context (>2000 chars) | gpt-5.1 |
| MODEL_SUMMARY | Summaries | gpt-5-mini |

**Main Components:**
- `CallStats`: Tracks API calls per message
- `_extract_parsed_result()`: Safely extracts from Response object
- `process_message()`: Full parsing pipeline
- `triage_message()`: Quick noise detection
- `parse_chunk()`: Single chunk parsing
- `estimate_cost()`: Token cost estimation

**Thresholds (env-configurable):**
- LONG_CONTEXT_THRESHOLD: 2000 chars / 500 tokens
- ESCALATION_THRESHOLD: 0.8 confidence
- SYMBOL_DENSITY_THRESHOLD: 10 tickers

**Interacts With:**
- **APIs:** OpenAI API (Responses API)
- **Tables:** discord_parsed_ideas, discord_messages

---

### 4.2 `src/nlp/schemas.py` (396 lines)
**Purpose:** Pydantic schemas for structured outputs

**Enums:**
- `ParseStatus`: pending, ok, noise, error, skipped
- `InstrumentType`: equity, option, crypto, index, sector, event_contract
- `Direction`: bullish, bearish, neutral, mixed
- `Action`: buy, sell, trim, add, watch, hold, short, hedge, none
- `TimeHorizon`: scalp, swing, long_term, unknown
- `LevelKind`: entry, target, support, resistance, stop
- `OptionType`: call, put

**Trading Labels (13 categories):**
1. TRADE_EXECUTION
2. TRADE_PLAN
3. TECHNICAL_ANALYSIS
4. FUNDAMENTAL_THESIS
5. CATALYST_NEWS
6. EARNINGS
7. INSTITUTIONAL_FLOW
8. OPTIONS
9. RISK_MANAGEMENT
10. SENTIMENT_CONVICTION
11. PORTFOLIO_UPDATE
12. QUESTION_REQUEST
13. RESOURCE_LINK

**Models:**
- `Level`: Price level with value/range/qualifier
- `ParsedIdea`: Single semantic idea unit
- `MessageParseResult`: Full message parse result
- `TriageResult`: Quick classification result

---

### 4.3 `src/nlp/preclean.py` (1,404 lines)
**Purpose:** Text preprocessing and ticker accuracy

**Main Components:**
- `ALIAS_MAP`: ~100 company name → ticker mappings
- `RESERVED_SIGNAL_WORDS`: 80+ trading terms (tgt, pt, support, etc.)
- `extract_candidate_tickers()`: Pre-LLM ticker extraction
- `validate_llm_tickers()`: Post-validate LLM output
- `is_reserved_signal_word()`: Check if word is trading terminology
- `is_bot_command()`: Detect bot commands (!help, !!chart)
- `is_url_only()`: Detect URL-only messages
- `normalize_text()`: Text normalization

**ALIAS_MAP Examples:**
```python
"google": "GOOGL", "tesla": "TSLA", "nvidia": "NVDA",
"target corp": "TGT", "bitcoin": "BTC", "spy": "SPY"
```

**RESERVED_SIGNAL_WORDS Examples:**
```python
"tgt", "pt", "tp", "sl", "be", "target", "support",
"resistance", "buy", "sell", "calls", "puts"
```

---

### 4.4 `src/nlp/soft_splitter.py` (483 lines)
**Purpose:** Deterministic pre-split before LLM parsing

**Thresholds:**
- SHORT_MESSAGE_THRESHOLD: 2500 chars (send as-is)
- LONG_CHUNK_THRESHOLD: 3000 chars (consider splitting)
- MAX_CHUNK_SIZE: 4000 chars (hard limit)
- MIN_CHUNK_SIZE: 200 chars (consolidate tiny chunks)

**Main Components:**
- `SoftChunk`: Dataclass for split chunks
- `extract_tickers()`: Ticker extraction from text
- `split_by_sections()`: Split at blank lines, headers, bullets
- `split_by_ticker_blocks()`: Split at ticker transitions
- `soft_split_message()`: Main splitting function

---

---

## 5. Discord Bot Infrastructure (src/bot/)

### 5.1 `src/bot/__init__.py` (30 lines)
**Purpose:** Bot factory function

**Main Component:**
- `create_bot()`: Creates Discord bot with intents, help, commands, events

---

### 5.2 `src/bot/bot.py` (40 lines)
**Purpose:** Discord bot entry point

**Flow:**
1. Load environment via dotenv
2. Create Twitter client (optional)
3. Create bot via `create_bot()`
4. Run bot with token

---

### 5.3 `src/bot/events.py` (50 lines)
**Purpose:** Event handlers

**Events:**
- `on_ready`: Bot startup logging
- `on_message`: Message processing with channel filtering

**Filtering:**
- Skips bot's own messages
- Skips other bots' messages
- Only logs from LOG_CHANNEL_IDS

---

### 5.4 `src/bot/help.py`
**Purpose:** Interactive help with dropdown categories

---

### 5.5 Commands (src/bot/commands/)

#### `chart.py` (1,050 lines)
**Purpose:** Advanced charting with FIFO position tracking

**Features:**
- `FIFOPositionTracker`: Realized P/L calculation
- Discord dark theme styling
- Moving averages by period
- Volume pane for 1y+ periods
- Position annotation overlays

**Command:** `!chart SYMBOL [period] [style]`

**Interacts With:**
- **APIs:** yfinance
- **Tables:** orders, positions

---

#### `snaptrade_cmd.py` (1,146 lines)
**Purpose:** Portfolio and brokerage commands

**Commands:**
- `!fetch [type]`: Sync brokerage data
- `!portfolio [filter] [limit]`: Interactive portfolio view
- `!orders [limit]`: Show recent orders
- `!movers`: Top gainers/losers

**Interacts With:**
- **APIs:** SnapTrade
- **Tables:** accounts, positions, orders, account_balances

---

#### `history.py` (100 lines)
**Purpose:** Message history fetching

**Command:** `!history [limit]`

**Features:**
- Rate limiting (429 handling)
- Deduplication check
- Batch processing with delays

**Interacts With:**
- **APIs:** Discord API
- **Tables:** discord_messages

---

#### `process.py` (531 lines)
**Purpose:** Channel data processing

**Commands:**
- `!process [channel_type]`: Process latest 50 messages
- `!backfill [channel_type]`: Full historical backfill
- `!stats`: Channel statistics
- `!peekraw [limit]`: Debug raw message JSON

**Interacts With:**
- **Tables:** discord_messages, discord_*_clean, processing_status

---

#### `twitter_cmd.py` (531 lines)
**Purpose:** Twitter data analysis

**Command:** `!twitter [SYMBOL]`

**Interacts With:**
- **Tables:** twitter_data

---

#### `eod.py` (100 lines)
**Purpose:** End-of-day stock data lookup

**Command:** `!EOD` (interactive)

**Interacts With:**
- **APIs:** yfinance

---

### 5.6 UI Components (src/bot/ui/)

#### `embed_factory.py` (500 lines)
**Purpose:** Centralized embed builder

**Components:**
- `EmbedCategory`: Enum with colors and emojis
- `EmbedFactory`: Static methods for embed creation
- `format_money()`, `format_pnl()`, `format_percent()`
- `render_table()`: Markdown table generation

---

#### `portfolio_view.py` (421 lines)
**Purpose:** Interactive portfolio display

**Features:**
- Page navigation (prev/next)
- Filter buttons (All/Winners/Losers)
- P/L display toggle ($/%)
- Refresh button

---

#### `logo_helper.py` (562 lines)
**Purpose:** Company logo fetching with caching

**Providers:**
1. Logo.dev API (primary)
2. Logokit API (fallback)
3. Database cache (symbols.logo_url)

**Cache:** TTL-based in-memory (default 24 hours)

**Interacts With:**
- **APIs:** Logo.dev, Logokit
- **Tables:** symbols

---

#### `symbol_resolver.py` (249 lines)
**Purpose:** Company name → ticker resolution

**Sources:**
1. ALIAS_MAP from preclean.py
2. Database symbols table
3. Database positions table

---

---

## 6. Scripts (scripts/)

### 6.1 `scripts/bootstrap.py` (365 lines)
**Purpose:** Application bootstrap and initialization

**Steps:**
1. Install dependencies from requirements.txt
2. Load project modules
3. Load environment configuration
4. Test database connection
5. Check migration status
6. Run migrations if needed

---

### 6.2 `scripts/deploy_database.py` (617 lines)
**Purpose:** Unified database deployment

**Modes:**
- `deploy_full()`: Schema + policies + verification
- `deploy_schema_only()`: Schema files only
- `deploy_policies_only()`: RLS policies only

**Features:**
- Applies baseline schema (000_baseline.sql)
- Deploys all migrations (015-050)
- Configures RLS policies
- Verification step

---

### 6.3 `scripts/verify_database.py` (1,036 lines)
**Purpose:** Comprehensive schema verification

**Modes:**
- Basic: Table existence check
- Comprehensive: Columns, types, constraints
- Performance: Index verification

**Uses:** EXPECTED_SCHEMAS from expected_schemas.py

---

### 6.4 NLP Scripts (scripts/nlp/)

#### `parse_messages.py` (1,049 lines)
**Purpose:** Live message parsing with OpenAI

**Features:**
- Continuation detection (context-aware)
- Context window for related messages
- Dry-run mode
- Skip triage option

**Command:**
```bash
python scripts/nlp/parse_messages.py --limit 100
python scripts/nlp/parse_messages.py --message-id 123456789
python scripts/nlp/parse_messages.py --context-window 5 --context-minutes 30
```

---

#### `batch_backfill.py` (557 lines)
**Purpose:** Unified batch pipeline orchestrator

**Steps:**
1. Verify schema
2. Build batch file with prefilters
3. Upload and run batch job
4. Poll until complete
5. Download and ingest results
6. Post-run integrity checks

**Command:**
```bash
python scripts/nlp/batch_backfill.py --limit 500
python scripts/nlp/batch_backfill.py --dry-run --limit 20
```

---

#### `build_batch.py`
**Purpose:** Builds OpenAI Batch API request files

#### `run_batch.py`
**Purpose:** Submits batch jobs to OpenAI

#### `ingest_batch.py`
**Purpose:** Ingests batch results to database

---

### 6.5 `scripts/backfill_ohlcv.py` (265 lines)
**Purpose:** Databento OHLCV backfill CLI

**Modes:**
- `--full`: Full historical (2023-03-28 to yesterday)
- `--daily`: Last 5 days update
- `--prune`: Remove old RDS data

**Command:**
```bash
python scripts/backfill_ohlcv.py --daily
python scripts/backfill_ohlcv.py --full --supabase
python scripts/backfill_ohlcv.py --prune --keep-days 365
```

---

### 6.6 Other Scripts

| Script | Purpose |
|--------|---------|
| `check_system_status.py` | Quick health check for DB and APIs |
| `schema_parser.py` | Generate expected_schemas.py from SQL DDL |
| `validate_live_schema.sql` | SQL for live schema inspection |
| `daily_pipeline.py` | Daily data pipeline orchestration |
| `fetch_discord_history_improved.py` | Discord history with better error handling |
| `setup_ec2_services.sh` | EC2 systemd service setup |

---

---

## 7. Database Schema (schema/)

### 7.1 Migration Files (36 total)

| Migration | Purpose |
|-----------|---------|
| `000_baseline.sql` | SSOT baseline schema with 18+ tables |
| `015_primary_key_alignment.sql` | Primary key fixes |
| `016_complete_rls_policies.sql` | RLS policies for all tables |
| `017_timestamp_field_migration.sql` | timestamptz standardization |
| `018_cleanup_schema_drift.sql` | Schema drift cleanup |
| `019_data_quality_cleanup.sql` | Data quality fixes |
| `020_drop_positions_redundant_columns.sql` | Column cleanup |
| `021_fix_processing_status_composite_key.sql` | PK fix |
| `022_add_attachments_column.sql` | Discord attachments |
| `023_event_contract_tables.sql` | Event contracts |
| `024_account_balances_unique_constraint.sql` | Constraint fix |
| `025_drop_backup_tables.sql` | Backup table cleanup |
| `026_add_twitter_media_column.sql` | Twitter media |
| `027_institutional_holdings.sql` | 13F holdings table |
| `028_add_raw_symbol_to_positions.sql` | Raw symbol column |
| `029_fix_account_balances_pk.sql` | PK fix |
| `030_discord_message_chunks.sql` | Message chunks (dropped in 049) |
| `031_stock_mentions.sql` | Stock mentions (dropped in 049) |
| `032-038` | LLM tagging, gold labels, idea units |
| `039_add_parse_status_to_discord_messages.sql` | NLP status tracking |
| `040_create_discord_parsed_ideas.sql` | Core NLP ideas table |
| `041-048` | Indexing, FK constraints, cleanup |
| `049_drop_legacy_tables.sql` | Drops unused tables |
| `050_ohlcv_daily.sql` | OHLCV market data |

---

### 7.2 Key Table Definitions

#### Core SnapTrade Tables
```sql
accounts (id, name, institution_name, total_equity, sync_timestamp)
account_balances (account_id, currency_code, cash, buying_power, snapshot_date)
positions (symbol, account_id, quantity, price, equity, average_buy_price, open_pnl)
orders (brokerage_order_id, symbol, action, status, total_quantity, execution_price)
symbols (id, ticker, description, asset_type, exchange_code)
trade_history (trade_id, symbol, action, quantity, price, executed_at)
```

#### Discord/Social Tables
```sql
discord_messages (message_id, content, author, channel, parse_status, created_at)
discord_market_clean (message_id, content, sentiment, processed_at)
discord_trading_clean (message_id, content, sentiment, processed_at)
discord_parsed_ideas (id, message_id, idea_text, primary_symbol, labels, direction)
twitter_data (id, tweet_id, content, author, sentiment, media_urls)
```

#### Market Data Tables
```sql
daily_prices (symbol, date, open, high, low, close, volume)
realtime_prices (symbol, timestamp, price, previous_close, percent_change)
stock_metrics (symbol, date, pe_ratio, market_cap, ...)
ohlcv_daily (symbol, date, open, high, low, close, volume, source)
```

#### System Tables
```sql
processing_status (message_id, channel, operation, processed_at)
schema_migrations (version, applied_at)
```

---

---

## 8. Tests (tests/)

### Test Files

| File | Purpose | Lines |
|------|---------|-------|
| `test_integration.py` | Ticker extraction, import tests | 117 |
| `validate_deployment.py` | Deployment readiness validation | 329 |
| `test_core_functions.py` | Unit tests with edge cases | - |
| `test_openai_parser.py` | NLP parser tests | - |
| `test_nlp_batch.py` | Batch API tests | - |
| `test_preclean_codeblock.py` | Preclean function tests | - |
| `test_triage_regression.py` | Triage model tests | - |
| `test_parser_regression.py` | Parser regression tests | - |
| `test_databento_collector.py` | OHLCV collector tests | - |
| `test_orders_formatting.py` | Order display tests | - |

### Running Tests
```bash
pytest tests/ --maxfail=1 --disable-warnings -v
python tests/test_integration.py
python tests/validate_deployment.py
```

---

---

## 9. Database Tables & Interactions

### Complete Table Map (20 Active Tables)

```
┌─────────────────────────────────────────────────────────────────────┐
│                         SUPABASE DATABASE                          │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  SnapTrade Integration (6 tables)                                   │
│  ├── accounts ──────────────── Brokerage accounts                   │
│  ├── account_balances ──────── Cash & buying power                  │
│  ├── positions ─────────────── Current holdings                     │
│  ├── orders ────────────────── Trade orders                         │
│  ├── symbols ───────────────── Security master data                 │
│  └── trade_history ─────────── Executed trades                      │
│                                                                     │
│  Discord Integration (4 tables)                                     │
│  ├── discord_messages ──────── Raw Discord messages                 │
│  ├── discord_market_clean ──── Cleaned market messages              │
│  ├── discord_trading_clean ─── Cleaned trading messages             │
│  └── discord_parsed_ideas ──── LLM-extracted ideas                  │
│                                                                     │
│  Market Data (4 tables)                                             │
│  ├── daily_prices ──────────── Historical OHLCV                     │
│  ├── realtime_prices ───────── Current prices                       │
│  ├── stock_metrics ─────────── Fundamentals                         │
│  └── ohlcv_daily ───────────── Databento OHLCV                      │
│                                                                     │
│  Twitter Integration (1 table)                                      │
│  └── twitter_data ──────────── Tweet data & sentiment               │
│                                                                     │
│  Event Contracts (2 tables)                                         │
│  ├── event_contract_trades ─── Contract trades                      │
│  └── event_contract_positions  Contract positions                   │
│                                                                     │
│  Institutional (1 table)                                            │
│  └── institutional_holdings ── 13F filings                          │
│                                                                     │
│  System (2 tables)                                                  │
│  ├── processing_status ─────── Processing flags                     │
│  └── schema_migrations ─────── Migration history                    │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### Key Relationships

```
discord_messages
    │
    ├──► discord_market_clean (via message_id)
    ├──► discord_trading_clean (via message_id)
    ├──► discord_parsed_ideas (FK: message_id → CASCADE delete)
    └──► processing_status (via message_id, channel)

positions
    │
    └──► orders (via symbol, account_id)

symbols
    │
    └──► positions (via symbol)
```

---

---

## 10. External API Integrations

### 10.1 SnapTrade API
**Purpose:** Brokerage data integration
**SDK:** snaptrade-python-sdk
**Authentication:** Client ID + Consumer Key + User Secret
**Endpoints Used:**
- `/accounts` - Account info
- `/accounts/{id}/positions` - Holdings
- `/accounts/{id}/orders` - Trade orders
- `/accounts/{id}/balances` - Cash balances

**Rate Limits:** Per SnapTrade tier
**Tables Updated:** accounts, positions, orders, account_balances, symbols

---

### 10.2 OpenAI API
**Purpose:** NLP semantic parsing
**SDK:** openai
**API Type:** Responses API with structured outputs
**Models:**
- gpt-5-mini (triage, main parsing, summary)
- gpt-5.1 (long context, escalation)

**Features:**
- Structured outputs for guaranteed JSON compliance
- Batch API for 50% cost savings
- Model routing based on message complexity

**Tables Updated:** discord_parsed_ideas, discord_messages (parse_status)

---

### 10.3 yfinance API
**Purpose:** Market data
**SDK:** yfinance
**Data Types:**
- Real-time prices
- Historical OHLCV
- Company info

**Rate Limits:** ~60 requests/minute
**Tables Updated:** daily_prices, realtime_prices, stock_metrics

---

### 10.4 Databento API
**Purpose:** OHLCV historical data
**SDK:** databento
**Datasets:**
- EQUS.MINI (pre-July 2024)
- EQUS.SUMMARY (current)

**Schema:** ohlcv-1d (daily bars)
**Storage:**
- RDS PostgreSQL (1-year rolling)
- S3 Parquet archive
- Supabase (optional sync)

---

### 10.5 Twitter API v2
**Purpose:** Tweet data and sentiment
**SDK:** tweepy
**Tier:** Free (1 request per 15 minutes)
**Data:**
- Tweet content
- Media attachments
- Author info
- Engagement metrics

**Tables Updated:** twitter_data

---

### 10.6 Discord API
**Purpose:** Real-time message collection
**SDK:** discord.py
**Events:**
- on_message
- on_ready

**Features:**
- Channel filtering
- Rate limit handling
- History fetching

**Tables Updated:** discord_messages

---

### 10.7 Logo APIs
**Purpose:** Company logo fetching
**Providers:**
1. Logo.dev (primary)
2. Logokit (fallback)

**Caching:** 24-hour TTL in-memory + database

---

---

## 11. AWS Services Integration

### 11.1 AWS RDS (PostgreSQL)
**Purpose:** OHLCV data storage with 1-year rolling retention

**Configuration:**
```
Host: ohlcv-db.cq9kmkmaen5c.us-east-1.rds.amazonaws.com
Port: 5432
Database: ohlcv-db
User: postgres
```

**Table:** ohlcv_daily (same schema as Supabase)

**Operations:**
- Daily inserts from Databento
- Annual pruning (older than 365 days)

---

### 11.2 AWS S3
**Purpose:** Parquet archive for historical data

**Configuration:**
```
Bucket: qqq-llm-raw-history
Prefix: ohlcv/daily/
Region: us-east-1
```

**Format:** Parquet files partitioned by date

**Operations:**
- Write after each backfill
- No automatic deletion (archive)

---

### 11.3 AWS EC2
**Purpose:** Bot hosting and scheduled jobs

**Instance:** i-023255baa654f7cb1
**Region:** us-east-1

**Services:**
- Discord bot (systemd service)
- Daily OHLCV backfill (cron)
- NLP batch processing

**Setup Script:** `scripts/setup_ec2_services.sh`

---

---

## 12. Data Flow Architecture

### 12.1 Primary Data Pipeline

```
┌──────────────────────────────────────────────────────────────────────┐
│                         DATA INGESTION                               │
├──────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  SnapTrade API ──────► snaptrade_collector.py                        │
│       │                      │                                       │
│       ▼                      ▼                                       │
│  Positions, Orders ────► PostgreSQL (Supabase)                       │
│  Accounts, Balances         │                                        │
│                             ▼                                        │
│  Discord Bot ────────► events.py / logging_utils.py                  │
│       │                      │                                       │
│       ▼                      ▼                                       │
│  Messages ───────────► discord_messages table                        │
│                             │                                        │
│  Twitter API ────────► twitter_analysis.py                           │
│       │                      │                                       │
│       ▼                      ▼                                       │
│  Tweets ─────────────► twitter_data table                            │
│                                                                      │
│  Databento API ──────► databento_collector.py                        │
│       │                      │                                       │
│       ▼                      ▼                                       │
│  OHLCV Bars ─────────► RDS / S3 / Supabase                           │
│                                                                      │
│  yfinance API ───────► data_collector.py                             │
│       │                      │                                       │
│       ▼                      ▼                                       │
│  Prices, Metrics ────► daily_prices, realtime_prices                 │
│                                                                      │
└──────────────────────────────────────────────────────────────────────┘
```

### 12.2 NLP Processing Pipeline

```
┌──────────────────────────────────────────────────────────────────────┐
│                         NLP PIPELINE                                 │
├──────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  discord_messages (parse_status='pending')                           │
│           │                                                          │
│           ▼                                                          │
│  ┌─────────────────────────────────────────────────────────┐        │
│  │  PRECLEAN (preclean.py)                                 │        │
│  │  • is_bot_command() → skip                              │        │
│  │  • is_url_only() → skip                                 │        │
│  │  • normalize_text()                                     │        │
│  │  • extract_candidate_tickers()                          │        │
│  └─────────────────────────────────────────────────────────┘        │
│           │                                                          │
│           ▼                                                          │
│  ┌─────────────────────────────────────────────────────────┐        │
│  │  SOFT SPLIT (soft_splitter.py)                          │        │
│  │  • <2500 chars: send as-is                              │        │
│  │  • >2500 chars: split by sections/tickers               │        │
│  │  • >4000 chars: route to gpt-5.1                        │        │
│  └─────────────────────────────────────────────────────────┘        │
│           │                                                          │
│           ▼                                                          │
│  ┌─────────────────────────────────────────────────────────┐        │
│  │  TRIAGE (openai_parser.py)                              │        │
│  │  • Quick noise detection (gpt-5-mini)                   │        │
│  │  • Returns: tradable | noise | context_needed           │        │
│  └─────────────────────────────────────────────────────────┘        │
│           │                                                          │
│           ▼                                                          │
│  ┌─────────────────────────────────────────────────────────┐        │
│  │  MAIN PARSE (openai_parser.py)                          │        │
│  │  • Structured outputs → ParsedIdea[]                    │        │
│  │  • Labels, symbols, levels, direction                   │        │
│  │  • Escalation if confidence < 0.8                       │        │
│  └─────────────────────────────────────────────────────────┘        │
│           │                                                          │
│           ▼                                                          │
│  ┌─────────────────────────────────────────────────────────┐        │
│  │  POST-VALIDATION (preclean.py)                          │        │
│  │  • validate_llm_tickers() vs candidates                 │        │
│  │  • Filter reserved signal words                         │        │
│  └─────────────────────────────────────────────────────────┘        │
│           │                                                          │
│           ▼                                                          │
│  discord_parsed_ideas (status='ok')                                  │
│  discord_messages (parse_status='ok')                                │
│                                                                      │
└──────────────────────────────────────────────────────────────────────┘
```

### 12.3 Discord Bot Command Flow

```
┌──────────────────────────────────────────────────────────────────────┐
│                      DISCORD COMMAND FLOW                            │
├──────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  User Message ──► on_message() ──► Process Commands                  │
│       │                                 │                            │
│       ▼                                 ▼                            │
│  !chart AAPL ──────► chart.py                                        │
│       │                  │                                           │
│       │                  ├── yfinance (fetch data)                   │
│       │                  ├── mplfinance (generate chart)             │
│       │                  ├── positions table (overlay trades)        │
│       │                  └── Discord (send image)                    │
│       │                                                              │
│  !portfolio ───────► snaptrade_cmd.py                                │
│       │                  │                                           │
│       │                  ├── positions table (query)                 │
│       │                  ├── PortfolioView (interactive)             │
│       │                  └── Discord (send embed)                    │
│       │                                                              │
│  !process ─────────► process.py                                      │
│       │                  │                                           │
│       │                  ├── Discord API (fetch history)             │
│       │                  ├── discord_messages (insert)               │
│       │                  ├── message_cleaner (process)               │
│       │                  └── discord_*_clean (insert)                │
│       │                                                              │
│  !fetch ───────────► snaptrade_cmd.py                                │
│       │                  │                                           │
│       │                  ├── SnapTrade API (fetch)                   │
│       │                  └── All SnapTrade tables (upsert)           │
│                                                                      │
└──────────────────────────────────────────────────────────────────────┘
```

---

---

## 13. Configuration Files

### 13.1 `.env` (Environment Variables)

| Category | Variable | Purpose |
|----------|----------|---------|
| **Database** | DATABASE_URL | PostgreSQL pooler URL (port 6543) |
| | DATABASE_DIRECT_URL | Direct PostgreSQL URL (port 5432) |
| **Supabase** | SUPABASE_URL | Project REST API URL |
| | SUPABASE_SERVICE_ROLE_KEY | Bypass RLS (required) |
| | SUPABASE_ANON_KEY | Public key |
| **Discord** | DISCORD_BOT_TOKEN | Bot authentication |
| | LOG_CHANNEL_IDS | Comma-separated channel IDs |
| **Twitter** | TWITTER_BEARER_TOKEN | API v2 authentication |
| **OpenAI** | OPENAI_API_KEY | API authentication |
| | OPENAI_MODEL_TRIAGE | Triage model (gpt-5-mini) |
| | OPENAI_MODEL_MAIN | Main parsing model |
| **SnapTrade** | SNAPTRADE_CLIENT_ID | Client ID |
| | SNAPTRADE_USER_SECRET | User secret |
| | ROBINHOOD_ACCOUNT_ID | Account ID |
| **Databento** | DATABENTO_API_KEY | API authentication |
| **AWS** | AWS_ACCESS_KEY_ID | IAM credentials |
| | S3_BUCKET_NAME | S3 bucket |
| | RDS_HOST | RDS endpoint |

---

### 13.2 `pyproject.toml`

```toml
[project]
name = "llm-portfolio-journal"
version = "1.0.0"
requires-python = ">=3.11"

[project.scripts]
generate-journal = "src.journal_generator:main"
portfolio-bot = "src.bot.bot:main"
```

---

### 13.3 `requirements.txt` (Key Dependencies)

| Package | Version | Purpose |
|---------|---------|---------|
| pandas | >=2.3.1 | Data manipulation |
| sqlalchemy | >=2.0.29 | Database ORM |
| psycopg2-binary | >=2.9.0 | PostgreSQL driver |
| pydantic-settings | >=2.2 | Configuration |
| yfinance | >=0.2.65 | Market data |
| snaptrade-python-sdk | >=11.0.98 | Brokerage API |
| openai | >=1.98.0 | LLM API |
| discord.py | >=2.5.2 | Discord bot |
| tweepy | >=4.14 | Twitter API |
| textblob | >=0.17 | Sentiment analysis |
| mplfinance | ==0.12.10b0 | Financial charts |
| databento | latest | OHLCV data |
| boto3 | latest | AWS SDK |

---

---

## Summary

The LLM Portfolio Journal is a comprehensive, production-ready system with:

- **36 schema migrations** managing 20 active database tables
- **~25,000+ lines of Python code** across 50+ source files
- **8 external API integrations** (SnapTrade, OpenAI, yfinance, Databento, Discord, Twitter, Logo.dev, Logokit)
- **3 AWS services** (RDS, S3, EC2)
- **Modular architecture** with clear separation of concerns
- **Comprehensive test coverage** with regression and integration tests
- **Full documentation** including this report, AGENTS.md, and ARCHITECTURE.md

---

*Report generated by comprehensive codebase analysis on January 23, 2026*
