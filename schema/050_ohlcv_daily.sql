-- ============================================================================
-- Migration 050: Create OHLCV Daily Table for Databento Market Data
-- ============================================================================
-- Purpose: Store daily OHLCV bars from Databento for portfolio symbols
-- Source: Databento EQUS.MINI (historical) and EQUS.SUMMARY (current)
-- Schema: ohlcv-1d (daily bars)
-- ============================================================================

-- Create the OHLCV daily table
CREATE TABLE IF NOT EXISTS ohlcv_daily (
    symbol TEXT NOT NULL,
    date DATE NOT NULL,
    open NUMERIC(18,6),
    high NUMERIC(18,6),
    low NUMERIC(18,6),
    close NUMERIC(18,6),
    volume BIGINT,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),
    source TEXT DEFAULT 'databento',
    PRIMARY KEY (symbol, date)
);

-- Add comments for documentation
COMMENT ON TABLE ohlcv_daily IS 'Daily OHLCV bars from Databento for portfolio symbols. Dates are in America/New_York timezone.';
COMMENT ON COLUMN ohlcv_daily.symbol IS 'Ticker symbol (e.g., AAPL, MSFT)';
COMMENT ON COLUMN ohlcv_daily.date IS 'Market session date in Eastern Time (America/New_York)';
COMMENT ON COLUMN ohlcv_daily.open IS 'Opening price in USD';
COMMENT ON COLUMN ohlcv_daily.high IS 'High price in USD';
COMMENT ON COLUMN ohlcv_daily.low IS 'Low price in USD';
COMMENT ON COLUMN ohlcv_daily.close IS 'Closing price in USD';
COMMENT ON COLUMN ohlcv_daily.volume IS 'Trading volume in shares';
COMMENT ON COLUMN ohlcv_daily.source IS 'Data source: databento, yfinance, etc.';

-- Create indexes for common queries
CREATE INDEX IF NOT EXISTS idx_ohlcv_daily_symbol ON ohlcv_daily(symbol);
CREATE INDEX IF NOT EXISTS idx_ohlcv_daily_date ON ohlcv_daily(date DESC);
CREATE INDEX IF NOT EXISTS idx_ohlcv_daily_symbol_date ON ohlcv_daily(symbol, date DESC);

-- Enable RLS
ALTER TABLE ohlcv_daily ENABLE ROW LEVEL SECURITY;

-- RLS policy for authenticated access
CREATE POLICY "Allow authenticated read access on ohlcv_daily"
    ON ohlcv_daily
    FOR SELECT
    TO authenticated
    USING (true);

CREATE POLICY "Allow service role full access on ohlcv_daily"
    ON ohlcv_daily
    FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);

-- Function to update updated_at on row changes
CREATE OR REPLACE FUNCTION update_ohlcv_daily_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger to auto-update updated_at
DROP TRIGGER IF EXISTS trigger_ohlcv_daily_updated_at ON ohlcv_daily;
CREATE TRIGGER trigger_ohlcv_daily_updated_at
    BEFORE UPDATE ON ohlcv_daily
    FOR EACH ROW
    EXECUTE FUNCTION update_ohlcv_daily_updated_at();
