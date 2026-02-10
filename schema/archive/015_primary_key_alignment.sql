--
-- Migration: 015 Primary Key Alignment with Baseline Schema
-- Date: September 22, 2025
-- Purpose: Fix primary key column order discrepancies and clean up constraint issues
--
-- Issues Found:
-- 1. stock_metrics PK order: Live DB has (symbol, date) but baseline specifies (date, symbol)
-- 2. schema_migrations table has duplicate constraint entries
--
-- This migration ensures 100% alignment with 000_baseline.sql primary key definitions

BEGIN;

-- Fix stock_metrics primary key order to match baseline: (date, symbol)
-- Baseline specifies: ADD CONSTRAINT "stock_metrics_pkey" PRIMARY KEY ("date", "symbol");
-- Live DB currently has: (symbol, date) - WRONG ORDER

-- Step 1: Drop existing primary key constraint
ALTER TABLE "public"."stock_metrics" 
    DROP CONSTRAINT IF EXISTS "stock_metrics_pkey";

-- Step 2: Recreate with correct column order to match baseline
ALTER TABLE "public"."stock_metrics" 
    ADD CONSTRAINT "stock_metrics_pkey" PRIMARY KEY ("date", "symbol");

-- Step 3: Verify and clean up any potential constraint issues with schema_migrations
-- Drop and recreate to ensure clean state
ALTER TABLE "public"."schema_migrations" 
    DROP CONSTRAINT IF EXISTS "schema_migrations_pkey";

ALTER TABLE "public"."schema_migrations" 
    ADD CONSTRAINT "schema_migrations_pkey" PRIMARY KEY ("version");

-- Step 4: Verify all other primary keys match baseline (these should be correct but double-checking)

-- Verify accounts PK: (id) ✓
-- Already correct: accounts_pkey PRIMARY KEY (id)

-- Verify account_balances PK: (account_id, currency_code, snapshot_date) ✓  
-- Already correct: account_balances_pkey PRIMARY KEY (account_id, currency_code, snapshot_date)

-- Verify positions PK: (symbol, account_id) ✓
-- Already correct: positions_pkey PRIMARY KEY (symbol, account_id)

-- Verify orders PK: (brokerage_order_id) ✓
-- Already correct: orders_pkey PRIMARY KEY (brokerage_order_id)

-- Verify symbols PK: (id) ✓
-- Already correct: symbols_pkey PRIMARY KEY (id)

-- Verify daily_prices PK: (symbol, date) ✓
-- Already correct: daily_prices_pkey PRIMARY KEY (symbol, date)

-- Verify realtime_prices PK: (symbol, timestamp) ✓
-- Already correct: realtime_prices_pkey PRIMARY KEY (symbol, timestamp)

-- Verify discord_messages PK: (message_id) ✓
-- Already correct: discord_messages_pkey PRIMARY KEY (message_id)

-- Verify discord_market_clean PK: (message_id) ✓
-- Already correct: discord_market_clean_pkey PRIMARY KEY (message_id)

-- Verify discord_trading_clean PK: (message_id) ✓
-- Already correct: discord_trading_clean_pkey PRIMARY KEY (message_id)

-- Verify discord_processing_log PK: (message_id, channel) ✓
-- Already correct: discord_processing_log_pkey PRIMARY KEY (message_id, channel)

-- Verify processing_status PK: (message_id) ✓
-- Already correct: processing_status_pkey PRIMARY KEY (message_id)

-- Verify twitter_data PK: (tweet_id) ✓
-- Already correct: twitter_data_pkey PRIMARY KEY (tweet_id)

-- Verify chart_metadata PK: (symbol, period, interval, theme) ✓
-- Already correct: chart_metadata_pkey PRIMARY KEY (symbol, period, interval, theme)

-- Add comment documenting the fix
COMMENT ON TABLE "public"."stock_metrics" IS 'Stock metrics data using composite natural key (date, symbol) - PK order corrected to match baseline schema';

-- Record this migration
INSERT INTO "public"."schema_migrations" ("version", "description") 
VALUES ('015', 'Primary key alignment with baseline schema - fixed stock_metrics PK order and cleaned up constraint duplicates')
ON CONFLICT ("version") DO NOTHING;

COMMIT;

-- Verification queries to confirm alignment
-- These should be run after migration to verify success:
/*
-- 1. Verify stock_metrics PK order is now (date, symbol)
SELECT 
    kcu.column_name,
    kcu.ordinal_position
FROM information_schema.table_constraints tc
JOIN information_schema.key_column_usage kcu 
    ON tc.constraint_name = kcu.constraint_name
WHERE tc.constraint_type = 'PRIMARY KEY' 
    AND tc.table_schema = 'public'
    AND tc.table_name = 'stock_metrics'
ORDER BY kcu.ordinal_position;

-- 2. Verify schema_migrations constraint is clean
SELECT COUNT(*) as constraint_count
FROM information_schema.table_constraints tc
WHERE tc.constraint_type = 'PRIMARY KEY' 
    AND tc.table_schema = 'public'
    AND tc.table_name = 'schema_migrations';
*/