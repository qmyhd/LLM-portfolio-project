-- Migration 023: Add Event Contract Tables
-- Stores parsed trade confirmations and open positions from Robinhood event contract PDFs
-- Supports idempotent loading with ON CONFLICT clauses

-- Event Contract Trades table
-- Stores monthly trade confirmations from event contract statements
CREATE TABLE IF NOT EXISTS event_contract_trades (
    trade_id TEXT PRIMARY KEY,  -- MD5 hash of key fields for deduplication
    trade_date DATE,
    at TEXT,  -- Account type (SW, etc.)
    qty_long INTEGER DEFAULT 0,
    qty_short INTEGER DEFAULT 0,
    subtype TEXT,  -- YES/NO for binary outcomes
    symbol TEXT NOT NULL,
    contract_year_month TEXT,
    exchange TEXT,  -- Kalshi, etc.
    exp_date DATE,
    trade_price NUMERIC(18, 8),
    currency_code TEXT DEFAULT 'USD',
    trade_type TEXT,  -- Trade, Final Settlement, etc.
    description TEXT,
    source_file TEXT,  -- Original PDF filename
    page_number INTEGER,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ
);

-- Event Contract Positions table  
-- Stores open positions snapshot from event contract statements
CREATE TABLE IF NOT EXISTS event_contract_positions (
    position_id TEXT PRIMARY KEY,  -- MD5 hash of key fields for deduplication
    date_opened DATE,
    at TEXT,  -- Account type
    quantity_buy INTEGER DEFAULT 0,
    quantity_sell INTEGER DEFAULT 0,
    subtype TEXT,
    symbol TEXT NOT NULL,
    contract_year_month TEXT,
    exchange TEXT,
    exp_date DATE,
    trade_price NUMERIC(18, 8),
    currency TEXT DEFAULT 'USD',
    settlement_price NUMERIC(18, 8),
    trade_type TEXT,
    description TEXT,
    source_file TEXT,  -- Original PDF filename
    page_number INTEGER,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ
);

-- Indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_event_contract_trades_date 
    ON event_contract_trades(trade_date);
CREATE INDEX IF NOT EXISTS idx_event_contract_trades_symbol 
    ON event_contract_trades(symbol);
CREATE INDEX IF NOT EXISTS idx_event_contract_trades_source 
    ON event_contract_trades(source_file);

CREATE INDEX IF NOT EXISTS idx_event_contract_positions_date 
    ON event_contract_positions(date_opened);
CREATE INDEX IF NOT EXISTS idx_event_contract_positions_symbol 
    ON event_contract_positions(symbol);
CREATE INDEX IF NOT EXISTS idx_event_contract_positions_source 
    ON event_contract_positions(source_file);

-- Enable RLS
ALTER TABLE event_contract_trades ENABLE ROW LEVEL SECURITY;
ALTER TABLE event_contract_positions ENABLE ROW LEVEL SECURITY;

-- Service role bypass policies
CREATE POLICY service_role_event_contract_trades 
    ON event_contract_trades 
    FOR ALL 
    USING (true) 
    WITH CHECK (true);

CREATE POLICY service_role_event_contract_positions 
    ON event_contract_positions 
    FOR ALL 
    USING (true) 
    WITH CHECK (true);

-- Comments
COMMENT ON TABLE event_contract_trades IS 'Trade confirmations from Robinhood event contract PDFs';
COMMENT ON TABLE event_contract_positions IS 'Open positions from Robinhood event contract PDFs';
COMMENT ON COLUMN event_contract_trades.trade_id IS 'MD5 hash of key fields for idempotent loading';
COMMENT ON COLUMN event_contract_positions.position_id IS 'MD5 hash of key fields for idempotent loading';
