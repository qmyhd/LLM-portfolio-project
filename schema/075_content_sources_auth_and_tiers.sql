-- =======================================================================
-- Migration 075: Content source timeline, Google users, and broader tiers
-- =======================================================================
-- Adds a provenance-rich journal layer for imported iMessage/X content,
-- human curation metadata for auto-labeled ideas, and Google-auth user
-- tracking for the frontend sign-in flow.

-- User tracking for Google sign-in / signup. The frontend should verify
-- users through its auth provider, then call the API so the portfolio app can
-- track first_seen/last_seen and display user metadata.
CREATE TABLE IF NOT EXISTS public.app_users (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    provider        TEXT NOT NULL DEFAULT 'google'
        CHECK (provider IN ('google')),
    provider_user_id TEXT NOT NULL,
    email           TEXT NOT NULL,
    full_name       TEXT,
    avatar_url      TEXT,
    role            TEXT NOT NULL DEFAULT 'viewer'
        CHECK (role IN ('owner', 'editor', 'viewer')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT app_users_provider_subject_key UNIQUE (provider, provider_user_id),
    CONSTRAINT app_users_email_key UNIQUE (email)
);
CREATE INDEX IF NOT EXISTS idx_app_users_email ON public.app_users (LOWER(email));

DROP TRIGGER IF EXISTS app_users_updated_at ON public.app_users;
CREATE TRIGGER app_users_updated_at
    BEFORE UPDATE ON public.app_users
    FOR EACH ROW EXECUTE FUNCTION public.tg_credibility_set_updated_at();

ALTER TABLE public.app_users ENABLE ROW LEVEL SECURITY;

-- Widen user_ideas sources beyond the first Discord/manual/transcribe set.
ALTER TABLE public.user_ideas
    DROP CONSTRAINT IF EXISTS user_ideas_source_check;
ALTER TABLE public.user_ideas
    ADD CONSTRAINT user_ideas_source_check
    CHECK (source IN ('discord', 'manual', 'transcribe', 'imessage', 'twitter', 'x'));

ALTER TABLE public.user_ideas
    ADD COLUMN IF NOT EXISTS title TEXT,
    ADD COLUMN IF NOT EXISTS source_url TEXT,
    ADD COLUMN IF NOT EXISTS source_created_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS author TEXT,
    ADD COLUMN IF NOT EXISTS author_id TEXT,
    ADD COLUMN IF NOT EXISTS platform_message_id TEXT,
    ADD COLUMN IF NOT EXISTS thread_key TEXT,
    ADD COLUMN IF NOT EXISTS source_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS review_status TEXT NOT NULL DEFAULT 'unreviewed'
        CHECK (review_status IN ('unreviewed', 'reviewed', 'needs_review')),
    ADD COLUMN IF NOT EXISTS review_notes TEXT,
    ADD COLUMN IF NOT EXISTS attributed_person_id INTEGER
        REFERENCES public.people (id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS attribution_kind TEXT NOT NULL DEFAULT 'self'
        CHECK (attribution_kind IN ('self', 'external_person', 'institution', 'unknown')),
    ADD COLUMN IF NOT EXISTS filing_type TEXT,
    ADD COLUMN IF NOT EXISTS filing_period TEXT,
    ADD COLUMN IF NOT EXISTS institution_name TEXT;

CREATE INDEX IF NOT EXISTS idx_user_ideas_source_created_at
    ON public.user_ideas (source_created_at DESC NULLS LAST);
CREATE INDEX IF NOT EXISTS idx_user_ideas_thread_key
    ON public.user_ideas (thread_key, source_created_at DESC NULLS LAST);
CREATE INDEX IF NOT EXISTS idx_user_ideas_review_status
    ON public.user_ideas (review_status, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_user_ideas_attributed_person
    ON public.user_ideas (attributed_person_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_user_ideas_source_platform_unique
    ON public.user_ideas (source, platform_message_id)
    WHERE platform_message_id IS NOT NULL;

-- Curation metadata for raw NLP output, so bad splits / 13F attribution can be
-- corrected without overwriting the original LLM parse.
ALTER TABLE public.discord_parsed_ideas
    ADD COLUMN IF NOT EXISTS review_status TEXT NOT NULL DEFAULT 'unreviewed'
        CHECK (review_status IN ('unreviewed', 'reviewed', 'needs_review')),
    ADD COLUMN IF NOT EXISTS review_notes TEXT,
    ADD COLUMN IF NOT EXISTS attributed_person_id INTEGER
        REFERENCES public.people (id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS attribution_kind TEXT NOT NULL DEFAULT 'self'
        CHECK (attribution_kind IN ('self', 'external_person', 'institution', 'unknown')),
    ADD COLUMN IF NOT EXISTS thesis_bucket TEXT,
    ADD COLUMN IF NOT EXISTS filing_type TEXT,
    ADD COLUMN IF NOT EXISTS filing_period TEXT,
    ADD COLUMN IF NOT EXISTS institution_name TEXT;

CREATE INDEX IF NOT EXISTS idx_discord_parsed_ideas_review_status
    ON public.discord_parsed_ideas (review_status, parsed_at DESC);
CREATE INDEX IF NOT EXISTS idx_discord_parsed_ideas_thesis_bucket
    ON public.discord_parsed_ideas (thesis_bucket);

-- Broaden the person tier taxonomy beyond finance/markets.
INSERT INTO public.credibility_categories (slug, label, description, sort_order) VALUES
 ('philosophy',        'Philosophy',        'Philosophy, ethics, metaphysics, and intellectual frameworks', 90),
 ('religious_studies', 'Religious Studies', 'Religion, theology, scripture, and comparative religion',     100),
 ('arts',              'Arts',              'Art, literature, music, aesthetics, and cultural criticism',   110)
ON CONFLICT (slug) DO UPDATE SET
    label = EXCLUDED.label,
    description = EXCLUDED.description,
    sort_order = EXCLUDED.sort_order;

INSERT INTO public.schema_migrations (version, description)
VALUES ('075_content_sources_auth_and_tiers',
        'Google app users, richer user_ideas provenance/curation, Discord idea curation, and philosophy/religion/arts tiers')
ON CONFLICT (version) DO NOTHING;
