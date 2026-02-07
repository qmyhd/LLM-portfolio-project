# Full Codebase Audit Report

> **Generated**: July 2026  
> **Scope**: `LLM-portfolio-project` (backend) + `LLM-portfolio-frontend` (Next.js)  
> **Purpose**: File-by-file documentation, overlap/redundancy tracking, issue inventory

---

## Table of Contents

1. [Auth Fix Verification](#1-auth-fix-verification)
2. [Backend: src/ Python Modules](#2-backend-src-python-modules)
3. [Backend: src/bot/ Discord Bot](#3-backend-srcbot-discord-bot)
4. [Backend: src/nlp/ NLP Pipeline](#4-backend-srcnlp-nlp-pipeline)
5. [Backend: app/ FastAPI Routes](#5-backend-app-fastapi-routes)
6. [Backend: scripts/](#6-backend-scripts)
7. [Backend: schema/ Migrations](#7-backend-schema-migrations)
8. [Backend: systemd/ Services](#8-backend-systemd-services)
9. [Frontend: Pages & Routing](#9-frontend-pages--routing)
10. [Frontend: API Routes](#10-frontend-api-routes)
11. [Frontend: Components](#11-frontend-components)
12. [Frontend: Hooks, Lib, Types](#12-frontend-hooks-lib-types)
13. [Config & Root Files](#13-config--root-files)
14. [Documentation Accuracy](#14-documentation-accuracy)
15. [Tests](#15-tests)
16. [Agents (.agent.md)](#16-agents-agentmd)
17. [Issue Inventory](#17-issue-inventory)
18. [Overlaps & Redundancies](#18-overlaps--redundancies)
19. [Recommended Actions](#19-recommended-actions)

---

## 1. Auth Fix Verification

### Problem
Vercel build error: `Module not found: Can't resolve '@/auth'`

### Root Cause
`auth.ts` was at `frontend/auth.ts` (project root) but `tsconfig.json` maps `@/*` → `./src/*`, so `@/auth` resolved to `frontend/src/auth.ts` which didn't exist.

### Fix Applied
| Action | File | Status |
|--------|------|--------|
| Created | `frontend/src/auth.ts` | ✅ NextAuth v5 config (Google OAuth + email allowlist) |
| Moved | `frontend/middleware.ts` → `frontend/src/middleware.ts` | ✅ Next.js src-directory convention |
| Deleted | `frontend/auth.ts` (stale root copy) | ✅ Confirmed removed |

### Verification
All 4 consuming files resolve with zero structural errors:
- `src/app/api/auth/[...nextauth]/route.ts` → imports `{ handlers }` from `@/auth`
- `src/middleware.ts` → imports `{ auth }` from `@/auth`
- `src/lib/api-client.ts` → imports `{ auth }` from `@/auth`
- `src/app/login/page.tsx` → imports from `next-auth/react` (client import, correct)

**NextAuth Version**: v5 (`next-auth@5.0.0-beta.25`). No mixed v4/v5 patterns found.

---

## 2. Backend: src/ Python Modules

### Core Services

| File | Lines | Purpose | Status |
|------|-------|---------|--------|
| `src/db.py` | ~1048 | SQLAlchemy 2.0 engine, `execute_sql()`, `save_parsed_ideas_atomic()`, `transaction()`, connection pooling, health checks | ✅ Active |
| `src/config.py` | ~280 | Pydantic `Settings` with env var mapping, `get_database_url()` | ✅ Active |
| `src/retry_utils.py` | ~140 | `@hardened_retry`, `@database_retry` decorators | ✅ Active (dead `__main__` block removed) |
| `src/env_bootstrap.py` | ~80 | AWS Secrets Manager → env vars bootstrap | ✅ Active (EC2) |
| `src/logging_utils.py` | ~215 | `configure_logging()`, `log_message_to_database()` | ✅ Active (dead CSV path removed) |
| `src/price_service.py` | ~185 | `get_ohlcv()`, `get_latest_close()`, `get_previous_close()` — Supabase `ohlcv_daily` | ✅ Active |

### Data Collection

| File | Lines | Purpose | Status |
|------|-------|---------|--------|
| `src/snaptrade_collector.py` | ~1371 | SnapTrade ETL: positions, orders, accounts, balances | ✅ Active (dead SQLite ref removed) |
| `src/databento_collector.py` | ~350 | Databento OHLCV daily bars → Supabase | ✅ Active |
| `src/twitter_analysis.py` | ~1288 | Twitter data collection + sentiment analysis | ✅ Active (dead CSV functions removed) |
| `src/message_cleaner.py` | ~1301 | Ticker extraction (`$AAPL`), sentiment, text cleaning | ✅ Active |
| `src/channel_processor.py` | ~245 | Process Discord channel data → `discord_*_clean` tables | ✅ Active (SQL injection fixed — parameterized) |

### Analysis & Generation

| File | Lines | Purpose | Status |
|------|-------|---------|--------|
| `src/position_analysis.py` | ~400 | Portfolio metrics, FIFO P/L calculation | ✅ Active (layering violation fixed — uses `trade_queries.py`) |
| `src/journal_generator.py` | ~1160 | Generate journal entries from CSV data | ⚠️ Legacy CSV-based (not DB-first) |
| `src/expected_schemas.py` | ~230 | Schema validation metadata | ✅ Regenerated (17 tables, includes `ohlcv_daily`) |

---

## 3. Backend: src/bot/ Discord Bot

### Infrastructure

| File | Purpose |
|------|---------|
| `src/bot/__init__.py` | `create_bot()` factory — wires intents, help, events, commands |
| `src/bot/bot.py` | Main entry point — AWS bootstrap → config → optional Tweepy → run |
| `src/bot/events.py` | `on_ready` + `on_message` handlers, channel type mapping, real-time message logging |
| `src/bot/help.py` | `PortfolioHelpCommand` — 5 categories, dropdown navigation, hidden commands |

### Commands (19 total)

| Command | Aliases | File | Data Source |
|---------|---------|------|-------------|
| `!chart SYMBOL [period] [type]` | — | chart.py | `ohlcv_daily` + positions/orders |
| `!position SYMBOL` | — | chart.py | positions table |
| `!EOD` | — | eod.py | `ohlcv_daily` via `get_ohlcv()` |
| `!history [limit]` | — | history.py | Discord API → `discord_messages` |
| `!process [channel_type]` | — | process.py | Discord API → `discord_*_clean` |
| `!backfill [channel_type]` | — | process.py | Discord API (one-time historical) |
| `!peekraw [limit]` | — | process.py | Raw JSON debug dump |
| `!fetch` | `sync`, `refresh` | snaptrade_cmd.py | SnapTrade API → DB |
| `!portfolio` | `positions`, `holdings` | snaptrade_cmd.py | DB positions |
| `!piechart` | `pie`, `allocation` | snaptrade_cmd.py | DB positions → matplotlib |
| `!orders` | `recent_orders`, `trades` | snaptrade_cmd.py | DB orders |
| `!movers` | `gainers`, `losers`, `pnl` | snaptrade_cmd.py | DB positions |
| `!status` | `data_status`, `db` | snaptrade_cmd.py | DB metadata |
| ~~`!auto_on`~~ | — | *(removed)* | Replaced by `nightly-pipeline.timer` |
| ~~`!auto_off`~~ | — | *(removed)* | Replaced by `nightly-pipeline.timer` |
| `!twitter [SYMBOL]` | — | twitter_cmd.py | `twitter_data` table |
| `!tweets` | — | twitter_cmd.py | `twitter_data` table |
| `!twitter_stats` | — | twitter_cmd.py | `twitter_data` table |
| `!twitter_backfill` | — | twitter_cmd.py | Discord → Twitter links |

### UI Design System

| File | Lines | Purpose |
|------|-------|---------|
| `src/bot/ui/embed_factory.py` | 500 | `EmbedFactory` + `EmbedCategory` enum (15 categories) + formatters |
| `src/bot/ui/pagination.py` | 133 | `PaginatedView` base class |
| `src/bot/ui/portfolio_view.py` | 421 | Interactive portfolio with filters (All/Winners/Losers) |
| `src/bot/ui/portfolio_chart.py` | 384 | Matplotlib pie chart with logos |
| `src/bot/ui/help_view.py` | 259 | Dropdown help navigation |
| `src/bot/ui/logo_helper.py` | 560 | Multi-provider logo fetch + cache (Logo.dev, Logokit) |
| `src/bot/ui/symbol_resolver.py` | 292 | User input → canonical ticker resolution |
| `src/bot/formatting/orders_view.py` | 974 | Order display formatting, OCC option parsing |

---

## 4. Backend: src/nlp/ NLP Pipeline

| File | Lines | Purpose |
|------|-------|---------|
| `src/nlp/openai_parser.py` | ~1719 | Main LLM parser: triage → main → escalation model routing |
| `src/nlp/schemas.py` | ~350 | Pydantic schemas: `ParsedIdea`, `MessageParseResult`, 13 `TradingLabels`, `ParseStatus` |
| `src/nlp/soft_splitter.py` | ~200 | Deterministic message splitting for long content |
| `src/nlp/preclean.py` | ~400 | `ALIAS_MAP` (~100 entries), `RESERVED_SIGNAL_WORDS` (80+ terms), `extract_candidate_tickers()`, `validate_llm_tickers()` |

**Pipeline flow**: `discord_messages` → triage (skip/parse) → main parse (structured output) → escalation (if too complex) → `discord_parsed_ideas`

---

## 5. Backend: app/ FastAPI Routes

### Authentication
- `app/auth.py`: Bearer token auth via `API_SECRET_KEY`, constant-time comparison, dev fallback

### Endpoints

| Method | Path | File | Purpose |
|--------|------|------|---------|
| GET | `/` | main.py | Welcome message |
| GET | `/health` | main.py | Health check (no auth) |
| GET | `/portfolio` | portfolio.py | Positions + summary with current prices |
| POST | `/portfolio/sync` | portfolio.py | Trigger SnapTrade sync |
| GET | `/orders` | orders.py | Order history with filters |
| POST | `/orders/{id}/notify` | orders.py | Mark order notified |
| GET | `/stocks/{ticker}` | stocks.py | Stock profile + pricing |
| GET | `/stocks/{ticker}/ideas` | stocks.py | Parsed trading ideas |
| GET | `/stocks/{ticker}/ohlcv` | stocks.py | OHLCV chart data + order overlays |
| POST | `/stocks/{ticker}/chat` | chat.py | AI chat about a stock |
| GET | `/search` | search.py | Symbol search by prefix/name |
| GET | `/watchlist` | watchlist.py | Current prices for tickers |
| POST | `/watchlist/validate` | watchlist.py | Validate ticker exists |
| POST | `/webhook/snaptrade` | webhook.py | SnapTrade webhook (HMAC verified) |

### Issues
- **BUG**: `watchlist.py` L128 queries `WHERE UPPER(symbol) = :symbol` but `symbols` table column is `ticker`. Also references `name` but column is `description`.
- **TODO**: `portfolio.py` `dayChange` hardcoded to `0.0` — never calculates actual day change.

---

## 6. Backend: scripts/

### Active Production (EC2 nightly pipeline)

| Script | Trigger | Purpose |
|--------|---------|---------|
| `nightly_pipeline.py` | systemd timer (1 AM daily) | Orchestrates: OHLCV backfill → NLP batch → stock profiles |
| `backfill_ohlcv.py` | nightly_pipeline.py | Databento OHLCV daily bars → Supabase |
| `refresh_stock_profiles.py` | nightly_pipeline.py | Refresh `stock_profile_current` from positions + OHLCV |
| `start_bot_with_secrets.py` | systemd service | AWS secrets → env → run Discord bot |

### NLP Batch Pipeline

| Script | Purpose |
|--------|---------|
| `scripts/nlp/parse_messages.py` | Live message parsing (OpenAI) |
| `scripts/nlp/build_batch.py` | Build OpenAI Batch API request file |
| `scripts/nlp/run_batch.py` | Submit batch to OpenAI |
| `scripts/nlp/ingest_batch.py` | Ingest batch results → `discord_parsed_ideas` |
| `scripts/nlp/batch_backfill.py` | Unified batch orchestrator |

### Manual / Maintenance

| Script | Purpose |
|--------|---------|
| `bootstrap.py` | Local dev setup (deps, DB connectivity, health checks) |
| `deploy_database.py` | Deploy schema migrations |
| `verify_database.py` | Validate 17+ tables + constraints |
| `snaptrade_notify.py` | Discord webhook for new order notifications |

### Dead / Deprecated

| Script | Status | Notes |
|--------|--------|-------|
| `daily_pipeline.py` | **TOMBSTONE** | Contains only deprecation notice → use `nightly_pipeline.py` |
| `run_pipeline_with_secrets.sh` | **TOMBSTONE** | Contains only deprecation notice |
| `verify_schema_state.sql` | **DEAD** | References dropped tables |
| `scripts/testing/` | **EMPTY** | Empty directory |

### EC2 Bootstrap Overlap

Three scripts cover similar ground (EC2 provisioning):
- `bootstrap.sh` — Ubuntu-oriented
- `ec2_user_data.sh` — Amazon Linux 2023 user data
- `setup_ec2_services.sh` — systemd service installation

---

## 7. Backend: schema/ Migrations

**Total files**: 45 (000 baseline + migrations 015–058, note: 050 is missing)

### Current Active Tables (17)

| Table | Purpose |
|-------|---------|
| `accounts` | Brokerage accounts (SnapTrade) |
| `account_balances` | Account balance snapshots |
| `positions` | Current stock positions |
| `orders` | Trade orders with fill status |
| `symbols` | Ticker metadata + logo URLs |
| `ohlcv_daily` | Databento OHLCV price data |
| `discord_messages` | Raw Discord messages |
| `discord_market_clean` | Cleaned market channel messages |
| `discord_trading_clean` | Cleaned trading channel messages |
| `discord_parsed_ideas` | NLP-parsed trading ideas |
| `twitter_data` | Twitter/X posts and sentiment |
| `institutional_holdings` | 13F institutional holdings |
| `symbol_aliases` | Company name → ticker mappings |
| `stock_profile_current` | Current stock profiles (derived) |
| `stock_profile_history` | Historical stock profile snapshots |
| `processing_status` | System processing state |
| `schema_migrations` | Migration tracking |

### Dropped Tables (in later migrations)
- 049: discord_message_chunks, discord_idea_units, stock_mentions, discord_processing_log
- 051: daily_prices, realtime_prices, stock_metrics
- 052: event_contract_trades, event_contract_positions, trade_history
- 054: chart_metadata

### Issues
- **Baseline stale**: `000_baseline.sql` still defines 6+ dropped tables (historical reference only)

---

## 8. Backend: systemd/ Services

| File | Type | Purpose |
|------|------|---------|
| `api.service` | Long-running | FastAPI on 127.0.0.1:8000 (Nginx fronts). MemoryMax=1G |
| `discord-bot.service` | Long-running | Discord bot via `start_bot_with_secrets.py`. MemoryMax=500M |
| `nightly-pipeline.service` | One-shot | Nightly data pipeline. 30min timeout |
| `nightly-pipeline.timer` | Timer | 1:00 AM daily ET, persistent, 5min random delay |
| `README.md` | Docs | Installation guide, AWS secrets setup, journald config |

---

## 9. Frontend: Pages & Routing

| Page | File | Data Source | Layout |
|------|------|-------------|--------|
| Dashboard | `src/app/page.tsx` | Delegates to child components | Sidebar + TopBar ✅ |
| Login | `src/app/login/page.tsx` | `next-auth/react` client signIn | Standalone ✅ |
| Orders | `src/app/orders/page.tsx` | **REAL** — `/api/orders` | Sidebar + TopBar ✅ |
| Positions | `src/app/positions/page.tsx` | **REAL** — `/api/portfolio` | Sidebar + TopBar ✅ |
| Watchlist | `src/app/watchlist/page.tsx` | **REAL** — `/api/watchlist` + localStorage | Sidebar + TopBar ✅ |
| Stock Hub | `src/app/stock/[ticker]/page.tsx` | Delegates to `StockHubContent` | Sidebar + TopBar ✅ |

---

## 10. Frontend: API Routes

All routes proxy to FastAPI backend via `backendFetch()` with Bearer token auth.

| Route | Auth | Cache | Backend Endpoint |
|-------|------|-------|------------------|
| `/api/auth/[...nextauth]` | NextAuth | — | Google OAuth |
| `/api/chart-data` | ✅ | — | `/ohlcv/...` |
| `/api/orders` | ✅ | 30s | `/orders` |
| `/api/portfolio` | ✅ | 30s (GET) | `/portfolio` |
| `/api/search` | ✅ | 60s | `/search` |
| `/api/stocks/[ticker]` | ✅ | 60s | `/stocks/{ticker}` |
| `/api/stocks/[ticker]/ideas` | ✅ | 60s | `/stocks/{ticker}/ideas` |
| `/api/stocks/[ticker]/ohlcv` | ✅ | 5min | `/stocks/{ticker}/ohlcv` |
| `/api/watchlist` | ✅ | 30s (GET) | `/watchlist` |

**Issue**: All API routes now have `authGuard()`. ✅ Resolved.

---

## 11. Frontend: Components

### Dashboard Components (SentimentOverview uses MOCK; rest are wired to live API)

| Component | Lines | Data | Purpose |
|-----------|-------|------|---------|
| `PortfolioPieChart.tsx` | 337 | Props (real) | SVG pie chart with logos, links to stock pages |
| `PortfolioSummary.tsx` | ~80 | **REAL** — `usePortfolio()` | Summary cards (value, daily P/L, open P/L) |
| `PositionsTable.tsx` | ~120 | **REAL** — `usePortfolio()` | Sortable positions table |
| `RecentOrders.tsx` | ~100 | **REAL** — SWR `/api/orders` | 5 recent orders with status badges |
| `SentimentOverview.tsx` | 107 | **MOCK** | Bull/bear/neutral sentiment |
| `TopMovers.tsx` | ~80 | **REAL** — derived from positions | Top 3 gainers and losers |

### Stock Components

| Component | Lines | Data | Purpose |
|-----------|-------|------|---------|
| `StockHubContent.tsx` | 263 | Orchestrator | Three-column stock page layout |
| `StockChart.tsx` | 429 | **REAL** | lightweight-charts OHLCV with order markers |
| `TradingViewChart.tsx` | 293 | **REAL** | TradingView widget embed |
| `StockMetrics.tsx` | 179 | **MOCK** | Price, volume, sentiment badges |
| `IdeasPanel.tsx` | 352 | **REAL** | NLP trading ideas with filters |
| `PositionCard.tsx` | 146 | **REAL** | Position P/L display |
| `SentimentCard.tsx` | 136 | **REAL** | Bull/bear/neutral from stock profile |
| `RiskCard.tsx` | 133 | **MOCK** | Risk metrics (beta, Sharpe, etc.) |
| `ChatWidget.tsx` | 205 | **MOCK** | AI chat placeholder |
| `RawMessagesPanel.tsx` | 168 | **MOCK** | Discord raw messages (fetch commented out) |

### Layout Components

| Component | Lines | Purpose |
|-----------|-------|---------|
| `Sidebar.tsx` | 222 | Navigation + favorite stocks (localStorage) |
| `TopBar.tsx` | 319 | Search bar (REAL API) + mobile menu |
| `LiveUpdatesToggle.tsx` | 90 | Polling toggle button |

---

## 12. Frontend: Hooks, Lib, Types

### Hooks

| Hook | Data | Purpose |
|------|------|---------|
| `usePortfolio.ts` | **REAL** — SWR | Portfolio fetch with polling toggle |
| `useIdeas.ts` | **REAL** — SWR | Ideas fetch with direction filter + polling |
| `useLiveUpdates.ts` | Zustand | Global live-polling state (localStorage persisted) |

### Lib

| File | Purpose |
|------|---------|
| `api-client.ts` | `backendFetch()` with Bearer auth, `authGuard()`, `requireAuth()` |

### Types

| File | Lines | Issue |
|------|-------|-------|
| `types/api.ts` | 249 | Canonical API types matching FastAPI. 13 `TradingLabel` values. |
| `types/index.ts` | 158 | **Partially duplicates** `api.ts` — own `Position`, `Order`, `Direction`, `TradingLabel` (10 vs 13 labels). |

---

## 13. Config & Root Files

| File | Purpose | Status |
|------|---------|--------|
| `pyproject.toml` | Build config, Ruff, pytest, coverage | ✅ Current (Python ≥3.11) |
| `requirements.txt` | 33 pinned dependencies | ✅ Current |
| `template.yaml` | AWS SAM Lambda template (alternative to EC2) | ⚠️ Unclear if maintained |
| `AGENTS.md` | Canonical AI contributor guide | ✅ Current |
| `CLAUDE.md` | Claude Code guidance | ✅ Current |
| `README.md` | Project README | ✅ Current (Python 3.11+) |
| `.env.example` | Env var template (173 lines) | ✅ `SQLITE_PATH` commented as deprecated |
| `nginx/api.conf` | Nginx reverse proxy config | ✅ Current |

---

## 14. Documentation Accuracy

| Doc | Claim | Reality | Status |
|-----|-------|---------|--------|
| `docs/schema-report.md` | "17 Active Tables" | 17 tables | ✅ Correct |
| `docs/legacy-migrations.md` | "57 migration files" | 45 files | ⚠️ Update count |
| `docs/EC2_README.md` | Links to `EC2_DEPLOYMENT.md` | File exists | ✅ Fixed (was EC2_SETUP_DETAILED.md) |
| `README.md` | "Python 3.11+" | pyproject.toml requires ≥3.11 | ✅ Correct |
| `.env.example` | `SQLITE_PATH` commented as deprecated | SQLite is banned | ✅ Acceptable |
| `src/expected_schemas.py` | Includes `ohlcv_daily`, 17 tables | Matches production | ✅ Regenerated |

---

## 15. Tests

**16 test files** + conftest.py + fixtures/ + validate_deployment.py

| File | Focus |
|------|-------|
| `test_integration.py` | Core module import validation |
| `test_preclean.py` | Ticker extraction + alias mapping |
| `test_preclean_codeblock.py` | Code block handling |
| `test_core_functions.py` | Prompt builder |
| `test_openai_parser.py` | OpenAI parser unit tests |
| `test_parser_regression.py` | Parser regression (JSONL fixtures) |
| `test_triage_regression.py` | Triage regression (JSONL fixtures) |
| `test_nlp_batch.py` | Batch processing |
| `test_chunk_indexing.py` | Chunk indexing logic |
| `test_databento_collector.py` | Databento OHLCV tests |
| `test_dividend_detection.py` | Dividend detection |
| `test_message_id_string.py` | Message ID handling |
| `test_orders_formatting.py` | Orders formatting |
| `test_schema_parser.py` | Schema parser |
| `test_symbol_resolver.py` | Symbol resolver |
| `test_verification_script.py` | Verification script |

CI runs on Python 3.11 + 3.12, skips `openai` and `integration` markers.

---

## 16. Agents (.agent.md)

| File | Agent Name | Purpose | Issues |
|------|-----------|---------|--------|
| `portfolio-assistant.agent.md` | Portfolio Assistant | Primary coder + delegator | None |
| `docs-agent.agent.md` | Documentation Assistant | Read-only codebase explanation | None |
| `planner.agent.md` | Plan | Multi-step planning | None |
| `repo-audit.agent.md` | Repo Audit & Documentation Assistant | Read-only auditing | Has edit tools despite "read-only" description |
| `se-ux-ui-designer.agent.md` | SE: UX Designer | UX research | None |
| `AGENT_MD_FORMAT_GUIDE.md` | — | Format reference | Not an agent (guide only) |

---

## 17. Issue Inventory

### HIGH Severity

| # | Location | Issue | Status |
|---|----------|-------|--------|
| H1 | `src/channel_processor.py` ~L180 | **SQL injection risk**: f-string interpolation for `message_ids` in SQL query | ✅ Fixed — parameterized query |
| H2 | `app/routes/watchlist.py` L128 | **BUG**: Queries `WHERE UPPER(symbol)` but `symbols` table column is `ticker`. Also queries `name` but column is `description`. | ✅ Fixed — columns corrected |

### MEDIUM Severity

| # | Location | Issue | Status |
|---|----------|-------|--------|
| M1 | `src/position_analysis.py` | Imports from `src.bot.commands.chart` — core module depends on bot (layering violation) | ✅ Fixed — `trade_queries.py` extracted |
| M2 | `src/bot/commands/eod.py` L21, L68 | References `EmbedCategory.MARKET` — enum member doesn't exist | ✅ Fixed — MARKET added to enum |
| M3 | `src/expected_schemas.py` | Missing `ohlcv_daily` table, stale metadata (wrong table count) | ✅ Fixed — regenerated with 17 tables |
| M4 | `schema/` | Migration 050 (`ohlcv_daily` creation) missing from tracked files | ✅ Fixed — `schema/050_ohlcv_daily.sql` created |
| M5 | `/api/chart-data/route.ts` | Only frontend API route **missing `authGuard()`** | ✅ Fixed — authGuard added |
| M6 | `types/index.ts` vs `types/api.ts` | Duplicate type definitions with inconsistencies (10 vs 13 TradingLabel values) | ✅ Fixed — 13 labels + 'mixed' direction synced |
| M7 | Dashboard components | 5 of 6 dashboard widgets use hardcoded mock data despite hooks existing | ✅ Partially fixed — 4 of 5 wired to live API (SentimentOverview still mock) |

### LOW Severity

| # | Location | Issue | Status |
|---|----------|-------|--------|
| L1 | `src/bot/commands/chart.py` L27 | Dead `DB_PATH` SQLite reference | ✅ Removed |
| L2 | `src/snaptrade_collector.py` L59 | Dead `PRICE_DB` SQLite reference | ✅ Removed |
| L3 | `src/journal_generator.py` | Legacy CSV-based (not DB-first) | ⚠️ Legacy — low priority |
| L4 | `src/logging_utils.py` | Dead `log_message_to_file` CSV path | ✅ Removed |
| L5 | `src/twitter_analysis.py` | Dead `log_tweet_to_file`, `write_x_posts_parquet` | ✅ Removed |
| L6 | `src/retry_utils.py` | Dead `__main__` self-test block | ✅ Removed |
| L7 | `.env.example` | Contains `SQLITE_PATH` reference | ✅ Commented as deprecated |
| L8 | `README.md` | Says "Python 3.9+" but requires 3.11+ | ✅ Fixed — says 3.11+ |
| L9 | `schema/000_baseline.sql` | Includes 6+ dropped tables — stale baseline | ⚠️ Historical reference |
| L10 | `docs/schema-report.md` | Says "19 tables" (now 17) | ✅ Fixed — says 17 |
| L11 | `docs/EC2_README.md` | References missing `EC2_SETUP_DETAILED.md` | ✅ Fixed — links updated to EC2_DEPLOYMENT.md |
| L12 | `app/routes/portfolio.py` | `dayChange` hardcoded to `0.0` (TODO) | ✅ Fixed — computed from previous close |
| L13 | Frontend `orders/`, `positions/`, `watchlist/` pages | Missing Sidebar/TopBar layout wrapper | ✅ Fixed — layout wrappers added |
| L14 | Stock page: `StockMetrics`, `ChatWidget`, `RawMessagesPanel`, `RiskCard` | Using mock data | ⚠️ Remaining — stock page wiring pending |

---

## 18. Overlaps & Redundancies

### Code Overlaps

| Category | Items | Resolution |
|----------|-------|------------|
| **Retry decorators** | `src/db.py` has internal retry logic + `src/retry_utils.py` exports `@database_retry` | Consolidate — use `retry_utils` everywhere |
| **History fetch** | `!history` command (bot) + `!process`/`!backfill` (bot) + `nightly_pipeline.py` (systemd) all fetch Discord messages | Intentional: bot = interactive, nightly = automated. Document clearly. |
| **EC2 bootstrap scripts** | `bootstrap.sh`, `ec2_user_data.sh`, `setup_ec2_services.sh` | Different OS targets. Add header comments clarifying when to use each. |
| **Type definitions** | `types/api.ts` vs `types/index.ts` (frontend) | ✅ Resolved — `index.ts` updated to match `api.ts` (13 TradingLabels, 'mixed' direction) |
| **SQLite references** | `chart.py`, `snaptrade_collector.py`, `.env.example` | ✅ Resolved — dead code removed, .env.example marked deprecated |
| **Auto-refresh** | `nightly-pipeline.timer` (EC2 systemd) is the **sole canonical scheduler**. Bot commands `!auto_on`/`!auto_off` have been **removed** (session 2). | ✅ Resolved |
| **Price data access** | `price_service.py` vs direct `ohlcv_daily` queries in various files | `price_service.py` should be the single entry point |
| **Order formatting** | `src/bot/formatting/orders_view.py` vs inline formatting in frontend `orders/page.tsx` | Expected (backend vs frontend). No action needed. |

### Dead Code Inventory

| Location | Dead Code | Status |
|----------|-----------|--------|
| `scripts/daily_pipeline.py` | Tombstone — redirects to `nightly_pipeline.py` | ⚠️ Keep as redirect |
| `scripts/run_pipeline_with_secrets.sh` | Tombstone | ⚠️ Keep as redirect |
| `scripts/verify_schema_state.sql` | References dropped tables | ⚠️ Low priority |
| `scripts/testing/` | Empty directory | ⚠️ Delete candidate |
| `src/journal_generator.py` | Legacy CSV-based approach | ⚠️ Legacy |
| `src/twitter_analysis.py` | `log_tweet_to_file()`, `write_x_posts_parquet()` | ✅ Removed |
| `src/logging_utils.py` | `log_message_to_file()` CSV path logic | ✅ Removed |
| `schema/000_baseline.sql` | Defines 6+ dropped tables | ⚠️ Historical reference |

---

## 19. Recommended Actions

### ✅ Completed (Sessions 1–5)

1. **H1**: Fixed `channel_processor.py` SQL injection — parameterized query
2. **H2**: Fixed `watchlist.py` SQL — `symbol` → `ticker`, `name` → `description`
3. **M1**: Fixed `position_analysis.py` layering — extracted `trade_queries.py`
4. **M2**: Added `MARKET` to `EmbedCategory` enum
5. **M3**: Regenerated `expected_schemas.py` with 17 tables + `ohlcv_daily`
6. **M4**: Created `schema/050_ohlcv_daily.sql`
7. **M5**: Added `authGuard()` to `/api/chart-data/route.ts`
8. **M6**: Synced `types/index.ts` with `types/api.ts` (13 TradingLabels, 'mixed' direction)
9. **M7**: Wired 4 of 5 dashboard components to live API (PortfolioSummary, PositionsTable, RecentOrders, TopMovers)
10. **L1–L2**: Removed dead SQLite references from `chart.py`, `snaptrade_collector.py`
11. **L4–L6**: Removed dead functions from `logging_utils.py`, `twitter_analysis.py`, `retry_utils.py`
12. **L8**: Updated `README.md` Python version to 3.11+
13. **L10**: Updated `schema-report.md` table count to 17
14. **L11**: Fixed `EC2_README.md` broken links (EC2_SETUP_DETAILED → EC2_DEPLOYMENT)
15. **L12**: Implemented `dayChange` from previous close in `portfolio.py`
16. **L13**: Added Sidebar/TopBar layout wrappers to orders, positions, watchlist pages
17. Removed `auto_on`/`auto_off` bot commands (scheduler debloat)
18. Created `schema/058_security_and_indexes.sql` for auth + indexing

### Remaining

| Priority | Item | Notes |
|----------|------|-------|
| Low | Wire `SentimentOverview.tsx` to live API | Needs sentiment endpoint |
| Low | Wire stock page mock components (`StockMetrics`, `RiskCard`, `ChatWidget`, `RawMessagesPanel`) | Needs backend endpoints |
| Low | `src/journal_generator.py` | Legacy CSV-based, low usage |
| Low | `scripts/testing/` empty directory | Delete candidate |
| Info | `schema/000_baseline.sql` defines dropped tables | Historical reference only |
| Info | `docs/legacy-migrations.md` migration count | Minor doc discrepancy |

---

*End of audit report*
