-- Migration: Add attachments column to discord_messages table
-- Date: 2025-11-01
-- Description: Add JSON column to store message attachments (URLs, filenames, etc.)

-- Add attachments column to discord_messages
ALTER TABLE discord_messages
ADD COLUMN IF NOT EXISTS attachments TEXT;

COMMENT ON COLUMN discord_messages.attachments IS 'JSON array of attachment URLs and metadata';
