--
-- Migration 021: Fix processing_status composite primary key
-- 
-- Purpose: Update processing_status table to use (message_id, channel) composite key
-- to properly track per-message per-channel processing status, consistent with
-- discord_processing_log design pattern.
--
-- Rationale:
-- - A single message may appear in multiple channels (cross-posts, shares)
-- - Processing status should be tracked separately for each channel occurrence
-- - Aligns with discord_processing_log table design: PRIMARY KEY (message_id, channel)
--
-- Date: October 15, 2025
--

-- Drop the existing single-column primary key and unique constraint
ALTER TABLE IF EXISTS "public"."processing_status" 
    DROP CONSTRAINT IF EXISTS "processing_status_pkey";

ALTER TABLE IF EXISTS "public"."processing_status"
    DROP CONSTRAINT IF EXISTS "processing_status_message_id_key";

-- Drop any additional unique constraint on message_id alone
ALTER TABLE IF EXISTS "public"."processing_status"
    DROP CONSTRAINT IF EXISTS "processing_status_message_id_unique";

-- Add composite primary key (message_id, channel)
ALTER TABLE ONLY "public"."processing_status"
    ADD CONSTRAINT "processing_status_pkey" PRIMARY KEY ("message_id", "channel");

-- Update comment to reflect new composite key design
COMMENT ON TABLE "public"."processing_status" IS 'Message processing status using (message_id, channel) composite natural key - tracks per-message per-channel processing flags';

-- Record migration
INSERT INTO schema_migrations (version, description) 
VALUES ('021', 'Fix processing_status composite primary key (message_id, channel)');
