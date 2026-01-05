-- Migration 040: Create discord_parsed_ideas table
-- Comprehensive schema for LLM-extracted trading ideas with rich metadata

CREATE TABLE IF NOT EXISTS discord_parsed_ideas (
    -- Primary identification
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    message_id BIGINT NOT NULL,  -- References discord_messages.message_id
    idea_index INTEGER NOT NULL,
    
    -- The extracted idea content
    idea_text TEXT NOT NULL,
    idea_summary TEXT,  -- LLM-generated summary of this idea
    context_summary TEXT,  -- Summary of the full message context
    
    -- Core identifiers
    primary_symbol TEXT,  -- The main focus ticker (nullable for portfolio/market)
    symbols TEXT[] DEFAULT '{}',  -- All mentioned tickers
    instrument TEXT CHECK (instrument IN ('equity', 'option', 'crypto', 'index', 'sector', 'event_contract')),
    direction TEXT CHECK (direction IN ('bullish', 'bearish', 'neutral', 'mixed')),
    
    -- Action structure
    action TEXT CHECK (action IN ('buy', 'sell', 'trim', 'add', 'watch', 'hold', 'short', 'hedge', 'none')),
    time_horizon TEXT CHECK (time_horizon IN ('scalp', 'swing', 'long_term', 'unknown')) DEFAULT 'unknown',
    trigger_condition TEXT,  -- e.g., "if breaks 220", "on pullback near 115"
    
    -- Levels (JSONB array of objects)
    -- Each: {kind: entry|target|support|resistance|stop, value, low, high, qualifier}
    levels JSONB DEFAULT '[]',
    
    -- Options-specific (nullable)
    option_type TEXT CHECK (option_type IN ('call', 'put')),
    strike NUMERIC,
    expiry DATE,
    premium NUMERIC,
    
    -- Multi-label classification (12 categories + noise)
    labels TEXT[] DEFAULT '{}',  -- Array of label names
    label_scores JSONB DEFAULT '{}',  -- {label_name: confidence_score}
    is_noise BOOLEAN DEFAULT FALSE,
    
    -- Provenance & audit trail
    author_id TEXT,
    channel_id TEXT,
    model TEXT NOT NULL,  -- e.g., 'gpt-5-mini', 'gpt-5.1'
    prompt_version TEXT NOT NULL,  -- e.g., 'v1.0'
    confidence NUMERIC(4,3),  -- Overall extraction confidence
    parsed_at TIMESTAMPTZ DEFAULT NOW(),
    raw_json JSONB,  -- Full LLM response for future-proofing
    
    -- Source tracking
    source_created_at TIMESTAMPTZ,  -- Original message timestamp
    
    -- Constraints
    UNIQUE(message_id, idea_index)
);

-- Performance indexes for common query patterns

-- Primary symbol lookups (most common filter)
CREATE INDEX IF NOT EXISTS idx_parsed_ideas_primary_symbol 
    ON discord_parsed_ideas(primary_symbol) 
    WHERE primary_symbol IS NOT NULL;

-- Direction filter (bullish/bearish)
CREATE INDEX IF NOT EXISTS idx_parsed_ideas_direction 
    ON discord_parsed_ideas(direction);

-- Action filter (buy/sell/watch)
CREATE INDEX IF NOT EXISTS idx_parsed_ideas_action 
    ON discord_parsed_ideas(action);

-- Time horizon filter
CREATE INDEX IF NOT EXISTS idx_parsed_ideas_time_horizon 
    ON discord_parsed_ideas(time_horizon);

-- Instrument type filter
CREATE INDEX IF NOT EXISTS idx_parsed_ideas_instrument 
    ON discord_parsed_ideas(instrument);

-- Multi-label search using GIN index
CREATE INDEX IF NOT EXISTS idx_parsed_ideas_labels 
    ON discord_parsed_ideas USING GIN(labels);

-- Symbols array search
CREATE INDEX IF NOT EXISTS idx_parsed_ideas_symbols 
    ON discord_parsed_ideas USING GIN(symbols);

-- Noise filter
CREATE INDEX IF NOT EXISTS idx_parsed_ideas_noise 
    ON discord_parsed_ideas(is_noise) 
    WHERE is_noise = FALSE;

-- Timestamp range queries
CREATE INDEX IF NOT EXISTS idx_parsed_ideas_parsed_at 
    ON discord_parsed_ideas(parsed_at DESC);

CREATE INDEX IF NOT EXISTS idx_parsed_ideas_source_created 
    ON discord_parsed_ideas(source_created_at DESC);

-- Options-specific queries
CREATE INDEX IF NOT EXISTS idx_parsed_ideas_options 
    ON discord_parsed_ideas(option_type, strike, expiry) 
    WHERE option_type IS NOT NULL;

-- Message lookup
CREATE INDEX IF NOT EXISTS idx_parsed_ideas_message 
    ON discord_parsed_ideas(message_id);

-- Enable RLS
ALTER TABLE discord_parsed_ideas ENABLE ROW LEVEL SECURITY;

-- RLS policy for service role access
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies 
        WHERE tablename = 'discord_parsed_ideas' AND policyname = 'Allow service role full access'
    ) THEN
        CREATE POLICY "Allow service role full access" ON discord_parsed_ideas
            FOR ALL TO service_role USING (true) WITH CHECK (true);
    END IF;
END $$;

-- Table and column comments for documentation
COMMENT ON TABLE discord_parsed_ideas IS 'LLM-extracted trading ideas with rich metadata for search, filtering, and summarization';
COMMENT ON COLUMN discord_parsed_ideas.primary_symbol IS 'Main ticker this idea focuses on (nullable for market/portfolio-wide ideas)';
COMMENT ON COLUMN discord_parsed_ideas.symbols IS 'All tickers mentioned in this idea';
COMMENT ON COLUMN discord_parsed_ideas.instrument IS 'Asset type: equity, option, crypto, index, sector, event_contract';
COMMENT ON COLUMN discord_parsed_ideas.direction IS 'Sentiment direction: bullish, bearish, neutral, mixed';
COMMENT ON COLUMN discord_parsed_ideas.action IS 'Intended trade action: buy, sell, trim, add, watch, hold, short, hedge, none';
COMMENT ON COLUMN discord_parsed_ideas.time_horizon IS 'Trading timeframe: scalp, swing, long_term, unknown';
COMMENT ON COLUMN discord_parsed_ideas.trigger_condition IS 'Condition for trade entry, e.g., "if breaks 220"';
COMMENT ON COLUMN discord_parsed_ideas.levels IS 'Price levels array: [{kind, value, low, high, qualifier}]';
COMMENT ON COLUMN discord_parsed_ideas.labels IS 'Multi-label classification from 13-category taxonomy';
COMMENT ON COLUMN discord_parsed_ideas.label_scores IS 'Confidence scores for each label';
COMMENT ON COLUMN discord_parsed_ideas.is_noise IS 'Whether this idea was classified as noise/non-actionable';
COMMENT ON COLUMN discord_parsed_ideas.raw_json IS 'Full LLM response preserved for future reprocessing';
