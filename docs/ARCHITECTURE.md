# LLM Portfolio Journal - Architecture Documentation

> **Last Updated:** March 1, 2026
> **Database:** PostgreSQL (Supabase) - 20 core tables, migrations 060-066, RLS 100% compliant

## Overview

The LLM Portfolio Journal is a data-driven application integrating brokerage data, market information, social sentiment analysis, and OHLCV price history to power trading insights and analytics.

## System Architecture

### Core Components

```text
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Data Sources  │    │  Processing     │    │    Output       │
│                 │    │   Engine        │    │   Generation    │
├─────────────────┤    ├─────────────────┤    ├─────────────────┤
│ • SnapTrade API │───▶│ • Price Service │───▶│ • Discord Bot   │
│ • Discord Bot   │    │ • Message Clean │    │ • NLP Ideas     │
│ • Twitter API   │    │ • Sentiment     │    │ • Charts        │
│ • Databento     │    │ • Database ETL  │    │ • Analytics     │
│ • OpenBB (FMP)  │    │ • OpenBB Cache  │    │ • Fundamentals  │
│ • OpenBB (SEC)  │    │ • Ideas Refine  │    │ • Filings/News  │
└─────────────────┘    │ • Discord Ingest│    │ • Ideas Journal │
                       └─────────────────┘    └─────────────────┘
```

### Database Layer

**PostgreSQL-Only Database Architecture (SQLAlchemy 2.0 Compatible):**
- **PostgreSQL/Supabase**: Single production database with real-time capabilities and connection pooling
- **Unified Interface**: All components use `execute_sql()` with named placeholders and dict parameters
- **No Fallback**: System requires PostgreSQL - no SQLite support
- **RLS Enabled**: All tables have Row Level Security enabled

**Key Tables (20 Core in Supabase):**
- **SnapTrade Integration**: `accounts` (with `bucket` strategy classification, migration 069), `account_balances`, `positions`, `orders`, `symbols`, `activities`
- **Discord/Social**: `discord_messages`, `discord_market_clean`, `discord_trading_clean`, `discord_parsed_ideas`
- **Ideas Journal**: `user_ideas` (unified ideas from Discord, manual entry, and transcription)
- **Discord Ingestion**: `discord_ingest_cursors` (incremental ingestion high-water marks)
- **Symbol Management**: `symbol_aliases` (ticker variants for resolution)
- **Market Data**: `ohlcv_daily` (Databento OHLCV source)
- **Stock Analytics**: `stock_profile_current`, `stock_profile_history` (derived metrics)
- **OpenBB / Notes**: `stock_notes` (user annotations per ticker)
- **System**: `twitter_data`, `processing_status`, `schema_migrations`, `institutional_holdings`

**Dropped Legacy Tables (Migrations 049-054):**
- `discord_message_chunks`, `discord_idea_units`, `stock_mentions`, `discord_processing_log`, `chart_metadata`
- `daily_prices`, `realtime_prices`, `stock_metrics` (replaced by `ohlcv_daily`)
- `event_contract_trades`, `event_contract_positions`, `trade_history` (no runtime usage)

**Key Relationships:**
- `discord_parsed_ideas.message_id` → `discord_messages.message_id` (CASCADE delete)
- `user_ideas.origin_message_id` → `discord_messages.message_id` (logical FK, partial unique on source+origin)

### Module Structure

#### Data Collection (`src/`)
- **`price_service.py`**: Centralized price data access (Supabase `ohlcv_daily`) - sole source for OHLCV data
- **`snaptrade_collector.py`**: SnapTrade API integration with enhanced field extraction
- **`databento_collector.py`**: Databento OHLCV daily bars → Supabase storage
- **`message_cleaner.py`**: Discord message cleaning with ticker extraction, sentiment analysis, alias upsert
- **`channel_processor.py`**: Production wrapper that fetches → cleans → writes to discord tables
- **`twitter_analysis.py`**: Twitter/X sentiment analysis and data extraction
- **`market_data_service.py`**: yfinance wrapper with TTL caching for real-time quotes, crypto identity mapping (`CRYPTO_IDENTITY`, `_CRYPTO_SYMBOLS`), and TradingView symbol resolution
- **`discord_ingest.py`**: Incremental Discord message ingestion with cursor-based tracking and content hash deduplication
- **`bucket.py`**: Strategy bucket utilities. Defines the `BucketName` enum (`long_term` / `swing` / `day` / `retirement` / `other`), `validate_bucket()` parser, `bucket_filter_sql(bucket, alias)` SQL-fragment builder, and the reusable `BucketQuery` FastAPI dependency. Every data endpoint accepts `?bucket=<name>` to scope positions/trades/risk to one strategy

#### OpenBB Fundamentals (`src/`)

- **`openbb_service.py`**: Cached service layer for the OpenBB Platform SDK (see [OpenBB Integration](#openbb-platform-integration) below)

#### Database Management (`src/`)

- **`db.py`**: Enhanced SQLAlchemy 2.0 engine with unified execute_sql(), connection pooling

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
  - Storage: Supabase `ohlcv_daily` table (unified storage)
- **`scripts/backfill_ohlcv.py`**: CLI for OHLCV backfills

### Operational Tooling (`scripts/`)
- **`bootstrap.py`**: Application bootstrap with dependency management
- **`deploy_database.py`**: Database deployment and schema application
- **`verify_database.py`**: Comprehensive schema verification
- **`schema_parser.py`**: Generate expected_schemas.py from SQL DDL
- **`check_system_status.py`**: Quick health check for DB and APIs
- **`backfill_ohlcv.py`**: Databento OHLCV backfill CLI

## Data Flow

### Primary Data Pipeline

```text
1. Data Ingestion
   ├─ SnapTrade API → Positions/Orders/Accounts
   ├─ Discord Bot → Message Stream → Ticker Extraction
   ├─ Twitter API → Tweet Analysis → Sentiment Scoring
   ├─ Databento → OHLCV Daily Bars → Supabase ohlcv_daily
   ├─ OpenBB SDK → Fundamentals/Filings/News/Transcripts (on-demand, cached)
   └─ Discord Incremental Ingest → cursor-based, deduped by content_hash

2. Data Processing
   ├─ Symbol Extraction → Ticker Normalization
   ├─ Sentiment Analysis → vaderSentiment Processing
   ├─ NLP Parsing → OpenAI Structured Outputs
   ├─ OpenBB TTL Caching → Thread-safe in-memory caches
   └─ Deduplication → Database Upserts

3. Data Storage
   └─ PostgreSQL (Supabase) → All data (unified)
       └─ stock_notes → User annotations per ticker

4. Outputs
   ├─ Discord Bot → Interactive commands and charts
   ├─ NLP Ideas → discord_parsed_ideas for search/filtering
   ├─ FastAPI → Next.js frontend (fundamentals, filings, news, notes)
   └─ Ideas API → CRUD + AI refine (user_ideas table)
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
- `schema/060_baseline_current.sql` - Complete baseline schema (fresh installs)
- `schema/061_*.sql` through `schema/066_*.sql` - Incremental migrations
- `schema/archive/` - Retired migrations (000-059), kept for reference

### Migration Workflow

1. Create migration file: `schema/062_your_change.sql` (never edit old files)
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
| `user_ideas` | Unified ideas journal (Discord + manual + transcribe) |
| `discord_ingest_cursors` | Incremental ingestion high-water marks |
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

### Model Strategy

The NLP pipeline uses a tiered model approach for cost/quality optimization:

| Tier | Model | Use Case |
|------|-------|----------|
| Triage | gpt-5-nano | Quick message classification |
| Main | gpt-5-mini | Standard parsing (80%+ of messages) |
| Escalation | gpt-5.1 | Complex/ambiguous content |
| Long Context | gpt-5.1 | Messages >500 tokens |
| Journal | gemini-1.5-flash | Daily summaries (free tier) |

**Fallbacks:**
- gpt-5-mini → gpt-4o-mini
- gpt-5.1 → gpt-4o

> **📖 See [LLM_MODELS.md](LLM_MODELS.md) for detailed model routing configuration.**

### Batch Pipeline

Cost-effective parsing using OpenAI Batch API (50% discount):

```bash
python scripts/nlp/batch_backfill.py --limit 500
```

## OpenBB Platform Integration

The OpenBB Platform SDK (`openbb>=4.6.0`) provides fundamental financial data through a multi-provider architecture. It connects via two data providers — **FMP** (Financial Modeling Prep) for premium fundamentals and **SEC** (free) for regulatory filings — and exposes the data through cached service functions and REST API endpoints.

### What OpenBB Provides

| Data Type | Provider | API Key Required | Description |
| --- | --- | --- | --- |
| Earnings Transcripts | FMP | Yes (`FMP_API_KEY`) | Quarterly earnings call transcripts with date, content, and fiscal period |
| Management Team | FMP | Yes | Executive roster with name, title, compensation, tenure |
| Fundamentals | FMP | Yes | Key financial metrics: P/E, EPS, D/E, ROE, market cap, revenue, margins |
| SEC Filings | SEC | No (free) | 10-K, 10-Q, 8-K, Form 4, and other regulatory filings with links |
| Company News | FMP | Yes | Recent news articles with title, source, date, and full text |
| Symbol Search | SEC | No (free) | Ticker/company lookup (used as 3rd fallback in `/search`) |

### Architecture

```text
┌──────────────────────────────────────────────────────────────────────┐
│  Next.js Frontend                                                    │
│  SWR hooks: useTranscript, useManagement, useFundamentals,          │
│             useFilings, useNews, useNotes                           │
└────────────────────────┬─────────────────────────────────────────────┘
                         │ BFF proxy (authGuard + backendFetch)
┌────────────────────────▼─────────────────────────────────────────────┐
│  FastAPI Backend  (app/routes/openbb.py)                             │
│  8 endpoints under /stocks/{ticker}/...                              │
│  - Ticker validation (regex: ^[A-Z]{1,6}(\.[A-Z]+)?$)              │
│  - asyncio.to_thread() wraps sync OpenBB calls                      │
│  - Notes endpoints use execute_sql() → PostgreSQL                   │
└────────────────────────┬─────────────────────────────────────────────┘
                         │
┌────────────────────────▼─────────────────────────────────────────────┐
│  src/openbb_service.py  (Cached Service Layer)                       │
│                                                                      │
│  Singleton pattern with lazy init + double-check locking             │
│  Sets FMP_API_KEY on obb.user.credentials at init                    │
│  All public functions return None/[] on failure (never raise)        │
│                                                                      │
│  ┌──────────────────┬──────────┬──────────┬───────────────────────┐  │
│  │ Cache            │ TTL      │ Max Size │ Thread Lock           │  │
│  ├──────────────────┼──────────┼──────────┼───────────────────────┤  │
│  │ Transcripts      │ 24 hours │ 100      │ _transcript_lock      │  │
│  │ Management       │ 24 hours │ 200      │ _management_lock      │  │
│  │ Fundamentals     │ 1 hour   │ 200      │ _fundamentals_lock    │  │
│  │ Filings          │ 1 hour   │ 200      │ _filings_lock         │  │
│  │ News             │ 15 min   │ 200      │ _news_lock            │  │
│  └──────────────────┴──────────┴──────────┴───────────────────────┘  │
│                                                                      │
│  Internal fetchers use @hardened_retry(max_retries=2, delay=1)       │
└────────────────────────┬─────────────────────────────────────────────┘
                         │
┌────────────────────────▼─────────────────────────────────────────────┐
│  OpenBB Platform SDK  (from openbb import obb)                       │
│  ├─ FMP Provider  ← requires FMP_API_KEY env var                    │
│  │   obb.equity.fundamental.ratios()                                │
│  │   obb.equity.estimates.consensus()                               │
│  │   obb.equity.ownership.major_holders()                           │
│  │   obb.news.company()                                             │
│  └─ SEC Provider  ← free, no key                                   │
│      obb.equity.fundamental.filings()                               │
│      obb.equity.search()                                            │
└──────────────────────────────────────────────────────────────────────┘
```

### API Endpoints

All endpoints are mounted at `/stocks` with `require_api_key` dependency. The frontend proxies through Next.js BFF routes (`/api/stocks/[ticker]/*`) which add NextAuth session validation.

| Method | Path | Provider | Cache Header |
| --- | --- | --- | --- |
| `GET` | `/{ticker}/transcript?year=&quarter=` | FMP | — |
| `GET` | `/{ticker}/management` | FMP | — |
| `GET` | `/{ticker}/fundamentals` | FMP | — |
| `GET` | `/{ticker}/filings?form_type=&limit=10` | SEC | `Cache-Control: public, max-age=3600` |
| `GET` | `/{ticker}/news?limit=10` | FMP | — |
| `GET` | `/{ticker}/notes?limit=50` | PostgreSQL | — |
| `POST` | `/{ticker}/notes` | PostgreSQL | 201 Created |
| `DELETE` | `/{ticker}/notes/{note_id}` | PostgreSQL | 204 No Content |

### Search Fallback Chain

The `/search` endpoint uses OpenBB as the third-tier fallback for symbol lookup:

1. **Local DB** — Query the `symbols` table (instant, no API call)
2. **yfinance** — `market_data_service.search_symbols()` (Yahoo Finance)
3. **OpenBB SEC** — `obb.equity.search(query, provider="sec")` (free, no key)

### Database Table: `stock_notes`

Created by `schema/062_stock_notes.sql`. Stores user annotations per ticker.

```sql
CREATE TABLE stock_notes (
    id          SERIAL PRIMARY KEY,
    symbol      VARCHAR(20) NOT NULL,
    content     TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
-- Indexes: UPPER(symbol), created_at DESC
-- Trigger: auto-update updated_at on modification
-- RLS: enabled
```

### Configuration

| Setting | Location | Required | Description |
| --- | --- | --- | --- |
| `FMP_API_KEY` | `.env` / AWS Secrets Manager | For FMP data | Financial Modeling Prep API key |

- Config defined in `src/config.py` as `FMP_API_KEY: str = ""`
- AWS mapping in `src/aws_secrets.py`: `"FMP_API_KEY": "FMP_API_KEY"`
- If missing: FMP endpoints return empty results; SEC endpoints still work

### Startup Health Check

On FastAPI startup (`app/main.py` lifespan), the app checks OpenBB availability:

```python
from src.openbb_service import is_available as obb_available
if obb_available():
    logger.info("OpenBB Platform SDK available (FMP + SEC providers)")
else:
    logger.warning("OpenBB not available — fundamental data disabled")
```

### Frontend Components

The Next.js frontend consumes OpenBB data through:

- **6 SWR hooks** in `hooks/useOpenBB.ts` — `useTranscript`, `useManagement`, `useFundamentals`, `useFilings`, `useNews`, `useNotes`
- **6 BFF proxy routes** in `app/api/stocks/[ticker]/` — each adds auth headers and caching
- **OpenBBInsightsPanel** — tabbed UI (News, Filings, Transcript, Management, Notes) on each stock page
- **FundamentalsCard** — key metrics sidebar card (P/E, EPS, D/E, ROE, etc.)

## Ideas Journal & Auto-Refine

The Ideas Journal provides a unified store for trading ideas from all sources (Discord, manual entry, voice transcription). It sits on top of the NLP pipeline as a user-facing "journal" layer.

### Ideas Architecture

```text
┌─────────────────────────────────────────────────────────────────┐
│  Next.js Frontend                                                │
│  /ideas page: capture form, filter bar, idea cards, detail drawer│
│  Car Ride Mode: simplified mobile capture                        │
│  Ticker Bar: scrolling portfolio positions on dashboard          │
│  Hooks: useUserIdeas (SWR), useMovers (SWR + polling)           │
└───────────────────────┬─────────────────────────────────────────┘
                        │ BFF proxy (authGuard + backendFetch)
┌───────────────────────▼─────────────────────────────────────────┐
│  FastAPI Backend  (app/routes/ideas.py)                          │
│  5 endpoints under /ideas                                        │
│  - GET (paginated list with filters)                             │
│  - POST (create with content_hash dedup)                         │
│  - PUT (partial update, hash recompute)                          │
│  - DELETE (with existence check)                                 │
│  - POST /{id}/refine (OpenAI gpt-4o-mini, optional auto-apply)  │
│                                                                  │
│  app/routes/portfolio.py — GET /portfolio/movers                 │
│  - Top gainers/losers from positions with price cascade          │
└───────────────────────┬─────────────────────────────────────────┘
                        │
┌───────────────────────▼─────────────────────────────────────────┐
│  PostgreSQL: user_ideas table                                    │
│  - UUID PK, symbols TEXT[], tags TEXT[] (GIN indexed)            │
│  - source CHECK (discord/manual/transcribe)                      │
│  - status CHECK (draft/refined/archived)                         │
│  - content_hash for same-day deduplication                       │
│  - partial unique on (source, origin_message_id)                 │
└─────────────────────────────────────────────────────────────────┘
```

### Database Table: `user_ideas`

Created by `schema/064_user_ideas.sql`. Coexists with `discord_parsed_ideas` (NLP output store).

```sql
CREATE TABLE user_ideas (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    symbol          TEXT,
    symbols         TEXT[],
    content         TEXT NOT NULL,
    source          TEXT NOT NULL CHECK (source IN ('discord','manual','transcribe')),
    status          TEXT NOT NULL DEFAULT 'draft',
    tags            TEXT[],
    origin_message_id TEXT,
    content_hash    TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
-- Indexes: UPPER(symbol)+created_at, GIN(tags), GIN(symbols), source+created_at, content_hash
-- Partial unique: (source, origin_message_id) WHERE NOT NULL; (content_hash, date) for dedup
```

## Discord Incremental Ingestion

Cursor-based ingestion pipeline for Discord messages with content hash deduplication.

### Ingestion Architecture

```text
Discord Bot (on_message)  ──┐
                             ├─► discord_messages (raw storage)
scripts/ingest_discord.py ──┘    │
    │                            ▼
    └─ cursor tracking ─► discord_ingest_cursors
       (high-water mark per channel)
```

- **`src/discord_ingest.py`** — Core module: `ingest_channel()`, `compute_content_hash()`, cursor management
- **`scripts/ingest_discord.py`** — CLI for manual/scheduled runs
- **`scripts/nightly_pipeline.py`** — Integrated as step in nightly pipeline
- **`schema/063_discord_ingestion.sql`** — `discord_ingest_cursors` table

## Extension Points

- **Modular Commands**: New Discord bot commands via plugin pattern
- **Data Sources**: Additional APIs through collector pattern
- **Processing Modules**: New analysis types via modular engine
