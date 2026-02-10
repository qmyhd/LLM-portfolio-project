--
-- Migration: 018 Cleanup Schema Drift  
-- Date: 2025-01-27
-- Purpose: Remove schema_design_rationale view and backup table cleanup
--
-- Issues Addressed:
-- 1. schema_design_rationale view lacks PK and isn't part of intended public schema
-- 2. Optional cleanup of backup tables from migration 017
--
-- This migration ensures 100% SSOT compliance with baseline + incremental migrations

BEGIN;

-- =============================================================================
-- DROP SCHEMA_DESIGN_RATIONALE VIEW
-- =============================================================================

-- This view was created outside the migration system and lacks a primary key
-- It's not part of the intended public schema per 000_baseline.sql
DROP VIEW IF EXISTS "public"."schema_design_rationale" CASCADE;

-- =============================================================================  
-- OPTIONAL: CLEANUP MIGRATION 017 BACKUP TABLES
-- =============================================================================

-- These backup tables served their purpose during timestamp migration
-- They can be safely removed now that migration 017 is verified complete

-- Drop backup tables created during migration 017
DROP TABLE IF EXISTS "public"."positions_backup_017" CASCADE;
DROP TABLE IF EXISTS "public"."accounts_backup_017" CASCADE;
DROP TABLE IF EXISTS "public"."account_balances_backup_017" CASCADE;

-- =============================================================================
-- VALIDATION QUERIES  
-- =============================================================================

-- Ensure schema_design_rationale no longer exists
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.views 
        WHERE table_schema = 'public' 
        AND table_name = 'schema_design_rationale'
    ) THEN
        RAISE EXCEPTION 'schema_design_rationale view still exists after migration';
    END IF;
END $$;

-- =============================================================================
-- RECORD MIGRATION
-- =============================================================================

-- Record this migration
INSERT INTO "public"."schema_migrations" ("version", "description") 
VALUES ('018', 'Cleanup schema drift - removed schema_design_rationale view and migration 017 backup tables')
ON CONFLICT ("version") DO NOTHING;

-- Add documentation comment
COMMENT ON TABLE "public"."schema_migrations" IS 'Schema migration tracking - ensures SSOT compliance with baseline + incremental migrations';

COMMIT;

-- Post-migration verification queries:
/*
-- 1. Verify schema_design_rationale view is gone
SELECT COUNT(*) as view_count
FROM information_schema.views 
WHERE table_schema = 'public' 
AND table_name = 'schema_design_rationale';
-- Expected: 0

-- 2. Verify backup tables are cleaned up  
SELECT table_name
FROM information_schema.tables 
WHERE table_schema = 'public' 
AND table_name LIKE '%backup_017';
-- Expected: No results

-- 3. Confirm operational table count (16 expected)
SELECT COUNT(*) as operational_table_count
FROM information_schema.tables 
WHERE table_schema = 'public' 
AND table_type = 'BASE TABLE'
AND table_name NOT LIKE '%backup%';
-- Expected: 16
*/