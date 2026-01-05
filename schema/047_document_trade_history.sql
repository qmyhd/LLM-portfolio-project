-- Migration 047: Document trade_history table
-- This table already exists in the database but was never documented in migrations.
-- Using CREATE TABLE IF NOT EXISTS for idempotency.

-- Create trade_history table (if not exists)
CREATE TABLE IF NOT EXISTS trade_history (
    id SERIAL PRIMARY KEY,
    symbol TEXT NOT NULL,
    account_id TEXT NOT NULL DEFAULT 'default_account',
    trade_type TEXT NOT NULL,
    trade_date TIMESTAMPTZ NOT NULL,
    quantity NUMERIC NOT NULL,
    execution_price NUMERIC NOT NULL,
    total_value NUMERIC,
    cost_basis NUMERIC,
    realized_pnl NUMERIC,
    realized_pnl_pct NUMERIC,
    position_qty_before NUMERIC,
    position_qty_after NUMERIC,
    holding_pct NUMERIC,
    portfolio_weight NUMERIC,
    brokerage_order_id TEXT UNIQUE,
    source TEXT DEFAULT 'snaptrade',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Create indexes if not exist
CREATE INDEX IF NOT EXISTS idx_trade_history_symbol ON trade_history(symbol);
CREATE INDEX IF NOT EXISTS idx_trade_history_account ON trade_history(account_id);
CREATE INDEX IF NOT EXISTS idx_trade_history_date ON trade_history(trade_date DESC);
CREATE INDEX IF NOT EXISTS idx_trade_history_type ON trade_history(trade_type);

-- Enable RLS (idempotent - safe to run multiple times)
ALTER TABLE trade_history ENABLE ROW LEVEL SECURITY;

-- Create RLS policies if not exist (using CREATE POLICY IF NOT EXISTS pattern)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies 
        WHERE tablename = 'trade_history' AND policyname = 'anon_read_trade_history'
    ) THEN
        CREATE POLICY anon_read_trade_history ON trade_history
            FOR SELECT TO anon USING (true);
    END IF;
    
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies 
        WHERE tablename = 'trade_history' AND policyname = 'authenticated_all_trade_history'
    ) THEN
        CREATE POLICY authenticated_all_trade_history ON trade_history
            FOR ALL TO authenticated USING (true) WITH CHECK (true);
    END IF;
END $$;

-- Record migration
INSERT INTO schema_migrations (version, description, applied_at)
VALUES ('047', 'Document trade_history table', NOW())
ON CONFLICT (version) DO NOTHING;
