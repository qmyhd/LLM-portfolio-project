# LLM Portfolio Journal - Documentation Hub

**Last Updated:** March 1, 2026

## Active Documentation

| Document | Purpose |
|----------|---------|
| [../AGENTS.md](../AGENTS.md) | AI agent development guide with setup, patterns, and troubleshooting |
| [ARCHITECTURE.md](ARCHITECTURE.md) | System architecture covering components, data flow, schema management |
| [api-reference.md](api-reference.md) | REST API endpoint reference with request/response examples |
| [CODEBASE_MAP.md](CODEBASE_MAP.md) | Active scripts and modules with their purposes |
| [schema-report.md](schema-report.md) | Database schema analysis and documentation |
| [legacy-migrations.md](legacy-migrations.md) | Historical migrations and configuration evolution |
| [LLM_MODELS.md](LLM_MODELS.md) | LLM model routing strategy and cost optimization |
| [EC2_DEPLOYMENT.md](EC2_DEPLOYMENT.md) | EC2 production deployment guide |
| [EC2_SETUP_QUICK_REFERENCE.md](EC2_SETUP_QUICK_REFERENCE.md) | Copy-paste EC2 setup commands |
| [recon_checklist.md](recon_checklist.md) | Portfolio reconciliation QA checklist |
| [robinhood_metric_map.md](robinhood_metric_map.md) | Robinhood UI → API field mapping |
| [ops/NGINX_HARDENING.md](ops/NGINX_HARDENING.md) | Nginx security hardening configuration |

## Directory Structure

```
docs/
├── README.md                     # This file
├── ARCHITECTURE.md               # Technical architecture
├── api-reference.md              # REST API documentation
├── CODEBASE_MAP.md               # Scripts and modules reference
├── schema-report.md              # Database schema documentation
├── legacy-migrations.md          # Historical reference
├── LLM_MODELS.md                 # LLM model routing strategy
├── FULL_CODEBASE_AUDIT.md        # Point-in-time audit (Feb 2026 snapshot)
├── EC2_DEPLOYMENT.md             # EC2 production deployment
├── EC2_SETUP_QUICK_REFERENCE.md  # EC2 quick commands
├── recon_checklist.md            # Portfolio QA checklist
├── robinhood_metric_map.md       # Robinhood metric mapping
├── ops/
│   └── NGINX_HARDENING.md        # Nginx hardening snippet
└── plans/                        # Design & implementation plans
```

## Essential Commands

```bash
# Validation & setup
python tests/validate_deployment.py
python scripts/bootstrap.py

# Schema management
python scripts/deploy_database.py
python scripts/verify_database.py --mode comprehensive

# Core operations
python -m src.bot.bot
python scripts/backfill_ohlcv.py --daily
python scripts/nightly_pipeline.py
```

## For AI Agents

**Reading Order:**
1. [AGENTS.md](../AGENTS.md) - Start here for setup and critical patterns
2. [ARCHITECTURE.md](ARCHITECTURE.md) - Deep technical implementation
3. [api-reference.md](api-reference.md) - Endpoint reference

**Critical Setup Requirements:**
- Supabase service role key (`sb_secret_`) in DATABASE_URL
- All database operations use `execute_sql()` from `src/db.py`
- Run `verify_database.py` before schema changes

**Current System Status:**
- 20 operational tables (migrations 060-066)
- PostgreSQL-only (Supabase)
- RLS policies on all tables
- Production ready

---

**Documentation Status:** Consolidated and validated (March 2026)
