-- Migration 052: Drop orphaned tables (no runtime usage)
--
-- Tables being dropped:
--   - event_contract_trades: No code reads/writes (created in 023, never used)
--   - event_contract_positions: No code reads/writes (created in 023, never used)
--   - trade_history: Only writer was data_collector.py (now deleted)
--
-- Date: 2026-01-26

-- ============================================================================
-- DROP RLS POLICIES FIRST
-- ============================================================================

-- event_contract_positions policies
DROP POLICY IF EXISTS "anon_read_event_contract_positions" ON public.event_contract_positions;
DROP POLICY IF EXISTS "authenticated_read_event_contract_positions" ON public.event_contract_positions;
DROP POLICY IF EXISTS "service_role_event_contract_positions" ON public.event_contract_positions;

-- event_contract_trades policies
DROP POLICY IF EXISTS "anon_read_event_contract_trades" ON public.event_contract_trades;
DROP POLICY IF EXISTS "authenticated_read_event_contract_trades" ON public.event_contract_trades;
DROP POLICY IF EXISTS "service_role_event_contract_trades" ON public.event_contract_trades;

-- trade_history policies
DROP POLICY IF EXISTS "anon_read_trade_history" ON public.trade_history;
DROP POLICY IF EXISTS "authenticated_read_trade_history" ON public.trade_history;
DROP POLICY IF EXISTS "service_role_all_trade_history" ON public.trade_history;
DROP POLICY IF EXISTS "service_role_trade_history" ON public.trade_history;

-- ============================================================================
-- DROP INDEXES
-- ============================================================================

-- event_contract indexes (already dropped in 048, but be safe)
DROP INDEX IF EXISTS idx_event_contract_trades_date;
DROP INDEX IF EXISTS idx_event_contract_trades_symbol;
DROP INDEX IF EXISTS idx_event_contract_positions_date;
DROP INDEX IF EXISTS idx_event_contract_positions_symbol;

-- trade_history indexes
DROP INDEX IF EXISTS idx_trade_history_symbol;
DROP INDEX IF EXISTS idx_trade_history_account;
DROP INDEX IF EXISTS idx_trade_history_date;
DROP INDEX IF EXISTS idx_trade_history_type;

-- ============================================================================
-- DROP TABLES
-- ============================================================================

DROP TABLE IF EXISTS public.event_contract_trades CASCADE;
DROP TABLE IF EXISTS public.event_contract_positions CASCADE;
DROP TABLE IF EXISTS public.trade_history CASCADE;

-- ============================================================================
-- RECORD MIGRATION
-- ============================================================================

INSERT INTO schema_migrations (version, description, applied_at)
VALUES ('052', 'Drop orphaned tables: event_contract_trades, event_contract_positions, trade_history', NOW())
ON CONFLICT (version) DO NOTHING;
