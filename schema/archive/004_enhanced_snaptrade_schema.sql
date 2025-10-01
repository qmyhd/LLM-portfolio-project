-- 004_enhanced_snaptrade_schema.sql - Enhanced SnapTrade API Schema Alignment
-- Adds missing fields for comprehensive SnapTrade API support with proper nested structure handling
-- Implements enhanced symbol extraction, JSONB storage, and option trading support

-- ==============================================
-- Enhanced SnapTrade Schema Migration
-- ==============================================

-- Record this migration
INSERT INTO schema_migrations (version, description) 
VALUES ('004_enhanced_snaptrade_schema', 'Enhanced SnapTrade API schema alignment with nested structure support') 
ON CONFLICT (version) DO NOTHING;

-- ==============================================
-- Enhance Positions Table
-- ==============================================

-- Add missing fields to positions table for comprehensive SnapTrade API support
DO $$ BEGIN
    -- Add symbol_id field for SnapTrade symbol UUID
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'positions' AND column_name = 'symbol_id') THEN
        ALTER TABLE positions ADD COLUMN symbol_id TEXT;
        RAISE NOTICE 'Added symbol_id field to positions table';
    END IF;

    -- Add exchange information fields
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'positions' AND column_name = 'exchange_code') THEN
        ALTER TABLE positions ADD COLUMN exchange_code TEXT;
        RAISE NOTICE 'Added exchange_code field to positions table';
    END IF;

    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'positions' AND column_name = 'exchange_name') THEN
        ALTER TABLE positions ADD COLUMN exchange_name TEXT;
        RAISE NOTICE 'Added exchange_name field to positions table';
    END IF;

    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'positions' AND column_name = 'mic_code') THEN
        ALTER TABLE positions ADD COLUMN mic_code TEXT;
        RAISE NOTICE 'Added mic_code field to positions table';
    END IF;

    -- Add FIGI code field
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'positions' AND column_name = 'figi_code') THEN
        ALTER TABLE positions ADD COLUMN figi_code TEXT;
        RAISE NOTICE 'Added figi_code field to positions table';
    END IF;

    -- Add trading status fields
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'positions' AND column_name = 'is_quotable') THEN
        ALTER TABLE positions ADD COLUMN is_quotable BOOLEAN DEFAULT TRUE;
        RAISE NOTICE 'Added is_quotable field to positions table';
    END IF;

    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'positions' AND column_name = 'is_tradable') THEN
        ALTER TABLE positions ADD COLUMN is_tradable BOOLEAN DEFAULT TRUE;
        RAISE NOTICE 'Added is_tradable field to positions table';
    END IF;

    -- Add updated_at timestamp
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'positions' AND column_name = 'updated_at') THEN
        ALTER TABLE positions ADD COLUMN updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;
        RAISE NOTICE 'Added updated_at field to positions table';
    END IF;
END $$;

-- ==============================================
-- Enhance Orders Table
-- ==============================================

-- Enhance orders table for better SnapTrade API support
DO $$ BEGIN
    -- Convert universal_symbol from TEXT to JSONB for proper object storage
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'orders' AND column_name = 'universal_symbol' AND data_type = 'text') THEN
        -- Create new JSONB column
        ALTER TABLE orders ADD COLUMN universal_symbol_new JSONB;
        
        -- Migrate existing data (attempt to parse as JSON, fallback to null)
        UPDATE orders SET universal_symbol_new = 
            CASE 
                WHEN universal_symbol IS NOT NULL AND universal_symbol != '' 
                THEN universal_symbol::JSONB 
                ELSE NULL 
            END;
        
        -- Drop old column and rename new one
        ALTER TABLE orders DROP COLUMN universal_symbol;
        ALTER TABLE orders RENAME COLUMN universal_symbol_new TO universal_symbol;
        
        RAISE NOTICE 'Converted universal_symbol from TEXT to JSONB';
    END IF;

    -- Convert quote_universal_symbol to JSONB if it exists as TEXT
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'orders' AND column_name = 'quote_universal_symbol' AND data_type = 'text') THEN
        ALTER TABLE orders ADD COLUMN quote_universal_symbol_new JSONB;
        UPDATE orders SET quote_universal_symbol_new = 
            CASE 
                WHEN quote_universal_symbol IS NOT NULL AND quote_universal_symbol != '' 
                THEN quote_universal_symbol::JSONB 
                ELSE NULL 
            END;
        ALTER TABLE orders DROP COLUMN quote_universal_symbol;
        ALTER TABLE orders RENAME COLUMN quote_universal_symbol_new TO quote_universal_symbol;
        RAISE NOTICE 'Converted quote_universal_symbol from TEXT to JSONB';
    END IF;

    -- Convert quote_currency to JSONB if it exists as TEXT
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'orders' AND column_name = 'quote_currency' AND data_type = 'text') THEN
        ALTER TABLE orders ADD COLUMN quote_currency_new JSONB;
        UPDATE orders SET quote_currency_new = 
            CASE 
                WHEN quote_currency IS NOT NULL AND quote_currency != '' 
                THEN quote_currency::JSONB 
                ELSE NULL 
            END;
        ALTER TABLE orders DROP COLUMN quote_currency;
        ALTER TABLE orders RENAME COLUMN quote_currency_new TO quote_currency;
        RAISE NOTICE 'Converted quote_currency from TEXT to JSONB';
    END IF;

    -- Convert option_symbol to JSONB if it exists as TEXT
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'orders' AND column_name = 'option_symbol' AND data_type = 'text') THEN
        ALTER TABLE orders ADD COLUMN option_symbol_new JSONB;
        UPDATE orders SET option_symbol_new = 
            CASE 
                WHEN option_symbol IS NOT NULL AND option_symbol != '' 
                THEN option_symbol::JSONB 
                ELSE NULL 
            END;
        ALTER TABLE orders DROP COLUMN option_symbol;
        ALTER TABLE orders RENAME COLUMN option_symbol_new TO option_symbol;
        RAISE NOTICE 'Converted option_symbol from TEXT to JSONB';
    END IF;

    -- Add option-specific fields for easier querying
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'orders' AND column_name = 'option_ticker') THEN
        ALTER TABLE orders ADD COLUMN option_ticker TEXT;
        RAISE NOTICE 'Added option_ticker field to orders table';
    END IF;

    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'orders' AND column_name = 'option_expiry') THEN
        ALTER TABLE orders ADD COLUMN option_expiry DATE;
        RAISE NOTICE 'Added option_expiry field to orders table';
    END IF;

    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'orders' AND column_name = 'option_strike') THEN
        ALTER TABLE orders ADD COLUMN option_strike DECIMAL(10,2);
        RAISE NOTICE 'Added option_strike field to orders table';
    END IF;

    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'orders' AND column_name = 'option_right') THEN
        ALTER TABLE orders ADD COLUMN option_right TEXT; -- 'CALL' or 'PUT'
        RAISE NOTICE 'Added option_right field to orders table';
    END IF;

    -- Convert child_brokerage_order_ids to proper array if it's currently TEXT
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'orders' AND column_name = 'child_brokerage_order_ids' AND data_type = 'text') THEN
        ALTER TABLE orders ADD COLUMN child_brokerage_order_ids_new TEXT[];
        UPDATE orders SET child_brokerage_order_ids_new = 
            CASE 
                WHEN child_brokerage_order_ids IS NOT NULL AND child_brokerage_order_ids != '' 
                THEN string_to_array(child_brokerage_order_ids, ',')
                ELSE NULL 
            END;
        ALTER TABLE orders DROP COLUMN child_brokerage_order_ids;
        ALTER TABLE orders RENAME COLUMN child_brokerage_order_ids_new TO child_brokerage_order_ids;
        RAISE NOTICE 'Converted child_brokerage_order_ids from TEXT to TEXT array';
    END IF;
END $$;

-- ==============================================
-- Enhance Symbols Table
-- ==============================================

-- Add trading hours and timezone information to symbols table
DO $$ BEGIN
    -- Add timezone field
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'symbols' AND column_name = 'timezone') THEN
        ALTER TABLE symbols ADD COLUMN timezone TEXT;
        RAISE NOTICE 'Added timezone field to symbols table';
    END IF;

    -- Add market trading hours
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'symbols' AND column_name = 'market_open_time') THEN
        ALTER TABLE symbols ADD COLUMN market_open_time TIME;
        RAISE NOTICE 'Added market_open_time field to symbols table';
    END IF;

    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'symbols' AND column_name = 'market_close_time') THEN
        ALTER TABLE symbols ADD COLUMN market_close_time TIME;
        RAISE NOTICE 'Added market_close_time field to symbols table';
    END IF;
END $$;

-- ==============================================
-- Create Indexes for New Fields
-- ==============================================

-- Indexes for positions table new fields
CREATE INDEX IF NOT EXISTS idx_positions_symbol_id ON positions(symbol_id);
CREATE INDEX IF NOT EXISTS idx_positions_exchange_code ON positions(exchange_code);
CREATE INDEX IF NOT EXISTS idx_positions_figi_code ON positions(figi_code);
CREATE INDEX IF NOT EXISTS idx_positions_updated_at ON positions(updated_at);

-- Indexes for orders table new fields
CREATE INDEX IF NOT EXISTS idx_orders_option_ticker ON orders(option_ticker);
CREATE INDEX IF NOT EXISTS idx_orders_option_expiry ON orders(option_expiry);
CREATE INDEX IF NOT EXISTS idx_orders_extracted_symbol ON orders(extracted_symbol);

-- JSONB indexes for complex object queries
CREATE INDEX IF NOT EXISTS idx_orders_universal_symbol_gin ON orders USING GIN (universal_symbol);
CREATE INDEX IF NOT EXISTS idx_orders_quote_universal_symbol_gin ON orders USING GIN (quote_universal_symbol);
CREATE INDEX IF NOT EXISTS idx_orders_option_symbol_gin ON orders USING GIN (option_symbol);

-- Indexes for symbols table new fields
CREATE INDEX IF NOT EXISTS idx_symbols_timezone ON symbols(timezone);

-- ==============================================
-- Update Constraints and Comments
-- ==============================================

-- Add helpful comments to document the enhanced schema
COMMENT ON COLUMN positions.symbol_id IS 'SnapTrade symbol UUID for API references';
COMMENT ON COLUMN positions.exchange_code IS 'Exchange code (NASDAQ, NYSE, etc.)';
COMMENT ON COLUMN positions.figi_code IS 'Financial Instrument Global Identifier';
COMMENT ON COLUMN positions.is_quotable IS 'Whether real-time quotes are available';
COMMENT ON COLUMN positions.is_tradable IS 'Whether the instrument can be traded';

COMMENT ON COLUMN orders.universal_symbol IS 'Complete SnapTrade symbol object as JSONB';
COMMENT ON COLUMN orders.quote_universal_symbol IS 'Quote symbol object as JSONB';
COMMENT ON COLUMN orders.option_symbol IS 'Option details object as JSONB';
COMMENT ON COLUMN orders.extracted_symbol IS 'Normalized ticker symbol for easy querying';
COMMENT ON COLUMN orders.option_ticker IS 'Underlying ticker for options (extracted from option_symbol)';
COMMENT ON COLUMN orders.option_expiry IS 'Option expiration date';
COMMENT ON COLUMN orders.option_strike IS 'Option strike price';
COMMENT ON COLUMN orders.option_right IS 'Option type: CALL or PUT';
COMMENT ON COLUMN orders.child_brokerage_order_ids IS 'Array of child order IDs for complex orders';

COMMENT ON COLUMN symbols.timezone IS 'Exchange timezone (America/New_York, etc.)';
COMMENT ON COLUMN symbols.market_open_time IS 'Market opening time in exchange timezone';
COMMENT ON COLUMN symbols.market_close_time IS 'Market closing time in exchange timezone';

-- Log completion
DO $$ BEGIN
    RAISE NOTICE 'Successfully enhanced SnapTrade schema with:';
    RAISE NOTICE '  • Enhanced positions table with symbol metadata and trading flags';
    RAISE NOTICE '  • Converted orders table complex fields to JSONB for proper object storage';
    RAISE NOTICE '  • Added option trading support with dedicated fields';
    RAISE NOTICE '  • Enhanced symbols table with trading hours and timezone info';
    RAISE NOTICE '  • Created optimized indexes for new fields and JSONB queries';
    RAISE NOTICE 'Schema now supports full SnapTrade API nested structure handling!';
END $$;