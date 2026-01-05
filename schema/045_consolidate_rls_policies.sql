-- Migration 045: Consolidate RLS policies
-- =========================================
-- This migration fixes three Supabase Advisor issues:
-- 1. Multiple permissive policies per table/action/role
-- 2. Policies using TO public (applies to ALL roles including internal Supabase roles)
-- 3. auth_rls_initplan: policies using auth.role() that get evaluated per row
--
-- Strategy:
-- - Service role bypasses RLS entirely, so we don't need policies for it
-- - Use TO anon for anonymous/public read access
-- - Use TO authenticated for authenticated user access
-- - Avoid TO public (too broad)
-- - Remove auth.role() checks from policy quals (service role doesn't need them)

-- ============================================================
-- discord_messages: has 5 overlapping policies!
-- Keep: simple anon read
-- Drop: Public read access, Service role write access, discord_read_policy, 
--       discord_write_policy, service_role_all_discord_messages
-- ============================================================
DROP POLICY IF EXISTS "Public read access" ON public.discord_messages;
DROP POLICY IF EXISTS "Service role write access" ON public.discord_messages;
DROP POLICY IF EXISTS "discord_read_policy" ON public.discord_messages;
DROP POLICY IF EXISTS "discord_write_policy" ON public.discord_messages;
DROP POLICY IF EXISTS "service_role_all_discord_messages" ON public.discord_messages;

CREATE POLICY "anon_read_discord_messages" ON public.discord_messages
    FOR SELECT TO anon USING (true);

CREATE POLICY "authenticated_read_discord_messages" ON public.discord_messages
    FOR SELECT TO authenticated USING (true);

-- ============================================================
-- daily_prices: anon_select (TO public) + service_role_all (TO public with auth.role())
-- ============================================================
DROP POLICY IF EXISTS "anon_select_daily_prices" ON public.daily_prices;
DROP POLICY IF EXISTS "service_role_all_daily_prices" ON public.daily_prices;

CREATE POLICY "anon_read_daily_prices" ON public.daily_prices
    FOR SELECT TO anon USING (true);

CREATE POLICY "authenticated_read_daily_prices" ON public.daily_prices
    FOR SELECT TO authenticated USING (true);

-- ============================================================
-- realtime_prices: same pattern as daily_prices
-- ============================================================
DROP POLICY IF EXISTS "anon_select_realtime_prices" ON public.realtime_prices;
DROP POLICY IF EXISTS "service_role_all_realtime_prices" ON public.realtime_prices;

CREATE POLICY "anon_read_realtime_prices" ON public.realtime_prices
    FOR SELECT TO anon USING (true);

CREATE POLICY "authenticated_read_realtime_prices" ON public.realtime_prices
    FOR SELECT TO authenticated USING (true);

-- ============================================================
-- stock_metrics: same pattern
-- ============================================================
DROP POLICY IF EXISTS "anon_select_stock_metrics" ON public.stock_metrics;
DROP POLICY IF EXISTS "service_role_all_stock_metrics" ON public.stock_metrics;

CREATE POLICY "anon_read_stock_metrics" ON public.stock_metrics
    FOR SELECT TO anon USING (true);

CREATE POLICY "authenticated_read_stock_metrics" ON public.stock_metrics
    FOR SELECT TO authenticated USING (true);

-- ============================================================
-- chart_metadata: TO public with auth.role() check
-- ============================================================
DROP POLICY IF EXISTS "service_role_all_chart_metadata" ON public.chart_metadata;

CREATE POLICY "anon_read_chart_metadata" ON public.chart_metadata
    FOR SELECT TO anon USING (true);

CREATE POLICY "authenticated_read_chart_metadata" ON public.chart_metadata
    FOR SELECT TO authenticated USING (true);

-- ============================================================
-- discord_market_clean: TO public with auth.role() check
-- ============================================================
DROP POLICY IF EXISTS "service_role_all_discord_general_clean" ON public.discord_market_clean;

CREATE POLICY "anon_read_discord_market_clean" ON public.discord_market_clean
    FOR SELECT TO anon USING (true);

CREATE POLICY "authenticated_read_discord_market_clean" ON public.discord_market_clean
    FOR SELECT TO authenticated USING (true);

-- ============================================================
-- discord_trading_clean: TO public with auth.role() check
-- ============================================================
DROP POLICY IF EXISTS "service_role_all_discord_trading_clean" ON public.discord_trading_clean;

CREATE POLICY "anon_read_discord_trading_clean" ON public.discord_trading_clean
    FOR SELECT TO anon USING (true);

CREATE POLICY "authenticated_read_discord_trading_clean" ON public.discord_trading_clean
    FOR SELECT TO authenticated USING (true);

-- ============================================================
-- processing_status: TO public with auth.role() check
-- ============================================================
DROP POLICY IF EXISTS "service_role_all_processing_status" ON public.processing_status;

CREATE POLICY "anon_read_processing_status" ON public.processing_status
    FOR SELECT TO anon USING (true);

CREATE POLICY "authenticated_read_processing_status" ON public.processing_status
    FOR SELECT TO authenticated USING (true);

-- ============================================================
-- twitter_data: TO public with auth.role() check
-- ============================================================
DROP POLICY IF EXISTS "service_role_all_twitter_data" ON public.twitter_data;

CREATE POLICY "anon_read_twitter_data" ON public.twitter_data
    FOR SELECT TO anon USING (true);

CREATE POLICY "authenticated_read_twitter_data" ON public.twitter_data
    FOR SELECT TO authenticated USING (true);

-- ============================================================
-- orders: read_policy + write_policy both TO public with auth.role()
-- ============================================================
DROP POLICY IF EXISTS "orders_read_policy" ON public.orders;
DROP POLICY IF EXISTS "orders_write_policy" ON public.orders;

CREATE POLICY "anon_read_orders" ON public.orders
    FOR SELECT TO anon USING (true);

CREATE POLICY "authenticated_read_orders" ON public.orders
    FOR SELECT TO authenticated USING (true);

-- ============================================================
-- discord_message_chunks: 3 policies TO public
-- ============================================================
DROP POLICY IF EXISTS "Enable insert for authenticated users" ON public.discord_message_chunks;
DROP POLICY IF EXISTS "Enable read access for all users" ON public.discord_message_chunks;
DROP POLICY IF EXISTS "Enable update for authenticated users" ON public.discord_message_chunks;

CREATE POLICY "anon_read_discord_message_chunks" ON public.discord_message_chunks
    FOR SELECT TO anon USING (true);

CREATE POLICY "authenticated_all_discord_message_chunks" ON public.discord_message_chunks
    FOR ALL TO authenticated USING (true) WITH CHECK (true);

-- ============================================================
-- stock_mentions: 3 policies TO public
-- ============================================================
DROP POLICY IF EXISTS "Enable insert for authenticated users" ON public.stock_mentions;
DROP POLICY IF EXISTS "Enable read access for all users" ON public.stock_mentions;
DROP POLICY IF EXISTS "Enable update for authenticated users" ON public.stock_mentions;

CREATE POLICY "anon_read_stock_mentions" ON public.stock_mentions
    FOR SELECT TO anon USING (true);

CREATE POLICY "authenticated_all_stock_mentions" ON public.stock_mentions
    FOR ALL TO authenticated USING (true) WITH CHECK (true);

-- ============================================================
-- trade_history: 4 separate policies TO public (select, insert, update, delete)
-- ============================================================
DROP POLICY IF EXISTS "trade_history_select_policy" ON public.trade_history;
DROP POLICY IF EXISTS "trade_history_insert_policy" ON public.trade_history;
DROP POLICY IF EXISTS "trade_history_update_policy" ON public.trade_history;
DROP POLICY IF EXISTS "trade_history_delete_policy" ON public.trade_history;

CREATE POLICY "anon_read_trade_history" ON public.trade_history
    FOR SELECT TO anon USING (true);

CREATE POLICY "authenticated_all_trade_history" ON public.trade_history
    FOR ALL TO authenticated USING (true) WITH CHECK (true);

-- ============================================================
-- event_contract_positions: TO public with true/true (too permissive)
-- ============================================================
DROP POLICY IF EXISTS "service_role_event_contract_positions" ON public.event_contract_positions;

CREATE POLICY "anon_read_event_contract_positions" ON public.event_contract_positions
    FOR SELECT TO anon USING (true);

CREATE POLICY "authenticated_all_event_contract_positions" ON public.event_contract_positions
    FOR ALL TO authenticated USING (true) WITH CHECK (true);

-- ============================================================
-- event_contract_trades: TO public with true/true (too permissive)
-- ============================================================
DROP POLICY IF EXISTS "service_role_event_contract_trades" ON public.event_contract_trades;

CREATE POLICY "anon_read_event_contract_trades" ON public.event_contract_trades
    FOR SELECT TO anon USING (true);

CREATE POLICY "authenticated_all_event_contract_trades" ON public.event_contract_trades
    FOR ALL TO authenticated USING (true) WITH CHECK (true);

-- ============================================================
-- CONSOLIDATE REDUNDANT service_role POLICIES
-- These tables have both *_authenticated_access (includes service_role) 
-- AND *_service_role_all - remove the redundant one
-- ============================================================

-- account_balances: drop redundant service_role_all
DROP POLICY IF EXISTS "account_balances_service_role_all" ON public.account_balances;

-- accounts: drop redundant service_role_all
DROP POLICY IF EXISTS "accounts_service_role_all" ON public.accounts;

-- positions: drop redundant service_role_all
DROP POLICY IF EXISTS "positions_service_role_all" ON public.positions;

-- symbols: drop redundant service_role_all
DROP POLICY IF EXISTS "symbols_service_role_all" ON public.symbols;

-- discord_processing_log: drop redundant service_role_all
DROP POLICY IF EXISTS "discord_processing_log_service_role_all" ON public.discord_processing_log;

-- schema_migrations: has both service_role_access and service_role_all (identical)
DROP POLICY IF EXISTS "schema_migrations_service_role_all" ON public.schema_migrations;

-- ============================================================
-- SUMMARY: After this migration
-- ============================================================
-- Each table now has:
-- 1. anon_read_* for anonymous SELECT access (TO anon)
-- 2. authenticated_read_* or authenticated_all_* (TO authenticated)
-- 3. service_role bypasses RLS entirely - no policies needed
--
-- Eliminated:
-- - TO public policies (applied to too many roles)
-- - auth.role() checks (caused per-row evaluation)
-- - Duplicate/overlapping policies
