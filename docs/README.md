# LLM Portfolio Journal - Documentation Hub

**Last Updated:** January 20, 2026

## Active Documentation

| Document | Purpose |
|----------|---------|
| [../AGENTS.md](../AGENTS.md) | AI agent development guide with setup, patterns, and troubleshooting |
| [ARCHITECTURE.md](ARCHITECTURE.md) | System architecture covering components, data flow, schema management |
| [API_REFERENCE.md](API_REFERENCE.md) | Module and function reference with usage examples |
| [STARTUP_GUIDE.md](STARTUP_GUIDE.md) | Quick-start guide for running the bot and collecting data |
| [CODEBASE_MAP.md](CODEBASE_MAP.md) | Active scripts and modules with their purposes |
| [SCHEMA_REPORT.md](SCHEMA_REPORT.md) | Database schema analysis and documentation |
| [LEGACY_MIGRATIONS.md](LEGACY_MIGRATIONS.md) | Historical migrations and configuration evolution |
| [CHUNK_INDEXING_FIX.md](CHUNK_INDEXING_FIX.md) | Fix for chunk indexing unique constraint violations |
| [CI_SCHEMA_VALIDATION.md](CI_SCHEMA_VALIDATION.md) | CI schema validation reference documentation |

## Directory Structure

```
docs/
├── README.md              # This file
├── ARCHITECTURE.md        # Technical architecture
├── API_REFERENCE.md       # API documentation
├── STARTUP_GUIDE.md       # Quick-start bot guide
├── CODEBASE_MAP.md        # Scripts and modules reference
├── SCHEMA_REPORT.md       # Database schema documentation
└── LEGACY_MIGRATIONS.md   # Historical reference
```

## Essential Commands

```bash
# Validation & setup
python tests/validate_deployment.py
python scripts/bootstrap.py

# Schema management
python scripts/schema_parser.py --output expected
python scripts/verify_database.py --mode comprehensive

# Core operations
python -m src.bot.bot
python scripts/backfill_ohlcv.py --daily
```

## For AI Agents

**Reading Order:**
1. [AGENTS.md](../AGENTS.md) - Start here for setup and critical patterns
2. [ARCHITECTURE.md](ARCHITECTURE.md) - Deep technical implementation
3. [API_REFERENCE.md](API_REFERENCE.md) - Module reference

**Critical Setup Requirements:**
- Supabase service role key (`sb_secret_`) in DATABASE_URL
- All database operations use `execute_sql()` from `src/db.py`
- Run `verify_database.py` before schema changes

**Current System Status:**
- 20 operational tables
- PostgreSQL-only (Supabase)
- 100% RLS policy compliance
- Production ready

---

**Documentation Status:** Consolidated and validated (January 2026)
