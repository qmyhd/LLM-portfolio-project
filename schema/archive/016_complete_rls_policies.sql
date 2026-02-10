--
-- Migration: 016 Complete RLS Policies
-- Date: September 22, 2025
-- Purpose: Add comprehensive RLS policies for all tables
--
-- Enables proper RLS policies for tables that have RLS enabled but lack policies:
-- accounts, account_balances, positions, symbols, discord_processing_log, schema_migrations
--
-- Note: RLS is already enabled on all tables, but some lack specific policies

BEGIN;

-- =============================================================================
-- ACCOUNTS TABLE
-- =============================================================================

-- Policy: Allow authenticated users and service role to manage accounts
CREATE POLICY "accounts_authenticated_access" ON "public"."accounts"
    FOR ALL 
    TO authenticated, service_role
    USING (true)
    WITH CHECK (true);

-- Policy: Allow anon users to read accounts (if needed for public data)
CREATE POLICY "accounts_anon_read" ON "public"."accounts"
    FOR SELECT 
    TO anon
    USING (true);

-- =============================================================================
-- ACCOUNT_BALANCES TABLE  
-- =============================================================================

-- Policy: Allow authenticated users and service role to manage account balances
CREATE POLICY "account_balances_authenticated_access" ON "public"."account_balances"
    FOR ALL
    TO authenticated, service_role
    USING (true)
    WITH CHECK (true);

-- Policy: Allow anon users to read account balances (if needed for public data)
CREATE POLICY "account_balances_anon_read" ON "public"."account_balances"
    FOR SELECT
    TO anon
    USING (true);

-- =============================================================================
-- POSITIONS TABLE
-- =============================================================================

-- Policy: Allow authenticated users and service role to manage positions
CREATE POLICY "positions_authenticated_access" ON "public"."positions"
    FOR ALL
    TO authenticated, service_role
    USING (true)
    WITH CHECK (true);

-- Policy: Allow anon users to read positions (if needed for public data)
CREATE POLICY "positions_anon_read" ON "public"."positions"
    FOR SELECT
    TO anon
    USING (true);

-- =============================================================================
-- SYMBOLS TABLE
-- =============================================================================

-- Policy: Allow authenticated users and service role to manage symbols
CREATE POLICY "symbols_authenticated_access" ON "public"."symbols"
    FOR ALL
    TO authenticated, service_role
    USING (true)
    WITH CHECK (true);

-- Policy: Allow anon users to read symbols (public reference data)
CREATE POLICY "symbols_anon_read" ON "public"."symbols"
    FOR SELECT
    TO anon
    USING (true);

-- =============================================================================
-- DISCORD_PROCESSING_LOG TABLE
-- =============================================================================

-- Policy: Allow authenticated users and service role to manage processing log
CREATE POLICY "discord_processing_log_authenticated_access" ON "public"."discord_processing_log"
    FOR ALL
    TO authenticated, service_role
    USING (true)
    WITH CHECK (true);

-- Policy: Allow anon users to read processing log (if needed for status checks)
CREATE POLICY "discord_processing_log_anon_read" ON "public"."discord_processing_log"
    FOR SELECT
    TO anon
    USING (true);

-- =============================================================================
-- SCHEMA_MIGRATIONS TABLE
-- =============================================================================

-- Policy: Service role has full access to manage migrations
CREATE POLICY "schema_migrations_service_role_access" ON "public"."schema_migrations"
    FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);

-- Policy: Authenticated users can read migration status
CREATE POLICY "schema_migrations_authenticated_read" ON "public"."schema_migrations"
    FOR SELECT
    TO authenticated
    USING (true);

-- Policy: Anon users can read migration status (for health checks)
CREATE POLICY "schema_migrations_anon_read" ON "public"."schema_migrations"
    FOR SELECT
    TO anon
    USING (true);

-- =============================================================================
-- VERIFICATION COMMENTS
-- =============================================================================

-- Add comments documenting the RLS setup
COMMENT ON TABLE "public"."accounts" IS 'Account data with RLS policies - authenticated/service_role: full access, anon: read-only';
COMMENT ON TABLE "public"."account_balances" IS 'Account balance data with RLS policies - authenticated/service_role: full access, anon: read-only';
COMMENT ON TABLE "public"."positions" IS 'Position data with RLS policies - authenticated/service_role: full access, anon: read-only';
COMMENT ON TABLE "public"."symbols" IS 'Symbol reference data with RLS policies - authenticated/service_role: full access, anon: read-only';
COMMENT ON TABLE "public"."discord_processing_log" IS 'Discord processing log with RLS policies - authenticated/service_role: full access, anon: read-only';
COMMENT ON TABLE "public"."schema_migrations" IS 'Schema migrations with RLS policies - service_role: full access, authenticated/anon: read-only';

-- Record this migration
INSERT INTO "public"."schema_migrations" ("version", "description") 
VALUES ('016', 'Complete RLS policies for accounts, account_balances, positions, symbols, discord_processing_log, and schema_migrations tables')
ON CONFLICT ("version") DO NOTHING;

COMMIT;

-- =============================================================================
-- VERIFICATION QUERIES
-- =============================================================================
/*
-- Verify RLS policies are in place
SELECT 
    schemaname,
    tablename,
    policyname,
    permissive,
    roles,
    cmd,
    qual,
    with_check
FROM pg_policies 
WHERE schemaname = 'public' 
    AND tablename IN ('accounts', 'account_balances', 'positions', 'symbols', 'discord_processing_log', 'schema_migrations')
ORDER BY tablename, policyname;

-- Verify RLS is enabled on all tables
SELECT 
    schemaname,
    tablename,
    rowsecurity
FROM pg_tables 
WHERE schemaname = 'public'
    AND tablename IN ('accounts', 'account_balances', 'positions', 'symbols', 'discord_processing_log', 'schema_migrations');
*/