-- Migration: Add unique constraint on account_balances for ON CONFLICT upsert support
-- Date: 2025-12-04
-- Columns: (account_id, currency_code, snapshot_date)

-- First, remove any duplicate rows (keep latest sync_timestamp)
DELETE FROM account_balances a
USING account_balances b
WHERE a.account_id = b.account_id 
  AND a.currency_code = b.currency_code 
  AND COALESCE(a.snapshot_date, '1970-01-01') = COALESCE(b.snapshot_date, '1970-01-01')
  AND COALESCE(a.sync_timestamp, '1970-01-01'::timestamptz) < COALESCE(b.sync_timestamp, '1970-01-01'::timestamptz);

-- Add the unique constraint (required for ON CONFLICT to work)
ALTER TABLE account_balances 
ADD CONSTRAINT account_balances_account_currency_date_key 
UNIQUE (account_id, currency_code, snapshot_date);

-- Note: The ON CONFLICT clause in snaptrade_collector.py uses:
-- conflict_columns=["account_id", "currency_code", "snapshot_date"]
