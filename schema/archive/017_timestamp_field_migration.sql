--
-- Migration 017: Convert text timestamp fields to proper PostgreSQL date/timestamp types
-- Forward-only migration for data integrity and performance improvements
-- Created: 2025-09-23
--

-- positions.sync_timestamp: text -> timestamptz
ALTER TABLE public.positions ADD COLUMN sync_timestamp_new timestamptz;
UPDATE public.positions
SET sync_timestamp_new =
  CASE
    WHEN sync_timestamp IS NOT NULL THEN sync_timestamp::timestamptz
  END;
ALTER TABLE public.positions DROP COLUMN sync_timestamp;
ALTER TABLE public.positions RENAME COLUMN sync_timestamp_new TO sync_timestamp;

-- accounts.last_successful_sync: text -> timestamptz
ALTER TABLE public.accounts ADD COLUMN last_successful_sync_new timestamptz;
UPDATE public.accounts 
SET last_successful_sync_new = 
  CASE
    WHEN last_successful_sync IS NOT NULL THEN last_successful_sync::timestamptz
  END;
ALTER TABLE public.accounts DROP COLUMN last_successful_sync;
ALTER TABLE public.accounts RENAME COLUMN last_successful_sync_new TO last_successful_sync;

-- accounts.sync_timestamp: text -> timestamptz
ALTER TABLE public.accounts ADD COLUMN sync_timestamp_new timestamptz;
UPDATE public.accounts
SET sync_timestamp_new =
  CASE
    WHEN sync_timestamp IS NOT NULL THEN sync_timestamp::timestamptz
  END;
ALTER TABLE public.accounts DROP COLUMN sync_timestamp;
ALTER TABLE public.accounts RENAME COLUMN sync_timestamp_new TO sync_timestamp;

-- account_balances.snapshot_date: text -> date
ALTER TABLE public.account_balances ADD COLUMN snapshot_date_new date;
UPDATE public.account_balances
SET snapshot_date_new =
  CASE
    WHEN snapshot_date IS NOT NULL THEN snapshot_date::date
  END;
ALTER TABLE public.account_balances DROP COLUMN snapshot_date;
ALTER TABLE public.account_balances RENAME COLUMN snapshot_date_new TO snapshot_date;

-- account_balances.sync_timestamp: text -> timestamptz
ALTER TABLE public.account_balances ADD COLUMN sync_timestamp_new timestamptz;
UPDATE public.account_balances
SET sync_timestamp_new =
  CASE
    WHEN sync_timestamp IS NOT NULL THEN sync_timestamp::timestamptz
  END;
ALTER TABLE public.account_balances DROP COLUMN sync_timestamp;
ALTER TABLE public.account_balances RENAME COLUMN sync_timestamp_new TO sync_timestamp;

-- orders.sync_timestamp: text -> timestamptz (if exists)
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns 
    WHERE table_name = 'orders' 
    AND column_name = 'sync_timestamp' 
    AND data_type = 'text'
  ) THEN
    ALTER TABLE public.orders ADD COLUMN sync_timestamp_new timestamptz;
    UPDATE public.orders
    SET sync_timestamp_new =
      CASE
        WHEN sync_timestamp IS NOT NULL THEN sync_timestamp::timestamptz
      END;
    ALTER TABLE public.orders DROP COLUMN sync_timestamp;
    ALTER TABLE public.orders RENAME COLUMN sync_timestamp_new TO sync_timestamp;
  END IF;
END $$;

-- daily_prices.date: text -> date
ALTER TABLE public.daily_prices ADD COLUMN date_new date;
UPDATE public.daily_prices
SET date_new =
  CASE
    WHEN date IS NOT NULL THEN date::date
  END;
ALTER TABLE public.daily_prices DROP COLUMN date;
ALTER TABLE public.daily_prices RENAME COLUMN date_new TO date;

-- realtime_prices.timestamp: text -> timestamptz
ALTER TABLE public.realtime_prices ADD COLUMN timestamp_new timestamptz;
UPDATE public.realtime_prices
SET timestamp_new =
  CASE
    WHEN timestamp IS NOT NULL THEN timestamp::timestamptz
  END;
ALTER TABLE public.realtime_prices DROP COLUMN timestamp;
ALTER TABLE public.realtime_prices RENAME COLUMN timestamp_new TO timestamp;

-- stock_metrics.date: text -> date
ALTER TABLE public.stock_metrics ADD COLUMN date_new date;
UPDATE public.stock_metrics
SET date_new =
  CASE
    WHEN date IS NOT NULL THEN date::date
  END;
ALTER TABLE public.stock_metrics DROP COLUMN date;
ALTER TABLE public.stock_metrics RENAME COLUMN date_new TO date;

-- discord_processing_log.processed_date: text -> date
ALTER TABLE public.discord_processing_log ADD COLUMN processed_date_new date;
UPDATE public.discord_processing_log
SET processed_date_new =
  CASE
    WHEN processed_date IS NOT NULL THEN processed_date::date
  END;
ALTER TABLE public.discord_processing_log DROP COLUMN processed_date;
ALTER TABLE public.discord_processing_log RENAME COLUMN processed_date_new TO processed_date;

-- twitter_data timestamp fields: text -> timestamptz
ALTER TABLE public.twitter_data ADD COLUMN discord_date_new timestamptz;
UPDATE public.twitter_data
SET discord_date_new =
  CASE
    WHEN discord_date IS NOT NULL THEN discord_date::timestamptz
  END;
ALTER TABLE public.twitter_data DROP COLUMN discord_date;
ALTER TABLE public.twitter_data RENAME COLUMN discord_date_new TO discord_date;

-- twitter_data.tweet_date: text -> timestamptz (nullable)
ALTER TABLE public.twitter_data ADD COLUMN tweet_date_new timestamptz;
UPDATE public.twitter_data
SET tweet_date_new =
  CASE
    WHEN tweet_date IS NOT NULL THEN tweet_date::timestamptz
  END;
ALTER TABLE public.twitter_data DROP COLUMN tweet_date;
ALTER TABLE public.twitter_data RENAME COLUMN tweet_date_new TO tweet_date;

-- twitter_data.discord_sent_date: text -> timestamptz (nullable)
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns 
    WHERE table_name = 'twitter_data' 
    AND column_name = 'discord_sent_date'
  ) THEN
    ALTER TABLE public.twitter_data ADD COLUMN discord_sent_date_new timestamptz;
    UPDATE public.twitter_data
    SET discord_sent_date_new =
      CASE
        WHEN discord_sent_date IS NOT NULL THEN discord_sent_date::timestamptz
      END;
    ALTER TABLE public.twitter_data DROP COLUMN discord_sent_date;
    ALTER TABLE public.twitter_data RENAME COLUMN discord_sent_date_new TO discord_sent_date;
  END IF;
END $$;

-- twitter_data.tweet_created_date: text -> timestamptz (nullable)
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns 
    WHERE table_name = 'twitter_data' 
    AND column_name = 'tweet_created_date'
  ) THEN
    ALTER TABLE public.twitter_data ADD COLUMN tweet_created_date_new timestamptz;
    UPDATE public.twitter_data
    SET tweet_created_date_new =
      CASE
        WHEN tweet_created_date IS NOT NULL THEN tweet_created_date::timestamptz
      END;
    ALTER TABLE public.twitter_data DROP COLUMN tweet_created_date;
    ALTER TABLE public.twitter_data RENAME COLUMN tweet_created_date_new TO tweet_created_date;
  END IF;
END $$;

-- Recreate indexes for better performance on timestamp fields
CREATE INDEX IF NOT EXISTS idx_positions_sync_timestamp ON public.positions(sync_timestamp);
CREATE INDEX IF NOT EXISTS idx_accounts_sync_timestamp ON public.accounts(sync_timestamp);
CREATE INDEX IF NOT EXISTS idx_account_balances_snapshot_date ON public.account_balances(snapshot_date);
CREATE INDEX IF NOT EXISTS idx_account_balances_sync_timestamp ON public.account_balances(sync_timestamp);
CREATE INDEX IF NOT EXISTS idx_daily_prices_date ON public.daily_prices(date);
CREATE INDEX IF NOT EXISTS idx_realtime_prices_timestamp ON public.realtime_prices(timestamp);
CREATE INDEX IF NOT EXISTS idx_stock_metrics_date ON public.stock_metrics(date);
CREATE INDEX IF NOT EXISTS idx_discord_processing_log_processed_date ON public.discord_processing_log(processed_date);
CREATE INDEX IF NOT EXISTS idx_twitter_data_discord_date ON public.twitter_data(discord_date);

-- Update composite primary key constraints where needed
-- account_balances primary key includes snapshot_date
ALTER TABLE public.account_balances DROP CONSTRAINT IF EXISTS account_balances_pkey;
ALTER TABLE public.account_balances ADD CONSTRAINT account_balances_pkey 
  PRIMARY KEY (currency_code, snapshot_date, account_id);

-- daily_prices primary key includes date
ALTER TABLE public.daily_prices DROP CONSTRAINT IF EXISTS daily_prices_pkey;
ALTER TABLE public.daily_prices ADD CONSTRAINT daily_prices_pkey 
  PRIMARY KEY (date, symbol);

-- realtime_prices primary key includes timestamp
ALTER TABLE public.realtime_prices DROP CONSTRAINT IF EXISTS realtime_prices_pkey;
ALTER TABLE public.realtime_prices ADD CONSTRAINT realtime_prices_pkey 
  PRIMARY KEY (timestamp, symbol);

-- stock_metrics primary key includes date
ALTER TABLE public.stock_metrics DROP CONSTRAINT IF EXISTS stock_metrics_pkey;
ALTER TABLE public.stock_metrics ADD CONSTRAINT stock_metrics_pkey 
  PRIMARY KEY (date, symbol);

-- Add comments documenting the migration
COMMENT ON COLUMN public.positions.sync_timestamp IS 'Timestamp of last sync from SnapTrade API (migrated from text to timestamptz)';
COMMENT ON COLUMN public.accounts.sync_timestamp IS 'Timestamp of last sync from SnapTrade API (migrated from text to timestamptz)';
COMMENT ON COLUMN public.account_balances.snapshot_date IS 'Date of balance snapshot (migrated from text to date)';
COMMENT ON COLUMN public.account_balances.sync_timestamp IS 'Timestamp of balance sync (migrated from text to timestamptz)';
COMMENT ON COLUMN public.daily_prices.date IS 'Date of price data (migrated from text to date)';
COMMENT ON COLUMN public.realtime_prices.timestamp IS 'Timestamp of realtime price (migrated from text to timestamptz)';
COMMENT ON COLUMN public.stock_metrics.date IS 'Date of metrics calculation (migrated from text to date)';

-- Migration completed successfully
INSERT INTO public.schema_migrations (version, applied_at) 
VALUES ('017', NOW()) 
ON CONFLICT (version) DO NOTHING;