-- =======================================================================
-- Migration 074: Video research saved quotes (YouTube)
-- =======================================================================
-- Stores ONLY user-saved quote excerpts. Transcripts are fetched live and
-- never persisted (spec: "saved excerpts only"). Additive only. RLS enabled
-- (no explicit policy — service role, mirrors 073). updated_at trigger reuses
-- 073's public.tg_credibility_set_updated_at().

CREATE TABLE IF NOT EXISTS public.video_quotes (
    id                      SERIAL PRIMARY KEY,
    video_id                TEXT NOT NULL,
    video_url               TEXT NOT NULL,
    video_title             TEXT,
    channel_name            TEXT,
    channel_url             TEXT,
    quote_text              TEXT NOT NULL,
    start_seconds           NUMERIC NOT NULL,
    end_seconds             NUMERIC,
    person_id               INTEGER REFERENCES public.people(id) ON DELETE SET NULL,
    category_slug           TEXT REFERENCES public.credibility_categories(slug),
    ticker                  VARCHAR(20),
    stock_thesis_profile_id INTEGER REFERENCES public.stock_thesis_profiles(id) ON DELETE SET NULL,
    thesis_note             TEXT,
    tags                    TEXT[] NOT NULL DEFAULT '{}',
    notes                   TEXT,
    status                  text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'archived')),
    saved_at                TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_video_quotes_video    ON public.video_quotes (video_id);
CREATE INDEX IF NOT EXISTS idx_video_quotes_person   ON public.video_quotes (person_id);
CREATE INDEX IF NOT EXISTS idx_video_quotes_category ON public.video_quotes (category_slug);
CREATE INDEX IF NOT EXISTS idx_video_quotes_ticker   ON public.video_quotes (UPPER(ticker));
CREATE INDEX IF NOT EXISTS idx_video_quotes_status   ON public.video_quotes (status);

DROP TRIGGER IF EXISTS video_quotes_updated_at ON public.video_quotes;
CREATE TRIGGER video_quotes_updated_at
    BEFORE UPDATE ON public.video_quotes
    FOR EACH ROW EXECUTE FUNCTION public.tg_credibility_set_updated_at();

ALTER TABLE public.video_quotes ENABLE ROW LEVEL SECURITY;

INSERT INTO public.schema_migrations (version, description)
VALUES ('074_video_quotes', 'Video research saved quote excerpts (YouTube)')
ON CONFLICT (version) DO NOTHING;
