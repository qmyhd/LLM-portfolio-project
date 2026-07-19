-- =======================================================================
-- Migration 076: Security hardening + schema cleanup
-- =======================================================================
-- 1. Drop an obsolete SECURITY DEFINER migration helper that anon could call.
-- 2. Revoke anon/authenticated table grants (all data flows through FastAPI
--    with the service role; the frontend never uses the anon key).
-- 3. Drop a duplicate index and add covering indexes for 3 unindexed FKs.
-- 4. Drop 4 confirmed-dead, unreferenced, zero-row tables.
--
-- NOT handled here (require the Supabase dashboard / Management API):
--   * Enable leaked-password protection (Auth settings)
--   * Upgrade Postgres to the latest patch (infra, causes brief downtime)

-- ---------------------------------------------------------------------------
-- 1. Obsolete SECURITY DEFINER helper — could drop columns / rewrite PKs and
--    was executable by anon/authenticated via PostgREST RPC.
-- ---------------------------------------------------------------------------
DROP FUNCTION IF EXISTS public.drop_id_column_and_update_pk(text, text[]);

-- ---------------------------------------------------------------------------
-- 2. Revoke API-role grants. RLS is already deny-by-default, so no rows leaked,
--    but the schema shape was discoverable and one bad policy from exposure.
--    service_role (used by the backend) is unaffected — it bypasses these.
-- ---------------------------------------------------------------------------
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM anon, authenticated;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM anon, authenticated;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA public FROM anon, authenticated;

-- Stop future migration-created objects from being granted to the API roles.
ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON TABLES FROM anon, authenticated;
ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON SEQUENCES FROM anon, authenticated;
ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON FUNCTIONS FROM anon, authenticated;

-- ---------------------------------------------------------------------------
-- 3. Index hygiene.
-- ---------------------------------------------------------------------------
-- Duplicate of idx_discord_parsed_ideas_message_id.
DROP INDEX IF EXISTS public.idx_parsed_ideas_message;

-- Covering indexes for foreign keys flagged by the linter.
CREATE INDEX IF NOT EXISTS idx_discord_parsed_ideas_attributed_person
    ON public.discord_parsed_ideas (attributed_person_id)
    WHERE attributed_person_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_stock_topic_tags_category_slug
    ON public.stock_topic_tags (category_slug);
CREATE INDEX IF NOT EXISTS idx_video_quotes_thesis_profile
    ON public.video_quotes (stock_thesis_profile_id)
    WHERE stock_thesis_profile_id IS NOT NULL;

-- ---------------------------------------------------------------------------
-- 4. Drop confirmed-dead tables (0 rows, no code references, no incoming FKs,
--    no dependent views — verified 2026-07-18).
-- ---------------------------------------------------------------------------
DROP TABLE IF EXISTS public.trade_history;
DROP TABLE IF EXISTS public.discord_trading_clean;
DROP TABLE IF EXISTS public.discord_market_clean;
DROP TABLE IF EXISTS public.discord_idea_units;

INSERT INTO public.schema_migrations (version, description)
VALUES ('076_security_and_cleanup',
        'Drop SECURITY DEFINER helper, revoke anon/auth grants, index hygiene, drop 4 dead tables')
ON CONFLICT (version) DO NOTHING;
