-- =======================================================================
-- Migration 071: Per-bucket stock_analysis_cache
-- =======================================================================
-- The multi-agent stock analysis now scopes position context and portfolio
-- value to the active bucket. That means different buckets produce
-- different ConsensusReports for the same ticker (e.g., AAPL viewed under
-- long_term sees the user's full Robinhood AAPL exposure, while AAPL
-- under day sees zero shares and gets a different risk-sizing signal).
--
-- Without bucket in the cache key, computing analysis for one bucket
-- would evict the other and the user would see stale/wrong data when
-- toggling the switcher.
--
-- 'all' represents the portfolio-wide (no bucket filter) entry, matching
-- the convention used by portfolio_risk_cache in migration 070.

BEGIN;

ALTER TABLE public.stock_analysis_cache
    ADD COLUMN IF NOT EXISTS bucket text NOT NULL DEFAULT 'all'
        CHECK (bucket IN (
            'long_term', 'swing', 'day', 'retirement', 'other', 'all'
        ));

-- Rebuild the primary key to include bucket. Same atomic DROP+ADD pattern
-- as migration 070.
ALTER TABLE public.stock_analysis_cache
    DROP CONSTRAINT IF EXISTS stock_analysis_cache_pkey;

ALTER TABLE public.stock_analysis_cache
    ADD CONSTRAINT stock_analysis_cache_pkey
    PRIMARY KEY (ticker, analysis_type, bucket);

-- The existing idx_analysis_cache_expires on expires_at still works.

INSERT INTO public.schema_migrations (version, description)
VALUES ('071_analysis_cache_bucket', 'Per-bucket stock analysis cache')
ON CONFLICT (version) DO NOTHING;

COMMIT;
