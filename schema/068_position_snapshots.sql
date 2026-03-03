-- =======================================================================
-- Migration 068: Position snapshots for historical P/L tracking
-- =======================================================================
-- Captures daily position state for accurate gain/loss calculations
-- on historical trades. Populated by nightly pipeline after SnapTrade sync.

CREATE TABLE IF NOT EXISTS public.position_snapshots (
    account_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    snapshot_date DATE NOT NULL,
    quantity NUMERIC(15,4),
    average_buy_price NUMERIC(12,4),
    current_price NUMERIC(12,4),
    equity NUMERIC(15,4),
    total_portfolio_value NUMERIC(15,4),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (account_id, symbol, snapshot_date)
);

CREATE INDEX IF NOT EXISTS idx_position_snapshots_symbol_date
    ON position_snapshots(symbol, snapshot_date DESC);

ALTER TABLE position_snapshots ENABLE ROW LEVEL SECURITY;

-- Track migration
INSERT INTO schema_migrations (version, description)
VALUES ('068_position_snapshots', 'Position snapshots for historical P/L tracking')
ON CONFLICT (version) DO NOTHING;
