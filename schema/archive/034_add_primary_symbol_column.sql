-- Migration 034: Add primary_symbol column to discord_message_chunks
-- This column stores the "subject" ticker of a chunk (from ## $TICKER headers or - $TICKER bullets)
-- Applied: 2025-12-13

ALTER TABLE discord_message_chunks
ADD COLUMN IF NOT EXISTS primary_symbol TEXT;

-- Add comment explaining the column
COMMENT ON COLUMN discord_message_chunks.primary_symbol IS 
    'Primary/subject ticker for this chunk, extracted from ## $TICKER headers or - $TICKER bullets';

-- Create index for querying by primary symbol
CREATE INDEX IF NOT EXISTS idx_chunks_primary_symbol 
ON discord_message_chunks(primary_symbol) 
WHERE primary_symbol IS NOT NULL;
