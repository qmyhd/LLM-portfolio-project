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

# Validate Robinhood positions against DB
python scripts/validate_robinhood.py --positions data/Robinhood_official_Reports/Jun2023–Feb2026.csv

# Backfill SnapTrade activities
python scripts/backfill_activities.py --start 2020-01-01
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
- **`src/snaptrade_collector.py`** — SnapTrade ETL (accounts, positions, orders, balances) with stale position reconciliation (safety-guarded: connection health, count sanity, sync recency)
- **`src/databento_collector.py`** — Databento OHLCV → Supabase upsert + optional S3 archive
- **`src/retry_utils.py`** — `@hardened_retry()` for API calls, `@database_retry()` for DB operations, `@snaptrade_retry()` for SnapTrade SDK calls (429 rate-limit aware)
- **`src/market_data_service.py`** — yfinance wrapper with TTL caching for real-time quotes, company info, return metrics, and search fallback
- **`src/market_data_service.py`** — yfinance wrapper with TTL caching for real-time quotes. Defines `CRYPTO_IDENTITY` dict (TradingView symbol mapping) and `_CRYPTO_SYMBOLS` frozenset (13 crypto tickers) used as guards against Databento ticker collisions.
- **`src/message_cleaner.py`** — Ticker extraction (`$AAPL`, `$BRK.B`), sentiment scoring via vaderSentiment
- **`src/openbb_service.py`** — OpenBB Platform SDK wrapper. Thread-safe TTL caches (transcripts 24h, fundamentals 1h, news 15m). FMP provider for fundamentals/transcripts/management/news, SEC provider for filings (free). Never raises — returns `None`/`[]` on failure. Requires `FMP_API_KEY` for FMP data.
- **`src/discord_ingest.py`** — Incremental Discord message ingestion with cursor-based tracking and content hash deduplication
- **`src/analysis/`** — Multi-agent stock analysis system (5 deterministic agents + LLM consensus):
  - `models.py` — Shared Pydantic models: `AnalysisInput`, `AnalystSignal`, `ConsensusReport`, `OHLCVBar`, `IdeaData`, `NewsItem`
  - `indicators.py` — Technical indicator math library (RSI, MACD, Bollinger, EMA, SMA, ADX, ATR, Hurst)
  - `technical.py` — 5-strategy weighted signal system (trend, mean_reversion, momentum, volatility, stat_arb)
  - `fundamental.py` — 4-pillar threshold scoring (profitability, growth, financial health, valuation)
  - `valuation.py` — 4-model weighted DCF (owner earnings, enhanced DCF, EV/EBITDA, residual income)
  - `sentiment.py` — 3-source aggregation (Discord ideas with time decay, Discord sentiment proxy, news keywords)
  - `risk.py` — Per-stock risk (annualized vol, max drawdown, position sizing) + portfolio-wide (VaR, HHI, correlation)
  - `consensus.py` — Deterministic scoring + OpenAI narrative generation (gpt-5-mini, escalates to gpt-5 on conflict)
  - `orchestrator.py` — Cache-first dispatch with stale-while-revalidate. Assembles `AnalysisInput` from 6 data sources. TTL: 4h equity, 1h crypto, 2h portfolio risk. Parallel agent execution via `asyncio.gather()`

### Discord Bot (`src/bot/`)

Modular command pattern. Each command file in `src/bot/commands/` exports a `register(bot, twitter_client=None)` function. UI components live in `src/bot/ui/` (embed factory, pagination, portfolio views).

### Database Schema

Consolidated schema in `schema/` (060_baseline_current.sql + 061-068 incremental, older files archived). 23 active tables. Recent migrations: 062 (stock_notes), 063 (discord_ingest_cursors), 064 (user_ideas), 065 (account_balances PK), 066 (accounts connection_status), 067 (stock_analysis_cache + portfolio_risk_cache), 068 (position_snapshots). Core tables: `discord_messages`, `discord_parsed_ideas`, `ohlcv_daily`, `positions`, `orders`, `accounts`, `account_balances`, `activities`, `user_ideas`, `twitter_data`, `stock_profile_current`, `stock_notes`, `discord_ingest_cursors`, `stock_analysis_cache`, `portfolio_risk_cache`, `position_snapshots`. All tables have RLS enabled — service role key required in DATABASE_URL.

### FastAPI Routes (`app/routes/`)

16 route files: `portfolio.py` (positions, sync, movers, sparklines), `orders.py`, `stocks.py` (profile, ideas, OHLCV), `openbb.py` (transcripts, fundamentals, filings, news, notes), `analysis.py` (multi-agent stock analysis, portfolio risk), `trades.py` (unified trade feed with P/L enrichment), `chat.py`, `search.py`, `watchlist.py`, `ideas.py` (CRUD, refine with 3-pass self-reflection, context), `activities.py`, `connections.py`, `sentiment.py`, `webhook.py`, `debug.py` (opt-in via `DEBUG_ENDPOINTS=1`).

### Deployment

**Auto-deploy**: Every push to `main` triggers `.github/workflows/deploy.yml` → SSH into EC2 → `scripts/deploy_ec2.sh` (pull, pip install, doctor checks, restart services, health check). Monitor at GitHub Actions tab.

**EC2 services**: `api.service` (FastAPI), `discord-bot.service` (long-running), `nightly-pipeline.service` + `.timer` (1 AM ET cron). Secrets via AWS Secrets Manager (`USE_AWS_SECRETS=1`). No Docker.

**Scripts**: `scripts/deploy_ec2.sh` (canonical deploy), `scripts/doctor_ec2.sh` (environment health check).

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
from src.retry_utils import hardened_retry, database_retry, snaptrade_retry
@hardened_retry(max_retries=3, delay=2)
def call_external_api(): ...
@snaptrade_retry()  # SnapTrade SDK calls (handles 429 rate limits)
def call_snaptrade(): ...
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
