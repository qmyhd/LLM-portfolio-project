-- Migration: 056_add_message_flags.sql
-- Description: Add is_bot, is_command, and channel_type flags to discord_messages
-- Purpose: Enable filtering of bot/command messages from NLP parsing pipeline
-- Date: 2026-01-26

-- Add is_bot column: TRUE if message author is a bot
ALTER TABLE discord_messages
ADD COLUMN IF NOT EXISTS is_bot BOOLEAN DEFAULT FALSE;

-- Add is_command column: TRUE if message is a bot command (starts with !, /, etc.)
ALTER TABLE discord_messages
ADD COLUMN IF NOT EXISTS is_command BOOLEAN DEFAULT FALSE;

-- Add channel_type column: Categorize channel for downstream processing
-- Values: 'trading', 'market', 'general', or NULL for unknown
ALTER TABLE discord_messages
ADD COLUMN IF NOT EXISTS channel_type TEXT;

-- Add index for filtering out bot/command messages in NLP pipeline
CREATE INDEX IF NOT EXISTS idx_discord_messages_parse_filter
ON discord_messages (is_bot, is_command)
WHERE is_bot = FALSE AND is_command = FALSE;

-- Add index for channel_type filtering
CREATE INDEX IF NOT EXISTS idx_discord_messages_channel_type
ON discord_messages (channel_type)
WHERE channel_type IS NOT NULL;

-- Comment on columns for documentation
COMMENT ON COLUMN discord_messages.is_bot IS 'TRUE if message author is a Discord bot';
COMMENT ON COLUMN discord_messages.is_command IS 'TRUE if message starts with command prefix (!, /, etc.)';
COMMENT ON COLUMN discord_messages.channel_type IS 'Channel category: trading, market, general';
