-- =======================================================================
-- Migration 072: Stock thesis profiles (AI-co-authored research dossiers)
-- =======================================================================
-- A per-(symbol, bucket) thesis dossier the user builds with AI. `bucket`
-- is the user's chosen strategy LABEL at creation (one of the 5 concrete
-- values — NOT 'all', which is a read-only aggregate view, unlike the
-- 070/071 caches). A surrogate `id` PK keeps the revisions FK simple, with
-- a separate UNIQUE(symbol, bucket) enforcing one profile per pair.

CREATE TABLE IF NOT EXISTS public.stock_thesis_profiles (
    id                    SERIAL PRIMARY KEY,
    symbol                VARCHAR(20) NOT NULL,
    bucket                text NOT NULL
        CHECK (bucket IN ('long_term', 'swing', 'day', 'retirement', 'other')),
    thesis                TEXT,
    conviction            SMALLINT CHECK (conviction BETWEEN 1 AND 5),
    conviction_rationale  TEXT,
    bull_case             TEXT,
    bear_case             TEXT,
    catalysts             JSONB NOT NULL DEFAULT '[]'::jsonb,
    risks                 JSONB NOT NULL DEFAULT '[]'::jsonb,
    levels                JSONB NOT NULL DEFAULT '{}'::jsonb,
    horizon               text,
    tags                  TEXT[] NOT NULL DEFAULT '{}',
    status                text NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft', 'active', 'archived')),
    ai_autofill_json      JSONB,
    interview_json        JSONB,
    model_used            text,
    data_sources          TEXT[] NOT NULL DEFAULT '{}',
    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    reviewed_at           TIMESTAMPTZ,
    CONSTRAINT stock_thesis_profiles_symbol_bucket_key UNIQUE (symbol, bucket)
);

CREATE INDEX IF NOT EXISTS idx_stock_thesis_profiles_symbol
    ON public.stock_thesis_profiles (UPPER(symbol));
CREATE INDEX IF NOT EXISTS idx_stock_thesis_profiles_bucket
    ON public.stock_thesis_profiles (bucket);
CREATE INDEX IF NOT EXISTS idx_stock_thesis_profiles_reviewed_at
    ON public.stock_thesis_profiles (reviewed_at);

CREATE OR REPLACE FUNCTION public.update_stock_thesis_profiles_updated_at()
RETURNS TRIGGER
LANGUAGE plpgsql
SET search_path TO 'public'
AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS stock_thesis_profiles_updated_at ON public.stock_thesis_profiles;
CREATE TRIGGER stock_thesis_profiles_updated_at
    BEFORE UPDATE ON public.stock_thesis_profiles
    FOR EACH ROW
    EXECUTE FUNCTION public.update_stock_thesis_profiles_updated_at();

ALTER TABLE public.stock_thesis_profiles ENABLE ROW LEVEL SECURITY;

-- Revision history: one snapshot appended on every save.
CREATE TABLE IF NOT EXISTS public.stock_thesis_profile_revisions (
    id            SERIAL PRIMARY KEY,
    profile_id    INTEGER NOT NULL
        REFERENCES public.stock_thesis_profiles (id) ON DELETE CASCADE,
    symbol        VARCHAR(20) NOT NULL,
    bucket        text NOT NULL,
    snapshot_json JSONB NOT NULL,
    conviction    SMALLINT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_stock_thesis_profile_revisions_profile
    ON public.stock_thesis_profile_revisions (profile_id, created_at DESC);

ALTER TABLE public.stock_thesis_profile_revisions ENABLE ROW LEVEL SECURITY;

INSERT INTO public.schema_migrations (version, description)
VALUES ('072_stock_thesis_profiles', 'AI-co-authored per-(symbol,bucket) thesis profiles + revisions')
ON CONFLICT (version) DO NOTHING;
