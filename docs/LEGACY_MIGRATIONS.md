# Legacy Migrations & Historical Changes

> **Historical migration documentation for reference**

## 📊 Schema Audit Summary (January 2026)

### Current Status: ✅ Production-Ready
- **Total Migrations:** 57 files (all properly versioned)
- **Active Tables:** 15 (verified in use)
- **Dropped Tables:** 10+ (safely cleaned up)
- **Deployment:** Ready with baseline auto-detection

### The 15 Active Production Tables

| Category | Tables |
|----------|--------|
| **SnapTrade** | accounts, account_balances, positions, orders, symbols |
| **Discord/NLP** | discord_messages, discord_market_clean, discord_trading_clean, discord_parsed_ideas ⭐ |
| **Twitter** | twitter_data |
| **Market Data** | ohlcv_daily (Databento) |
| **System** | processing_status, schema_migrations, symbol_aliases, institutional_holdings |

### Safely Dropped Tables (No Action Needed)
- **NLP Legacy:** discord_message_chunks, discord_idea_units, stock_mentions → Replaced by discord_parsed_ideas
- **Price Legacy:** daily_prices, realtime_prices, stock_metrics → Replaced by ohlcv_daily
- **Orphaned:** event_contract_trades, event_contract_positions, trade_history

### Deployment Readiness
✅ All 15 active tables verified in production code  
✅ Dropped tables confirmed no longer accessed  
✅ Migration versioning working correctly  
✅ Baseline detection implemented  
✅ SQL parsing enhanced (handles DO blocks)  
✅ Idempotent deployments (ON CONFLICT DO NOTHING)  

---

## Major Migration Events

### January 2026 - Supabase Schema Audit & Deployment Fixes

**Comprehensive Schema Analysis Completed**
- Analyzed all 57 migration files across production database
- Verified 15 active production tables actively used in codebase
- Identified 10+ properly-dropped legacy tables (safe cleanup)
- Validated Supabase PostgreSQL connection requirements
- All schemas verified cross-referenced with live code usage

**Deployment Script Enhancements**
1. **SQL Statement Splitting**: Replaced simple line-based splitter with `sqlparse.split()` 
   - Now properly handles DO $$ blocks as single statements
   - Preserves -- and /* */ comments correctly
   - Fallback implementation for robust error handling
   - Added to requirements.txt as `sqlparse>=0.5.0`

2. **Baseline Detection**: Implemented automatic detection of already-applied baseline
   - Checks for existence of 'accounts' table (core baseline table)
   - Automatically skips baseline.sql if already present
   - Added `--skip-baseline` CLI flag for manual override
   - Safe for existing Supabase projects

3. **Schema Migration Conflict Handling**: Verified idempotent migrations
   - All schema_migrations inserts use `ON CONFLICT (version) DO NOTHING`
   - Safe to retry failed deployments
   - No duplicate version errors

**Bootstrap Script Cleanup**
- Removed deprecated `python3.12-distutils` from apt installs
- Replaced with standard `python3-setuptools` handling
- Fixes Ubuntu 22.04+ compatibility

**Active Production Tables (15 verified)**
- SnapTrade: accounts, account_balances, positions, orders, symbols
- Discord/NLP: discord_messages, discord_market_clean, discord_trading_clean, discord_parsed_ideas
- Twitter: twitter_data
- Market Data: ohlcv_daily (Databento)
- System: processing_status, schema_migrations, symbol_aliases, institutional_holdings

**Properly Dropped Tables (Safe to ignore)**
- NLP legacy: discord_message_chunks, discord_idea_units, stock_mentions (replaced by discord_parsed_ideas)
- Price legacy: daily_prices, realtime_prices, stock_metrics (replaced by ohlcv_daily)
- Orphaned: event_contract_trades, event_contract_positions, trade_history
- UI legacy: chart_metadata, discord_processing_log

**Deployment Status**
✅ Ready for production - no breaking changes  
✅ Auto-detection working for existing databases  
✅ All fixes implemented and verified  
✅ Idempotent deployments with conflict handling  

**Recommended Deployment**
```bash
# For existing Supabase database
python scripts/deploy_database.py --skip-baseline

# For fresh database
python scripts/deploy_database.py
```

### October 2025 - Schema Management & Documentation Overhaul

**Schema & Migration Improvements**
1. **Migration 020**: Dropped redundant position columns
2. **Schema Parser Enhancement**: Added comprehensive validation mode
3. **Multi-Schema Support**: Extended verification beyond public schema
4. **Documentation Consolidation**: Reduced documentation files to essential references

**Key Files Modified**
- `schema/020_drop_positions_redundant_columns.sql` - Schema cleanup
- `scripts/schema_parser.py` - Enhanced with comprehensive mode
- `scripts/verify_database.py` - Multi-schema verification support
- `docs/*` - Documentation cleanup and consolidation

### September 2025 - Supabase-Only Migration & Data Integrity Validation

**Issues Resolved**
1. **Database Connection Authentication**
   - Problem: Using direct PostgreSQL password instead of Supabase service role key
   - Impact: RLS policies blocking INSERT operations
   - Solution: Updated DATABASE_URL to use `SUPABASE_SERVICE_ROLE_KEY`

2. **Transaction Management**
   - Problem: DML operations (INSERT/UPDATE/DELETE) not auto-committing  
   - Impact: Data appearing to insert successfully but not persisting
   - Solution: Modified `src/db.py` to auto-commit both DDL and DML write operations

3. **Schema Alignment**  
   - Problem: Code attempting to insert non-existent columns
   - Impact: Orders table inserts failing with "column does not exist" errors
   - Solution: Removed phantom column references, aligned with actual schema

4. **Account-Position Relationships**
   - Problem: Positions linked to fake "default_account" 
   - Impact: Broken foreign key relationships
   - Solution: Fixed account_id propagation in position extraction

5. **Symbol Table Population**
   - Problem: Case-sensitive filtering preventing symbol extraction
   - Impact: Empty symbols table despite valid ticker data
   - Solution: Changed to case-insensitive comparison for filtering

**Validation Results**
```sql
-- All tests PASSED (September 27, 2025):
✅ Account-Position Links: 165/165 positions correctly linked
✅ Symbols Population: 177 symbols extracted
✅ Schema Alignment: All operations use validated 16-table schema  
✅ Transaction Management: Operations auto-commit correctly
```

### 2024 - Timestamp Field Migration

**Changes Made**
- **Target Tables**: positions, orders, accounts, balances, symbols
- **Field Updates**: `sync_timestamp` text → `sync_timestamp` timestamptz
- **Method**: New column, data migration with timezone conversion, drop old column

### 2024 - SnapTrade Response Handling Improvements

**Key Improvements**
1. **Safe Response Extraction**: Helper method for API response handling
2. **Nested Data Navigation**: Handling of complex response structures  
3. **Error Recovery**: Graceful degradation for varying API responses

## Schema Evolution

### Current Schema
- **16 Operational Tables**: Validated with proper relationships
- **RLS Policies**: Row Level Security implementation
- **Primary Keys**: Aligned with live database
- **Foreign Keys**: Validated relationships

### Key Schema Files
- `schema/000_baseline.sql` - Complete 16-table schema definition
- `schema/016_complete_rls_policies.sql` - Row Level Security policies
- `schema/017_timestamp_field_migration.sql` - Modern timestamp type migration

### Migration Pattern
1. **Baseline**: `000_baseline.sql` establishes core structure
2. **Incremental Updates**: Numbered migration files (015-020)
3. **Validation**: Post-migration integrity checks

## Configuration Evolution

### Database Connection Timeline
```bash
# Phase 1 - Dual architecture (deprecated)
DATABASE_URL with SQLite fallback

# Phase 2 - Supabase with Direct Password  
DATABASE_URL with direct password

# Phase 3 - Supabase with Service Role Key (Current)
DATABASE_URL with sb_secret_ key
```

### Key Configuration Changes
1. **Removed**: SQLite fallback support, `SQLITE_PATH` variables
2. **Added**: Supabase service role key, Twitter batch size configuration
3. **Enhanced**: Environment variable mapping with backward compatibility

## Documentation Evolution

### October 2025 - Documentation Consolidation
- **Reduced**: Documentation to essential references
- **Consolidated**: Schema and workflow docs into ARCHITECTURE.md
- **Archived**: Obsolete status and proposal documents
- **Polished**: Removed verbose descriptions and marketing language

### Current Documentation Structure
```
ACTIVE DOCUMENTATION:
├── AGENTS.md                    # AI contributor guide
├── docs/ARCHITECTURE.md         # Technical architecture
├── docs/API_REFERENCE.md        # Module documentation
├── docs/README.md              # Navigation hub
└── docs/LEGACY_MIGRATIONS.md   # This file

ARCHIVED:
├── docs/archive/EXPECTED_SCHEMAS.md           # Merged into ARCHITECTURE.md
├── docs/archive/POST_MIGRATION_WORKFLOW.md    # Merged into ARCHITECTURE.md
├── docs/archive/DISCORD_ARCHITECTURE.md       # Merged into ARCHITECTURE.md
├── docs/archive/DOCUMENTATION_STATUS.md       # Obsolete
└── docs/archive/TWITTER_BULK_UPSERT_WORKFLOW.md # Completed
```

## Migration Guidelines

### For Development
1. **Document Major Changes**: Create fix documents for critical issues
2. **Validate Thoroughly**: Run integrity checks post-migration
3. **Update Documentation**: Keep AGENTS.md and ARCHITECTURE.md in sync

### Migration Best Practices
1. **Schema Changes**: Create new column, migrate data, drop old column
2. **Data Integrity**: Validate relationships before and after
3. **Transaction Safety**: Use explicit transactions for multi-step operations

### Documentation Standards
- **AGENTS.md**: Primary development guide with troubleshooting
- **ARCHITECTURE.md**: Technical implementation details
- **LEGACY_MIGRATIONS.md**: Historical reference (this file)

---

**Last Updated: October 9, 2025**  
**Status: All migrations completed**