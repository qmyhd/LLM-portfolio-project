# LLM Portfolio Journal - Architecture Documentation

> **Last Updated:** January 3, 2026  
> **Database:** PostgreSQL (Supabase) - 19 active tables, RLS 100% compliant

## Overview

The LLM Portfolio Journal is a data-driven application integrating brokerage data, market information, and social sentiment analysis to generate trading insights using Large Language Models.

## System Architecture

### Core Components

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Data Sources  │    │  Processing     │    │    Output       │
│                 │    │   Engine        │    │   Generation    │
├─────────────────┤    ├─────────────────┤    ├─────────────────┤
│ • SnapTrade API │───▶│ • Data Collector│───▶│ • Journal Gen   │
│ • Discord Bot   │    │ • Message Clean │    │ • Markdown      │
│ • Twitter API   │    │ • Sentiment     │    │ • Text Summary  │
│ • yfinance      │    │ • Database ETL  │    │ • Charts        │
└─────────────────┘    └─────────────────┘    └─────────────────┘
```

### Database Layer

**PostgreSQL-Only Database Architecture (SQLAlchemy 2.0 Compatible):**
- **PostgreSQL/Supabase**: Production database with real-time capabilities and connection pooling
- **Unified Interface**: All components use `execute_sql()` with named placeholders and dict parameters
- **No Fallback**: System requires PostgreSQL - no SQLite support
- **RLS Enabled**: All tables have Row Level Security enabled

**Key Tables (19 operational):**
- **SnapTrade Integration**: `accounts`, `account_balances`, `positions`, `orders`, `symbols`, `trade_history`
- **Discord/Social**: `discord_messages`, `discord_market_clean`, `discord_trading_clean`
- **NLP Pipeline**: `discord_parsed_ideas` (canonical table for parsed trading ideas)
- **Market Data**: `daily_prices`, `realtime_prices`, `stock_metrics`
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
- **`message_cleaner.py`**: Discord message cleaning with ticker extraction, sentiment analysis, and write helpers
- **`channel_processor.py`**: Production wrapper that fetches → cleans → writes to discord_market_clean/discord_trading_clean
- **`twitter_analysis.py`**: Twitter/X sentiment analysis and data extraction

#### Database Management (`src/`)
- **`db.py`**: Enhanced SQLAlchemy 2.0 engine with unified execute_sql(), connection pooling, bulk operations, and parameter type validation

- **`market_data.py`**: Consolidated portfolio and trade data queries with PostgreSQL compatibility

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
- **`ui/`**: Centralized UI design system:
  - `embed_factory.py`: Standardized embed builder with color coding by category
  - `pagination.py`: Base class for paginated views
  - `portfolio_view.py`: Interactive portfolio with filter buttons (All/Winners/Losers)
  - `help_view.py`: Dropdown-based help navigation by command category

#### Processing Engine (`src/`)
- **`message_cleaner.py`**: Text processing and ticker symbol extraction
- **`journal_generator.py`**: LLM integration for journal generation
- **`position_analysis.py`**: Advanced position tracking and analytics
- **`chart_enhancements.py`**: Enhanced charting with position overlays

#### NLP Pipeline (`src/nlp/`)
- **`openai_parser.py`**: LLM-based semantic parsing with OpenAI structured outputs
  - Model routing: gpt-5-mini (triage/main/summary) and gpt-5.1 (long-context/escalation)
  - Thresholds: 2000 chars / 500 tokens → gpt-5.1, confidence < 0.8 → escalation
- **`schemas.py`**: Pydantic schemas for structured outputs (ParsedIdea, MessageParseResult, 13 TradingLabels)
- **`soft_splitter.py`**: Deterministic message splitting for long content
- **`preclean.py`**: Text preprocessing before LLM parsing
  - **Alias mapping**: Company names → ticker symbols (e.g., "nvidia" → "$NVDA")
  - **Short action whitelist**: Valid brief actions that can stand alone ("Buy AAPL")
  - **Merge logic**: Auto-merge fragmentary ideas with neighboring context
  - **Ticker context validation**: Guard against false positive ticker extraction
  - **SSOT prefilter**: `should_skip_message()` used by all parsing components

#### NLP Scripts (`scripts/nlp/`)
- **`parse_messages.py`**: Live message parsing with OpenAI
  - Context injection: Fetches prior messages for continuation detection
  - Post-parse cleanup: Merges short ideas via `merge_short_ideas()`
  - Prefilters: `is_bot_command()`, `is_bot_response()` (skips bot commands/users)
- **`build_batch.py`**: Batch API request builder with prefilters
- **`run_batch.py`**: Submit batch jobs to OpenAI and poll for completion
- **`ingest_batch.py`**: Ingest batch results to database with atomic writes
- **`batch_backfill.py`**: Unified orchestrator for the complete batch pipeline

#### Utilities (`src/`)
- **`config.py`**: Centralized configuration management with Pydantic
- **`retry_utils.py`**: Hardened retry decorator with exception handling
- **`logging_utils.py`**: Database logging with Twitter integration

#### ETL Pipeline (`src/etl/`)
- **`sec_13f_parser.py`**: Standalone tool for parsing SEC 13F filings

### Operational Tooling (`scripts/`)
- **`bootstrap.py`**: Application bootstrap with dependency management
- **`deploy_database.py`**: Database deployment and schema application
- **`verify_database.py`**: Comprehensive schema verification (imports from `src.expected_schemas`)
- **`schema_parser.py`**: Generate `expected_schemas.py` from SQL DDL (single source of truth)
- **`check_system_status.py`**: Quick health check for DB and APIs
- **`fetch_discord_history_improved.py`**: Discord history backfill with rate limiting

## Data Flow

### Primary Data Pipeline

```
1. Data Ingestion
   ├─ SnapTrade API → Positions/Orders/Accounts
   ├─ Discord Bot → Message Stream → Ticker Extraction
   ├─ Twitter API → Tweet Analysis → Sentiment Scoring
   └─ yfinance → Market Data → Price History

2. Data Processing
   ├─ CSV Cleaning → Data Validation → Error Handling
   ├─ Symbol Extraction → Ticker Normalization
   ├─ Sentiment Analysis → TextBlob Processing
   └─ Deduplication → Database Upserts

3. Data Storage
   ├─ PostgreSQL (Production) → Real-time Writes with Connection Pooling
   └─ CSV Backup → Raw Data Persistence

4. Analysis & Generation
   ├─ Portfolio Analysis → Position Tracking → P/L Calculation
   ├─ Sentiment Correlation → Market Data Integration
   ├─ LLM Processing → Prompt Engineering → Journal Generation
   └─ Chart Generation → Technical Analysis → Visualization
```

### Real-time Processing

- **Discord Event Stream**: Live message processing with ticker detection
- **Database Writes**: Immediate persistence with fallback mechanisms
- **Sentiment Analysis**: Real-time TextBlob processing
- **Deduplication**: Message ID tracking to prevent duplicates

## Key Design Patterns

### Error Handling Strategy
- **Graceful Degradation**: Services continue operating when dependencies fail
- **Retry Mechanisms**: Exponential backoff with circuit breaker patterns
- **Connection Pooling**: Automatic retry and connection management
- **Exception Filtering**: Non-retryable exceptions handled immediately

### Database Patterns
- **Single Persistence**: PostgreSQL/Supabase with CSV backup for historical data
- **Connection Pooling**: SQLAlchemy 2.0 with health checks and automatic failover
- **Schema Management**: Automated schema validation via verify_database.py
- **Prepared Statements**: Named parameters optimized for Supabase compatibility

### API Integration Patterns
- **Safe Response Handling**: Structured parsing with error recovery
- **Optional Dependencies**: Import failure handling for external services
- **Rate Limiting**: Respectful API usage with built-in delays
- **Authentication Management**: Secure credential handling via environment

### Data Processing Patterns
- **Modular ETL**: Separate extraction, transformation, and loading
- **Type Safety**: Comprehensive type checking and validation
- **Schema Enforcement**: Strict data validation before persistence
- **Performance Optimization**: Bulk operations and efficient queries

## Security Considerations

- **Credential Management**: Environment-based secrets with `.env` files
- **SQL Injection Prevention**: Parameterized queries and prepared statements
- **Data Sanitization**: Input validation and cleaning before storage
- **Access Control**: Database-level permissions and connection security

## Performance Optimizations

- **Connection Pooling**: Reusable database connections
- **Bulk Operations**: Batch processing for large datasets
- **Caching Strategies**: In-memory caching for frequently accessed data
- **Lazy Loading**: On-demand module imports and data loading

## Monitoring & Observability

- **Comprehensive Logging**: Structured logging throughout the application
- **Health Checks**: Database and service availability monitoring
- **Error Tracking**: Detailed exception logging and reporting
- **Performance Metrics**: Database size and query performance tracking

## NLP Parsing Rules

### Ticker Accuracy System (Multi-Layer)

The NLP pipeline uses a deterministic pre-extraction layer combined with LLM validation to ensure ticker accuracy:

**Pipeline Flow:**
```
Message → preclean.py (extract_candidate_tickers) → LLM (parse_message with hint) → validate_llm_tickers → Final Ideas
```

1. **Pre-LLM Extraction** (`extract_candidate_tickers`):
   - Extracts tickers deterministically before LLM sees the message
   - Respects RESERVED_SIGNAL_WORDS blocklist (80+ trading terms)
   - Applies alias mapping for company names

2. **LLM Hint Injection** (`parse_message`):
   - Passes candidate tickers to LLM: `[HINT: Candidate tickers: AAPL, NVDA...]`
   - LLM picks from candidates rather than inventing tickers

3. **Post-Validation** (`validate_llm_tickers`):
   - Validates LLM output against candidate list
   - Drops tickers not in original message (unless strict=False)
   - Ensures primary_symbol and symbols are legitimate

### Reserved Signal Words (preclean.py)

**RESERVED_SIGNAL_WORDS** (80+ terms) - These NEVER become tickers:
- **Price targets**: `tgt`, `pt`, `tp`, `target`, `price target`
- **Levels**: `support`, `resistance`, `pivot`, `r1`, `r2`, `r3`, `s1`, `s2`, `s3`
- **Actions**: `buy`, `sell`, `hold`, `long`, `short`, `trim`, `add`, `entry`, `exit`, `stop`
- **Time**: `eod`, `dte`, `exp`, `weekly`, `monthly`
- **Risk**: `sl`, `be` (stop loss, break even)

This prevents "price target $50" from becoming "$TGT $50".

### Alias Mapping
Company names and common references are automatically mapped to ticker symbols:
- **Company names**: "nvidia" → "$NVDA", "crowdstrike" → "$CRWD", "amazon" → "$AMZN"
- **Lowercase tickers**: "pltr" → "$PLTR", "aapl" → "$AAPL" (without $ prefix)
- **Subsidiaries**: "waymo" → "$GOOGL", "instagram" → "$META"
- **Specific variants**: "target corp" → "$TGT", "target store" → "$TGT" (NOT bare "target")

### Ticker Context Validation
To prevent false positive ticker extraction:
- **$ prefix**: Always valid (e.g., "$AAPL")
- **Action word context**: Valid if preceded by buy/sell/trim/add (e.g., "bought NVDA")
- **Trading suffix**: Valid if followed by calls/puts/shares (e.g., "SPY calls")
- **Reserved word check**: Words in RESERVED_SIGNAL_WORDS are never tickers

### Short Message Handling
Short ideas (<20 characters) are handled specially:

**Whitelist of Valid Short Actions** (never merged):
- Buy/sell actions: "buy", "sold", "selling", "short", "shorting"
- Position management: "trim", "add", "hedge", "exit", "close"
- Observation: "hold", "watch"

**Merge Rules** for short fragments:
1. Ideas starting with `$TICKER` or action verbs are preserved
2. Short fragments merge with previous idea if same primary_symbol
3. Short fragments merge with next idea if can't merge with previous
4. Fragments that can't be safely merged are kept as-is

**Post-Processing** (`process_message`):
- Applies `merge_short_ideas()` after LLM parsing
- Re-numbers idea_index after merging
- Validates all tickers against candidate list

### Context Injection
For terse or continuation messages:
- **Continuation detection**: Messages starting with "but", "also", "agreed", etc.
- **Low entity density**: Short messages with few/no tickers may need context
- **Context window**: Prior messages from same channel within time window (`--context-window N`)
- **Safe application**: Only applied when message is clearly a continuation
- **Storage**: Context message IDs stored in `raw_json` (no schema changes)

### Quality Checks
Parser output is validated for quality:
- **Min length exemptions**: Trade executions and crypto ideas exempt from 20-char minimum
- **Duplicate detection**: Identical idea texts are flagged
- **skip_quality_check**: Only allowed for short alerts (<150 chars)

## Batch Pipeline (Backfill via Batch API)

### Overview
The batch pipeline provides cost-effective parsing for large backlogs using OpenAI's Batch API (50% discount). It is fully aligned with live parsing.

### Prefilters (Same as Live Parsing)
Both live parsing and batch apply identical prefilters:
1. **`is_bot_command()`**: Skip messages starting with `!`, `/`, etc.
2. **`is_url_only()`**: Skip URL-only messages (cannot extract ideas)
3. **`is_bot_response()`**: Skip messages from bot users (QBOT, TradingBot, etc.)
4. **Empty after clean**: Skip messages that become empty after preprocessing

### Endpoint Difference
- **Live parsing**: Uses Responses API (`/v1/responses`) with structured outputs
- **Batch**: Uses Chat Completions (`/v1/chat/completions`) with `response_format` JSON schema
- **Same output**: Both produce identical `MessageParseResult` via the same Pydantic schema

### Unified Orchestrator Command
```bash
# Full batch backfill (500 pending messages)
python scripts/nlp/batch_backfill.py

# Custom limit with dry-run validation
python scripts/nlp/batch_backfill.py --limit 1000 --dry-run

# Skip schema verification (faster)
python scripts/nlp/batch_backfill.py --skip-verify --limit 500
```

### Pipeline Steps
1. **Schema verification**: Checks tables and columns exist
2. **Build batch**: Creates JSONL with prefilters, marks skipped in DB
3. **Upload & run**: Submits to OpenAI Batch API, polls until complete
4. **Download**: Retrieves output JSONL
5. **Ingest**: Atomic delete+insert per message, updates `parse_status`
6. **Integrity checks**: Validates no duplicates, no orphan ideas

### Custom ID Format
Deterministic mapping: `msg-{message_id}-chunk-{chunk_index}`
- Ingestion parses custom_id to recover message_id (not output order)
- Supports multi-chunk messages with correct indexing

### Write Path Alignment
| Aspect | Live Parsing | Batch Ingestion |
|--------|--------------|-----------------|
| Delete existing | `pg_advisory_xact_lock` | `pg_advisory_xact_lock` |
| Insert | `save_parsed_ideas_atomic()` | `delete_and_insert_ideas_atomic()` |
| Status update | Sets `parse_status` | Sets `parse_status` |
| Unique constraint | `(message_id, soft_chunk_index, local_idea_index)` | Same |

### parse_status Transitions
```
pending → skipped (prefilter matched)
pending → noise (triage/parser marked as noise)
pending → ok (ideas extracted successfully)
pending → error (API error or parse failure)
```

## Development Workflow

### Local Development
1. **Environment Setup**: Virtual environment with requirements.txt
2. **Database Initialization**: PostgreSQL/Supabase connection required
3. **Configuration**: `.env` file with PostgreSQL credentials
4. **Testing**: Comprehensive unit and integration tests

### Production Deployment
1. **Bootstrap Process**: Automated dependency and database setup
2. **Schema Validation**: PostgreSQL schema verification and setup
3. **Health Validation**: Comprehensive system health checks
4. **Monitoring**: Ongoing performance and error monitoring

## Schema Management & Validation

### Single Source of Truth

The schema system follows a strict hierarchy:

```
SQL DDL (schema/*.sql) → schema_parser.py → expected_schemas.py → verify_database.py
```

**Source Files**: 
- `schema/000_baseline.sql` - Complete baseline schema
- `schema/015-020_*.sql` - Incremental migrations
- Generated output: `src/expected_schemas.py`

### Schema Generation Process

**Command**: `python scripts/schema_parser.py --output expected`

1. **Parse DDL**: Extracts `CREATE TABLE` statements from SQL files in order
2. **Normalize Types**: Converts PostgreSQL types to standardized verification types
3. **Extract Primary Keys**: Identifies PK constraints from ALTER TABLE statements
4. **Generate Python**: Writes dictionary to `src/expected_schemas.py`

### Type Normalization

PostgreSQL types are normalized for validation:

| PostgreSQL Type | Verification Type |
|-----------------|-------------------|
| `TEXT`, `VARCHAR`, `CHARACTER` | `text` |
| `INTEGER`, `SERIAL`, `SMALLINT` | `integer` |
| `BIGINT`, `BIGSERIAL` | `bigint` |
| `NUMERIC`, `DECIMAL` | `numeric` |
| `BOOLEAN` | `boolean` |
| `DATE` | `date` |
| `TIMESTAMP`, `TIMESTAMPTZ` | `timestamp` |
| `TIME` | `time` |
| `JSON`, `JSONB` | `json` |
| Array types (`[]`) | `array` |

### Schema Validation

Use `verify_database.py` to validate live database against expected schemas:

```python
from src.expected_schemas import EXPECTED_SCHEMAS

# Verify single table
for table_name, schema_def in EXPECTED_SCHEMAS.items():
    validate_table_schema(table_name, schema_def)
```

**Validation Modes**:
- **Basic**: Tables exist, columns present, types match
- **Strict**: Fails on any warnings (for CI/CD)
- **Comprehensive**: Full audit with constraints, indexes, RLS policies

### Best Practices

1. **Never manually edit** `expected_schemas.py` - always regenerate from SQL
2. **Always verify** after regeneration: `python scripts/verify_database.py`
3. **Commit together**: SQL migration + generated Python schemas
4. **Type safety**: Use warn-only validation in production, strict in CI/CD

## Migration Workflow

### Standard 4-Step Process

All database schema changes follow this mandatory workflow:

**1. Create Migration File**

```bash
# Format: NNN_descriptive_name.sql
# Example: schema/021_add_trades_table.sql
```

**2. Deploy to Database**

```bash
python scripts/deploy_database.py
```

**3. Regenerate Python Schemas** (MANDATORY)

```bash
python scripts/schema_parser.py --output expected
# Updates src/expected_schemas.py from SQL files
```

**4. Verify Alignment** (MANDATORY)

```bash
python scripts/verify_database.py --mode comprehensive
# Validates live DB matches expected schemas
```

### Commit All Together

```bash
git add schema/021_*.sql src/expected_schemas.py
git commit -m "feat: add trades table

- Migration 021: Create trades table
- Regenerated expected_schemas.py
- Verified with verify_database.py"
```

### Critical Rules

❌ **DO NOT** manually edit `expected_schemas.py`  
❌ **DO NOT** commit migrations without regenerating schemas  
❌ **DO NOT** skip verification before commit  
✅ **DO** edit SQL files, then regenerate  
✅ **DO** commit migration + schema + verification together  
✅ **DO** run verification in strict mode for CI/CD

### Troubleshooting

**Schema parser doesn't detect new migration**:
```bash
ls -la schema/*.sql | tail -5  # Check file naming
```

**Verification fails with type mismatches**:
```bash
python -c "from src.db import execute_sql; print(execute_sql('SELECT column_name, data_type FROM information_schema.columns WHERE table_name=...', fetch_results=True))"
```

**Primary key order mismatch**:
- Composite PKs must match exact order in EXPECTED_SCHEMAS
- Example: `PRIMARY KEY (symbol, account_id)` not `(account_id, symbol)`

## Discord Bot System

### Architecture Overview

The Discord bot processes messages through a two-stage pipeline:

```
Discord Messages → discord_messages (raw)
                 ↓
         message_cleaner.py (extract tickers, sentiment)
                 ↓
         channel_processor.py (coordinate)
                 ↓
discord_market_clean OR discord_trading_clean (processed)
```

### Module Responsibilities

**`message_cleaner.py` (Core Cleaning Engine)**:
- `extract_ticker_symbols()` - Parse $TICKER mentions from text
- `clean_text()` - Remove URLs, mentions, normalize content
- `calculate_sentiment()` - TextBlob sentiment analysis
- `save_to_database()` - Write processed messages to database
- Main processing pipeline with deduplication

**`channel_processor.py` (Production Coordinator)**:
- `process_channel_data()` - Orchestrates message processing
- `parse_messages_with_llm()` - LLM parsing pipeline orchestration
- Delegates all cleaning to `message_cleaner.py`
- Handles unprocessed message tracking

**`bot/commands/` (Discord Commands)**:
- `chart.py` - Advanced charting with position tracking
- `history.py` - Message history fetching with deduplication
- `process.py` - Channel data processing and statistics
- `twitter_cmd.py` - Twitter data analysis
- `eod.py` - End-of-day stock data queries

### Table Mapping

| Table | Purpose | Source |
|-------|---------|--------|
| `discord_messages` | Raw Discord messages | Bot events |
| `discord_market_clean` | General market messages | Processed |
| `discord_trading_clean` | Trading-specific messages | Processed |
| `discord_parsed_ideas` | LLM-extracted trading ideas | NLP Pipeline |
| `processing_status` | Processing status tracking | System |

Channel type determines target table:
- `channel_type="general"` → `discord_market_clean`
- `channel_type="trading"` → `discord_trading_clean`

### Data Flow

1. **Capture**: Bot receives message via Discord event
2. **Store**: Raw message saved to `discord_messages`
3. **Extract**: Ticker symbols parsed from content
4. **Analyze**: Sentiment calculated via TextBlob
5. **Clean**: Text normalized, URLs removed
6. **Route**: Message written to appropriate clean table
7. **Track**: Processing status recorded in `processing_status`
8. **Parse**: LLM extracts trading ideas → `discord_parsed_ideas`

## Extension Points

The architecture supports easy extension through:
- **Modular Commands**: New Discord bot commands via plugin pattern
- **Data Sources**: Additional APIs through standardized collector pattern
- **Processing Modules**: New analysis types via modular processing engine
- **Output Formats**: Additional journal formats through generator plugins

This architecture ensures scalability, maintainability, and robust operation across development and production environments.
