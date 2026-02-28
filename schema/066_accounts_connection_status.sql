-- =======================================================================
-- Migration 066: Add connection status tracking to accounts
-- =======================================================================
-- Tracks brokerage connection health via SnapTrade webhook events
-- (CONNECTION_CONNECTED, CONNECTION_DISCONNECTED, CONNECTION_ERROR, CONNECTION_DELETED).

ALTER TABLE accounts ADD COLUMN IF NOT EXISTS connection_status text DEFAULT 'connected';
ALTER TABLE accounts ADD COLUMN IF NOT EXISTS connection_disabled_at timestamptz;
ALTER TABLE accounts ADD COLUMN IF NOT EXISTS connection_error_message text;
ALTER TABLE accounts ADD COLUMN IF NOT EXISTS brokerage_authorization_id text;

-- Validate connection_status values
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'accounts_connection_status_check'
    ) THEN
        ALTER TABLE accounts ADD CONSTRAINT accounts_connection_status_check
            CHECK (connection_status IN ('connected', 'disconnected', 'error', 'deleted'));
    END IF;
END $$;

-- Track migration (use full filename stem to match deploy_database.py ledger)
INSERT INTO schema_migrations (version, description)
VALUES ('066_accounts_connection_status', 'Add connection status columns to accounts')
ON CONFLICT (version) DO NOTHING;
