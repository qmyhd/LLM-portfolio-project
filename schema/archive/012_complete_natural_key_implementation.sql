-- 012_complete_natural_key_implementation.sql - Complete Natural Key Implementation
-- Finishes the implementation of natural keys across all tables
-- 
-- This migration continues the work from 010 which had some silent failures
-- and completes the transition to natural keys as primary keys.

-- Record this migration
INSERT INTO schema_migrations (version, description) 
VALUES ('012_complete_natural_key_implementation', 'Complete natural key implementation - finish dropping ID columns and set natural keys as primary keys') 
ON CONFLICT (version) DO NOTHING;

-- ==============================================
-- Phase 1: Complete Natural Key Implementation
-- ==============================================

DO $$ BEGIN
    RAISE NOTICE 'Starting natural key implementation for remaining tables';
    
    -- orders table: Use brokerage_order_id as primary key
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'orders' AND column_name = 'id') THEN
        -- Check if there are any nulls in brokerage_order_id
        IF (SELECT COUNT(*) FROM orders WHERE brokerage_order_id IS NULL) = 0 THEN
            ALTER TABLE orders DROP CONSTRAINT IF EXISTS orders_pkey;
            ALTER TABLE orders DROP COLUMN id;
            ALTER TABLE orders ADD CONSTRAINT orders_pkey PRIMARY KEY (brokerage_order_id);
            RAISE NOTICE '✅ Updated orders table to use brokerage_order_id as primary key';
        ELSE
            RAISE NOTICE '⚠️ Cannot update orders table - brokerage_order_id has NULL values';
        END IF;
    END IF;
    
    -- account_balances table: Use composite key (account_id, currency_code, snapshot_date)
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'account_balances' AND column_name = 'id') THEN
        -- Check for nulls in composite key columns
        IF (SELECT COUNT(*) FROM account_balances WHERE account_id IS NULL OR currency_code IS NULL OR snapshot_date IS NULL) = 0 THEN
            ALTER TABLE account_balances DROP CONSTRAINT IF EXISTS account_balances_pkey;
            ALTER TABLE account_balances DROP COLUMN id;
            ALTER TABLE account_balances ADD CONSTRAINT account_balances_pkey PRIMARY KEY (account_id, currency_code, snapshot_date);
            RAISE NOTICE '✅ Updated account_balances table to use composite natural key';
        ELSE
            RAISE NOTICE '⚠️ Cannot update account_balances table - composite key has NULL values';
        END IF;
    END IF;
    
    -- discord_market_clean table: Use message_id as primary key
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'discord_market_clean' AND column_name = 'id') THEN
        IF (SELECT COUNT(*) FROM discord_market_clean WHERE message_id IS NULL) = 0 THEN
            ALTER TABLE discord_market_clean DROP CONSTRAINT IF EXISTS discord_market_clean_pkey;
            ALTER TABLE discord_market_clean DROP COLUMN id;
            ALTER TABLE discord_market_clean ADD CONSTRAINT discord_market_clean_pkey PRIMARY KEY (message_id);
            RAISE NOTICE '✅ Updated discord_market_clean table to use message_id as primary key';
        ELSE
            RAISE NOTICE '⚠️ Cannot update discord_market_clean table - message_id has NULL values';
        END IF;
    END IF;
    
    -- discord_trading_clean table: Use message_id as primary key
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'discord_trading_clean' AND column_name = 'id') THEN
        IF (SELECT COUNT(*) FROM discord_trading_clean WHERE message_id IS NULL) = 0 THEN
            ALTER TABLE discord_trading_clean DROP CONSTRAINT IF EXISTS discord_trading_clean_pkey;
            ALTER TABLE discord_trading_clean DROP COLUMN id;
            ALTER TABLE discord_trading_clean ADD CONSTRAINT discord_trading_clean_pkey PRIMARY KEY (message_id);
            RAISE NOTICE '✅ Updated discord_trading_clean table to use message_id as primary key';
        ELSE
            RAISE NOTICE '⚠️ Cannot update discord_trading_clean table - message_id has NULL values';
        END IF;
    END IF;
    
    -- processing_status table: Use message_id as primary key
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'processing_status' AND column_name = 'id') THEN
        IF (SELECT COUNT(*) FROM processing_status WHERE message_id IS NULL) = 0 THEN
            ALTER TABLE processing_status DROP CONSTRAINT IF EXISTS processing_status_pkey;
            ALTER TABLE processing_status DROP COLUMN id;
            ALTER TABLE processing_status ADD CONSTRAINT processing_status_pkey PRIMARY KEY (message_id);
            RAISE NOTICE '✅ Updated processing_status table to use message_id as primary key';
        ELSE
            RAISE NOTICE '⚠️ Cannot update processing_status table - message_id has NULL values';
        END IF;
    END IF;
    
    -- daily_prices table: Use composite key (symbol, date)
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'daily_prices' AND column_name = 'id') THEN
        IF (SELECT COUNT(*) FROM daily_prices WHERE symbol IS NULL OR date IS NULL) = 0 THEN
            ALTER TABLE daily_prices DROP CONSTRAINT IF EXISTS daily_prices_pkey;
            ALTER TABLE daily_prices DROP COLUMN id;
            ALTER TABLE daily_prices ADD CONSTRAINT daily_prices_pkey PRIMARY KEY (symbol, date);
            RAISE NOTICE '✅ Updated daily_prices table to use composite natural key';
        ELSE
            RAISE NOTICE '⚠️ Cannot update daily_prices table - composite key has NULL values';
        END IF;
    END IF;
    
    -- realtime_prices table: Use composite key (symbol, timestamp)
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'realtime_prices' AND column_name = 'id') THEN
        IF (SELECT COUNT(*) FROM realtime_prices WHERE symbol IS NULL OR timestamp IS NULL) = 0 THEN
            ALTER TABLE realtime_prices DROP CONSTRAINT IF EXISTS realtime_prices_pkey;
            ALTER TABLE realtime_prices DROP COLUMN id;
            ALTER TABLE realtime_prices ADD CONSTRAINT realtime_prices_pkey PRIMARY KEY (symbol, timestamp);
            RAISE NOTICE '✅ Updated realtime_prices table to use composite natural key';
        ELSE
            RAISE NOTICE '⚠️ Cannot update realtime_prices table - composite key has NULL values';
        END IF;
    END IF;
    
    -- stock_metrics table: Use composite key (symbol, date)
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'stock_metrics' AND column_name = 'id') THEN
        IF (SELECT COUNT(*) FROM stock_metrics WHERE symbol IS NULL OR date IS NULL) = 0 THEN
            ALTER TABLE stock_metrics DROP CONSTRAINT IF EXISTS stock_metrics_pkey;
            ALTER TABLE stock_metrics DROP COLUMN id;
            ALTER TABLE stock_metrics ADD CONSTRAINT stock_metrics_pkey PRIMARY KEY (symbol, date);
            RAISE NOTICE '✅ Updated stock_metrics table to use composite natural key';
        ELSE
            RAISE NOTICE '⚠️ Cannot update stock_metrics table - composite key has NULL values';
        END IF;
    END IF;
    
    -- twitter_data table: Use tweet_id as primary key
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'twitter_data' AND column_name = 'id') THEN
        IF (SELECT COUNT(*) FROM twitter_data WHERE tweet_id IS NULL) = 0 THEN
            ALTER TABLE twitter_data DROP CONSTRAINT IF EXISTS twitter_data_pkey;
            ALTER TABLE twitter_data DROP COLUMN id;
            ALTER TABLE twitter_data ADD CONSTRAINT twitter_data_pkey PRIMARY KEY (tweet_id);
            RAISE NOTICE '✅ Updated twitter_data table to use tweet_id as primary key';
        ELSE
            RAISE NOTICE '⚠️ Cannot update twitter_data table - tweet_id has NULL values';
        END IF;
    END IF;
    
    -- chart_metadata table: Use composite key (symbol, period, interval, theme)
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'chart_metadata' AND column_name = 'id') THEN
        IF (SELECT COUNT(*) FROM chart_metadata WHERE symbol IS NULL OR period IS NULL OR interval IS NULL OR theme IS NULL) = 0 THEN
            ALTER TABLE chart_metadata DROP CONSTRAINT IF EXISTS chart_metadata_pkey;
            ALTER TABLE chart_metadata DROP COLUMN id;
            ALTER TABLE chart_metadata ADD CONSTRAINT chart_metadata_pkey PRIMARY KEY (symbol, period, interval, theme);
            RAISE NOTICE '✅ Updated chart_metadata table to use composite natural key';
        ELSE
            RAISE NOTICE '⚠️ Cannot update chart_metadata table - composite key has NULL values';
        END IF;
    END IF;
    
    -- discord_processing_log table: Use composite key (message_id, channel)
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'discord_processing_log' AND column_name = 'id') THEN
        IF (SELECT COUNT(*) FROM discord_processing_log WHERE message_id IS NULL OR channel IS NULL) = 0 THEN
            ALTER TABLE discord_processing_log DROP CONSTRAINT IF EXISTS discord_processing_log_pkey;
            ALTER TABLE discord_processing_log DROP COLUMN id;
            ALTER TABLE discord_processing_log ADD CONSTRAINT discord_processing_log_pkey PRIMARY KEY (message_id, channel);
            RAISE NOTICE '✅ Updated discord_processing_log table to use composite natural key';
        ELSE
            RAISE NOTICE '⚠️ Cannot update discord_processing_log table - composite key has NULL values';
        END IF;
    END IF;
    
    RAISE NOTICE 'Completed natural key implementation for all applicable tables';
END $$;

-- ==============================================
-- Phase 2: Keep Appropriate Tables with ID columns
-- ==============================================

DO $$ BEGIN
    RAISE NOTICE 'Note: The following tables keep their ID columns as they need auto-increment behavior:';
    RAISE NOTICE '• accounts - uses auto-increment for new account creation';
    RAISE NOTICE '• symbols - uses auto-increment as there is no reliable natural key';
    RAISE NOTICE '• stock_charts - uses auto-increment for chart storage efficiency';
    RAISE NOTICE '• schema_migrations - uses version as primary key (no ID column needed)';
END $$;