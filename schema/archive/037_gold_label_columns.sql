-- Migration 037: Add gold label columns for human-verified labels from Argilla
-- These store the final human-corrected labels, separate from LLM predictions

-- Add gold label columns to discord_message_chunks
ALTER TABLE discord_message_chunks
ADD COLUMN IF NOT EXISTS gold_intents text[],
ADD COLUMN IF NOT EXISTS gold_facets text[],
ADD COLUMN IF NOT EXISTS labeled_at timestamptz,
ADD COLUMN IF NOT EXISTS labeled_by text;

-- Add comments for documentation
COMMENT ON COLUMN discord_message_chunks.gold_intents IS 'Human-verified intent labels from Argilla';
COMMENT ON COLUMN discord_message_chunks.gold_facets IS 'Human-verified facet labels from Argilla';
COMMENT ON COLUMN discord_message_chunks.labeled_at IS 'When the human labeling was completed';
COMMENT ON COLUMN discord_message_chunks.labeled_by IS 'Argilla user who labeled this chunk';

-- Index for finding labeled vs unlabeled chunks
CREATE INDEX IF NOT EXISTS idx_chunks_labeled 
ON discord_message_chunks (labeled_at)
WHERE labeled_at IS NOT NULL;

-- Index for training data queries (chunks with gold labels)
CREATE INDEX IF NOT EXISTS idx_chunks_gold_intents 
ON discord_message_chunks USING GIN (gold_intents)
WHERE gold_intents IS NOT NULL;
