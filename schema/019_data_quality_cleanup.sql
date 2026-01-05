--
-- Migration: 019 Data Quality Cleanup
-- Date: 2025-10-03  
-- Purpose: Fix data quality issues in orders and positions tables
--
-- Issues Addressed:
-- 1. Orders: Fix child_brokerage_order_ids empty object -> empty array
-- 2. Orders: Drop unused optional fields (100% NULL)
-- 3. Positions: Change REAL to NUMERIC for precision
-- 4. Positions: Drop redundant boolean fields (always true)

BEGIN;

-- =============================================================================
-- BACKUP EXISTING DATA
-- =============================================================================

-- Create backup tables
CREATE TABLE IF NOT EXISTS "public"."orders_backup_019" AS 
SELECT * FROM "public"."orders";

CREATE TABLE IF NOT EXISTS "public"."positions_backup_019" AS 
SELECT * FROM "public"."positions";

-- =============================================================================
-- ORDERS TABLE FIXES
-- =============================================================================

-- Fix child_brokerage_order_ids: {} -> []
UPDATE "public"."orders" 
SET child_brokerage_order_ids = '[]'::jsonb 
WHERE child_brokerage_order_ids = '{}'::jsonb;

-- Drop unused optional columns that are 100% NULL
ALTER TABLE "public"."orders" DROP COLUMN IF EXISTS "state";
ALTER TABLE "public"."orders" DROP COLUMN IF EXISTS "user_secret"; 
ALTER TABLE "public"."orders" DROP COLUMN IF EXISTS "parent_brokerage_order_id";
ALTER TABLE "public"."orders" DROP COLUMN IF EXISTS "quote_currency_code";
ALTER TABLE "public"."orders" DROP COLUMN IF EXISTS "diary";

-- =============================================================================
-- POSITIONS TABLE FIXES  
-- =============================================================================

-- Change numeric fields from REAL to NUMERIC for better precision
ALTER TABLE "public"."positions" 
  ALTER COLUMN "quantity" TYPE NUMERIC(15,4),
  ALTER COLUMN "price" TYPE NUMERIC(12,4),
  ALTER COLUMN "equity" TYPE NUMERIC(15,4),
  ALTER COLUMN "average_buy_price" TYPE NUMERIC(12,4),
  ALTER COLUMN "open_pnl" TYPE NUMERIC(15,4);

-- Drop redundant boolean columns (always true)
ALTER TABLE "public"."positions" DROP COLUMN IF EXISTS "is_quotable";
ALTER TABLE "public"."positions" DROP COLUMN IF EXISTS "is_tradable";

-- =============================================================================
-- UPDATE COMMENTS
-- =============================================================================

COMMENT ON COLUMN "public"."orders"."child_brokerage_order_ids" IS 
'Array of child order IDs stored as JSONB array (not object) - enables complex order relationships';

COMMENT ON COLUMN "public"."positions"."quantity" IS 
'Position quantity with high precision (NUMERIC 15,4) - supports fractional shares and large positions';

COMMENT ON COLUMN "public"."positions"."price" IS 
'Current price per share with high precision (NUMERIC 12,4) - supports high-value securities';

COMMENT ON COLUMN "public"."positions"."equity" IS 
'Total position value with high precision (NUMERIC 15,4) - calculated as quantity * price';

-- =============================================================================
-- VALIDATION QUERIES
-- =============================================================================

-- Verify child_brokerage_order_ids fix
DO $$
DECLARE
    empty_object_count INTEGER;
    empty_array_count INTEGER;
BEGIN
    SELECT COUNT(*) INTO empty_object_count 
    FROM "public"."orders" 
    WHERE child_brokerage_order_ids = '{}'::jsonb;
    
    SELECT COUNT(*) INTO empty_array_count 
    FROM "public"."orders" 
    WHERE child_brokerage_order_ids = '[]'::jsonb;
    
    IF empty_object_count > 0 THEN
        RAISE EXCEPTION 'Still have % orders with empty object {}', empty_object_count;
    END IF;
    
    RAISE NOTICE 'Fixed child_brokerage_order_ids: % orders now have empty array []', empty_array_count;
END $$;

-- Verify dropped columns
DO $$
BEGIN
    -- Check that dropped columns no longer exist
    IF EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'orders' 
        AND column_name IN ('state', 'user_secret', 'parent_brokerage_order_id', 'quote_currency_code', 'diary')
    ) THEN
        RAISE EXCEPTION 'Unused orders columns still exist after drop';
    END IF;
    
    IF EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'positions' 
        AND column_name IN ('is_quotable', 'is_tradable')
    ) THEN
        RAISE EXCEPTION 'Redundant positions boolean columns still exist after drop';
    END IF;
    
    RAISE NOTICE 'Successfully dropped unused columns';
END $$;

-- Verify numeric precision upgrade
DO $$
DECLARE
    numeric_columns INTEGER;
BEGIN
    SELECT COUNT(*) INTO numeric_columns
    FROM information_schema.columns 
    WHERE table_name = 'positions' 
    AND column_name IN ('quantity', 'price', 'equity', 'average_buy_price', 'open_pnl')
    AND data_type = 'numeric';
    
    IF numeric_columns < 5 THEN
        RAISE EXCEPTION 'Not all positions numeric fields converted to NUMERIC type';
    END IF;
    
    RAISE NOTICE 'Successfully converted % numeric columns to NUMERIC type', numeric_columns;
END $$;

-- =============================================================================
-- RECORD MIGRATION
-- =============================================================================

INSERT INTO "public"."schema_migrations" ("version", "description") 
VALUES ('019', 'Data quality cleanup - fixed child_brokerage_order_ids, dropped unused fields, improved numeric precision')
ON CONFLICT ("version") DO NOTHING;

COMMIT;

-- =============================================================================
-- POST-MIGRATION VERIFICATION QUERIES
-- =============================================================================

/*
-- 1. Verify child_brokerage_order_ids are properly formatted
SELECT 
  child_brokerage_order_ids,
  COUNT(*) as count
FROM orders 
GROUP BY child_brokerage_order_ids;
-- Expected: All should be [] or null, no {} objects

-- 2. Verify dropped columns are gone
SELECT column_name 
FROM information_schema.columns 
WHERE table_name = 'orders' 
AND column_name IN ('state', 'user_secret', 'parent_brokerage_order_id', 'quote_currency_code', 'diary');
-- Expected: No results

-- 3. Verify numeric precision
SELECT column_name, data_type, numeric_precision, numeric_scale
FROM information_schema.columns 
WHERE table_name = 'positions' 
AND column_name IN ('quantity', 'price', 'equity', 'average_buy_price', 'open_pnl');
-- Expected: All should be 'numeric' type with proper precision

-- 4. Verify redundant booleans are gone  
SELECT column_name 
FROM information_schema.columns 
WHERE table_name = 'positions' 
AND column_name IN ('is_quotable', 'is_tradable');
-- Expected: No results

-- 5. Check data integrity
SELECT COUNT(*) as total_orders FROM orders;
SELECT COUNT(*) as total_positions FROM positions;
-- Expected: Same counts as before migration (214 orders, 165 positions)
*/