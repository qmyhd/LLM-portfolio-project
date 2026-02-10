-- Migration 042: Add chunk indexing columns for deterministic batch processing
-- Adds soft_chunk_index and local_idea_index to enable deterministic ordering
-- when batch results arrive unordered

-- 1. Add new columns
ALTER TABLE discord_parsed_ideas 
ADD COLUMN IF NOT EXISTS soft_chunk_index INTEGER DEFAULT 0 NOT NULL,
ADD COLUMN IF NOT EXISTS local_idea_index INTEGER DEFAULT 0 NOT NULL;

-- 2. Backfill local_idea_index from existing idea_index
-- For existing rows, soft_chunk_index stays 0 (non-chunked), local_idea_index = idea_index
UPDATE discord_parsed_ideas 
SET local_idea_index = idea_index 
WHERE local_idea_index = 0;

-- 3. Drop old unique constraint
ALTER TABLE discord_parsed_ideas 
DROP CONSTRAINT IF EXISTS discord_parsed_ideas_message_id_idea_index_key;

-- 4. Add new unique constraint on (message_id, soft_chunk_index, local_idea_index)
ALTER TABLE discord_parsed_ideas 
ADD CONSTRAINT discord_parsed_ideas_message_chunk_idx_key 
UNIQUE (message_id, soft_chunk_index, local_idea_index);

-- 5. Add index for efficient querying by message
CREATE INDEX IF NOT EXISTS idx_parsed_ideas_message_chunks 
ON discord_parsed_ideas (message_id, soft_chunk_index, local_idea_index);

-- 6. Add comment explaining the indexing strategy
COMMENT ON COLUMN discord_parsed_ideas.soft_chunk_index IS 'Index of the soft chunk this idea came from (0-based, 0 for non-chunked messages)';
COMMENT ON COLUMN discord_parsed_ideas.local_idea_index IS 'Index of the idea within its soft chunk (0-based)';
COMMENT ON COLUMN discord_parsed_ideas.idea_index IS 'Global idea index across all chunks (computed for backwards compatibility)';
