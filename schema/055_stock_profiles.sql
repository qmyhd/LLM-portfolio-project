-- Migration 055: Stock Profile Tables
-- Purpose: Derived metrics per ticker for dashboard and analytics
-- Date: 2026-01-26
--
-- Tables created:
--   - stock_profile_current: One row per ticker with latest derived metrics
--   - stock_profile_history: Time-series of profile metrics (partitioned by month)
--   - stock_idea_link: View joining tickers to parsed ideas
--
-- Data sources:
--   - RDS ohlcv_daily: Price metrics (returns, volatility)
--   - positions/orders: Trading activity metrics
--   - discord_parsed_ideas: Sentiment and mention metrics
--
-- Note: ohlcv_daily is in RDS, so joins with Supabase tables will be done
--       via application-level aggregation, not SQL joins.

-- ============================================================================
-- 1. STOCK_PROFILE_CURRENT - One row per ticker, refreshed daily
-- ============================================================================

CREATE TABLE IF NOT EXISTS public.stock_profile_current (
    -- Primary key
    ticker VARCHAR(10) PRIMARY KEY,
    last_updated TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    -- ========== Price Metrics (from RDS ohlcv_daily) ==========
    latest_close_price NUMERIC(12,4),
    previous_close_price NUMERIC(12,4),
    daily_change_pct NUMERIC(8,4),
    
    -- Return metrics (computed from OHLCV)
    return_1w_pct NUMERIC(8,4),      -- 5 trading days
    return_1m_pct NUMERIC(8,4),      -- 21 trading days
    return_3m_pct NUMERIC(8,4),      -- 63 trading days
    return_1y_pct NUMERIC(8,4),      -- 252 trading days
    
    -- Volatility metrics (std dev of daily returns)
    volatility_30d NUMERIC(8,4),
    volatility_90d NUMERIC(8,4),
    
    -- 52-week range
    year_high NUMERIC(12,4),
    year_low NUMERIC(12,4),
    
    -- Volume metrics
    avg_volume_30d BIGINT,
    
    -- ========== Position Metrics (from positions/orders) ==========
    current_position_qty NUMERIC(12,4),
    current_position_value NUMERIC(14,2),
    avg_buy_price NUMERIC(12,4),
    unrealized_pnl NUMERIC(14,2),
    unrealized_pnl_pct NUMERIC(8,4),
    
    -- Trading activity
    total_orders_count INTEGER DEFAULT 0,
    buy_orders_count INTEGER DEFAULT 0,
    sell_orders_count INTEGER DEFAULT 0,
    avg_order_size NUMERIC(12,4),
    first_trade_date DATE,
    last_trade_date DATE,
    
    -- ========== Sentiment Metrics (from discord_parsed_ideas) ==========
    total_mention_count INTEGER DEFAULT 0,
    mention_count_30d INTEGER DEFAULT 0,
    mention_count_7d INTEGER DEFAULT 0,
    
    -- Sentiment scores (-1.0 to 1.0)
    avg_sentiment_score NUMERIC(5,4),
    
    -- Direction breakdown (percentages)
    bullish_mention_pct NUMERIC(5,2),
    bearish_mention_pct NUMERIC(5,2),
    neutral_mention_pct NUMERIC(5,2),
    
    -- Timing
    first_mentioned_at TIMESTAMPTZ,
    last_mentioned_at TIMESTAMPTZ,
    
    -- ========== Label Counts (from discord_parsed_ideas) ==========
    label_trade_execution_count INTEGER DEFAULT 0,
    label_trade_plan_count INTEGER DEFAULT 0,
    label_technical_analysis_count INTEGER DEFAULT 0,
    label_options_count INTEGER DEFAULT 0,
    label_catalyst_news_count INTEGER DEFAULT 0,
    
    -- ========== Metadata ==========
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_stock_profile_current_updated ON public.stock_profile_current(last_updated DESC);
CREATE INDEX IF NOT EXISTS idx_stock_profile_current_mentions ON public.stock_profile_current(mention_count_30d DESC);
CREATE INDEX IF NOT EXISTS idx_stock_profile_current_position ON public.stock_profile_current(current_position_qty DESC NULLS LAST);

-- ============================================================================
-- 2. STOCK_PROFILE_HISTORY - Time-series of profile metrics
-- ============================================================================

CREATE TABLE IF NOT EXISTS public.stock_profile_history (
    -- Composite primary key
    ticker VARCHAR(10) NOT NULL,
    as_of_date DATE NOT NULL,
    
    -- ========== Price Metrics Snapshot ==========
    close_price NUMERIC(12,4),
    daily_change_pct NUMERIC(8,4),
    return_1w_pct NUMERIC(8,4),
    return_1m_pct NUMERIC(8,4),
    return_3m_pct NUMERIC(8,4),
    return_1y_pct NUMERIC(8,4),
    volatility_30d NUMERIC(8,4),
    volatility_90d NUMERIC(8,4),
    year_high NUMERIC(12,4),
    year_low NUMERIC(12,4),
    avg_volume_30d BIGINT,
    
    -- ========== Position Metrics Snapshot ==========
    position_qty NUMERIC(12,4),
    position_value NUMERIC(14,2),
    avg_buy_price NUMERIC(12,4),
    unrealized_pnl NUMERIC(14,2),
    unrealized_pnl_pct NUMERIC(8,4),
    
    -- ========== Cumulative Metrics ==========
    total_orders_count INTEGER DEFAULT 0,
    total_mention_count INTEGER DEFAULT 0,
    mention_count_30d INTEGER DEFAULT 0,
    avg_sentiment_score NUMERIC(5,4),
    bullish_mention_pct NUMERIC(5,2),
    
    -- ========== Metadata ==========
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    -- Primary key constraint
    PRIMARY KEY (ticker, as_of_date)
);

-- Indexes for time-series queries
CREATE INDEX IF NOT EXISTS idx_stock_profile_history_ticker ON public.stock_profile_history(ticker, as_of_date DESC);
CREATE INDEX IF NOT EXISTS idx_stock_profile_history_date ON public.stock_profile_history(as_of_date DESC);

-- ============================================================================
-- 3. STOCK_IDEA_LINK - View linking tickers to parsed ideas
-- ============================================================================

-- Create as a materialized view for performance (can be refreshed on schedule)
-- Note: Using regular view first, can convert to materialized if performance needed

CREATE OR REPLACE VIEW public.stock_idea_link AS
SELECT 
    -- Ticker info
    dpi.primary_symbol AS ticker,
    COALESCE(dpi.symbols, ARRAY[]::text[]) AS all_symbols,
    
    -- Idea details
    dpi.id AS idea_id,
    dpi.message_id,
    dpi.idea_text,
    dpi.idea_summary,
    
    -- Author info (from discord_messages)
    dm.author,
    dm.channel AS source_channel,
    
    -- Semantic analysis
    dpi.direction,
    dpi.action,
    dpi.instrument,
    dpi.time_horizon,
    dpi.confidence,
    dpi.labels,
    dpi.levels,
    
    -- Timestamps
    dpi.source_created_at AS idea_date,
    dpi.created_at AS parsed_at,
    dm.created_at AS message_created_at
    
FROM public.discord_parsed_ideas dpi
LEFT JOIN public.discord_messages dm ON dpi.message_id = dm.message_id
WHERE dpi.primary_symbol IS NOT NULL
  AND dpi.primary_symbol != ''
ORDER BY dpi.source_created_at DESC;

-- Add comment
COMMENT ON VIEW public.stock_idea_link IS 'Links ticker symbols to their parsed trading ideas with author and sentiment context';

-- ============================================================================
-- 4. ROW LEVEL SECURITY
-- ============================================================================

ALTER TABLE public.stock_profile_current ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.stock_profile_history ENABLE ROW LEVEL SECURITY;

-- Read access for all (these are derived/public metrics)
CREATE POLICY "anon_read_stock_profile_current" ON public.stock_profile_current
    FOR SELECT TO anon USING (true);
CREATE POLICY "authenticated_read_stock_profile_current" ON public.stock_profile_current
    FOR SELECT TO authenticated USING (true);
CREATE POLICY "service_role_all_stock_profile_current" ON public.stock_profile_current
    FOR ALL TO service_role USING (true) WITH CHECK (true);

CREATE POLICY "anon_read_stock_profile_history" ON public.stock_profile_history
    FOR SELECT TO anon USING (true);
CREATE POLICY "authenticated_read_stock_profile_history" ON public.stock_profile_history
    FOR SELECT TO authenticated USING (true);
CREATE POLICY "service_role_all_stock_profile_history" ON public.stock_profile_history
    FOR ALL TO service_role USING (true) WITH CHECK (true);

-- ============================================================================
-- 5. COMMENTS
-- ============================================================================

COMMENT ON TABLE public.stock_profile_current IS 'Current derived metrics per ticker - refreshed daily from OHLCV, positions, and parsed ideas';
COMMENT ON TABLE public.stock_profile_history IS 'Historical time-series of stock profile metrics for trend analysis';

COMMENT ON COLUMN public.stock_profile_current.return_1w_pct IS '5 trading day return percentage';
COMMENT ON COLUMN public.stock_profile_current.volatility_30d IS '30-day annualized volatility (std dev of daily returns)';
COMMENT ON COLUMN public.stock_profile_current.avg_sentiment_score IS 'Average sentiment from parsed ideas (-1.0 to 1.0)';

-- ============================================================================
-- 6. RECORD MIGRATION
-- ============================================================================

INSERT INTO schema_migrations (version, description, applied_at)
VALUES ('055', 'Create stock_profile_current, stock_profile_history tables and stock_idea_link view', NOW())
ON CONFLICT (version) DO NOTHING;
