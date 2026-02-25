-- =======================================================================
-- Migration 064: Add user_ideas table for unified ideas store
-- =======================================================================
-- Coexists with discord_parsed_ideas (NLP output).
-- This is the user-facing "journal" layer for ideas from any source:
-- Discord (promoted), manual entry, or transcribed audio.

CREATE TABLE IF NOT EXISTS public.user_ideas (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    symbol            TEXT,                    -- primary symbol (nullable for general ideas)
    symbols           TEXT[],                  -- multi-symbol attachment
    content           TEXT NOT NULL,
    source            TEXT NOT NULL CHECK (source IN ('discord', 'manual', 'transcribe')),
    status            TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'refined', 'archived')),
    tags              TEXT[],
    origin_message_id TEXT,                    -- reference to discord_messages.message_id
    content_hash      TEXT NOT NULL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Fast lookups by primary symbol
CREATE INDEX IF NOT EXISTS idx_user_ideas_symbol_created
    ON public.user_ideas (UPPER(symbol), created_at DESC);

-- GIN indexes for array containment queries
CREATE INDEX IF NOT EXISTS idx_user_ideas_tags
    ON public.user_ideas USING GIN (tags);

CREATE INDEX IF NOT EXISTS idx_user_ideas_symbols
    ON public.user_ideas USING GIN (symbols);

-- Filter by source + recent
CREATE INDEX IF NOT EXISTS idx_user_ideas_source_created
    ON public.user_ideas (source, created_at DESC);

-- Content hash for dedup lookups
CREATE INDEX IF NOT EXISTS idx_user_ideas_content_hash
    ON public.user_ideas (content_hash);

-- Partial unique: one entry per Discord message (prevents duplicate imports)
CREATE UNIQUE INDEX IF NOT EXISTS idx_user_ideas_origin_unique
    ON public.user_ideas (source, origin_message_id)
    WHERE origin_message_id IS NOT NULL;

-- Same-day content dedup (prevents spam/duplicate submissions)
CREATE UNIQUE INDEX IF NOT EXISTS idx_user_ideas_hash_day
    ON public.user_ideas (content_hash, (created_at::date));

-- Auto-update updated_at on row modification
CREATE OR REPLACE FUNCTION public.update_user_ideas_updated_at()
RETURNS TRIGGER
LANGUAGE plpgsql
SET search_path TO 'public'
AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS user_ideas_updated_at ON public.user_ideas;
CREATE TRIGGER user_ideas_updated_at
    BEFORE UPDATE ON public.user_ideas
    FOR EACH ROW
    EXECUTE FUNCTION public.update_user_ideas_updated_at();

-- Enable Row Level Security (project standard)
ALTER TABLE public.user_ideas ENABLE ROW LEVEL SECURITY;
