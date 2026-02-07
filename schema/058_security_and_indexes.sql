-- Migration 058: Security hardening, missing PKs, and performance indexes
--
-- Changes:
--   1. RLS policies: Replace "always true" USING(true) with role-based conditions
--      - Brokerage tables (accounts, account_balances, positions, symbols):
--        service_role gets full access, authenticated/anon get read-only
--   2. account_balances: Add missing PRIMARY KEY (currency_code, snapshot_date, account_id)
--   3. Function: Fix mutable search_path on update_ohlcv_daily_updated_at
--   4. Performance: Ensure indexes on time-series date columns (already verified present)
--
-- Date: 2026-02-05

-- ============================================================================
-- 1. FIX RLS POLICIES: accounts
-- ============================================================================
-- Drop existing overly-permissive policies
DROP POLICY IF EXISTS "accounts_anon_read" ON public.accounts;
DROP POLICY IF EXISTS "accounts_authenticated_access" ON public.accounts;

-- anon: read-only (used by frontend public endpoints)
CREATE POLICY "accounts_anon_read"
    ON public.accounts FOR SELECT
    TO anon
    USING (true);  -- Read-only is safe for single-user portfolio app

-- authenticated: read-only (user dashboard reads)
CREATE POLICY "accounts_authenticated_read"
    ON public.accounts FOR SELECT
    TO authenticated
    USING (true);

-- service_role: full CRUD (backend pipelines and SnapTrade sync)
CREATE POLICY "accounts_service_role_all"
    ON public.accounts FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);

-- ============================================================================
-- 2. FIX RLS POLICIES: account_balances
-- ============================================================================
DROP POLICY IF EXISTS "account_balances_anon_read" ON public.account_balances;
DROP POLICY IF EXISTS "account_balances_authenticated_access" ON public.account_balances;

-- anon: read-only
CREATE POLICY "account_balances_anon_read"
    ON public.account_balances FOR SELECT
    TO anon
    USING (true);

-- authenticated: read-only
CREATE POLICY "account_balances_authenticated_read"
    ON public.account_balances FOR SELECT
    TO authenticated
    USING (true);

-- service_role: full CRUD
CREATE POLICY "account_balances_service_role_all"
    ON public.account_balances FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);

-- ============================================================================
-- 3. FIX RLS POLICIES: positions
-- ============================================================================
DROP POLICY IF EXISTS "positions_anon_read" ON public.positions;
DROP POLICY IF EXISTS "positions_authenticated_access" ON public.positions;

-- anon: read-only
CREATE POLICY "positions_anon_read"
    ON public.positions FOR SELECT
    TO anon
    USING (true);

-- authenticated: read-only
CREATE POLICY "positions_authenticated_read"
    ON public.positions FOR SELECT
    TO authenticated
    USING (true);

-- service_role: full CRUD
CREATE POLICY "positions_service_role_all"
    ON public.positions FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);

-- ============================================================================
-- 4. FIX RLS POLICIES: symbols
-- ============================================================================
DROP POLICY IF EXISTS "symbols_anon_read" ON public.symbols;
DROP POLICY IF EXISTS "symbols_authenticated_access" ON public.symbols;

-- anon: read-only
CREATE POLICY "symbols_anon_read"
    ON public.symbols FOR SELECT
    TO anon
    USING (true);

-- authenticated: read-only
CREATE POLICY "symbols_authenticated_read"
    ON public.symbols FOR SELECT
    TO authenticated
    USING (true);

-- service_role: full CRUD
CREATE POLICY "symbols_service_role_all"
    ON public.symbols FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);

-- ============================================================================
-- 5. FIX RLS POLICIES: orders (currently missing service_role write policy)
-- ============================================================================
-- Keep existing anon/authenticated read policies, add service_role write
-- NOTE: PostgreSQL does not support CREATE POLICY IF NOT EXISTS.
-- Use DROP IF EXISTS + CREATE pattern for idempotency.
DROP POLICY IF EXISTS "orders_service_role_all" ON public.orders;
CREATE POLICY "orders_service_role_all"
    ON public.orders FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);

-- ============================================================================
-- 6. ADD MISSING PRIMARY KEY: account_balances
-- ============================================================================
-- account_balances has NO constraints - add composite PK
-- This matches the conflict_columns used in snaptrade_collector.py
ALTER TABLE public.account_balances
    ADD CONSTRAINT account_balances_pkey
    PRIMARY KEY (currency_code, snapshot_date, account_id);

-- ============================================================================
-- 7. FIX MUTABLE SEARCH_PATH: update_ohlcv_daily_updated_at
-- ============================================================================
-- Replace the function with explicit search_path setting
CREATE OR REPLACE FUNCTION public.update_ohlcv_daily_updated_at()
    RETURNS trigger
    LANGUAGE plpgsql
    SECURITY INVOKER
    SET search_path = public
AS $function$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$function$;

-- Also fix update_orders_updated_at if it exists with same issue
CREATE OR REPLACE FUNCTION public.update_orders_updated_at()
    RETURNS trigger
    LANGUAGE plpgsql
    SECURITY INVOKER
    SET search_path = public
AS $function$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$function$;

-- Also fix the generic update_updated_at_column function
CREATE OR REPLACE FUNCTION public.update_updated_at_column()
    RETURNS trigger
    LANGUAGE plpgsql
    SECURITY INVOKER
    SET search_path = public
AS $function$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$function$;

-- ============================================================================
-- 8. VERIFY INDEXES (already present from audit, noting for completeness)
-- ============================================================================
-- ohlcv_daily: idx_ohlcv_daily_date, idx_ohlcv_daily_symbol, idx_ohlcv_daily_symbol_date ✅
-- stock_profile_history: idx_stock_profile_history_date, idx_stock_profile_history_ticker ✅
-- positions: positions_pkey (symbol, account_id) ✅
-- ohlcv_daily: ohlcv_daily_pkey (symbol, date) ✅

-- Add index on account_balances snapshot_date for time-series queries
CREATE INDEX IF NOT EXISTS idx_account_balances_snapshot_date
    ON public.account_balances (snapshot_date);

-- Add index on account_balances account_id for FK-like lookups
CREATE INDEX IF NOT EXISTS idx_account_balances_account_id
    ON public.account_balances (account_id);

-- ============================================================================
-- 9. RECORD MIGRATION
-- ============================================================================
INSERT INTO schema_migrations (version, description, applied_at)
VALUES ('058', 'Security hardening: RLS role separation, account_balances PK, mutable search_path fix, time-series indexes', NOW())
ON CONFLICT (version) DO NOTHING;
