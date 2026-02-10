-- Migration 051: Drop legacy price tables (replaced by RDS ohlcv_daily)
--
-- These tables were originally used for yfinance data but have been superseded by:
--   - ohlcv_daily: Databento OHLCV daily bars stored in RDS
--   - price_service.py: Centralized OHLCV data access module
--
-- Tables being dropped:
--   - daily_prices: Historical yfinance daily OHLCV data
--   - realtime_prices: Intraday yfinance price snapshots  
--   - stock_metrics: Derived metrics from yfinance data
--
-- Date: 2026-01-20

-- Drop policies first (they reference the tables)
DROP POLICY IF EXISTS "anon_read_daily_prices" ON public.daily_prices;
DROP POLICY IF EXISTS "authenticated_read_daily_prices" ON public.daily_prices;
DROP POLICY IF EXISTS "service_role_all_daily_prices" ON public.daily_prices;
DROP POLICY IF EXISTS "anon_select_daily_prices" ON public.daily_prices;

DROP POLICY IF EXISTS "anon_read_realtime_prices" ON public.realtime_prices;
DROP POLICY IF EXISTS "authenticated_read_realtime_prices" ON public.realtime_prices;
DROP POLICY IF EXISTS "service_role_all_realtime_prices" ON public.realtime_prices;
DROP POLICY IF EXISTS "anon_select_realtime_prices" ON public.realtime_prices;

DROP POLICY IF EXISTS "anon_read_stock_metrics" ON public.stock_metrics;
DROP POLICY IF EXISTS "authenticated_read_stock_metrics" ON public.stock_metrics;
DROP POLICY IF EXISTS "service_role_all_stock_metrics" ON public.stock_metrics;
DROP POLICY IF EXISTS "anon_select_stock_metrics" ON public.stock_metrics;

-- Drop indexes (if any remain)
DROP INDEX IF EXISTS idx_daily_prices_symbol;
DROP INDEX IF EXISTS idx_daily_prices_date;
DROP INDEX IF EXISTS idx_realtime_prices_symbol;
DROP INDEX IF EXISTS idx_realtime_prices_timestamp;
DROP INDEX IF EXISTS idx_stock_metrics_symbol;
DROP INDEX IF EXISTS idx_stock_metrics_date;

-- Drop the tables
DROP TABLE IF EXISTS public.daily_prices CASCADE;
DROP TABLE IF EXISTS public.realtime_prices CASCADE;
DROP TABLE IF EXISTS public.stock_metrics CASCADE;

-- Record migration
INSERT INTO schema_migrations (version, description, applied_at)
VALUES ('051', 'Drop legacy price tables (daily_prices, realtime_prices, stock_metrics) - replaced by RDS ohlcv_daily', NOW())
ON CONFLICT (version) DO NOTHING;
