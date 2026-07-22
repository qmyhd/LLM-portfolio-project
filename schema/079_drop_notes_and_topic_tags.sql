-- =======================================================================
-- Migration 079: Drop the cut stock_notes and stock_topic_tags features
-- =======================================================================
-- Both were unused (0 rows) and their routes/components have been removed.
-- stock_topic_tags fed per-stock credibility routing that never had data;
-- CredibilityResolver now falls back to author/tier weighting only.
-- Already applied to production via Supabase (registered in schema_migrations).

DROP TABLE IF EXISTS public.stock_notes;
DROP TABLE IF EXISTS public.stock_topic_tags;

INSERT INTO public.schema_migrations (version, description)
VALUES ('079_drop_notes_and_topic_tags',
        'Drop unused stock_notes and stock_topic_tags tables (features cut)')
ON CONFLICT (version) DO NOTHING;
