# Database Reports

This directory contains reports and snapshots of database schema and configuration.

## Current Reports

### Status & Configuration
- **supabase-status.md** - Supabase database status and health check results
- **schema-standardization.md** - Schema standardization validation and compliance
- **schema-generation.md** - Schema generation process documentation

### Live Schema Snapshots (Parent Directory)

The parent `reports/` directory contains live database schema exports:
- `live_schema_dump.sql` - Complete PostgreSQL schema dump
- `live_columns_detailed.csv` - Detailed column definitions
- `live_indexes.csv` - Index definitions
- `live_primary_keys.csv` - Primary key constraints
- `live_unique_constraints.csv` - Unique constraints
- `live_rls_policies.csv` - Row-Level Security policies

## Schema Management Workflow

### 1. Define Schema Changes
Edit files in `schema/` directory:
```
schema/
├── 000_baseline.sql (core tables - SSOT)
├── 015_primary_key_alignment.sql
├── 016_complete_rls_policies.sql
├── 017_timestamp_field_migration.sql
├── 018_cleanup_schema_drift.sql
├── 019_data_quality_cleanup.sql
├── 020_drop_positions_redundant_columns.sql
├── 021_fix_processing_status_composite_key.sql
├── 022_add_attachments_column.sql
├── 023_event_contract_tables.sql
├── 024_account_balances_unique_constraint.sql
├── 025_drop_backup_tables.sql
└── 026_add_twitter_media_column.sql
```

### 2. Generate Expected Schema
```bash
python scripts/schema_parser.py --output expected
```
This creates `src/expected_schemas.py` from all migration files.

### 3. Deploy to Database
```bash
python scripts/deploy_database.py
```

### 4. Verify Schema Compliance
```bash
python scripts/verify_database.py --mode comprehensive
```

### 5. Export Live Schema (For Reference)
```bash
# Manual export using pg_dump or Supabase dashboard
# Store in reports/ directory with timestamp
```

## Related Documentation

- **docs/EXPECTED_SCHEMAS.md** - Schema documentation standard
- **docs/LEGACY_MIGRATIONS.md** - Historical migration information
- **docs/POST_MIGRATION_WORKFLOW.md** - Migration deployment process
- **docs/ARCHITECTURE.md** - Overall system architecture

## Schema Validation Tools

### verify_database.py
```bash
# Basic connectivity and table existence
python scripts/verify_database.py --mode basic

# Comprehensive schema validation
python scripts/verify_database.py --mode comprehensive

# Performance index checks
python scripts/verify_database.py --performance

# Specific table validation
python scripts/verify_database.py --table positions
```

### schema_parser.py
```bash
# Generate expected_schemas.py
python scripts/schema_parser.py --output expected

# Generate documentation
python scripts/schema_parser.py --output docs

# Verbose mode with detailed parsing
python scripts/schema_parser.py --verbose
```

## Report Maintenance

### When to Update Reports

**supabase-status.md**: After major infrastructure changes
**schema-standardization.md**: After schema refactoring or standardization efforts
**schema-generation.md**: After changing schema parsing or generation logic

### Report Format

All reports should include:
1. **Timestamp** - When the report was generated
2. **Context** - What triggered the report
3. **Findings** - What was discovered/validated
4. **Actions** - What was changed or recommended
5. **Verification** - How to test/validate the changes
