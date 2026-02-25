-- =======================================================================
-- Migration 063: Discord incremental ingestion cursor tracking
-- =======================================================================
-- Adds discord_ingestion_state table to track per-channel ingestion
-- cursors, and content_hash column on discord_messages for dedup.

-- ── discord_ingestion_state: one row per channel, tracks cursor ──────
CREATE TABLE IF NOT EXISTS public.discord_ingestion_state (
    channel_id      TEXT PRIMARY KEY,
    channel_name    TEXT,
    last_message_id TEXT,                -- Discord snowflake of last ingested message
    last_message_ts TIMESTAMPTZ,         -- Timestamp of that message (for readability)
    messages_total  BIGINT DEFAULT 0,    -- Running count of all ingested messages
    last_run_at     TIMESTAMPTZ,         -- When last run completed
    last_run_new    INTEGER DEFAULT 0,   -- New messages in last run
    last_run_dupes  INTEGER DEFAULT 0,   -- Dupes skipped in last run
    status          TEXT DEFAULT 'idle', -- idle | running | error
    error_message   TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Index on status for finding stale/errored channels
CREATE INDEX IF NOT EXISTS idx_discord_ingestion_state_status
    ON public.discord_ingestion_state (status);

-- Auto-update updated_at on row modification
CREATE OR REPLACE FUNCTION public.update_discord_ingestion_state_updated_at()
RETURNS TRIGGER
LANGUAGE plpgsql
SET search_path TO 'public'
AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS discord_ingestion_state_updated_at ON public.discord_ingestion_state;
CREATE TRIGGER discord_ingestion_state_updated_at
    BEFORE UPDATE ON public.discord_ingestion_state
    FOR EACH ROW
    EXECUTE FUNCTION public.update_discord_ingestion_state_updated_at();

-- Enable Row Level Security (project standard)
ALTER TABLE public.discord_ingestion_state ENABLE ROW LEVEL SECURITY;

-- ── Add content_hash column to discord_messages (nullable, backward-compatible) ──
ALTER TABLE public.discord_messages ADD COLUMN IF NOT EXISTS content_hash TEXT;

CREATE INDEX IF NOT EXISTS idx_discord_messages_content_hash
    ON public.discord_messages (content_hash) WHERE content_hash IS NOT NULL;

-- Composite index for cursor queries (channel + message_id)
CREATE INDEX IF NOT EXISTS idx_discord_messages_channel_message_id
    ON public.discord_messages (channel, message_id);
