-- Migration: Create institutional_holdings table for SEC 13F data
-- Description: Stores institutional ownership data parsed from SEC XML filings
-- Date: 2025-12-06

CREATE TABLE IF NOT EXISTS institutional_holdings (
    id SERIAL PRIMARY KEY,
    filing_date DATE,
    manager_cik VARCHAR(10),
    manager_name VARCHAR(255),
    
    -- The Asset
    cusip VARCHAR(9) NOT NULL,
    ticker VARCHAR(10),
    company_name VARCHAR(255),
    
    -- The Position
    value_usd BIGINT,       -- Store as full integer, not x1000
    shares BIGINT,
    share_type VARCHAR(10), -- 'SH' or 'PRN'
    
    -- Metadata
    is_put BOOLEAN DEFAULT FALSE,
    is_call BOOLEAN DEFAULT FALSE,
    
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Create indexes for performance
CREATE INDEX IF NOT EXISTS idx_institutional_holdings_cusip ON institutional_holdings (cusip);
CREATE INDEX IF NOT EXISTS idx_institutional_holdings_manager ON institutional_holdings (manager_cik);
CREATE INDEX IF NOT EXISTS idx_institutional_holdings_ticker ON institutional_holdings (ticker);

-- Enable Row Level Security
ALTER TABLE institutional_holdings ENABLE ROW LEVEL SECURITY;

-- Create RLS Policies
-- 1. Allow read access to authenticated users
CREATE POLICY "Allow read access for authenticated users" ON institutional_holdings
    FOR SELECT
    TO authenticated
    USING (true);

-- 2. Allow full access to service role (for ETL scripts)
CREATE POLICY "Allow full access for service role" ON institutional_holdings
    FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);

-- Grant permissions
GRANT SELECT ON institutional_holdings TO authenticated;
GRANT ALL ON institutional_holdings TO service_role;
