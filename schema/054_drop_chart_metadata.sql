-- Migration: 054_drop_chart_metadata.sql
-- Purpose: Drop unused chart_metadata table
-- Date: 2026-01-26
--
-- Analysis:
--   - chart_metadata was never actively used by any runtime code
--   - Defined in 000_baseline.sql but no INSERT/UPDATE operations exist
--   - No charting code references this table
--   - grep confirms "never actively used" per SCHEMA_REPORT.md
--
-- Tables dropped:
--   - chart_metadata: Stores chart configs (symbol, period, interval, theme) - unused
--
-- Safety: This migration only drops an unused table

-- Drop RLS policy first
DROP POLICY IF EXISTS "Allow all for chart_metadata" ON public.chart_metadata;

-- Drop the table
DROP TABLE IF EXISTS public.chart_metadata CASCADE;

-- Record migration
INSERT INTO public.schema_migrations (version, name, applied_at)
VALUES ('054', 'drop_chart_metadata', NOW())
ON CONFLICT (version) DO NOTHING;
