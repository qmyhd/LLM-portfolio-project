-- Migration 059: Create activities table for SnapTrade account activities
--
-- Tracks account activities (buys, sells, dividends, fees, transfers, etc.)
-- separately from orders. The `id` column stores the SnapTrade activity ID
-- and serves as the primary key for idempotent upserts.
--
-- Date: 2026-02-09

-- ============================================================================
-- 1. CREATE TABLE
-- ============================================================================
CREATE TABLE IF NOT EXISTS "public"."activities" (
    "id"                    text        NOT NULL PRIMARY KEY,
    "account_id"            text        NOT NULL,
    "activity_type"         text,
    "trade_date"            timestamp with time zone,
    "settlement_date"       timestamp with time zone,
    "amount"                numeric,
    "price"                 numeric,
    "units"                 numeric,
    "symbol"                text,
    "description"           text,
    "currency"              text        DEFAULT 'USD',
    "fee"                   numeric     DEFAULT 0,
    "fx_rate"               numeric,
    "external_reference_id" text,
    "institution"           text,
    "option_type"           text,
    "sync_timestamp"        timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    "created_at"            timestamp with time zone DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================================
-- 2. INDEXES
-- ============================================================================
CREATE INDEX IF NOT EXISTS idx_activities_account_trade_date
    ON public.activities (account_id, trade_date DESC);

CREATE INDEX IF NOT EXISTS idx_activities_symbol
    ON public.activities (symbol);

CREATE INDEX IF NOT EXISTS idx_activities_trade_date
    ON public.activities (trade_date DESC);

CREATE INDEX IF NOT EXISTS idx_activities_activity_type
    ON public.activities (activity_type);

-- ============================================================================
-- 3. ROW LEVEL SECURITY
-- ============================================================================
ALTER TABLE public.activities ENABLE ROW LEVEL SECURITY;

-- anon: read-only
CREATE POLICY "activities_anon_read"
    ON public.activities FOR SELECT
    TO anon
    USING (true);

-- authenticated: read-only
CREATE POLICY "activities_authenticated_read"
    ON public.activities FOR SELECT
    TO authenticated
    USING (true);

-- service_role: full CRUD (backend pipelines and SnapTrade sync)
CREATE POLICY "activities_service_role_all"
    ON public.activities FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);

-- ============================================================================
-- 4. COMMENTS
-- ============================================================================
COMMENT ON TABLE public.activities IS 'SnapTrade account activities (buys, sells, dividends, fees, transfers, etc.)';
COMMENT ON COLUMN public.activities.id IS 'Unique activity ID from SnapTrade';
COMMENT ON COLUMN public.activities.activity_type IS 'Activity type: BUY, SELL, DIVIDEND, INTEREST, FEE, TRANSFER, etc.';
COMMENT ON COLUMN public.activities.trade_date IS 'When the activity/trade occurred';
COMMENT ON COLUMN public.activities.settlement_date IS 'When the activity settles';
COMMENT ON COLUMN public.activities.amount IS 'Total dollar amount of the activity';
COMMENT ON COLUMN public.activities.price IS 'Price per unit (for trades)';
COMMENT ON COLUMN public.activities.units IS 'Number of units/shares involved';
COMMENT ON COLUMN public.activities.symbol IS 'Ticker symbol (extracted from SnapTrade nested object)';
COMMENT ON COLUMN public.activities.external_reference_id IS 'Brokerage-assigned reference ID';
