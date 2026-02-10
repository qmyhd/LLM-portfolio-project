-- Migration 036: Add LLM tagging columns to discord_message_chunks
-- Purpose: Store OpenAI GPT-4o-mini predictions for automatic chunk tagging
-- This enables:
--   1. Auto-filling chunk metadata using LLM
--   2. Argilla workflow with LLM suggestions for human correction
--   3. Training data collection for custom models

-- Add LLM prediction columns
ALTER TABLE discord_message_chunks
ADD COLUMN IF NOT EXISTS llm_intents text[] DEFAULT '{}',
ADD COLUMN IF NOT EXISTS llm_facets text[] DEFAULT '{}',
ADD COLUMN IF NOT EXISTS llm_summary text,
ADD COLUMN IF NOT EXISTS llm_action_items text[] DEFAULT '{}',
ADD COLUMN IF NOT EXISTS llm_confidence numeric(3,2),
ADD COLUMN IF NOT EXISTS llm_reasoning text,
ADD COLUMN IF NOT EXISTS llm_model text,
ADD COLUMN IF NOT EXISTS llm_tagged_at timestamptz;

-- Add index for filtering by LLM-tagged status
CREATE INDEX IF NOT EXISTS idx_chunks_llm_tagged 
ON discord_message_chunks(llm_tagged_at) 
WHERE llm_tagged_at IS NOT NULL;

-- Add index for filtering by confidence
CREATE INDEX IF NOT EXISTS idx_chunks_llm_confidence
ON discord_message_chunks(llm_confidence)
WHERE llm_confidence IS NOT NULL;

COMMENT ON COLUMN discord_message_chunks.llm_intents IS 'LLM-predicted intent labels (TRADE_EXECUTION, TRADE_PLAN, etc.)';
COMMENT ON COLUMN discord_message_chunks.llm_facets IS 'LLM-predicted facet labels (OPTIONS_DERIVATIVES, RISK_MANAGEMENT, etc.)';
COMMENT ON COLUMN discord_message_chunks.llm_summary IS 'Brief LLM-generated summary of the chunk';
COMMENT ON COLUMN discord_message_chunks.llm_action_items IS 'Extracted action items (e.g., "Buy AAPL at $150")';
COMMENT ON COLUMN discord_message_chunks.llm_confidence IS 'LLM confidence score (0.00 to 1.00)';
COMMENT ON COLUMN discord_message_chunks.llm_reasoning IS 'Brief explanation of LLM classification';
COMMENT ON COLUMN discord_message_chunks.llm_model IS 'Model used for tagging (e.g., gpt-4o-mini)';
COMMENT ON COLUMN discord_message_chunks.llm_tagged_at IS 'Timestamp when LLM tagging was performed';
