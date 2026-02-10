-- Migration: 043_add_parsed_ideas_foreign_key.sql
-- Description: Add foreign key from discord_parsed_ideas.message_id to discord_messages.message_id
-- This ensures referential integrity and enables cascade deletion when messages are removed.
-- 
-- The ON DELETE CASCADE means when a discord_messages row is deleted, all related
-- parsed ideas are automatically deleted. This is the desired behavior for:
-- 1. Message corrections/redactions
-- 2. Bulk reprocessing (delete message → reparse → new ideas)
-- 3. User data deletion requests
--
-- IDEMPOTENCY: This migration checks if the FK already exists before adding.
-- Supports both `fk_discord_parsed_ideas_message` (already deployed) and 
-- `fk_parsed_ideas_message` (original name in this migration).

-- First, clean up any orphaned ideas (where message_id doesn't exist in discord_messages)
-- This is a safety step before adding the FK constraint
DELETE FROM discord_parsed_ideas 
WHERE message_id NOT IN (SELECT message_id FROM discord_messages);

-- Add the foreign key constraint ONLY if it doesn't already exist
-- Check for both possible constraint names
DO $$
BEGIN
    -- Check if either FK constraint already exists
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint c
        JOIN pg_class t ON t.oid = c.conrelid
        WHERE t.relname = 'discord_parsed_ideas'
        AND c.contype = 'f'
        AND c.conname IN ('fk_parsed_ideas_message', 'fk_discord_parsed_ideas_message')
    ) THEN
        -- Add the constraint only if neither exists
        ALTER TABLE discord_parsed_ideas
        ADD CONSTRAINT fk_parsed_ideas_message
        FOREIGN KEY (message_id) 
        REFERENCES discord_messages(message_id) 
        ON DELETE CASCADE;
        
        RAISE NOTICE 'Foreign key fk_parsed_ideas_message created successfully';
    ELSE
        RAISE NOTICE 'Foreign key constraint already exists, skipping creation';
    END IF;
END $$;

-- Verify at least one FK constraint exists
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint c
        JOIN pg_class t ON t.oid = c.conrelid
        WHERE t.relname = 'discord_parsed_ideas'
        AND c.contype = 'f'
        AND c.conname IN ('fk_parsed_ideas_message', 'fk_discord_parsed_ideas_message')
    ) THEN
        RAISE EXCEPTION 'No foreign key constraint found on discord_parsed_ideas.message_id';
    END IF;
END $$;
