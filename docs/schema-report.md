# LLM Portfolio Journal - Schema Report

> **Generated on:** January 2, 2026 (header updated July 2026)  
> **Database System:** PostgreSQL (Supabase)  
> **Status:** Verified - 17 Active Tables, RLS 100% Compliant  
> **Latest Migration:** 058_security_and_indexes.sql

## 1. Schema Overview

The database consists of **17 active tables** organized into functional groups. All tables are in the `public` schema and have Row Level Security (RLS) enabled.

**Note:** Legacy tables dropped in migrations 049-054:
- `discord_message_chunks`, `discord_idea_units`, `stock_mentions`, `discord_processing_log`, `chart_metadata` (migration 049/054)
- `daily_prices`, `realtime_prices`, `stock_metrics` (migration 051 - replaced by `ohlcv_daily`)
- `trade_history`, `event_contract_trades`, `event_contract_positions` (migration 052)

**Tables added post-baseline:**
- `ohlcv_daily` - Databento OHLCV daily bars (PK: symbol, date)
- `stock_profile_current` - Derived metrics per ticker (migration 055)
- `stock_profile_history` - Time-series profile metrics (migration 055)

### Database Statistics
| Metric | Count |
|--------|-------|
| Tables | 17 |
| Primary Keys | 17 |
| Foreign Keys | 1 |
| Unique Constraints | 4 |
| RLS Policies | ~50 |

### Active Tables (17)
| Table | Primary Key |
|-------|-------------|
| accounts | `id` |
| account_balances | `currency_code, snapshot_date, account_id` |
| positions | `symbol, account_id` |
| orders | `brokerage_order_id` |
| symbols | `id` |
| ohlcv_daily | `symbol, date` |
| discord_messages | `message_id` |
| discord_market_clean | `message_id` |
| discord_trading_clean | `message_id` |
| discord_parsed_ideas | `id` |
| twitter_data | `tweet_id` |
| institutional_holdings | `id` |
| symbol_aliases | `id` |
| stock_profile_current | `ticker` |
| stock_profile_history | `ticker, as_of_date` |
| schema_migrations | `version` |
| processing_status | `message_id, channel` |

---

## 2. Table Usage Map (Readers/Writers)

This section documents which files and functions access each table.

### A. Discord & Social Tables

#### `discord_messages` (Raw Discord Message Storage)

**Source table for all Discord message ingestion.** This is the input for both live NLP parsing and batch backfill.

| Operation | File | Function/Method |
|-----------|------|-----------------|
| **INSERT** | `src/logging_utils.py` | `log_message_to_database()` |
| **INSERT** | `src/bot/commands/history.py` | `!history` command (via log_message_to_database) |
| **INSERT** | `src/bot/commands/process.py` | `!backfill` command (via log_message_to_database) |
| **SELECT** | `src/db.py` | `get_unprocessed_messages()` |
| **SELECT** | `src/twitter_analysis.py` | `analyze_discord_for_twitter()` - finds Twitter links |
| **SELECT** | `src/journal_generator.py` | `load_discord_messages()` |
| **SELECT** | `scripts/nlp/parse_messages.py` | `fetch_context_messages()` - context injection |
| **SELECT** | `scripts/nlp/build_batch.py` | `_fetch_pending_messages()` - batch input |
| **UPDATE** | `src/db.py` | `save_parsed_ideas_atomic()` - updates parse_status |
| **UPDATE** | `scripts/nlp/build_batch.py` | `_mark_skipped_messages()` - marks prefiltered |
| **UPDATE** | `scripts/nlp/ingest_batch.py` | `_update_parse_status()` - batch completion |

#### `discord_parsed_ideas` (LLM-Extracted Trading Ideas)

**Canonical table for all NLP-parsed trading ideas.** Replaces legacy tables `discord_message_chunks`, `discord_idea_units`, and `stock_mentions`.

**Key Design Points:**
- **Unique constraint**: `(message_id, soft_chunk_index, local_idea_index)` prevents duplicates
- **Foreign key**: `message_id → discord_messages.message_id` (CASCADE delete)
- **Atomic writes**: Uses PostgreSQL advisory locks for delete+insert patterns
- **parse_status lifecycle**: `pending → ok/noise/skipped/error`

| Operation | File | Function/Method |
|-----------|------|-----------------|
| **DELETE** | `src/db.py` | `save_parsed_ideas_atomic()` - atomic reparse |
| **INSERT** | `src/db.py` | `save_parsed_ideas_atomic()` - insert fresh ideas |
| **DELETE** | `scripts/nlp/ingest_batch.py` | `delete_and_insert_ideas_atomic()` - batch ingestion |
| **INSERT** | `scripts/nlp/ingest_batch.py` | `delete_and_insert_ideas_atomic()` - batch ingestion |
| **SELECT** | `scripts/nlp/parse_messages.py` | Deduplication check before parsing |
| **SELECT** | `scripts/nlp/build_batch.py` | Pre-batch dedup check |

#### `discord_trading_clean` / `discord_market_clean` (Cleaned Messages)
| Operation | File | Function/Method |
|-----------|------|-----------------|
| **INSERT** | `src/message_cleaner.py` | `save_to_database()` |


#### `twitter_data` (Tweet Data Linked to Discord)
| Operation | File | Function/Method |
|-----------|------|-----------------|
| **INSERT** | `src/twitter_analysis.py` | `save_tweet_to_db()` |
| **SELECT** | `src/twitter_analysis.py` | `get_data_status()` |
| **SELECT** | `src/bot/commands/twitter_cmd.py` | `!twitter` command |

#### `processing_status` (Message Processing Flags)
| Operation | File | Function/Method |
|-----------|------|-----------------|
| **INSERT/UPDATE** | `src/db.py` | `mark_message_processed()` |
| **SELECT** | `src/db.py` | `get_unprocessed_messages()` - LEFT JOIN filter |

---

### B. Brokerage & Portfolio Tables (SnapTrade)

#### `positions` (Current Portfolio Holdings)
| Operation | File | Function/Method |
|-----------|------|-----------------|
| **INSERT/UPSERT** | `src/snaptrade_collector.py` | `write_to_database()` with ON CONFLICT |
| **SELECT** | `src/data_collector.py` | `get_current_price()`, `get_portfolio_summary()` |
| **SELECT** | `src/position_analysis.py` | `get_current_position()` |
| **SELECT** | `src/snaptrade_collector.py` | `get_current_positions_from_db()` |
| **SELECT** | `src/bot/commands/snaptrade_cmd.py` | `!portfolio`, `!movers` commands |
| **SELECT** | `src/bot/commands/chart.py` | Position overlay on charts |
| **UPDATE** | `src/data_collector.py` | `update_position_prices()` |

#### `orders` (Trade Order History)
| Operation | File | Function/Method |
|-----------|------|-----------------|
| **INSERT/UPSERT** | `src/snaptrade_collector.py` | `write_to_database()` with ON CONFLICT |
| **SELECT** | `src/market_data.py` | `get_recent_trades()` |
| **SELECT** | `src/bot/commands/chart.py` | Trade overlays on charts |
| **SELECT** | `src/bot/commands/snaptrade_cmd.py` | `!orders`, `!movers` commands |

#### `accounts` (Brokerage Account Metadata)
| Operation | File | Function/Method |
|-----------|------|-----------------|
| **INSERT/UPSERT** | `src/snaptrade_collector.py` | `write_to_database()` |
| **SELECT** | `scripts/validate_live_schema.py` | Schema validation |

#### `account_balances` (Cash & Buying Power Snapshots)
| Operation | File | Function/Method |
|-----------|------|-----------------|
| **INSERT/UPSERT** | `src/snaptrade_collector.py` | `write_to_database()` |
| **SELECT** | `src/bot/commands/snaptrade_cmd.py` | `!portfolio` command |

#### `symbols` (Security Reference Data)
| Operation | File | Function/Method |
|-----------|------|-----------------|
| **INSERT/UPSERT** | `src/snaptrade_collector.py` | `upsert_symbols_table()` |

#### `trade_history` (Individual Trade P/L Records)
| Operation | File | Function/Method |
|-----------|------|-----------------|
| **INSERT** | `src/data_collector.py` | `save_trade_to_history()` |
| **SELECT** | `src/data_collector.py` | `get_realized_pnl()` |

---

### C. Market Data Tables

#### `realtime_prices` / `daily_prices` / `stock_metrics`
| Operation | File | Function/Method |
|-----------|------|-----------------|
| **INSERT** | `src/data_collector.py` | Various price collection functions |
| **SELECT** | `src/data_collector.py` | `get_current_price()` (fallback chain) |
| **SELECT** | `src/position_analysis.py` | `get_current_price()` |

---

### D. Special Purpose Tables

#### `institutional_holdings` (SEC 13F Data)
| Operation | File | Function/Method |
|-----------|------|-----------------|
| **INSERT** | `src/etl/sec_13f_parser.py` | `generate_sql_inserts()` |

#### `event_contract_trades` / `event_contract_positions`
| Operation | File | Function/Method |
|-----------|------|-----------------|
| **INSERT** | Manual SQL or external ETL | Not in Python code |

#### `schema_migrations` (Migration Tracking)
| Operation | File | Function/Method |
|-----------|------|-----------------|
| **INSERT** | `scripts/deploy_database.py` | Migration deployment |
| **SELECT** | `scripts/run_timestamp_migration.py` | Migration status check |

---

### E. Legacy/Unused Tables

These tables are from earlier NLP pipeline iterations:

| Table | Status | Notes |
|-------|--------|-------|
| `discord_message_chunks` | Legacy | Replaced by `discord_parsed_ideas` |
| `discord_idea_units` | Legacy | Replaced by `discord_parsed_ideas` |
| `stock_mentions` | Legacy | Replaced by structured parsing |
| `discord_processing_log` | Unused | Processing now uses `processing_status` |
| `chart_metadata` | Unused | Chart generation doesn't persist metadata |

---

## 3. Data Flow Diagrams

### A. Discord Message Processing Pipeline

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        DISCORD MESSAGE PIPELINE                              │
└─────────────────────────────────────────────────────────────────────────────┘

Discord Bot (on_message event)
       │
       ▼
┌──────────────────────────────┐
│ src/logging_utils.py         │
│ log_message_to_database()    │──────────────▶ discord_messages (INSERT)
└──────────────────────────────┘
       │
       ▼ (via !process command)
┌──────────────────────────────┐
│ src/channel_processor.py     │
│ process_channel_data()       │
└──────────────────────────────┘
       │
       ▼
┌──────────────────────────────┐     ┌────────────────────────────────┐
│ src/db.py                    │     │ JOIN                            │
│ get_unprocessed_messages()   │◀────│ discord_messages LEFT JOIN      │
└──────────────────────────────┘     │ processing_status               │
       │                              └────────────────────────────────┘
       ▼
┌──────────────────────────────┐
│ src/message_cleaner.py       │
│ process_messages_for_channel │
│ save_to_database()           │──────────────▶ discord_trading_clean (INSERT)
└──────────────────────────────┘              OR discord_market_clean
       │
       ▼
┌──────────────────────────────┐
│ src/db.py                    │
│ mark_message_processed()     │──────────────▶ processing_status (UPSERT)
└──────────────────────────────┘
```

### B. NLP Parsing Pipeline

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          NLP PARSING PIPELINE                                │
└─────────────────────────────────────────────────────────────────────────────┘

scripts/nlp/parse_messages.py --message-id X
       │
       ▼
┌──────────────────────────────┐
│ fetch_pending_messages()     │◀─────────────── discord_messages (SELECT)
│ or --message-id query        │               WHERE parse_status = 'pending'
└──────────────────────────────┘
       │
       ▼
┌──────────────────────────────┐
│ fetch_context_messages()     │◀─────────────── discord_messages (SELECT)
│ [Optional: --context-window] │               Recent messages from same channel
└──────────────────────────────┘
       │
       ▼
┌──────────────────────────────┐
│ src/nlp/preclean.py          │
│ is_bot_command()             │──────▶ Skip before LLM (deterministic)
│ is_url_only()                │
└──────────────────────────────┘
       │
       ▼
┌──────────────────────────────┐
│ src/nlp/openai_parser.py     │
│ process_message()            │──────▶ OpenAI API (triage → parse → escalate)
└──────────────────────────────┘
       │
       ▼
┌──────────────────────────────┐     ┌─────────────────────────────────────┐
│ src/db.py                    │     │ ATOMIC TRANSACTION:                  │
│ save_parsed_ideas_atomic()   │─────│ 1. pg_advisory_xact_lock()           │
└──────────────────────────────┘     │ 2. DELETE discord_parsed_ideas       │
                                      │ 3. INSERT discord_parsed_ideas       │
                                      │ 4. UPDATE discord_messages            │
                                      │    (parse_status, prompt_version)     │
                                      └─────────────────────────────────────┘
```

### C. SnapTrade Data Collection Pipeline

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                      SNAPTRADE COLLECTION PIPELINE                           │
└─────────────────────────────────────────────────────────────────────────────┘

src/snaptrade_collector.py:collect_all_data()
       │
       ├─────────▶ get_accounts() ─────────────────▶ accounts (UPSERT)
       │
       ├─────────▶ get_balances() ─────────────────▶ account_balances (UPSERT)
       │
       ├─────────▶ get_positions() ────────────────▶ positions (UPSERT)
       │                │
       │                └──────▶ extract_symbol_metadata() ──▶ symbols (UPSERT)
       │
       └─────────▶ get_orders() ───────────────────▶ orders (UPSERT)
                        │
                        └──────▶ extract_symbol_metadata() ──▶ symbols (UPSERT)
```

### D. Journal Generation Pipeline

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                       JOURNAL GENERATION PIPELINE                            │
└─────────────────────────────────────────────────────────────────────────────┘

generate_journal.py --force
       │
       ▼
┌──────────────────────────────┐
│ src/data_collector.py        │     ┌────────────────────────────────────┐
│ update_all_data()            │────▶│ Price lookup chain:                 │
└──────────────────────────────┘     │ 1. realtime_prices (SELECT)         │
       │                              │ 2. positions.current_price (SELECT) │
       │                              │ 3. daily_prices (SELECT)            │
       │                              └────────────────────────────────────┘
       │
       ▼
┌──────────────────────────────┐
│ update_position_prices()     │──────────────▶ positions (UPDATE current_price)
└──────────────────────────────┘
       │
       ▼
┌──────────────────────────────┐
│ src/journal_generator.py     │
│ load_discord_messages()      │◀─────────────── discord_messages (SELECT)
└──────────────────────────────┘
       │
       ▼
┌──────────────────────────────┐
│ create_enhanced_journal_     │
│ prompt()                     │──────▶ Gemini/OpenAI API
│ generate_journal_entry()     │
└──────────────────────────────┘
```

### E. Bot Command Table Dependencies

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         BOT COMMAND → TABLE MAP                              │
└─────────────────────────────────────────────────────────────────────────────┘

!portfolio ─────────────▶ positions, account_balances
!movers ────────────────▶ positions, orders
!orders ────────────────▶ orders
!chart SYMBOL ──────────▶ orders (trade overlays), positions (current qty)
!history ───────────────▶ discord_messages (INSERT via log_message_to_database)
!process ───────────────▶ discord_messages → processing_status → discord_trading_clean
!backfill ──────────────▶ discord_messages (INSERT many)
!stats ─────────────────▶ discord_messages, discord_trading_clean, twitter_data
!twitter ───────────────▶ twitter_data
!EOD ───────────────────▶ (external yfinance only, no DB)
```

---

## 4. Table Definitions

### A. Brokerage & Portfolio (SnapTrade)
Core financial data synced from brokerage accounts.

| Table | Primary Key | Description |
| :--- | :--- | :--- |
| **`accounts`** | `id` | Brokerage accounts with total_equity, institution_name |
| **`account_balances`** | `account_id, currency_code, snapshot_date` | Cash and buying power snapshots |
| **`positions`** | `symbol, account_id` | Current holdings with quantity, price, equity |
| **`orders`** | `brokerage_order_id` | Trade history with status, action, execution |
| **`symbols`** | `id` | Reference data for tickers (UNIQUE on ticker) |
| **`trade_history`** | `id` | Historical trade records (UNIQUE on brokerage_order_id) |

### B. Social Sentiment (Discord & Twitter)
Data captured from social platforms for sentiment analysis.

| Table | Primary Key | Description |
| :--- | :--- | :--- |
| **`discord_messages`** | `message_id` | Raw Discord messages with content, author, tickers, parse_status |
| **`discord_market_clean`** | `message_id` | Processed "General" channel messages |
| **`discord_trading_clean`** | `message_id` | Processed "Trading" channel messages with stock_mentions |
| **`discord_processing_log`** | `message_id, channel` | Processing status tracking (legacy) |
| **`twitter_data`** | `tweet_id` | Tweets linked to Discord messages |

### C. NLP Pipeline
Structured extraction from Discord messages using OpenAI.

| Table | Primary Key | Description |
| :--- | :--- | :--- |
| **`discord_parsed_ideas`** | `id` | LLM-parsed ideas with labels, symbols, levels, direction |
| **`discord_message_chunks`** | `message_id, chunk_index` | Message segments (legacy) |
| **`discord_idea_units`** | `message_id, idea_index` | Extracted idea units (legacy) |
| **`stock_mentions`** | `id` | Individual stock mentions (legacy) |

### D. Market Data
Historical and real-time pricing data.

| Table | Primary Key | Description |
| :--- | :--- | :--- |
| **`daily_prices`** | `symbol, date` | End-of-day OHLCV data |
| **`realtime_prices`** | `symbol, timestamp` | Intraday price snapshots |
| **`stock_metrics`** | `symbol, date` | Fundamental metrics (P/E, market cap) |

### E. Event Contracts & Institutional
Specialized data sets.

| Table | Primary Key | Description |
| :--- | :--- | :--- |
| **`event_contract_trades`** | `trade_id` | Event contract trade records |
| **`event_contract_positions`** | `position_id` | Event contract holdings |
| **`institutional_holdings`** | `id` | 13F filing data from SEC |

### F. System & Metadata
Configuration and tracking tables.

| Table | Primary Key | Description |
| :--- | :--- | :--- |
| **`schema_migrations`** | `version` | Migration history with applied_at |
| **`processing_status`** | `message_id, channel` | Message processing flags |
| **`chart_metadata`** | `symbol, period, interval, theme` | Chart generation configs (unused) |

---

## 5. Key Relationships

### Foreign Keys
| From Table | Column | To Table | Column | On Delete |
|------------|--------|----------|--------|-----------|
| `discord_parsed_ideas` | `message_id` | `discord_messages` | `message_id` | CASCADE |

### Unique Constraints (Non-PK)
| Table | Constraint | Columns |
|-------|------------|---------|
| `discord_parsed_ideas` | `discord_parsed_ideas_message_chunk_idx_key` | `message_id, soft_chunk_index, local_idea_index` |
| `symbols` | `symbols_ticker_unique` | `ticker` |
| `trade_history` | `trade_history_brokerage_order_id_key` | `brokerage_order_id` |

---

## 6. RLS Policy Summary

All 19 tables have Row Level Security enabled. Policies are scoped to specific roles:

| Role | Purpose |
|------|---------|
| `anon` | Anonymous read access (SELECT only) |
| `authenticated` | Authenticated user access (SELECT, INSERT, UPDATE, DELETE) |
| `service_role` | Backend service access (bypasses RLS via key) |

Most tables have 2 policies (anon + authenticated). The `service_role` bypasses RLS entirely via the Supabase service role key.

---

## 7. Data Types & Standards

- **Timestamps**: All timestamps use `timestamptz` or `timestamp` (UTC)
- **Financials**: Monetary values use `numeric` or `real` for precision
- **IDs**: Most IDs are `text` (UUIDs) or `bigint` (Discord snowflakes)
- **Arrays**: PostgreSQL arrays for multi-value columns (tickers, labels)
- **JSON**: `jsonb` for complex nested data (levels, label_scores)

---

## 8. Recent Schema Changes (January 2026)

### Migration 047: Document trade_history
- Added documentation comment to trade_history table

### Migration 048: Drop Unused NLP Indexes
- Dropped 5 unused indexes from discord_message_chunks
- Dropped 3 unused indexes from discord_idea_units
- Indexes retained for discord_parsed_ideas (message_id, symbol, labels)

### Migration 049: Drop Legacy NLP Tables
- Dropped `discord_message_chunks` (replaced by discord_parsed_ideas)
- Dropped `discord_idea_units` (replaced by discord_parsed_ideas)
- Dropped `stock_mentions` (replaced by structured parsing)
- Dropped `discord_processing_log` (replaced by processing_status)
- Dropped `chart_metadata` (never actively used)

---

## 9. Batch Pipeline (NLP Backfill)

The batch pipeline provides cost-effective backfill parsing using OpenAI's Batch API.

### Scripts

| Script | Purpose |
|--------|---------|
| `scripts/nlp/batch_backfill.py` | Unified orchestrator (recommended) |
| `scripts/nlp/build_batch.py` | Build JSONL batch input file |
| `scripts/nlp/run_batch.py` | Upload, poll, download batch job |
| `scripts/nlp/ingest_batch.py` | Ingest results into database |

### Prefilters (Same as Live Parsing)

All messages are filtered identically to live parsing:
1. `is_bot_command()` - Skip `!`, `/` commands
2. `is_url_only()` - Skip URL-only messages  
3. `is_bot_response()` - Skip messages from bot users (QBOT, etc.)
4. Empty after cleaning - Skip empty messages

### parse_status Transitions

| From | To | Reason |
|------|-----|--------|
| `pending` | `skipped` | Prefilter matched (bot command, URL-only, bot response) |
| `pending` | `noise` | LLM triage/parser marked as noise |
| `pending` | `ok` | Ideas extracted successfully |
| `pending` | `error` | API error or parse failure |

### Custom ID Format

Deterministic format: `msg-{message_id}-chunk-{chunk_index}`

This format is:
- Parseable by ingestion to recover message_id
- Unique per message chunk
- Works for multi-chunk messages

### Usage

```bash
# Full batch backfill (recommended)
python scripts/nlp/batch_backfill.py --limit 500

# Dry-run validation
python scripts/nlp/batch_backfill.py --dry-run --limit 100

# Individual steps (advanced)
python scripts/nlp/build_batch.py --limit 500 --output batch.jsonl
python scripts/nlp/run_batch.py --input batch.jsonl
python scripts/nlp/ingest_batch.py --input output.jsonl
```

---

## 10. Verification Commands

```bash
# Verify schema alignment
python scripts/verify_database.py --verbose

# Regenerate expected schemas from SQL
python scripts/schema_parser.py --output expected

# Query live table counts
python -c "from src.db import execute_sql; print(execute_sql('SELECT COUNT(*) FROM discord_messages', fetch_results=True))"

# Verify database schema compliance
python scripts/verify_database.py --mode comprehensive
```

---

## 10. Key Implementation Files

| File | Purpose | Primary Tables |
|------|---------|----------------|
| `src/db.py` | Database layer with atomic helpers | All tables |
| `src/logging_utils.py` | Discord message capture | discord_messages |
| `src/message_cleaner.py` | Message cleaning & sentiment | discord_*_clean |
| `src/channel_processor.py` | Processing orchestration | discord_messages, processing_status |
| `src/snaptrade_collector.py` | Brokerage data sync | accounts, positions, orders, symbols |
| `src/data_collector.py` | Market data & prices | positions, *_prices, trade_history |
| `src/twitter_analysis.py` | Twitter integration | twitter_data, discord_messages |
| `src/nlp/openai_parser.py` | LLM parsing | discord_parsed_ideas |
| `scripts/nlp/parse_messages.py` | NLP batch processing | discord_messages, discord_parsed_ideas |
| `src/bot/commands/*.py` | Discord bot commands | Various (see section 3E) |
