-- =======================================================================
-- Migration 070: Add bucket dimension to portfolio_risk_cache
-- =======================================================================
-- The risk cache previously had a single row per portfolio. With per-bucket
-- risk analysis (Phase 1 of portfolio-buckets plan), we need separate
-- cache entries per bucket — otherwise computing long-term risk would
-- evict the day-trade risk cache and vice versa.
--
-- The 'all' value represents the portfolio-wide (unfiltered) cache entry,
-- which corresponds to the API call without a ?bucket= query parameter.

-- Wrap all DDL in a transaction so the table never spends time without a
-- primary key. If anything in the block fails, PostgreSQL rolls back to
-- the pre-migration state. (The deploy runner's autocommit-per-statement
-- wouldn't guarantee this without the explicit BEGIN/COMMIT.)
BEGIN;

-- Add the column. Existing rows get 'all' so they remain valid.
ALTER TABLE public.portfolio_risk_cache
    ADD COLUMN IF NOT EXISTS bucket text NOT NULL DEFAULT 'all'
        CHECK (bucket IN (
            'long_term', 'swing', 'day', 'retirement', 'other', 'all'
        ));

-- Drop the existing primary key (if any) and recreate it with bucket
-- included. The DROP + ADD pair lives in the same transaction above, so
-- the table is never visible to readers without a PK.
ALTER TABLE public.portfolio_risk_cache
    DROP CONSTRAINT IF EXISTS portfolio_risk_cache_pkey;

ALTER TABLE public.portfolio_risk_cache
    ADD CONSTRAINT portfolio_risk_cache_pkey
    PRIMARY KEY (portfolio_id, bucket);

-- Track migration
INSERT INTO public.schema_migrations (version, description)
VALUES ('070_risk_cache_bucket', 'Per-bucket portfolio risk cache')
ON CONFLICT (version) DO NOTHING;

COMMIT;
