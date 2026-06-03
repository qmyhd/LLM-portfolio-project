-- =======================================================================
-- Migration 073: Source credibility layer (Phase 1)
-- =======================================================================
-- Manually-curated person/source S/A/B/C/D credibility tiers per topic
-- category, with narrative profiles + revision history, plus per-stock topic
-- tags for context-routed weighting of the Discord-ideas sentiment source.
--
-- Additive only. RLS is ENABLED on every new table with NO explicit policy --
-- exactly like 072: the service role in DATABASE_URL bypasses RLS, so an
-- enabled-but-policy-less table is the project's established "locked down to
-- service role" pattern. Mirrors 072 otherwise: main table + revision
-- snapshots + a BEFORE UPDATE updated_at trigger + a schema_migrations row.

-- Shared updated_at trigger function (scoped name to avoid clobbering any
-- existing generic helper; same mechanism as 072's per-table function).
CREATE OR REPLACE FUNCTION public.tg_credibility_set_updated_at()
RETURNS TRIGGER
LANGUAGE plpgsql
SET search_path TO 'public'
AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;

-- People (curated profile entity) --------------------------------------
CREATE TABLE IF NOT EXISTS public.people (
    id           SERIAL PRIMARY KEY,
    full_name    TEXT NOT NULL,
    display_name TEXT,
    role         TEXT,
    bio          TEXT,
    notes        TEXT,
    status       text NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'archived')),
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_people_status ON public.people (status);

DROP TRIGGER IF EXISTS people_updated_at ON public.people;
CREATE TRIGGER people_updated_at
    BEFORE UPDATE ON public.people
    FOR EACH ROW EXECUTE FUNCTION public.tg_credibility_set_updated_at();

ALTER TABLE public.people ENABLE ROW LEVEL SECURITY;

-- Revision history: one snapshot appended on every save (mirrors 072) -----
CREATE TABLE IF NOT EXISTS public.person_revisions (
    id            SERIAL PRIMARY KEY,
    person_id     INTEGER NOT NULL
        REFERENCES public.people (id) ON DELETE CASCADE,
    snapshot_json JSONB NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_person_revisions_person
    ON public.person_revisions (person_id, created_at DESC);

ALTER TABLE public.person_revisions ENABLE ROW LEVEL SECURITY;

-- Credibility categories (editable taxonomy) ---------------------------
CREATE TABLE IF NOT EXISTS public.credibility_categories (
    slug        TEXT PRIMARY KEY,
    label       TEXT NOT NULL,
    description TEXT,
    sort_order  INTEGER NOT NULL DEFAULT 0
);

ALTER TABLE public.credibility_categories ENABLE ROW LEVEL SECURITY;

-- Per-(person, category) tier ------------------------------------------
CREATE TABLE IF NOT EXISTS public.person_category_tiers (
    id            SERIAL PRIMARY KEY,
    person_id     INTEGER NOT NULL
        REFERENCES public.people (id) ON DELETE CASCADE,
    category_slug TEXT NOT NULL
        REFERENCES public.credibility_categories (slug),
    tier          text NOT NULL CHECK (tier IN ('S', 'A', 'B', 'C', 'D')),
    muted         BOOLEAN NOT NULL DEFAULT FALSE,
    rationale     TEXT,
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT person_category_tiers_person_category_key UNIQUE (person_id, category_slug)
);
CREATE INDEX IF NOT EXISTS idx_person_category_tiers_category
    ON public.person_category_tiers (category_slug);

DROP TRIGGER IF EXISTS person_category_tiers_updated_at ON public.person_category_tiers;
CREATE TRIGGER person_category_tiers_updated_at
    BEFORE UPDATE ON public.person_category_tiers
    FOR EACH ROW EXECUTE FUNCTION public.tg_credibility_set_updated_at();

ALTER TABLE public.person_category_tiers ENABLE ROW LEVEL SECURITY;

-- Stable source identities (flag-don't-merge) --------------------------
CREATE TABLE IF NOT EXISTS public.source_identities (
    id               SERIAL PRIMARY KEY,
    person_id        INTEGER REFERENCES public.people (id) ON DELETE SET NULL,
    platform         text NOT NULL
        CHECK (platform IN ('twitter', 'discord', 'youtube')),
    platform_user_id TEXT NOT NULL,
    handle           TEXT,
    match_status     text NOT NULL DEFAULT 'suggested'
        CHECK (match_status IN ('confirmed', 'suggested', 'unmatched', 'conflict')),
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT source_identities_platform_user_key UNIQUE (platform, platform_user_id)
);
CREATE INDEX IF NOT EXISTS idx_source_identities_person
    ON public.source_identities (person_id);

DROP TRIGGER IF EXISTS source_identities_updated_at ON public.source_identities;
CREATE TRIGGER source_identities_updated_at
    BEFORE UPDATE ON public.source_identities
    FOR EACH ROW EXECUTE FUNCTION public.tg_credibility_set_updated_at();

ALTER TABLE public.source_identities ENABLE ROW LEVEL SECURITY;

-- Tier -> multiplier (tunable curve) -----------------------------------
CREATE TABLE IF NOT EXISTS public.tier_multipliers (
    tier       text PRIMARY KEY CHECK (tier IN ('S', 'A', 'B', 'C', 'D')),
    multiplier NUMERIC NOT NULL
);

ALTER TABLE public.tier_multipliers ENABLE ROW LEVEL SECURITY;

-- Per-stock topic tags (context routing) -------------------------------
CREATE TABLE IF NOT EXISTS public.stock_topic_tags (
    id            SERIAL PRIMARY KEY,
    symbol        VARCHAR(20) NOT NULL,
    category_slug TEXT NOT NULL
        REFERENCES public.credibility_categories (slug),
    weight        NUMERIC NOT NULL CHECK (weight >= 0),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT stock_topic_tags_symbol_category_key UNIQUE (symbol, category_slug)
);
CREATE INDEX IF NOT EXISTS idx_stock_topic_tags_symbol
    ON public.stock_topic_tags (UPPER(symbol));

DROP TRIGGER IF EXISTS stock_topic_tags_updated_at ON public.stock_topic_tags;
CREATE TRIGGER stock_topic_tags_updated_at
    BEFORE UPDATE ON public.stock_topic_tags
    FOR EACH ROW EXECUTE FUNCTION public.tg_credibility_set_updated_at();

ALTER TABLE public.stock_topic_tags ENABLE ROW LEVEL SECURITY;

-- Seeds ----------------------------------------------------------------
INSERT INTO public.credibility_categories (slug, label, description, sort_order) VALUES
 ('markets',              'Markets',              'Broad market / equity-picking skill',                    10),
 ('company_fundamentals', 'Company Fundamentals', 'Reading a specific company''s financials / business',    20),
 ('macro',                'Macro',                'Macroeconomics, rates, cycles',                          30),
 ('geopolitics',          'Geopolitics',          'Geopolitics & foreign affairs',                          40),
 ('crypto',               'Crypto',               'Crypto / digital assets',                                50),
 ('options_trading',      'Options Trading',      'Options structure, flow, volatility',                    60),
 ('technical_analysis',   'Technical Analysis',   'Price action / technical analysis',                      70),
 ('media_noise',          'Media Narratives',     'Skill at interpreting media-driven / noisy narratives',  80)
ON CONFLICT (slug) DO NOTHING;

INSERT INTO public.tier_multipliers (tier, multiplier) VALUES
 ('S', 1.35), ('A', 1.15), ('B', 1.00), ('C', 0.75), ('D', 0.45)
ON CONFLICT (tier) DO NOTHING;

INSERT INTO public.schema_migrations (version, description)
VALUES ('073_source_credibility',
        'Source credibility layer: people, tiers, identities, categories, tier multipliers, stock topic tags')
ON CONFLICT (version) DO NOTHING;
