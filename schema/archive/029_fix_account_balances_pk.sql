-- Migration: Fix account_balances Primary Key
-- Description: Make snapshot_date NOT NULL and re-add Primary Key
-- Created: 2025-12-08

-- 1. Ensure no nulls in snapshot_date (shouldn't be any, but just in case)
UPDATE account_balances SET snapshot_date = CURRENT_DATE WHERE snapshot_date IS NULL;

-- 2. Make snapshot_date NOT NULL
ALTER TABLE account_balances ALTER COLUMN snapshot_date SET NOT NULL;

-- 3. Add Primary Key
-- Drop if exists just in case (though verify said it's missing)
ALTER TABLE account_balances DROP CONSTRAINT IF EXISTS account_balances_pkey;
ALTER TABLE account_balances ADD CONSTRAINT account_balances_pkey PRIMARY KEY (currency_code, snapshot_date, account_id);
