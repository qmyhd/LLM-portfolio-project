-- ============================================================================
-- Migration 049: Drop Legacy/Unused Tables
-- ============================================================================
-- Purpose: Remove tables that have been superseded by the discord_parsed_ideas
-- system and are no longer actively used in the codebase.
--
-- Tables dropped:
-- - discord_message_chunks: Replaced by discord_parsed_ideas (legacy chunking)
-- - discord_idea_units: Replaced by discord_parsed_ideas (legacy idea extraction)
-- - stock_mentions: Replaced by structured parsing in discord_parsed_ideas
-- - discord_processing_log: Replaced by processing_status table
-- - chart_metadata: Never actively used (0 rows)
--
-- Date: 2026-01-02
-- ============================================================================

-- Drop tables (CASCADE handles any remaining dependencies)
DROP TABLE IF EXISTS discord_message_chunks CASCADE;
DROP TABLE IF EXISTS discord_idea_units CASCADE;
DROP TABLE IF EXISTS stock_mentions CASCADE;
DROP TABLE IF EXISTS discord_processing_log CASCADE;
DROP TABLE IF EXISTS chart_metadata CASCADE;

-- Note: After running this migration:
-- 1. Run: python scripts/schema_parser.py --output expected
-- 2. Run: python scripts/verify_database.py
-- 3. Commit both migration and updated expected_schemas.py
