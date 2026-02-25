# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

LLM Portfolio Journal is a data-driven portfolio analytics system that integrates brokerage data (SnapTrade), market prices (Databento OHLCV), Discord message collection with NLP parsing, and Twitter/X sentiment analysis. It provides a Discord bot interface and optional FastAPI backend, deployed on EC2 via systemd services.

**Stack**: Python 3.11+ | PostgreSQL/Supabase (no SQLite) | SQLAlchemy 2.0 | Discord.py | OpenAI structured outputs | Databento | SnapTrade SDK

## Common Commands

```bash
# Run the Discord bot
python -m src.bot.bot

# Run tests (CI mirrors this)
pytest tests/ -v -m "not openai and not integration"

# Run tests with coverage
pytest tests/ -v --cov=src --cov-report=term-missing

# Run a single test file
pytest tests/test_preclean.py -v

# Lint
ruff check src/ tests/

# Type check
pyright src/

# Pre-deployment validation
python tests/validate_deployment.py

# Database schema verification
python scripts/verify_database.py --verbose

# Deploy schema migrations
python scripts/deploy_database.py

# OHLCV data backfill
python scripts/backfill_ohlcv.py --daily

# NLP batch processing
python scripts/nlp/parse_messages.py

# Nightly pipeline (EC2 production)
python scripts/nightly_pipeline.py
```

## Architecture

### Data Flow

```
SnapTrade API  ─┐
Discord msgs   ─┼→ PostgreSQL (Supabase) → NLP Parser → discord_parsed_ideas
Databento OHLCV ─┤                         (OpenAI structured outputs)
Twitter/X      ─┤
OpenBB (FMP+SEC)─┘→ Cached fundamentals/filings/news → FastAPI → Next.js frontend
```

### Key Modules

- **`src/db.py`** — SQLAlchemy 2.0 engine singleton with connection pooling (pool_size=5, pre_ping=True). All DB access goes through `execute_sql(query, params, fetch_results)` using named `:param` placeholders.
- **`src/config.py`** — Pydantic Settings that auto-loads `.env`. Access via `settings()` (cached). `get_database_url()` returns PostgreSQL URL only.
- **`src/price_service.py`** — Sole source for OHLCV price data from the `ohlcv_daily` table (Databento source). Replaces all legacy price tables.
- **`src/nlp/`** — NLP pipeline with tiered model routing:
  - `openai_parser.py` — Triage (nano) → Main (mini, 80%+ of messages) → Escalation (large, complex content)
  - `schemas.py` — Pydantic models: `ParsedIdea`, `MessageParseResult`, `TradingLabels` enum (13 label types)
  - `preclean.py` — Deterministic pre-LLM ticker extraction. `RESERVED_SIGNAL_WORDS` (80+ terms) prevents false positives like "target" → $TGT. `ALIAS_MAP` resolves company names to tickers.
  - `soft_splitter.py` — Deterministic message splitting for long content
- **`src/snaptrade_collector.py`** — SnapTrade ETL (accounts, positions, orders, balances)
- **`src/databento_collector.py`** — Databento OHLCV → Supabase upsert + optional S3 archive
- **`src/retry_utils.py`** — `@hardened_retry()` for API calls, `@database_retry()` for DB operations
- **`src/market_data_service.py`** — yfinance wrapper with TTL caching for real-time quotes, company info, return metrics, and search fallback
- **`src/message_cleaner.py`** — Ticker extraction (`$AAPL`, `$BRK.B`), sentiment scoring via vaderSentiment
- **`src/openbb_service.py`** — OpenBB Platform SDK wrapper. Thread-safe TTL caches (transcripts 24h, fundamentals 1h, news 15m). FMP provider for fundamentals/transcripts/management/news, SEC provider for filings (free). Never raises — returns `None`/`[]` on failure. Requires `FMP_API_KEY` for FMP data.

### Discord Bot (`src/bot/`)

Modular command pattern. Each command file in `src/bot/commands/` exports a `register(bot, twitter_client=None)` function. UI components live in `src/bot/ui/` (embed factory, pagination, portfolio views).

### Database Schema

Consolidated schema in `schema/` (060_baseline_current.sql + 061_cleanup, older files archived). Core tables: `discord_messages`, `discord_parsed_ideas`, `ohlcv_daily`, `positions`, `orders`, `accounts`, `account_balances`, `twitter_data`, `stock_profile_current`, `stock_notes`. All tables have RLS enabled — service role key required in DATABASE_URL.

### Deployment

EC2 systemd services: `discord-bot.service` (long-running), `api.service` (FastAPI), `nightly-pipeline.service` + `.timer` (1 AM ET cron). Secrets via AWS Secrets Manager (`USE_AWS_SECRETS=1`). No Docker.

## Critical Patterns

**Database — always use named placeholders:**
```python
from src.db import execute_sql, get_connection
execute_sql("SELECT * FROM positions WHERE symbol = :symbol", params={'symbol': 'AAPL'}, fetch_results=True)
```

**Advisory locks required for discord_parsed_ideas writes:**
```python
lock_key = int(message_id) if str(message_id).isdigit() else hash(str(message_id)) & 0x7FFFFFFFFFFFFFFF
execute_sql("SELECT pg_advisory_xact_lock(:lock_key)", params={"lock_key": lock_key})
# Then: DELETE existing → INSERT new (within same transaction)
```

**Retry decorators required for all external API calls:**
```python
from src.retry_utils import hardened_retry, database_retry
@hardened_retry(max_retries=3, delay=2)
def call_external_api(): ...
```

**File paths — always use pathlib.Path, never string concatenation.**

## Constraints

- PostgreSQL-only — no SQLite fallback anywhere
- `src/db.py`, `src/config.py`, and `src/retry_utils.py` are foundational — modify with extreme care
- Ruff config: line-length 120, target Python 3.11
- CI runs on Python 3.11 and 3.12, skips tests marked `openai` or `integration`
- Coverage threshold: 20% (most bot commands need external services)
- NLP batch processing uses OpenAI Batch API for 50% cost savings (`scripts/nlp/`)

## Canonical References

- **AGENTS.md** — Authoritative AI contributor guide (setup, patterns, rules)
- **docs/ARCHITECTURE.md** — System architecture deep-dive
- **.github/copilot-instructions.md** — Code patterns and integration examples
