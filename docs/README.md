# LLM Portfolio Journal - Documentation Hub

**Last Updated:** January 3, 2026

## Active Documentation

| Document | Purpose |
|----------|---------|
| [../AGENTS.md](../AGENTS.md) | AI agent development guide with setup, patterns, and troubleshooting |
| [ARCHITECTURE.md](ARCHITECTURE.md) | System architecture covering components, data flow, schema management, and migration workflow |
| [API_REFERENCE.md](API_REFERENCE.md) | Module and function reference with usage examples |
| [STARTUP_GUIDE.md](STARTUP_GUIDE.md) | Quick-start guide for running the bot and collecting data |
| [CODEBASE_MAP.md](CODEBASE_MAP.md) | Active scripts and modules with their purposes |
| [SCHEMA_REPORT.md](SCHEMA_REPORT.md) | Database schema analysis and documentation |
| [LEGACY_MIGRATIONS.md](LEGACY_MIGRATIONS.md) | Historical migrations and configuration evolution |
| [CHUNK_INDEXING_FIX.md](CHUNK_INDEXING_FIX.md) | Fix for chunk indexing unique constraint violations (Dec 2025) |
| [CI_SCHEMA_VALIDATION.md](CI_SCHEMA_VALIDATION.md) | CI schema validation reference documentation |

## Directory Structure

```
docs/
├── README.md              # This file
├── ARCHITECTURE.md        # Technical architecture (includes schema management, migrations, Discord bot)
├── API_REFERENCE.md       # API documentation
├── STARTUP_GUIDE.md       # Quick-start bot guide
├── CODEBASE_MAP.md        # Scripts and modules reference
├── SCHEMA_REPORT.md       # Database schema documentation
└── LEGACY_MIGRATIONS.md   # Historical reference
```

## Documentation Consolidation (October 2025)

The following documents were merged into ARCHITECTURE.md and archived:
- **EXPECTED_SCHEMAS.md** → "Schema Management & Validation" section
- **POST_MIGRATION_WORKFLOW.md** → "Migration Workflow" section
- **DISCORD_ARCHITECTURE.md** → "Discord Bot System" section

Obsolete files archived:
- **DOCUMENTATION_STATUS.md** - Meta-documentation superseded by this README
- **TWITTER_BULK_UPSERT_WORKFLOW.md** - Completed proposal

## Essential Commands

```bash
# Validation & setup
python tests/validate_deployment.py
python scripts/bootstrap.py

# Schema management
python scripts/schema_parser.py --output expected
python scripts/verify_database.py --mode comprehensive

# Core operations
python generate_journal.py --force
python -m src.bot.bot
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
- 16 operational tables
- PostgreSQL-only (Supabase)
- 100% RLS policy compliance
- Production ready

---

**Documentation Status:** Consolidated and validated (October 2025)
