-- schema/067_analysis_cache.sql
-- Analysis cache tables for multi-agent stock analysis system

-- Cache for per-stock analysis results
CREATE TABLE IF NOT EXISTS stock_analysis_cache (
    ticker TEXT NOT NULL,
    analysis_type TEXT NOT NULL DEFAULT 'full',
    result JSONB NOT NULL,
    agent_signals JSONB NOT NULL,
    model_used TEXT NOT NULL,
    data_sources TEXT[] NOT NULL,
    computed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (ticker, analysis_type)
);

CREATE INDEX IF NOT EXISTS idx_analysis_cache_expires
    ON stock_analysis_cache (expires_at);

-- Cache for portfolio-wide risk analysis
CREATE TABLE IF NOT EXISTS portfolio_risk_cache (
    portfolio_id TEXT NOT NULL DEFAULT 'default',
    result JSONB NOT NULL,
    computed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (portfolio_id)
);

-- Enable RLS (required by project convention)
ALTER TABLE stock_analysis_cache ENABLE ROW LEVEL SECURITY;
ALTER TABLE portfolio_risk_cache ENABLE ROW LEVEL SECURITY;
