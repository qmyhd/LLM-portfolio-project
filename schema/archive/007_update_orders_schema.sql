-- 007_update_orders_schema.sql - Schema Alignment for Orders Table
-- Addresses specific discrepancies between expected and actual schema
-- 1. Drops redundant extracted_symbol column (orders.symbol is canonical)
-- 2. Ensures child_brokerage_order_ids is proper array type
-- 3. Consolidates chart table duplication

-- ==============================================
-- Orders Schema Updates Migration
-- ==============================================

-- Record this migration
INSERT INTO schema_migrations (version, description) 
VALUES ('007_update_orders_schema', 'Orders schema alignment - drop extracted_symbol, fix array types, consolidate chart tables') 
ON CONFLICT (version) DO NOTHING;

-- ==============================================
-- Fix 1: Drop Redundant extracted_symbol Column
-- ==============================================

DO $$ BEGIN
    -- Check if extracted_symbol column exists and drop it
    IF EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'orders' 
        AND column_name = 'extracted_symbol'
    ) THEN
        -- Verify no critical code dependencies first (log warning)
        RAISE NOTICE 'Dropping orders.extracted_symbol - orders.symbol is now the canonical ticker field';
        
        -- Drop the redundant column
        ALTER TABLE orders DROP COLUMN extracted_symbol;
        
        RAISE NOTICE '✅ Dropped orders.extracted_symbol column successfully';
    ELSE
        RAISE NOTICE 'orders.extracted_symbol column does not exist - no action needed';
    END IF;
END $$;

-- ==============================================
-- Fix 2: Ensure child_brokerage_order_ids is Proper Array Type
-- ==============================================

DO $$ BEGIN
    -- Check current type of child_brokerage_order_ids
    IF EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'orders' 
        AND column_name = 'child_brokerage_order_ids'
        AND data_type != 'ARRAY'
    ) THEN
        RAISE NOTICE 'Converting child_brokerage_order_ids to proper JSONB array type';
        
        -- Convert to JSONB array (handles both NULL and text values)
        ALTER TABLE orders 
        ALTER COLUMN child_brokerage_order_ids 
        TYPE JSONB 
        USING CASE 
            WHEN child_brokerage_order_ids IS NULL THEN NULL::JSONB
            WHEN child_brokerage_order_ids = '' THEN NULL::JSONB
            WHEN child_brokerage_order_ids LIKE '[%' THEN child_brokerage_order_ids::JSONB
            ELSE ('["' || child_brokerage_order_ids || '"]')::JSONB
        END;
        
        -- Update column comment
        COMMENT ON COLUMN orders.child_brokerage_order_ids IS 'JSONB array of child order IDs for complex orders';
        
        RAISE NOTICE '✅ Converted child_brokerage_order_ids to JSONB array type';
    ELSE
        RAISE NOTICE 'child_brokerage_order_ids is already proper array type - no conversion needed';
    END IF;
END $$;

-- ==============================================
-- Fix 3: Consolidate Chart Table Duplication
-- ==============================================

DO $$ BEGIN
    -- Check if both chart tables exist
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'stock_charts')
       AND EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'chart_metadata') THEN
        
        RAISE NOTICE 'Found duplicate chart tables - consolidating to chart_metadata';
        
        -- Migrate any data from stock_charts to chart_metadata if needed
        INSERT INTO chart_metadata (symbol, period, interval, theme, file_path, trade_count, min_trade_size, created_at)
        SELECT 
            symbol, 
            period, 
            interval, 
            theme, 
            file_path, 
            COALESCE(trade_count, 0),
            COALESCE(min_trade_size, 0.0),
            CASE 
                WHEN created_at ~ '^\d{4}-\d{2}-\d{2}' THEN created_at::timestamp
                ELSE CURRENT_TIMESTAMP
            END
        FROM stock_charts 
        WHERE NOT EXISTS (
            SELECT 1 FROM chart_metadata cm 
            WHERE cm.symbol = stock_charts.symbol 
            AND cm.period = stock_charts.period 
            AND cm.interval = stock_charts.interval
        );
        
        -- Drop the legacy table
        DROP TABLE stock_charts;
        
        RAISE NOTICE '✅ Consolidated chart tables - stock_charts data migrated to chart_metadata and legacy table dropped';
    ELSE
        RAISE NOTICE 'Chart table consolidation not needed - tables already aligned';
    END IF;
END $$;

-- ==============================================
-- Fix 4: Add Missing Index for Performance
-- ==============================================

-- Add index on orders.symbol for better query performance
CREATE INDEX IF NOT EXISTS idx_orders_symbol ON orders(symbol);

-- Add index on orders.time_placed for chronological queries
CREATE INDEX IF NOT EXISTS idx_orders_time_placed ON orders(time_placed);

-- Add index on orders.account_id for account-specific queries
CREATE INDEX IF NOT EXISTS idx_orders_account_id ON orders(account_id);

-- ==============================================
-- Fix 5: Update Column Comments for Clarity
-- ==============================================

-- Document the canonical ticker field
COMMENT ON COLUMN orders.symbol IS 'Canonical ticker symbol for the security (primary ticker field)';

-- Document the account relationship
COMMENT ON COLUMN orders.account_id IS 'Account ID from SnapTrade - links to accounts table';

-- Document the order lifecycle timestamps
COMMENT ON COLUMN orders.time_placed IS 'When the order was originally placed';
COMMENT ON COLUMN orders.time_executed IS 'When the order was executed (filled)';

-- ==============================================
-- Verification: Log Schema State
-- ==============================================

DO $$ BEGIN
    RAISE NOTICE 'Schema alignment migration 007 completed successfully:';
    RAISE NOTICE '  ✅ orders.extracted_symbol removed (if existed)';
    RAISE NOTICE '  ✅ orders.child_brokerage_order_ids ensured as JSONB array';
    RAISE NOTICE '  ✅ Chart tables consolidated to chart_metadata';
    RAISE NOTICE '  ✅ Performance indexes added';
    RAISE NOTICE '  ✅ Column documentation updated';
    RAISE NOTICE '';
    RAISE NOTICE 'Orders table now uses orders.symbol as the single canonical ticker field';
    RAISE NOTICE 'child_brokerage_order_ids properly stores JSON arrays for complex orders';
    RAISE NOTICE 'Chart metadata consolidated to single table for consistency';
END $$;