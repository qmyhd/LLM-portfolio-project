-- Migration 025: Drop backup tables from migration 019
-- These backup tables are no longer needed after successful data migration verification
-- Date: 2025-12-05

-- Drop backup tables created during migration 019
DROP TABLE IF EXISTS orders_backup_019;
DROP TABLE IF EXISTS positions_backup_019;

-- Comment: Migration 019 created backups for data quality cleanup
-- The cleanup has been verified successful, backups are no longer needed
