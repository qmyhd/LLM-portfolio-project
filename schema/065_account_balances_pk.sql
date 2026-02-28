-- =======================================================================
-- Migration 065: Add composite primary key to account_balances
-- =======================================================================
-- The collector writes with ON CONFLICT (currency_code, snapshot_date, account_id)
-- but the baseline DDL has no PK, leading to potential duplicate rows.
-- This migration deduplicates any existing rows and adds the PK constraint.

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'account_balances'::regclass AND contype = 'p'
    ) THEN
        -- Deduplicate: keep the physically last-inserted row (highest ctid) per group
        DELETE FROM account_balances a
        USING account_balances b
        WHERE a.ctid < b.ctid
          AND a.account_id = b.account_id
          AND a.currency_code = b.currency_code
          AND a.snapshot_date = b.snapshot_date;

        ALTER TABLE account_balances
            ADD CONSTRAINT account_balances_pkey
            PRIMARY KEY (account_id, currency_code, snapshot_date);
    END IF;
END $$;

-- Track migration (use full filename stem to match deploy_database.py ledger)
INSERT INTO schema_migrations (version, description)
VALUES ('065_account_balances_pk', 'Add PK to account_balances (account_id, currency_code, snapshot_date)')
ON CONFLICT (version) DO NOTHING;
