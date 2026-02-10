-- Migration: 020_drop_positions_redundant_columns
-- Purpose: Remove is_quotable and is_tradable columns from positions table
-- Reason: These columns were always TRUE (redundant) and only needed in symbols table
-- Date: 2025-10-08
-- Impact: Positions table reduced from 20 to 18 columns

-- Drop the redundant boolean columns from positions table
-- These fields are maintained in the symbols table where they're actually used
ALTER TABLE IF EXISTS public.positions DROP COLUMN IF EXISTS is_quotable;
ALTER TABLE IF EXISTS public.positions DROP COLUMN IF EXISTS is_tradable;

-- Verification query (run after migration):
-- SELECT column_name, data_type 
-- FROM information_schema.columns 
-- WHERE table_name = 'positions' 
-- ORDER BY ordinal_position;
-- Expected: 18 columns (symbol, symbol_id, symbol_description, quantity, price, equity, 
--           average_buy_price, open_pnl, asset_type, currency, logo_url, exchange_code, 
--           exchange_name, mic_code, figi_code, account_id, created_at, sync_timestamp)
