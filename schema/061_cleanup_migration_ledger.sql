-- =============================================================================
-- 061_cleanup_migration_ledger.sql
-- =============================================================================
-- Consolidates the messy schema_migrations table.
--
-- The old deployer recorded migrations under BOTH the numeric prefix ('015')
-- and the full filename stem ('015_primary_key_alignment'), creating duplicate
-- entries.  This migration:
--
--   1. Removes the numeric-only duplicates where a full-name entry also exists.
--   2. Inserts the baseline record for existing databases.
--   3. Inserts this migration's own record.
--
-- Fully idempotent – safe to run multiple times.
-- =============================================================================

-- Remove numeric-only entries that have a matching full-name entry.
-- e.g. if both '016' and '016_complete_rls_policies' exist, delete '016'.
DELETE FROM schema_migrations
WHERE version ~ '^\d{3}$'
  AND EXISTS (
      SELECT 1 FROM schema_migrations sm2
      WHERE sm2.version LIKE (schema_migrations.version || '_%')
  );

-- Mark the baseline as applied for existing databases
-- (fresh installs already have it from 060_baseline_current.sql)
INSERT INTO schema_migrations (version, description)
VALUES ('060_baseline_current', 'Baseline snapshot — marked applied for existing DB')
ON CONFLICT (version) DO NOTHING;

-- Self-record
INSERT INTO schema_migrations (version, description)
VALUES ('061_cleanup_migration_ledger', 'Consolidate duplicate migration entries')
ON CONFLICT (version) DO NOTHING;
