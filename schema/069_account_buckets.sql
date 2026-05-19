-- =======================================================================
-- Migration 069: Account buckets (strategy classification)
-- =======================================================================
-- Adds a `bucket` column to `accounts` so positions and trades can be
-- filtered by strategy (long_term / swing / day / retirement / other).
--
-- Buckets are a property of the account, not the individual trade. Historical
-- queries JOIN to the current `accounts.bucket` value (retroactive labeling),
-- which means reassigning an account immediately re-labels its history. This
-- is intentional — keeps the model simple and removes the need for per-row
-- bucket tracking on activities/orders/position_snapshots.
--
-- Crypto holdings are folded into whichever bucket holds them; the UI labels
-- them distinctly via `_CRYPTO_SYMBOLS` in market_data_service.py.

-- Add the column. Default 'other' so existing rows stay valid; tighten with
-- a CHECK constraint to the five enum values.
ALTER TABLE public.accounts
    ADD COLUMN IF NOT EXISTS bucket text NOT NULL DEFAULT 'other'
        CHECK (bucket IN ('long_term', 'swing', 'day', 'retirement', 'other'));

-- Index for fast bucket-filtered queries (every positions/trades query
-- joining accounts will benefit).
CREATE INDEX IF NOT EXISTS accounts_bucket_idx ON public.accounts(bucket);

COMMENT ON COLUMN public.accounts.bucket IS
    'Strategy classification: long_term (taxable buy-and-hold), swing (multi-day to multi-week), day (intraday), retirement (IRA/Roth/401k), other (default for new connections).';

-- Track migration
INSERT INTO public.schema_migrations (version, description)
VALUES ('069_account_buckets', 'Account strategy bucket classification')
ON CONFLICT (version) DO NOTHING;

-- =======================================================================
-- One-time bucket assignment for current accounts.
-- Review the current account list first:
--   SELECT id, name, institution_name, bucket FROM accounts;
-- Then uncomment and adjust the UPDATEs below to match your actual rows.
-- These are templates — names will differ; LIKE patterns are illustrative.
-- =======================================================================

-- Robinhood (taxable) → long_term
-- UPDATE public.accounts
--    SET bucket = 'long_term'
--  WHERE institution_name ILIKE '%robinhood%'
--    AND name NOT ILIKE '%ira%'
--    AND name NOT ILIKE '%roth%';

-- IRA / Roth IRA / 401k → retirement
-- UPDATE public.accounts
--    SET bucket = 'retirement'
--  WHERE name ILIKE '%ira%'
--     OR name ILIKE '%roth%'
--     OR name ILIKE '%401k%';
