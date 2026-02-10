-- Migration 039: Add parsing status columns to discord_messages
-- Tracks LLM parsing status for each message

-- Add parsing status columns
ALTER TABLE discord_messages
  ADD COLUMN IF NOT EXISTS prompt_version TEXT,
  ADD COLUMN IF NOT EXISTS parse_status TEXT NOT NULL DEFAULT 'pending',
  ADD COLUMN IF NOT EXISTS error_reason TEXT;

-- Add check constraint for parse_status values
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint 
        WHERE conname = 'discord_messages_parse_status_chk'
    ) THEN
        ALTER TABLE discord_messages
            ADD CONSTRAINT discord_messages_parse_status_chk
            CHECK (parse_status IN ('pending', 'ok', 'error', 'skipped', 'noise'));
    END IF;
END $$;

-- Index for finding unparsed messages
CREATE INDEX IF NOT EXISTS idx_discord_messages_parse_status 
    ON discord_messages(parse_status) 
    WHERE parse_status = 'pending';

-- Index for finding messages with errors
CREATE INDEX IF NOT EXISTS idx_discord_messages_parse_errors
    ON discord_messages(parse_status)
    WHERE parse_status = 'error';

COMMENT ON COLUMN discord_messages.prompt_version IS 'Version of the prompt used for LLM parsing (e.g., v1.0)';
COMMENT ON COLUMN discord_messages.parse_status IS 'LLM parsing status: pending, ok, error, skipped, noise';
COMMENT ON COLUMN discord_messages.error_reason IS 'Error message if parse_status is error';
