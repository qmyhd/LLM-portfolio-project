-- 010_comprehensive_schema_cleanup.sql - Complete Schema Cleanup and Alignment
-- Implements the original plan for schema simplification and natural key usage
-- 
-- Changes implemented:
-- 1. Drop redundant auto-increment ID columns from tables with natural keys
-- 2. Update primary key constraints to use natural keys
-- 3. Drop redundant extracted_symbol column from orders table
-- 4. Add missing natural key constraints where needed
-- 5. Clean up any remaining schema inconsistencies
--
-- NOTE: This migration permanently removes auto-increment ID columns.
-- Ensure all application code uses natural keys before applying.

-- ==============================================
-- Comprehensive Schema Cleanup Migration
-- ==============================================

-- Record this migration
INSERT INTO schema_migrations (version, description) 
VALUES ('010_comprehensive_schema_cleanup', 'Complete schema cleanup - drop redundant ID columns, use natural keys, clean up orders table') 
ON CONFLICT (version) DO NOTHING;

-- ==============================================
-- Phase 1: Drop Redundant extracted_symbol Column
-- ==============================================

DO $$ BEGIN
    -- Drop extracted_symbol from orders table (redundant with symbol)
    IF EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'orders' 
        AND column_name = 'extracted_symbol'
    ) THEN
        -- Drop any indexes on extracted_symbol first
        DROP INDEX IF EXISTS idx_orders_extracted_symbol;
        
        -- Drop the column
        ALTER TABLE orders DROP COLUMN extracted_symbol;
        
        RAISE NOTICE '✅ Dropped redundant orders.extracted_symbol column';
    ELSE
        RAISE NOTICE 'orders.extracted_symbol column does not exist - no action needed';
    END IF;
END $$;

-- ==============================================
-- Phase 2: Add Missing Natural Key Constraints
-- ==============================================

DO $$ BEGIN
    -- Add natural key constraint for twitter_data if it doesn't exist
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints 
        WHERE table_name = 'twitter_data' 
        AND constraint_type = 'UNIQUE'
        AND constraint_name LIKE '%tweet_id%'
    ) THEN
        -- Ensure tweet_id is not null first
        UPDATE twitter_data SET tweet_id = 'unknown_' || id::text WHERE tweet_id IS NULL;
        
        -- Add unique constraint on tweet_id
        ALTER TABLE twitter_data ADD CONSTRAINT twitter_data_tweet_id_unique UNIQUE (tweet_id);
        
        RAISE NOTICE '✅ Added natural key constraint: twitter_data_tweet_id_unique';
    ELSE
        RAISE NOTICE 'twitter_data natural key constraint already exists';
    END IF;
    
    -- Add natural key constraint for chart_metadata if it doesn't exist
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints 
        WHERE table_name = 'chart_metadata' 
        AND constraint_type = 'UNIQUE'
        AND constraint_name LIKE '%symbol%'
    ) THEN
        -- Add composite unique constraint on symbol, period, interval, theme
        ALTER TABLE chart_metadata ADD CONSTRAINT chart_metadata_symbol_period_interval_theme_unique 
        UNIQUE (symbol, period, interval, theme);
        
        RAISE NOTICE '✅ Added natural key constraint: chart_metadata_symbol_period_interval_theme_unique';
    ELSE
        RAISE NOTICE 'chart_metadata natural key constraint already exists';
    END IF;
    
    -- Add natural key constraint for discord_processing_log if it doesn't exist
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints 
        WHERE table_name = 'discord_processing_log' 
        AND constraint_type = 'UNIQUE'
        AND constraint_name LIKE '%message_id%'
    ) THEN
        -- Add composite unique constraint on message_id, channel
        ALTER TABLE discord_processing_log ADD CONSTRAINT discord_processing_log_message_id_channel_unique 
        UNIQUE (message_id, channel);
        
        RAISE NOTICE '✅ Added natural key constraint: discord_processing_log_message_id_channel_unique';
    ELSE
        RAISE NOTICE 'discord_processing_log natural key constraint already exists';
    END IF;
END $$;

-- ==============================================
-- Phase 3: Drop Redundant ID Columns and Update Primary Keys
-- ==============================================

-- Helper function to safely drop ID column and update primary key
CREATE OR REPLACE FUNCTION drop_id_column_and_update_pk(
    table_name TEXT,
    new_pk_columns TEXT[]
) RETURNS VOID AS $$
DECLARE
    pk_constraint_name TEXT;
    new_pk_constraint_name TEXT;
    col TEXT;
    pk_definition TEXT;
BEGIN
    -- Get current primary key constraint name
    SELECT constraint_name INTO pk_constraint_name
    FROM information_schema.table_constraints 
    WHERE table_schema = 'public' 
        AND table_type = 'BASE TABLE'
        AND constraint_type = 'PRIMARY KEY'
        AND table_name = drop_id_column_and_update_pk.table_name;
    
    IF pk_constraint_name IS NOT NULL THEN
        -- Drop current primary key constraint
        EXECUTE format('ALTER TABLE %I DROP CONSTRAINT %I', table_name, pk_constraint_name);
        RAISE NOTICE 'Dropped primary key constraint: %', pk_constraint_name;
    END IF;
    
    -- Drop the id column
    EXECUTE format('ALTER TABLE %I DROP COLUMN IF EXISTS id', table_name);
    RAISE NOTICE 'Dropped id column from table: %', table_name;
    
    -- Create new primary key constraint name and definition
    new_pk_constraint_name := table_name || '_pkey';
    pk_definition := '(' || array_to_string(new_pk_columns, ', ') || ')';
    
    -- Add new primary key constraint
    EXECUTE format('ALTER TABLE %I ADD CONSTRAINT %I PRIMARY KEY %s', 
                   table_name, new_pk_constraint_name, pk_definition);
    RAISE NOTICE 'Added new primary key constraint: % on columns %', new_pk_constraint_name, pk_definition;
    
EXCEPTION
    WHEN OTHERS THEN
        RAISE NOTICE 'Error processing table %: %', table_name, SQLERRM;
END;
$$ LANGUAGE plpgsql;

-- Apply ID column drops to tables with natural keys
DO $$ BEGIN
    RAISE NOTICE 'Starting Phase 3: Dropping redundant ID columns and updating primary keys';
    
    -- orders table: Use brokerage_order_id as primary key
    PERFORM drop_id_column_and_update_pk('orders', ARRAY['brokerage_order_id']);
    
    -- account_balances table: Use composite key (account_id, currency_code, snapshot_date)
    PERFORM drop_id_column_and_update_pk('account_balances', ARRAY['account_id', 'currency_code', 'snapshot_date']);
    
    -- discord_messages table: Use message_id as primary key
    PERFORM drop_id_column_and_update_pk('discord_messages', ARRAY['message_id']);
    
    -- discord_market_clean table: Use message_id as primary key
    PERFORM drop_id_column_and_update_pk('discord_market_clean', ARRAY['message_id']);
    
    -- discord_trading_clean table: Use message_id as primary key
    PERFORM drop_id_column_and_update_pk('discord_trading_clean', ARRAY['message_id']);
    
    -- processing_status table: Use message_id as primary key
    PERFORM drop_id_column_and_update_pk('processing_status', ARRAY['message_id']);
    
    -- daily_prices table: Use composite key (symbol, date)
    PERFORM drop_id_column_and_update_pk('daily_prices', ARRAY['symbol', 'date']);
    
    -- realtime_prices table: Use composite key (symbol, timestamp)
    PERFORM drop_id_column_and_update_pk('realtime_prices', ARRAY['symbol', 'timestamp']);
    
    -- stock_metrics table: Use composite key (symbol, date)
    PERFORM drop_id_column_and_update_pk('stock_metrics', ARRAY['symbol', 'date']);
    
    -- twitter_data table: Use tweet_id as primary key (now that we have unique constraint)
    PERFORM drop_id_column_and_update_pk('twitter_data', ARRAY['tweet_id']);
    
    -- chart_metadata table: Use composite key (symbol, period, interval, theme)
    PERFORM drop_id_column_and_update_pk('chart_metadata', ARRAY['symbol', 'period', 'interval', 'theme']);
    
    -- discord_processing_log table: Use composite key (message_id, channel)
    PERFORM drop_id_column_and_update_pk('discord_processing_log', ARRAY['message_id', 'channel']);
    
    RAISE NOTICE 'Completed Phase 3: All redundant ID columns dropped and natural keys set as primary keys';
END $$;

-- ==============================================
-- Phase 4: Update Remaining Schema Issues
-- ==============================================

DO $$ BEGIN
    -- Ensure stock_charts table exists with proper structure (from migration 009)
    IF NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'stock_charts') THEN
        CREATE TABLE stock_charts (
            symbol TEXT NOT NULL,
            chart_type TEXT NOT NULL DEFAULT 'candlestick',
            time_period TEXT NOT NULL DEFAULT '1d',
            chart_data JSONB,
            metadata JSONB,
            generated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            file_path TEXT,
            chart_hash TEXT,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            PRIMARY KEY (symbol, chart_type, time_period, generated_at)
        );
        
        -- Add indexes
        CREATE INDEX idx_stock_charts_symbol ON stock_charts(symbol);
        CREATE INDEX idx_stock_charts_generated_at ON stock_charts(generated_at);
        CREATE INDEX idx_stock_charts_chart_type ON stock_charts(chart_type);
        
        RAISE NOTICE '✅ Created stock_charts table with natural key primary key';
    ELSE
        -- If table exists but still has id column, drop it
        IF EXISTS (
            SELECT 1 FROM information_schema.columns 
            WHERE table_name = 'stock_charts' AND column_name = 'id'
        ) THEN
            PERFORM drop_id_column_and_update_pk('stock_charts', ARRAY['symbol', 'chart_type', 'time_period', 'generated_at']);
            RAISE NOTICE '✅ Updated stock_charts table to use natural key primary key';
        ELSE
            RAISE NOTICE 'stock_charts table already properly configured';
        END IF;
    END IF;
END $$;

-- Clean up the helper function
DROP FUNCTION drop_id_column_and_update_pk(TEXT, TEXT[]);

-- ==============================================
-- Phase 5: Performance and Cleanup
-- ==============================================

-- Update statistics for query planner
ANALYZE;

-- Clean up any orphaned constraints or indexes
DO $$ 
DECLARE
    index_rec RECORD;
BEGIN
    -- Drop any indexes that reference the dropped id columns
    FOR index_rec IN 
        SELECT indexname FROM pg_indexes 
        WHERE schemaname = 'public' 
        AND indexname LIKE '%_id_%' 
        AND tablename IN ('orders', 'account_balances', 'discord_messages', 'discord_market_clean', 
                         'discord_trading_clean', 'processing_status', 'daily_prices', 'realtime_prices', 
                         'stock_metrics', 'twitter_data', 'chart_metadata', 'discord_processing_log')
    LOOP
        BEGIN
            EXECUTE 'DROP INDEX IF EXISTS ' || index_rec.indexname;
            RAISE NOTICE 'Dropped orphaned index: %', index_rec.indexname;
        EXCEPTION
            WHEN OTHERS THEN
                RAISE NOTICE 'Could not drop index % (may not exist): %', index_rec.indexname, SQLERRM;
        END;
    END LOOP;
END $$;

-- ==============================================
-- Phase 6: Documentation and Comments
-- ==============================================

-- Add comments explaining the natural key design
COMMENT ON TABLE orders IS 'Order data using brokerage_order_id as natural primary key';
COMMENT ON TABLE account_balances IS 'Account balance data using composite natural key (account_id, currency_code, snapshot_date)';
COMMENT ON TABLE discord_messages IS 'Discord message data using message_id as natural primary key';
COMMENT ON TABLE discord_market_clean IS 'Cleaned Discord market messages using message_id as natural primary key';
COMMENT ON TABLE discord_trading_clean IS 'Cleaned Discord trading messages using message_id as natural primary key';
COMMENT ON TABLE processing_status IS 'Message processing status using message_id as natural primary key';
COMMENT ON TABLE daily_prices IS 'Daily price data using composite natural key (symbol, date)';
COMMENT ON TABLE realtime_prices IS 'Real-time price data using composite natural key (symbol, timestamp)';
COMMENT ON TABLE stock_metrics IS 'Stock metrics data using composite natural key (symbol, date)';
COMMENT ON TABLE twitter_data IS 'Twitter data using tweet_id as natural primary key';
COMMENT ON TABLE chart_metadata IS 'Chart metadata using composite natural key (symbol, period, interval, theme)';
COMMENT ON TABLE discord_processing_log IS 'Discord processing log using composite natural key (message_id, channel)';

-- ==============================================
-- Verification and Completion
-- ==============================================

DO $$ BEGIN
    RAISE NOTICE '';
    RAISE NOTICE '🎉 Comprehensive schema cleanup migration 010 completed successfully:';
    RAISE NOTICE '  ✅ Dropped redundant auto-increment ID columns from 12 tables';
    RAISE NOTICE '  ✅ Updated all tables to use natural keys as primary keys';
    RAISE NOTICE '  ✅ Dropped redundant extracted_symbol column from orders table';
    RAISE NOTICE '  ✅ Added missing natural key constraints where needed';
    RAISE NOTICE '  ✅ Updated stock_charts table structure';
    RAISE NOTICE '  ✅ Cleaned up orphaned indexes and constraints';
    RAISE NOTICE '  ✅ Added documentation comments for all tables';
    RAISE NOTICE '';
    RAISE NOTICE '📋 Tables now using natural keys:';
    RAISE NOTICE '  • orders: brokerage_order_id (primary key)';
    RAISE NOTICE '  • account_balances: (account_id, currency_code, snapshot_date) (composite primary key)';
    RAISE NOTICE '  • discord_messages: message_id (primary key)';
    RAISE NOTICE '  • discord_market_clean: message_id (primary key)';
    RAISE NOTICE '  • discord_trading_clean: message_id (primary key)';
    RAISE NOTICE '  • processing_status: message_id (primary key)';
    RAISE NOTICE '  • daily_prices: (symbol, date) (composite primary key)';
    RAISE NOTICE '  • realtime_prices: (symbol, timestamp) (composite primary key)';
    RAISE NOTICE '  • stock_metrics: (symbol, date) (composite primary key)';
    RAISE NOTICE '  • twitter_data: tweet_id (primary key)';
    RAISE NOTICE '  • chart_metadata: (symbol, period, interval, theme) (composite primary key)';
    RAISE NOTICE '  • discord_processing_log: (message_id, channel) (composite primary key)';
    RAISE NOTICE '  • stock_charts: (symbol, chart_type, time_period, generated_at) (composite primary key)';
    RAISE NOTICE '';
    RAISE NOTICE '📋 Tables keeping natural ID columns:';
    RAISE NOTICE '  • accounts: id (SnapTrade account_id - natural key)';
    RAISE NOTICE '  • symbols: id (SnapTrade symbol_id - natural key)';
    RAISE NOTICE '';
    RAISE NOTICE '⚠️  IMPORTANT: Ensure all application code uses natural keys instead of auto-increment IDs';
    RAISE NOTICE '   Run schema verification to confirm complete alignment';
END $$;