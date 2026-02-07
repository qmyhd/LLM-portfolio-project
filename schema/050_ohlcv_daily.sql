-- Migration 050: Create ohlcv_daily table
--
-- Databento OHLCV daily bars — the sole source of truth for price data.
-- Primary key: (symbol, date) — one row per ticker per trading day.
-- Populated by scripts/backfill_ohlcv.py and the nightly EC2 pipeline.
--
-- Note: This table was originally created directly in Supabase/RDS.
-- This migration file is added retroactively as documentation and for
-- repeatable deployments (uses IF NOT EXISTS).

BEGIN;

CREATE TABLE IF NOT EXISTS ohlcv_daily (
    symbol      TEXT        NOT NULL,
    date        DATE        NOT NULL,
    open        NUMERIC     NOT NULL,
    high        NUMERIC     NOT NULL,
    low         NUMERIC     NOT NULL,
    close       NUMERIC     NOT NULL,
    volume      BIGINT      NOT NULL DEFAULT 0,
    source      TEXT        NOT NULL DEFAULT 'databento',
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (symbol, date)
);

-- Performance indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_ohlcv_daily_symbol
    ON ohlcv_daily (symbol);
CREATE INDEX IF NOT EXISTS idx_ohlcv_daily_date
    ON ohlcv_daily (date);
CREATE INDEX IF NOT EXISTS idx_ohlcv_daily_symbol_date
    ON ohlcv_daily (symbol, date DESC);

-- Auto-update updated_at on row modification
CREATE OR REPLACE FUNCTION public.update_ohlcv_daily_updated_at()
RETURNS TRIGGER
LANGUAGE plpgsql
SET search_path = public
AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_ohlcv_daily_updated_at ON ohlcv_daily;
CREATE TRIGGER trg_ohlcv_daily_updated_at
    BEFORE UPDATE ON ohlcv_daily
    FOR EACH ROW
    EXECUTE FUNCTION update_ohlcv_daily_updated_at();

-- Track migration
INSERT INTO schema_migrations (version, description, applied_at)
VALUES ('050', 'Create ohlcv_daily table for Databento OHLCV bars', NOW())
ON CONFLICT (version) DO NOTHING;

COMMIT;
