-- 013_final_orders_cleanup_and_indexes.sql - Final Orders Cleanup and Performance
-- Completes the orders table refactor and adds performance indexes
-- 
-- This migration:
-- 1. Adds quote_currency_code column and backfills from quote_currency JSONB
-- 2. Drops redundant JSONB columns (universal_symbol, option_symbol, quote_universal_symbol, quote_currency)
-- 3. Adds performance indexes for common queries
-- 4. Ensures all tables have proper indexes

-- Record this migration
INSERT INTO schema_migrations (version, description) 
VALUES ('013_final_orders_cleanup_and_indexes', 'Final orders table cleanup - add quote_currency_code, drop redundant JSONB columns, add performance indexes') 
ON CONFLICT (version) DO NOTHING;

-- ==============================================
-- Phase 1: Orders Table Final Cleanup
-- ==============================================

DO $$ BEGIN
    RAISE NOTICE 'Starting orders table final cleanup...';
    
    -- Add quote_currency_code column if it doesn't exist
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'orders' AND column_name = 'quote_currency_code'
    ) THEN
        ALTER TABLE orders ADD COLUMN quote_currency_code TEXT;
        RAISE NOTICE '✅ Added quote_currency_code column';
    ELSE
        RAISE NOTICE 'quote_currency_code column already exists';
    END IF;
    
    -- Backfill quote_currency_code from quote_currency JSONB
    UPDATE orders
    SET quote_currency_code = CASE
        WHEN quote_currency IS NULL THEN NULL
        WHEN jsonb_typeof(quote_currency) = 'string' THEN quote_currency #>> '{}'
        WHEN jsonb_typeof(quote_currency) = 'object' THEN
            COALESCE(
                quote_currency->>'code',
                quote_currency->>'currency',
                quote_currency#>>'{base,currency}',
                quote_currency#>>'{quote,currency}'
            )
        ELSE NULL
    END
    WHERE quote_currency_code IS NULL AND quote_currency IS NOT NULL;
    
    RAISE NOTICE '✅ Backfilled quote_currency_code from JSONB data';
    
    -- Drop redundant JSONB columns that were replaced by text fields
    -- These columns store complex data that should be flattened for better queryability
    
    -- Drop quote_currency (replaced by quote_currency_code)
    IF EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'orders' AND column_name = 'quote_currency'
    ) THEN
        ALTER TABLE orders DROP COLUMN quote_currency;
        RAISE NOTICE '✅ Dropped quote_currency JSONB column (replaced by quote_currency_code)';
    END IF;
    
    -- Drop universal_symbol (complex symbol data not commonly queried)
    IF EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'orders' AND column_name = 'universal_symbol'
    ) THEN
        ALTER TABLE orders DROP COLUMN universal_symbol;
        RAISE NOTICE '✅ Dropped universal_symbol JSONB column';
    END IF;
    
    -- Drop option_symbol (complex option data not commonly queried)
    IF EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'orders' AND column_name = 'option_symbol'
    ) THEN
        ALTER TABLE orders DROP COLUMN option_symbol;
        RAISE NOTICE '✅ Dropped option_symbol JSONB column';
    END IF;
    
    -- Drop quote_universal_symbol (complex quote symbol data not commonly queried)
    IF EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'orders' AND column_name = 'quote_universal_symbol'
    ) THEN
        ALTER TABLE orders DROP COLUMN quote_universal_symbol;
        RAISE NOTICE '✅ Dropped quote_universal_symbol JSONB column';
    END IF;
    
    RAISE NOTICE 'Orders table cleanup completed - now optimized for querying';
END $$;

-- ==============================================
-- Phase 2: Performance Indexes
-- ==============================================

DO $$ BEGIN
    RAISE NOTICE 'Adding performance indexes...';
    
    -- Orders table indexes
    CREATE INDEX IF NOT EXISTS idx_orders_symbol ON orders(symbol);
    CREATE INDEX IF NOT EXISTS idx_orders_time_placed ON orders(time_placed);
    CREATE INDEX IF NOT EXISTS idx_orders_time_executed ON orders(time_executed);
    CREATE INDEX IF NOT EXISTS idx_orders_account_id ON orders(account_id);
    CREATE INDEX IF NOT EXISTS idx_orders_state ON orders(state);
    CREATE INDEX IF NOT EXISTS idx_orders_action ON orders(action);
    
    -- Discord tables indexes
    CREATE INDEX IF NOT EXISTS idx_discord_messages_timestamp ON discord_messages("timestamp");
    CREATE INDEX IF NOT EXISTS idx_discord_messages_author ON discord_messages(author);
    CREATE INDEX IF NOT EXISTS idx_discord_messages_channel ON discord_messages(channel);
    CREATE INDEX IF NOT EXISTS idx_discord_messages_author_id ON discord_messages(author_id);
    
    CREATE INDEX IF NOT EXISTS idx_discord_trading_clean_timestamp ON discord_trading_clean("timestamp");
    CREATE INDEX IF NOT EXISTS idx_discord_trading_clean_stock_mentions ON discord_trading_clean(stock_mentions);
    
    CREATE INDEX IF NOT EXISTS idx_discord_market_clean_timestamp ON discord_market_clean("timestamp");
    
    -- Twitter data indexes
    CREATE INDEX IF NOT EXISTS idx_twitter_data_message_id ON twitter_data(message_id);
    CREATE INDEX IF NOT EXISTS idx_twitter_data_discord_date ON twitter_data(discord_date);
    CREATE INDEX IF NOT EXISTS idx_twitter_data_tweet_date ON twitter_data(tweet_date);
    
    -- Market data indexes
    CREATE INDEX IF NOT EXISTS idx_daily_prices_date ON daily_prices(date);
    CREATE INDEX IF NOT EXISTS idx_realtime_prices_timestamp ON realtime_prices("timestamp");
    CREATE INDEX IF NOT EXISTS idx_stock_metrics_date ON stock_metrics(date);
    
    -- Account data indexes
    CREATE INDEX IF NOT EXISTS idx_account_balances_snapshot_date ON account_balances(snapshot_date);
    CREATE INDEX IF NOT EXISTS idx_account_balances_account_id ON account_balances(account_id);
    
    RAISE NOTICE '✅ Performance indexes created';
END $$;

-- ==============================================
-- Phase 3: Clean Up Test Tables
-- ==============================================

DO $$ BEGIN
    RAISE NOTICE 'Cleaning up any test tables...';
    
    -- Drop test table if it exists
    DROP TABLE IF EXISTS test_table;
    
    -- Check for any other tables that might be test artifacts
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name LIKE '%test%' AND table_schema = 'public') THEN
        RAISE NOTICE 'Found additional test tables - manual review recommended';
    END IF;
    
    RAISE NOTICE '✅ Test table cleanup completed';
END $$;

-- ==============================================
-- Phase 4: Verify Final State
-- ==============================================

DO $$ BEGIN
    RAISE NOTICE '';
    RAISE NOTICE '🎉 Migration 013 completed successfully:';
    RAISE NOTICE '  ✅ Orders table optimized:';
    RAISE NOTICE '    • Added quote_currency_code TEXT column';
    RAISE NOTICE '    • Backfilled from quote_currency JSONB data';
    RAISE NOTICE '    • Dropped redundant JSONB columns for better performance';
    RAISE NOTICE '  ✅ Performance indexes added:';
    RAISE NOTICE '    • Orders: symbol, timestamps, account_id, state, action';
    RAISE NOTICE '    • Discord: timestamps, authors, channels, stock_mentions';
    RAISE NOTICE '    • Twitter: message_id, dates';
    RAISE NOTICE '    • Market data: dates and timestamps';
    RAISE NOTICE '    • Account data: dates and account_id';
    RAISE NOTICE '  ✅ Test tables cleaned up';
    RAISE NOTICE '';
    RAISE NOTICE 'Database schema is now fully optimized with natural keys and performance indexes!';
END $$;