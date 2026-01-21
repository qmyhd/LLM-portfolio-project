# LLM Portfolio Journal - Architecture Documentation

> **Last Updated:** January 20, 2026  
> **Database:** PostgreSQL (Supabase) - 20 active tables, RLS 100% compliant

## Overview

The LLM Portfolio Journal is a data-driven application integrating brokerage data, market information, social sentiment analysis, and OHLCV price history to power trading insights and analytics.

## System Architecture

### Core Components

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Data Sources  │    │  Processing     │    │    Output       │
│                 │    │   Engine        │    │   Generation    │
├─────────────────┤    ├─────────────────┤    ├─────────────────┤
│ • SnapTrade API │───▶│ • Data Collector│───▶│ • Discord Bot   │
│ • Discord Bot   │    │ • Message Clean │    │ • NLP Ideas     │
│ • Twitter API   │    │ • Sentiment     │    │ • Charts        │
│ • Databento     │    │ • Database ETL  │    │ • Analytics     │
└─────────────────┘    └─────────────────┘    └─────────────────┘
```

### Database Layer

**PostgreSQL-Only Database Architecture (SQLAlchemy 2.0 Compatible):**
- **PostgreSQL/Supabase**: Production database with real-time capabilities and connection pooling
- **Unified Interface**: All components use `execute_sql()` with named placeholders and dict parameters
- **No Fallback**: System requires PostgreSQL - no SQLite support
- **RLS Enabled**: All tables have Row Level Security enabled

**Key Tables (20 operational):**
- **SnapTrade Integration**: `accounts`, `account_balances`, `positions`, `orders`, `symbols`, `trade_history`
- **Discord/Social**: `discord_messages`, `discord_market_clean`, `discord_trading_clean`
- **NLP Pipeline**: `discord_parsed_ideas` (canonical table for parsed trading ideas)
- **Market Data**: `daily_prices`, `realtime_prices`, `stock_metrics`, `ohlcv_daily`
- **System**: `twitter_data`, `processing_status`, `schema_migrations`
- **Event Contracts**: `event_contract_trades`, `event_contract_positions`
- **Institutional**: `institutional_holdings`

**Dropped Legacy Tables (Migration 049):**
- `discord_message_chunks`, `discord_idea_units`, `stock_mentions`, `discord_processing_log`, `chart_metadata`

**Key Relationships:**
- `discord_parsed_ideas.message_id` → `discord_messages.message_id` (CASCADE delete)

### Module Structure

#### Data Collection (`src/`)
- **`data_collector.py`**: General market data collection, yfinance integration
- **`snaptrade_collector.py`**: SnapTrade API integration with enhanced field extraction
- **`databento_collector.py`**: Databento OHLCV daily bars with RDS/S3/Supabase storage
- **`message_cleaner.py`**: Discord message cleaning with ticker extraction, sentiment analysis
- **`channel_processor.py`**: Production wrapper that fetches → cleans → writes to discord tables
- **`twitter_analysis.py`**: Twitter/X sentiment analysis and data extraction

#### Database Management (`src/`)
- **`db.py`**: Enhanced SQLAlchemy 2.0 engine with unified execute_sql(), connection pooling
- **`market_data.py`**: Consolidated portfolio and trade data queries

#### Bot Infrastructure (`src/bot/`)
- **`bot.py`**: Discord bot entry point with Twitter client integration
- **`events.py`**: Message event handlers and channel filtering
- **`help.py`**: Custom help command with interactive dropdown categories
- **`commands/`**: Modular command structure:
  - `chart.py`: Advanced charting with FIFO position tracking
  - `history.py`: Message history fetching with deduplication
  - `process.py`: Channel data processing and statistics
  - `snaptrade_cmd.py`: Portfolio, orders, movers, and brokerage status
  - `twitter_cmd.py`: Twitter data analysis commands
  - `eod.py`: End-of-day stock data queries
- **`ui/`**: Centralized UI design system with embeds and pagination

#### NLP Pipeline (`src/nlp/`)
- **`openai_parser.py`**: LLM-based semantic parsing with OpenAI structured outputs
- **`schemas.py`**: Pydantic schemas for structured outputs (ParsedIdea, MessageParseResult)
- **`soft_splitter.py`**: Deterministic message splitting for long content
- **`preclean.py`**: Text preprocessing, alias mapping, reserved word blocklist

#### NLP Scripts (`scripts/nlp/`)
- **`parse_messages.py`**: Live message parsing with OpenAI
- **`build_batch.py`**: Batch API request builder
- **`run_batch.py`**: Submit batch jobs to OpenAI
- **`ingest_batch.py`**: Ingest batch results to database
- **`batch_backfill.py`**: Unified orchestrator for batch pipeline

#### OHLCV Data Pipeline
- **`src/databento_collector.py`**: Databento Historical API integration
  - Dataset routing: EQUS.MINI (pre-2024-07-01), EQUS.SUMMARY (current)
  - Storage: RDS (1-year rolling), S3 (Parquet archive), Supabase (optional)
- **`scripts/backfill_ohlcv.py`**: CLI for EC2 backfills

### Operational Tooling (`scripts/`)
- **`bootstrap.py`**: Application bootstrap with dependency management
- **`deploy_database.py`**: Database deployment and schema application
- **`verify_database.py`**: Comprehensive schema verification
- **`schema_parser.py`**: Generate expected_schemas.py from SQL DDL
- **`check_system_status.py`**: Quick health check for DB and APIs
- **`backfill_ohlcv.py`**: Databento OHLCV backfill CLI

## Data Flow

### Primary Data Pipeline

```
1. Data Ingestion
   ├─ SnapTrade API → Positions/Orders/Accounts
   ├─ Discord Bot → Message Stream → Ticker Extraction
   ├─ Twitter API → Tweet Analysis → Sentiment Scoring
   ├─ Databento → OHLCV Daily Bars → RDS/S3/Supabase
   └─ yfinance → Market Data → Price History

2. Data Processing
   ├─ Symbol Extraction → Ticker Normalization
   ├─ Sentiment Analysis → TextBlob Processing
   ├─ NLP Parsing → OpenAI Structured Outputs
   └─ Deduplication → Database Upserts

3. Data Storage
   ├─ PostgreSQL (Supabase) → Real-time Writes
   ├─ RDS PostgreSQL → OHLCV rolling 1-year
   └─ S3 → Parquet archive

4. Outputs
   ├─ Discord Bot → Interactive commands and charts
   └─ NLP Ideas → discord_parsed_ideas for search/filtering
```

## Key Design Patterns

### Error Handling Strategy
- **Graceful Degradation**: Services continue when dependencies fail
- **Retry Mechanisms**: Exponential backoff with circuit breaker patterns
- **Connection Pooling**: Automatic retry and connection management

### Database Patterns
- **PostgreSQL-Only**: No SQLite fallback - Supabase required
- **Connection Pooling**: SQLAlchemy 2.0 with health checks
- **Schema Management**: Automated validation via verify_database.py

## Schema Management

### Single Source of Truth

```
SQL DDL (schema/*.sql) → schema_parser.py → expected_schemas.py → verify_database.py
```

**Source Files**: 
- `schema/000_baseline.sql` - Complete baseline schema
- `schema/015-050_*.sql` - Incremental migrations (37 files total)

### Migration Workflow

1. Create migration file: `schema/051_*.sql`
2. Deploy: `python scripts/deploy_database.py`
3. Regenerate: `python scripts/schema_parser.py --output expected`
4. Verify: `python scripts/verify_database.py --mode comprehensive`

## Discord Bot System

### Data Flow

```
Discord Messages → discord_messages (raw)
                 ↓
         message_cleaner.py (extract tickers, sentiment)
                 ↓
discord_market_clean OR discord_trading_clean (processed)
                 ↓
         NLP Pipeline (openai_parser.py)
                 ↓
         discord_parsed_ideas (structured ideas)
```

### Table Mapping

| Table | Purpose |
|-------|---------|
| `discord_messages` | Raw Discord messages |
| `discord_market_clean` | General market messages |
| `discord_trading_clean` | Trading-specific messages |
| `discord_parsed_ideas` | LLM-extracted trading ideas |
| `processing_status` | Processing status tracking |

## NLP Parsing

### Ticker Accuracy System

**Pipeline Flow:**
```
Message → preclean.py (extract_candidate_tickers) → LLM → validate_llm_tickers → Final Ideas
```

**RESERVED_SIGNAL_WORDS** (80+ terms) prevent false positives:
- Price targets: `tgt`, `pt`, `tp`, `target`
- Levels: `support`, `resistance`, `pivot`
- Actions: `buy`, `sell`, `hold`, `trim`

### Batch Pipeline

Cost-effective parsing using OpenAI Batch API (50% discount):

```bash
python scripts/nlp/batch_backfill.py --limit 500
```

## Extension Points

- **Modular Commands**: New Discord bot commands via plugin pattern
- **Data Sources**: Additional APIs through collector pattern
- **Processing Modules**: New analysis types via modular engine
