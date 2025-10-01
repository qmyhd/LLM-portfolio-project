-- Schema State Verification Script
-- Run this to check current database state before migrations

\echo '=== SCHEMA STATE VERIFICATION ==='

-- Check if base tables exist
\echo 'Checking base table existence...'
SELECT 
    table_name,
    CASE WHEN table_name IS NOT NULL THEN '✅ EXISTS' ELSE '❌ MISSING' END as status
FROM information_schema.tables 
WHERE table_schema = 'public' 
    AND table_name IN (
        'discord_messages',
        'discord_market_clean', 
        'discord_trading_clean',
        'discord_general_clean',  -- Check for old naming
        'schema_migrations'
    )
ORDER BY table_name;

-- Check constraint names that might need renaming
\echo 'Checking constraint names...'
SELECT 
    conname as constraint_name,
    conrelid::regclass as table_name
FROM pg_constraint 
WHERE conrelid IN (
    'public.discord_market_clean'::regclass,
    'public.discord_general_clean'::regclass
)
AND conname LIKE '%discord_general%'
ORDER BY table_name, constraint_name;

-- Check unique indexes on message_id
\echo 'Checking unique indexes...'
SELECT 
    schemaname,
    tablename, 
    indexname,
    indexdef
FROM pg_indexes 
WHERE schemaname = 'public' 
    AND tablename IN ('discord_market_clean', 'discord_trading_clean')
    AND indexdef LIKE '%message_id%'
ORDER BY tablename, indexname;

-- Check data counts (if tables exist)
\echo 'Checking data counts...'
DO $$
DECLARE
    market_count INTEGER := 0;
    trading_count INTEGER := 0;
    general_count INTEGER := 0;
BEGIN
    -- Check discord_market_clean
    IF to_regclass('public.discord_market_clean') IS NOT NULL THEN
        EXECUTE 'SELECT COUNT(*) FROM discord_market_clean' INTO market_count;
        RAISE NOTICE 'discord_market_clean: % rows', market_count;
    ELSE
        RAISE NOTICE 'discord_market_clean: Table does not exist';
    END IF;
    
    -- Check discord_trading_clean  
    IF to_regclass('public.discord_trading_clean') IS NOT NULL THEN
        EXECUTE 'SELECT COUNT(*) FROM discord_trading_clean' INTO trading_count;
        RAISE NOTICE 'discord_trading_clean: % rows', trading_count;
    ELSE
        RAISE NOTICE 'discord_trading_clean: Table does not exist';
    END IF;
    
    -- Check old discord_general_clean
    IF to_regclass('public.discord_general_clean') IS NOT NULL THEN
        EXECUTE 'SELECT COUNT(*) FROM discord_general_clean' INTO general_count;
        RAISE NOTICE '⚠️  discord_general_clean: % rows (needs migration)', general_count;
    ELSE
        RAISE NOTICE 'discord_general_clean: Table does not exist (good)';
    END IF;
END$$;

\echo '=== VERIFICATION COMPLETE ==='
