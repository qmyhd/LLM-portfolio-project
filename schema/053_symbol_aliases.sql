-- Migration 053: Create symbol_aliases table
--
-- Purpose: Track ticker symbol aliases/variants for better symbol resolution
-- Used by message_cleaner.py and symbol_resolver.py to handle:
--   - Discord formatting variants ($AAPL vs AAPL)
--   - SnapTrade symbol formats
--   - Manual mappings for common aliases
--
-- Date: 2026-01-26

-- ============================================================================
-- CREATE TABLE
-- ============================================================================

CREATE TABLE IF NOT EXISTS public.symbol_aliases (
    id SERIAL PRIMARY KEY,
    ticker VARCHAR(10) NOT NULL,           -- Canonical ticker (e.g., 'AAPL')
    alias VARCHAR(50) NOT NULL,            -- Variant/alias (e.g., '$AAPL', 'Apple', 'apple inc')
    source VARCHAR(20) NOT NULL DEFAULT 'manual',  -- Source: 'discord', 'snaptrade', 'manual'
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    -- Ensure unique alias per source (same alias can come from different sources)
    CONSTRAINT symbol_aliases_alias_source_unique UNIQUE (alias, source)
);

-- Index for fast lookups by alias
CREATE INDEX IF NOT EXISTS idx_symbol_aliases_alias ON public.symbol_aliases(alias);
CREATE INDEX IF NOT EXISTS idx_symbol_aliases_ticker ON public.symbol_aliases(ticker);
CREATE INDEX IF NOT EXISTS idx_symbol_aliases_source ON public.symbol_aliases(source);

-- Case-insensitive lookup index
CREATE INDEX IF NOT EXISTS idx_symbol_aliases_alias_lower ON public.symbol_aliases(LOWER(alias));

-- ============================================================================
-- ROW LEVEL SECURITY
-- ============================================================================

ALTER TABLE public.symbol_aliases ENABLE ROW LEVEL SECURITY;

-- Read access for all
CREATE POLICY "anon_read_symbol_aliases" ON public.symbol_aliases
    FOR SELECT TO anon USING (true);

CREATE POLICY "authenticated_read_symbol_aliases" ON public.symbol_aliases
    FOR SELECT TO authenticated USING (true);

-- Full access for service role
CREATE POLICY "service_role_all_symbol_aliases" ON public.symbol_aliases
    FOR ALL TO service_role USING (true) WITH CHECK (true);

-- ============================================================================
-- COMMENTS
-- ============================================================================

COMMENT ON TABLE public.symbol_aliases IS 'Symbol aliases/variants for improved ticker resolution across sources';
COMMENT ON COLUMN public.symbol_aliases.ticker IS 'Canonical ticker symbol (uppercase, 1-10 chars)';
COMMENT ON COLUMN public.symbol_aliases.alias IS 'Alias or variant of the ticker (case-preserved)';
COMMENT ON COLUMN public.symbol_aliases.source IS 'Source of alias: discord, snaptrade, manual';

-- ============================================================================
-- RECORD MIGRATION
-- ============================================================================

INSERT INTO schema_migrations (version, description, applied_at)
VALUES ('053', 'Create symbol_aliases table for ticker resolution', NOW())
ON CONFLICT (version) DO NOTHING;
