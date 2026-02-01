# LLM Portfolio Journal - Repository Overview

> **Last Updated:** February 1, 2026

## 🎯 What This Project Does

This is a **sophisticated portfolio analytics and trading journal system** that integrates multiple data sources to provide trading insights. It combines:

1. **Brokerage Data** (SnapTrade API) - Real positions, orders, account balances
2. **Social Sentiment** (Discord Bot + Twitter/X) - Captures trading ideas and market chatter
3. **Market Data** (Databento) - OHLCV price history
4. **AI/NLP Processing** (OpenAI) - Extracts structured trading ideas from unstructured text

---

## 📁 Directory Organization

### `/src/` - Core Application Code

The main application logic, organized by function:

| Module                   | Purpose                                                    |
| ------------------------ | ---------------------------------------------------------- |
| `db.py`                  | PostgreSQL/Supabase database interface with SQLAlchemy 2.0 |
| `config.py`              | Pydantic-based configuration from environment variables    |
| `price_service.py`       | Centralized OHLCV data access                              |
| `snaptrade_collector.py` | Brokerage API integration                                  |
| `databento_collector.py` | Market data ingestion                                      |
| `message_cleaner.py`     | Ticker extraction & sentiment analysis                     |
| `retry_utils.py`         | Hardened retry decorators for external APIs                |

### `/src/bot/` - Discord Bot

A modular Discord bot for real-time data collection:

- **`bot.py`** - Entry point
- **`commands/`** - Individual commands (`!chart`, `!process`, `!history`, etc.)
- **`ui/`** - Embed factory, pagination, interactive views

### `/src/nlp/` - NLP Pipeline

OpenAI-powered semantic parsing:

- **`openai_parser.py`** - LLM structured output extraction
- **`schemas.py`** - Pydantic models for trading ideas
- **`preclean.py`** - Ticker accuracy (reserved words, alias mapping)

### `/schema/` - Database Migrations

44 SQL migration files managing the PostgreSQL schema:

- `000_baseline.sql` - Initial schema
- Sequential migrations (`015_*.sql` through `057_*.sql`)
- **17 core tables** including: `positions`, `orders`, `discord_messages`, `discord_parsed_ideas`, `ohlcv_daily`, `stock_profile_current`

### `/scripts/` - Operational Tools

Automation and maintenance scripts:

- **`bootstrap.py`** - Complete environment setup
- **`deploy_database.py`** - Schema deployment
- **`verify_database.py`** - Schema validation
- **`backfill_ohlcv.py`** - Historical price data loading
- **`nlp/`** - Batch NLP processing scripts

### `/tests/` - Test Suite

- `test_integration.py` - Core integration tests
- `validate_deployment.py` - Pre-deployment checks

### `/app/` - Web API (FastAPI)

A FastAPI backend for the web interface:

- `main.py` - API entry point
- `auth.py` - Authentication
- `routes/` - API endpoints

### `/docs/` - Documentation

Architecture guides, API references, deployment instructions.

---

## 🔄 Data Flow Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│                         DATA SOURCES                                  │
├─────────────────┬─────────────────┬─────────────────┬────────────────┤
│   SnapTrade     │   Discord Bot   │   Twitter/X     │   Databento    │
│  (Brokerage)    │   (Messages)    │  (Sentiment)    │   (OHLCV)      │
└────────┬────────┴────────┬────────┴────────┬────────┴───────┬────────┘
         │                 │                 │                │
         ▼                 ▼                 ▼                ▼
┌──────────────────────────────────────────────────────────────────────┐
│                    PROCESSING ENGINE                                  │
│  • Ticker Extraction (regex + alias mapping)                          │
│  • Sentiment Analysis (TextBlob)                                      │
│  • NLP Parsing (OpenAI structured outputs)                            │
│  • Deduplication & Normalization                                      │
└────────────────────────────────┬─────────────────────────────────────┘
                                 │
                                 ▼
┌──────────────────────────────────────────────────────────────────────┐
│                    POSTGRESQL (SUPABASE)                              │
│  positions │ orders │ discord_messages │ discord_parsed_ideas │ etc  │
└────────────────────────────────┬─────────────────────────────────────┘
                                 │
                                 ▼
┌──────────────────────────────────────────────────────────────────────┐
│                         OUTPUTS                                       │
│  • Discord Bot Commands (!chart, !portfolio, !eod)                    │
│  • Web Dashboard (FastAPI)                                            │
│  • Structured Trading Ideas for Analysis                              │
└──────────────────────────────────────────────────────────────────────┘
```

---

## 🧠 Key Concepts

### 1. **NLP Pipeline** (The "LLM" in LLM Portfolio Journal)

Messages from Discord → OpenAI extracts structured **"trading ideas"** with:

- Primary symbol (`$AAPL`)
- Direction (bullish/bearish)
- Labels (13 categories like `entry_idea`, `price_target`, `support_level`)
- Confidence scores
- Price levels

### 2. **Ticker Extraction**

Sophisticated pattern matching:

- Handles `$AAPL`, `$BRK.B` formats
- **80+ reserved words** prevent false positives (`target`, `support` aren't tickers)
- **~100 alias mappings** (company names → tickers)

### 3. **Database-First Design**

- Supabase
- Row Level Security (RLS) enabled on all tables
- Named parameter queries with `execute_sql()`

### 4. **Retry Patterns**

All external API calls use `@hardened_retry` decorators for resilience.

---

## 🚀 How to Run It

```bash
# 1. Validate environment
python tests/validate_deployment.py

# 2. Bootstrap (installs deps, validates DB)
python scripts/bootstrap.py

# 3. Configure .env with API keys (DISCORD_BOT_TOKEN, OPENAI_API_KEY, etc.)

# 4. Run the Discord bot
python -m src.bot.bot
```

---

## 📊 Key Tables (17 Core)

| Category        | Tables                                                                                      |
| --------------- | ------------------------------------------------------------------------------------------- |
| **Brokerage**   | `accounts`, `account_balances`, `positions`, `orders`, `symbols`                            |
| **Discord**     | `discord_messages`, `discord_market_clean`, `discord_trading_clean`, `discord_parsed_ideas` |
| **Market Data** | `ohlcv_daily`                                                                               |
| **Analytics**   | `stock_profile_current`, `stock_profile_history`                                            |
| **Social**      | `twitter_data`                                                                              |
| **System**      | `processing_status`, `schema_migrations`, `symbol_aliases`, `institutional_holdings`        |

---

## 🎛️ Configuration Files

| File                  | Purpose                            |
| --------------------- | ---------------------------------- |
| `.env` / `.env.local` | API keys, database URLs            |
| `pyproject.toml`      | Python package metadata            |
| `requirements.txt`    | Dependencies                       |
| `template.yaml`       | AWS SAM template (if using Lambda) |

---

## 📚 Related Documentation

- [ARCHITECTURE.md](ARCHITECTURE.md) - Detailed technical architecture
- [QUICK_START.md](QUICK_START.md) - Getting started guide
- [API_REFERENCE.md](API_REFERENCE.md) - API documentation
- [EC2_DEPLOYMENT.md](EC2_DEPLOYMENT.md) - Production deployment guide

This is a well-architected data engineering project focused on **capturing, processing, and analyzing trading-related data** from multiple sources, with AI-powered semantic understanding of trading ideas.
