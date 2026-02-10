-- Migration 038: Create discord_idea_units table for semantic chunking
-- Each idea unit represents ONE distinct thought about ONE subject

CREATE TABLE IF NOT EXISTS discord_idea_units (
    -- Primary identification
    message_id TEXT NOT NULL,
    idea_index INTEGER NOT NULL,
    
    -- The extracted idea content
    idea_text TEXT NOT NULL,
    
    -- Subject identification (the KEY improvement)
    subject_symbol TEXT,  -- NULL for portfolio/market-wide ideas
    subject_type TEXT NOT NULL CHECK (subject_type IN ('stock', 'market', 'portfolio', 'crypto', 'other')),
    
    -- Classification (aligned with intent taxonomy)
    idea_type TEXT NOT NULL,  -- 'TECHNICAL_ANALYSIS', 'TRADE_PLAN', 'FUNDAMENTAL_THESIS', etc.
    
    -- LLM extraction metadata
    confidence NUMERIC(4,3),
    llm_model TEXT,
    llm_reasoning TEXT,
    extracted_at TIMESTAMPTZ DEFAULT NOW(),
    
    -- Source tracking
    source_table TEXT,  -- 'discord_trading_clean' or 'discord_market_clean'
    
    -- Gold labels for training (human corrections)
    gold_subject_symbol TEXT,
    gold_subject_type TEXT,
    gold_idea_type TEXT,
    gold_idea_text TEXT,  -- Corrected text boundaries
    labeled_at TIMESTAMPTZ,
    labeled_by TEXT,
    
    -- Metadata for training
    char_count INTEGER GENERATED ALWAYS AS (LENGTH(idea_text)) STORED,
    
    PRIMARY KEY (message_id, idea_index)
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_idea_units_subject_symbol ON discord_idea_units(subject_symbol) WHERE subject_symbol IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_idea_units_subject_type ON discord_idea_units(subject_type);
CREATE INDEX IF NOT EXISTS idx_idea_units_idea_type ON discord_idea_units(idea_type);
CREATE INDEX IF NOT EXISTS idx_idea_units_unlabeled ON discord_idea_units(message_id) WHERE gold_idea_type IS NULL;
CREATE INDEX IF NOT EXISTS idx_idea_units_source ON discord_idea_units(source_table);

-- Enable RLS
ALTER TABLE discord_idea_units ENABLE ROW LEVEL SECURITY;

-- RLS policy for service role access
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies 
        WHERE tablename = 'discord_idea_units' AND policyname = 'Allow service role full access'
    ) THEN
        CREATE POLICY "Allow service role full access" ON discord_idea_units
            FOR ALL TO service_role USING (true) WITH CHECK (true);
    END IF;
END $$;

COMMENT ON TABLE discord_idea_units IS 'Semantic chunks extracted from Discord messages - one idea per row with single subject';
COMMENT ON COLUMN discord_idea_units.subject_symbol IS 'The primary stock/crypto this idea is about (NULL for portfolio/market-wide)';
COMMENT ON COLUMN discord_idea_units.subject_type IS 'Category of subject: stock, market, portfolio, crypto, other';
COMMENT ON COLUMN discord_idea_units.idea_type IS 'Classification matching intent taxonomy (TRADE_PLAN, TECHNICAL_ANALYSIS, etc.)';
