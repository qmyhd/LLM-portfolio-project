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

-- created_day is used for same-day dedup without non-IMMUTABLE index expressions.
ALTER TABLE public.user_ideas
ADD COLUMN IF NOT EXISTS created_day date;

-- Backfill for existing rows (timezone-explicit to avoid ambiguity)
UPDATE public.user_ideas
SET created_day = (created_at AT TIME ZONE 'UTC')::date
WHERE created_day IS NULL;

-- Fast lookups by primary symbol
DROP INDEX IF EXISTS public.idx_user_ideas_symbol_created;
CREATE INDEX IF NOT EXISTS idx_user_ideas_symbol_created
    ON public.user_ideas (symbol, created_at DESC);

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

-- Ensure future inserts populate created_day
CREATE OR REPLACE FUNCTION public.set_user_ideas_created_day()
RETURNS TRIGGER
LANGUAGE plpgsql
SET search_path TO 'public'
AS $$
BEGIN
    -- Mimic default now() if created_at wasn't provided
    IF NEW.created_at IS NULL THEN
        NEW.created_at := NOW();
    END IF;

    NEW.created_day := (NEW.created_at AT TIME ZONE 'UTC')::date;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS user_ideas_set_created_day ON public.user_ideas;
CREATE TRIGGER user_ideas_set_created_day
BEFORE INSERT ON public.user_ideas
FOR EACH ROW
EXECUTE FUNCTION public.set_user_ideas_created_day();

-- Drop the old broken index if it exists (older deploys)
DROP INDEX IF EXISTS public.idx_user_ideas_hash_day;

-- Same-day content dedup: one per content_hash per day
CREATE UNIQUE INDEX IF NOT EXISTS idx_user_ideas_hash_day
    ON public.user_ideas (content_hash, created_day);

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
