-- 006_symbols_ticker_unique.sql - Add unique constraint to symbols.ticker
-- Ensures ticker symbols are unique across the symbols table for canonical ticker management

-- ==============================================
-- Symbols Ticker Unique Constraint Migration
-- ==============================================

-- Record this migration
INSERT INTO schema_migrations (version, description) 
VALUES ('006_symbols_ticker_unique', 'Add unique constraint to symbols.ticker for canonical ticker management') 
ON CONFLICT (version) DO NOTHING;

-- ==============================================
-- Add Unique Constraint to symbols.ticker
-- ==============================================

DO $$ BEGIN
    -- Check if unique constraint already exists
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.table_constraints 
        WHERE table_name = 'symbols' 
        AND constraint_type = 'UNIQUE' 
        AND constraint_name = 'symbols_ticker_unique'
    ) THEN
        -- Remove duplicates before adding constraint (keep first occurrence)
        DELETE FROM symbols 
        WHERE id IN (
            SELECT id 
            FROM (
                SELECT id, 
                       ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY created_at ASC) as rn
                FROM symbols 
                WHERE ticker IS NOT NULL
            ) t 
            WHERE rn > 1
        );
        
        -- Add unique constraint on ticker
        ALTER TABLE symbols ADD CONSTRAINT symbols_ticker_unique UNIQUE (ticker);
        
        RAISE NOTICE 'Added unique constraint symbols_ticker_unique to symbols.ticker';
    ELSE
        RAISE NOTICE 'Unique constraint symbols_ticker_unique already exists on symbols.ticker';
    END IF;
END $$;

-- ==============================================
-- Add Index for Performance (if not exists)
-- ==============================================

-- Ensure ticker index exists for performance
CREATE UNIQUE INDEX IF NOT EXISTS idx_symbols_ticker_unique ON symbols(ticker);

-- Log completion
DO $$ BEGIN
    RAISE NOTICE 'Successfully ensured symbols.ticker unique constraint:';
    RAISE NOTICE '  ✅ Removed duplicate ticker entries (keeping oldest)';
    RAISE NOTICE '  ✅ Added unique constraint symbols_ticker_unique';
    RAISE NOTICE '  ✅ Added unique index idx_symbols_ticker_unique for performance';
    RAISE NOTICE 'Symbols table now enforces ticker uniqueness for canonical ticker management!';
END $$;