-- =======================================================================
-- Migration 078: Drop the orphaned twitter_data table
-- =======================================================================
-- The live Twitter/X API integration was removed (the API tier no longer
-- permits tweet reads; shared tweets are now captured via Discord embeds and
-- backfilled by scripts/backfill_tweet_text.py). twitter_data had 0 rows, no
-- FK dependencies, and its only reader/writer (twitter_cmd.py,
-- twitter_analysis.py) were deleted.
--
-- Already applied to production via Supabase (registered in schema_migrations).

DROP TABLE IF EXISTS public.twitter_data;

INSERT INTO public.schema_migrations (version, description)
VALUES ('078_drop_twitter_data',
        'Drop orphaned twitter_data table after removing the dead Twitter API integration')
ON CONFLICT (version) DO NOTHING;
