-- 008_comprehensive_schema_alignment.sql - Final Schema Alignment
-- Comprehensive migration to fix all remaining schema discrepancies
-- Based on detailed verification analysis addressing:
-- 1. Orders table child_brokerage_order_ids array → JSONB conversion (migration 007 fix)
-- 2. Constraint naming standardization (_key → _unique)  
-- 3. Extra table cleanup (test_table, old positions)
-- 4. Missing/extra column alignment
-- 5. Type consistency improvements

-- ==============================================
-- Comprehensive Schema Alignment Migration
-- ==============================================

-- Record this migration
INSERT INTO schema_migrations (version, description) 
VALUES ('008_comprehensive_schema_alignment', 'Comprehensive schema alignment - fix arrays, constraints, cleanup tables, align types') 
ON CONFLICT (version) DO NOTHING;

-- ==============================================
-- Fix 1: Orders Table - child_brokerage_order_ids Array → JSONB
-- ==============================================

DO $$ BEGIN
    -- Fix the issue from migration 007 where conversion didn't work due to conditional logic
    RAISE NOTICE 'Fixing orders.child_brokerage_order_ids conversion from text[] to JSONB';
    
    -- Check current type and convert regardless of current state
    IF EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'orders' 
        AND column_name = 'child_brokerage_order_ids'
    ) THEN
        -- Convert text[] or any other type to JSONB using to_jsonb function
        ALTER TABLE orders 
        ALTER COLUMN child_brokerage_order_ids 
        TYPE JSONB 
        USING CASE 
            WHEN child_brokerage_order_ids IS NULL THEN NULL::JSONB
            ELSE to_jsonb(child_brokerage_order_ids)
        END;
        
        RAISE NOTICE '✅ Successfully converted child_brokerage_order_ids to JSONB array type';
    ELSE
        RAISE NOTICE 'orders.child_brokerage_order_ids column not found - no conversion needed';
    END IF;
END $$;

-- ==============================================
-- Fix 2: Constraint Naming Standardization
-- ==============================================

DO $$ BEGIN
    RAISE NOTICE 'Standardizing constraint names from _key to _unique suffix';
    
    -- Discord market clean
    IF EXISTS (SELECT 1 FROM information_schema.table_constraints 
               WHERE constraint_name = 'discord_market_clean_message_id_key') THEN
        ALTER TABLE discord_market_clean 
        RENAME CONSTRAINT discord_market_clean_message_id_key 
        TO discord_market_clean_message_id_unique;
        RAISE NOTICE '✅ Renamed discord_market_clean constraint';
    END IF;
    
    -- Discord trading clean  
    IF EXISTS (SELECT 1 FROM information_schema.table_constraints 
               WHERE constraint_name = 'discord_trading_clean_message_id_key') THEN
        ALTER TABLE discord_trading_clean 
        RENAME CONSTRAINT discord_trading_clean_message_id_key 
        TO discord_trading_clean_message_id_unique;
        RAISE NOTICE '✅ Renamed discord_trading_clean constraint';
    END IF;
    
    -- Discord messages
    IF EXISTS (SELECT 1 FROM information_schema.table_constraints 
               WHERE constraint_name = 'discord_messages_message_id_key') THEN
        ALTER TABLE discord_messages 
        RENAME CONSTRAINT discord_messages_message_id_key 
        TO discord_messages_message_id_unique;
        RAISE NOTICE '✅ Renamed discord_messages constraint';
    END IF;
    
    -- Orders brokerage_order_id  
    IF EXISTS (SELECT 1 FROM information_schema.table_constraints 
               WHERE constraint_name = 'orders_brokerage_order_id_key') THEN
        ALTER TABLE orders 
        RENAME CONSTRAINT orders_brokerage_order_id_key 
        TO orders_brokerage_order_id_unique;
        RAISE NOTICE '✅ Renamed orders constraint';
    END IF;
    
    -- Processing status
    IF EXISTS (SELECT 1 FROM information_schema.table_constraints 
               WHERE constraint_name = 'processing_status_message_id_key') THEN
        ALTER TABLE processing_status 
        RENAME CONSTRAINT processing_status_message_id_key 
        TO processing_status_message_id_unique;
        RAISE NOTICE '✅ Renamed processing_status constraint';
    END IF;
    
    -- Account balances (multi-column constraint)
    IF EXISTS (SELECT 1 FROM information_schema.table_constraints 
               WHERE constraint_name = 'account_balances_account_id_currency_code_snapshot_date_key') THEN
        ALTER TABLE account_balances 
        RENAME CONSTRAINT account_balances_account_id_currency_code_snapshot_date_key 
        TO account_balances_account_id_currency_code_snapshot_date_unique;
        RAISE NOTICE '✅ Renamed account_balances constraint';
    END IF;
    
    -- Daily prices
    IF EXISTS (SELECT 1 FROM information_schema.table_constraints 
               WHERE constraint_name = 'daily_prices_symbol_date_key') THEN
        ALTER TABLE daily_prices 
        RENAME CONSTRAINT daily_prices_symbol_date_key 
        TO daily_prices_symbol_date_unique;
        RAISE NOTICE '✅ Renamed daily_prices constraint';
    END IF;
    
    -- Stock metrics  
    IF EXISTS (SELECT 1 FROM information_schema.table_constraints 
               WHERE constraint_name = 'stock_metrics_symbol_date_key') THEN
        ALTER TABLE stock_metrics 
        RENAME CONSTRAINT stock_metrics_symbol_date_key 
        TO stock_metrics_symbol_date_unique;
        RAISE NOTICE '✅ Renamed stock_metrics constraint';
    END IF;
    
    -- Realtime prices
    IF EXISTS (SELECT 1 FROM information_schema.table_constraints 
               WHERE constraint_name = 'realtime_prices_symbol_timestamp_key') THEN
        ALTER TABLE realtime_prices 
        RENAME CONSTRAINT realtime_prices_symbol_timestamp_key 
        TO realtime_prices_symbol_timestamp_unique;
        RAISE NOTICE '✅ Renamed realtime_prices constraint';
    END IF;
    
    RAISE NOTICE 'Constraint naming standardization completed';
END $$;

-- ==============================================
-- Fix 3: Clean Up Extra Tables
-- ==============================================

DO $$ BEGIN
    RAISE NOTICE 'Cleaning up extra tables that should not exist';
    
    -- Drop test_table if it exists
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'test_table') THEN
        DROP TABLE test_table;
        RAISE NOTICE '✅ Dropped test_table';
    ELSE
        RAISE NOTICE 'test_table does not exist - no cleanup needed';
    END IF;
    
    -- Drop old positions table if it exists (replaced by SnapTrade positions)
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'positions') THEN
        -- Check if it has any important data first
        DECLARE
            row_count INTEGER;
        BEGIN
            SELECT COUNT(*) INTO row_count FROM positions;
            IF row_count > 0 THEN
                RAISE NOTICE 'WARNING: positions table has % rows - creating backup first', row_count;
                -- Create backup table
                CREATE TABLE positions_backup_008 AS SELECT * FROM positions;
                RAISE NOTICE 'Created backup table: positions_backup_008';
            END IF;
        END;
        
        DROP TABLE positions;
        RAISE NOTICE '✅ Dropped old positions table (backup created if data existed)';
    ELSE
        RAISE NOTICE 'Old positions table does not exist - no cleanup needed';
    END IF;
    
    RAISE NOTICE 'Extra table cleanup completed';
END $$;

-- ==============================================
-- Fix 4: Twitter Data Column Alignment
-- ==============================================

DO $$ BEGIN
    RAISE NOTICE 'Aligning twitter_data table columns with expected schema';
    
    -- Add missing columns that exist in database but not in expected schema
    -- Based on verification showing extra columns: tweet_date, quote_count, retrieved_at, discord_date, reply_count, content, source_url, message_id
    
    -- These columns already exist in the database, so this is for documentation
    -- and to ensure our expected schema includes them
    
    RAISE NOTICE 'twitter_data columns already aligned - extra columns are expected';
    
    -- Add index on message_id for better performance
    CREATE INDEX IF NOT EXISTS idx_twitter_data_message_id ON twitter_data(message_id);
    
    RAISE NOTICE '✅ Added performance index on twitter_data.message_id';
END $$;

-- ==============================================
-- Fix 5: Symbols Table Extra Columns
-- ==============================================

DO $$ BEGIN
    RAISE NOTICE 'Documenting symbols table extra columns';
    
    -- The database has market_close_time, timezone, market_open_time columns
    -- These are valuable for trading hours information, so we should keep them
    -- and update our expected schema to include them
    
    -- Add comments to document these fields
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'symbols' AND column_name = 'market_open_time') THEN
        COMMENT ON COLUMN symbols.market_open_time IS 'Market opening time for this symbol exchange';
    END IF;
    
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'symbols' AND column_name = 'market_close_time') THEN
        COMMENT ON COLUMN symbols.market_close_time IS 'Market closing time for this symbol exchange';
    END IF;
    
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'symbols' AND column_name = 'timezone') THEN
        COMMENT ON COLUMN symbols.timezone IS 'Timezone for market hours of this symbol';
    END IF;
    
    RAISE NOTICE '✅ Documented symbols table market timing columns';
END $$;

-- ==============================================
-- Fix 6: Add Missing Extracted Symbol Column (If Needed)
-- ==============================================

DO $$ BEGIN
    -- Check if the application actually needs extracted_symbol
    -- Based on verification, it's expected but missing from database
    
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'orders' 
        AND column_name = 'extracted_symbol'
    ) THEN
        -- Add the column and populate it from symbol column
        ALTER TABLE orders ADD COLUMN extracted_symbol TEXT;
        
        -- Populate with current symbol values (they should be the same)
        UPDATE orders SET extracted_symbol = symbol WHERE symbol IS NOT NULL;
        
        -- Add comment explaining the purpose
        COMMENT ON COLUMN orders.extracted_symbol IS 'Extracted symbol from order data - should match symbol column';
        
        RAISE NOTICE '✅ Added extracted_symbol column and populated from symbol';
    ELSE
        RAISE NOTICE 'extracted_symbol column already exists - no action needed';
    END IF;
END $$;

-- ==============================================
-- Fix 7: Performance Indexes for Discord Tables
-- ==============================================

-- Add recommended indexes for better query performance
CREATE INDEX IF NOT EXISTS idx_discord_messages_timestamp ON discord_messages(timestamp);
CREATE INDEX IF NOT EXISTS idx_discord_messages_author ON discord_messages(author);
CREATE INDEX IF NOT EXISTS idx_discord_messages_channel ON discord_messages(channel);

CREATE INDEX IF NOT EXISTS idx_discord_trading_clean_timestamp ON discord_trading_clean(timestamp);
CREATE INDEX IF NOT EXISTS idx_discord_market_clean_timestamp ON discord_market_clean(timestamp);

-- ==============================================
-- Verification: Log Final Schema State
-- ==============================================

DO $$ BEGIN
    RAISE NOTICE '';
    RAISE NOTICE '🎉 Comprehensive schema alignment migration 008 completed successfully:';
    RAISE NOTICE '  ✅ Fixed orders.child_brokerage_order_ids array → JSONB conversion';
    RAISE NOTICE '  ✅ Standardized constraint naming (_key → _unique)';
    RAISE NOTICE '  ✅ Cleaned up extra tables (test_table, old positions)';
    RAISE NOTICE '  ✅ Aligned twitter_data and symbols column expectations';
    RAISE NOTICE '  ✅ Added missing extracted_symbol column to orders';
    RAISE NOTICE '  ✅ Added performance indexes for Discord tables';
    RAISE NOTICE '';
    RAISE NOTICE 'Schema should now be fully aligned between expected and actual state';
    RAISE NOTICE 'Run verification script to confirm all issues are resolved';
END $$;