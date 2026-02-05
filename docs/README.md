# LLM Portfolio Journal - Documentation Hub

**Last Updated:** February 5, 2026

## Active Documentation

| Document | Purpose |
|----------|---------|
| [../AGENTS.md](../AGENTS.md) | AI agent development guide with setup, patterns, and troubleshooting |
| [ARCHITECTURE.md](ARCHITECTURE.md) | System architecture covering components, data flow, schema management |
| [api-reference.md](api-reference.md) | Module and function reference with usage examples |
| [startup-guide.md](startup-guide.md) | Quick-start guide for running the bot and collecting data |
| [CODEBASE_MAP.md](CODEBASE_MAP.md) | Active scripts and modules with their purposes |
| [schema-report.md](schema-report.md) | Database schema analysis and documentation |
| [legacy-migrations.md](legacy-migrations.md) | Historical migrations and configuration evolution |
| [chunk-indexing-fix.md](chunk-indexing-fix.md) | Fix for chunk indexing unique constraint violations |
| [ci-schema-validation.md](ci-schema-validation.md) | CI schema validation reference documentation |
| [LLM_MODELS.md](LLM_MODELS.md) | LLM model routing strategy and cost optimization |

## Directory Structure

```
docs/
├── README.md              # This file
├── ARCHITECTURE.md        # Technical architecture
├── api-reference.md       # API documentation
├── startup-guide.md       # Quick-start bot guide
├── CODEBASE_MAP.md        # Scripts and modules reference
├── schema-report.md       # Database schema documentation
├── legacy-migrations.md   # Historical reference
├── LLM_MODELS.md          # LLM model routing strategy
├── EC2_DEPLOYMENT.md      # EC2 production deployment
└── EC2_README.md          # EC2 documentation hub
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
