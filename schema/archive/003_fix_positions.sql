-- 003_fix_positions.sql - Fix positions table schema to match 001_base.sql specification
-- This migration drops the existing positions table and recreates it with the correct schema
-- to resolve inconsistencies between actual database and schema definition

-- ==============================================
-- Fix positions table schema inconsistency
-- ==============================================

-- Record this migration
INSERT INTO schema_migrations (version, description) 
VALUES ('003_fix_positions', 'Fix positions table schema to match 001_base.sql specification') 
ON CONFLICT (version) DO NOTHING;

-- Drop existing positions table (CASCADE to handle any foreign key dependencies)
DROP TABLE IF EXISTS positions CASCADE;

-- Recreate positions table with correct schema from 001_base.sql
CREATE TABLE positions (
    id SERIAL PRIMARY KEY,
    account_id TEXT,
    symbol TEXT NOT NULL,
    symbol_description TEXT,
    quantity REAL,
    price REAL,
    equity REAL,
    average_buy_price REAL,
    open_pnl REAL,
    asset_type TEXT,
    currency TEXT DEFAULT 'USD',
    logo_url TEXT,
    sync_timestamp TEXT NOT NULL,
    calculated_equity REAL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(account_id, symbol, sync_timestamp)
);

-- Create indexes as defined in 001_base.sql
CREATE INDEX IF NOT EXISTS idx_positions_symbol ON positions(symbol);
CREATE INDEX IF NOT EXISTS idx_positions_sync_timestamp ON positions(sync_timestamp);
CREATE INDEX IF NOT EXISTS idx_positions_account_id ON positions(account_id);

-- Log completion
DO $$ BEGIN
    RAISE NOTICE 'Successfully recreated positions table with correct schema';
    RAISE NOTICE 'Fields updated: user_id->account_id, type->asset_type, added symbol_description, open_pnl, logo_url';
    RAISE NOTICE 'Timestamp fields: updated_at->created_at';
END $$;