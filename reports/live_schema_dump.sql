--
-- Live Database Schema Dump
-- Generated: September 23, 2025
-- Source: Supabase PostgreSQL public schema
-- Total Tables: 16
--

-- account_balances
CREATE TABLE IF NOT EXISTS "public"."account_balances" (
    "account_id" text NOT NULL,
    "currency_code" text NOT NULL,
    "currency_name" text,
    "currency_id" text,
    "cash" real,
    "buying_power" real,
    "snapshot_date" text NOT NULL,
    "sync_timestamp" text NOT NULL
);

-- accounts
CREATE TABLE IF NOT EXISTS "public"."accounts" (
    "id" text NOT NULL,
    "brokerage_authorization" text,
    "portfolio_group" text,
    "name" text,
    "number" text,
    "institution_name" text,
    "last_successful_sync" text,
    "total_equity" real,
    "sync_timestamp" text NOT NULL
);

-- chart_metadata
CREATE TABLE IF NOT EXISTS "public"."chart_metadata" (
    "symbol" text NOT NULL,
    "period" text NOT NULL,
    "interval" text NOT NULL,
    "theme" text NOT NULL,
    "file_path" text NOT NULL,
    "trade_count" integer DEFAULT 0,
    "min_trade_size" real DEFAULT 0.0,
    "created_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);

-- daily_prices
CREATE TABLE IF NOT EXISTS "public"."daily_prices" (
    "symbol" text NOT NULL,
    "date" text NOT NULL,
    "open" real,
    "high" real,
    "low" real,
    "close" real,
    "volume" integer,
    "dividends" real,
    "stock_splits" real
);

-- discord_market_clean
CREATE TABLE IF NOT EXISTS "public"."discord_market_clean" (
    "message_id" text NOT NULL,
    "author" text NOT NULL,
    "content" text NOT NULL,
    "sentiment" real,
    "cleaned_content" text,
    "timestamp" text NOT NULL,
    "processed_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);

-- discord_messages
CREATE TABLE IF NOT EXISTS "public"."discord_messages" (
    "message_id" text NOT NULL,
    "author" text NOT NULL,
    "content" text NOT NULL,
    "channel" text NOT NULL,
    "timestamp" text NOT NULL,
    "created_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "user_id" text DEFAULT 'default_user'::text,
    "num_chars" integer,
    "num_words" integer,
    "tickers_detected" text,
    "tweet_urls" text,
    "sentiment_score" numeric(5,4),
    "author_id" bigint,
    "is_reply" boolean DEFAULT false,
    "reply_to_id" bigint,
    "mentions" text
);

-- discord_processing_log
CREATE TABLE IF NOT EXISTS "public"."discord_processing_log" (
    "message_id" text NOT NULL,
    "channel" text NOT NULL,
    "processed_date" text NOT NULL,
    "processed_file" text,
    "created_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);

-- discord_trading_clean
CREATE TABLE IF NOT EXISTS "public"."discord_trading_clean" (
    "message_id" text NOT NULL,
    "author" text NOT NULL,
    "content" text NOT NULL,
    "sentiment" real,
    "cleaned_content" text,
    "stock_mentions" text,
    "timestamp" text NOT NULL,
    "processed_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);

-- orders
CREATE TABLE IF NOT EXISTS "public"."orders" (
    "brokerage_order_id" text NOT NULL,
    "account_id" text,
    "status" text NOT NULL,
    "action" text NOT NULL,
    "symbol" text NOT NULL,
    "total_quantity" numeric(18,6),
    "open_quantity" numeric(18,6) DEFAULT 0,
    "canceled_quantity" numeric(18,6) DEFAULT 0,
    "filled_quantity" numeric(18,6),
    "execution_price" numeric(18,6),
    "limit_price" numeric(18,6),
    "stop_price" numeric(18,6),
    "order_type" text,
    "time_in_force" text,
    "time_placed" timestamp with time zone,
    "time_updated" timestamp with time zone,
    "time_executed" timestamp with time zone,
    "expiry_date" date,
    "child_brokerage_order_ids" jsonb,
    "created_at" timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    "updated_at" timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    "user_id" text DEFAULT 'default_user'::text,
    "option_ticker" text,
    "option_expiry" date,
    "option_strike" numeric(10,2),
    "option_right" text,
    "diary" text,
    "parent_brokerage_order_id" text,
    "state" text,
    "user_secret" text,
    "sync_timestamp" text DEFAULT CURRENT_TIMESTAMP,
    "quote_currency_code" text
);

-- positions
CREATE TABLE IF NOT EXISTS "public"."positions" (
    "symbol" text NOT NULL,
    "symbol_id" text,
    "symbol_description" text,
    "quantity" numeric,
    "price" real,
    "equity" real,
    "average_buy_price" real,
    "open_pnl" real,
    "asset_type" text,
    "currency" text,
    "logo_url" text,
    "exchange_code" text,
    "exchange_name" text,
    "mic_code" text,
    "figi_code" text,
    "is_quotable" boolean DEFAULT true,
    "is_tradable" boolean DEFAULT true,
    "account_id" text NOT NULL DEFAULT 'default_account'::text,
    "sync_timestamp" text NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "created_at" timestamp with time zone DEFAULT CURRENT_TIMESTAMP
);

-- processing_status
CREATE TABLE IF NOT EXISTS "public"."processing_status" (
    "message_id" text NOT NULL,
    "channel" text NOT NULL,
    "processed_for_cleaning" boolean DEFAULT false,
    "processed_for_twitter" boolean DEFAULT false,
    "updated_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);

-- realtime_prices
CREATE TABLE IF NOT EXISTS "public"."realtime_prices" (
    "symbol" text NOT NULL,
    "timestamp" text NOT NULL,
    "price" real,
    "previous_close" real,
    "abs_change" real,
    "percent_change" real
);

-- schema_migrations
CREATE TABLE IF NOT EXISTS "public"."schema_migrations" (
    "version" text NOT NULL,
    "applied_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "description" text
);

-- stock_metrics
CREATE TABLE IF NOT EXISTS "public"."stock_metrics" (
    "symbol" text NOT NULL,
    "date" text NOT NULL,
    "pe_ratio" real,
    "market_cap" real,
    "dividend_yield" real,
    "fifty_day_avg" real,
    "two_hundred_day_avg" real
);

-- symbols
CREATE TABLE IF NOT EXISTS "public"."symbols" (
    "id" text NOT NULL,
    "ticker" text,
    "description" text,
    "asset_type" text,
    "type_code" text,
    "exchange_code" text,
    "exchange_name" text,
    "exchange_mic" text,
    "figi_code" text,
    "raw_symbol" text,
    "logo_url" text,
    "base_currency_code" text,
    "is_supported" boolean DEFAULT true,
    "is_quotable" boolean DEFAULT true,
    "is_tradable" boolean DEFAULT true,
    "created_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "updated_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "timezone" text,
    "market_open_time" time without time zone,
    "market_close_time" time without time zone
);

-- twitter_data
CREATE TABLE IF NOT EXISTS "public"."twitter_data" (
    "message_id" text NOT NULL,
    "discord_date" text NOT NULL,
    "tweet_date" text,
    "content" text NOT NULL,
    "stock_tags" text,
    "author" text NOT NULL,
    "channel" text NOT NULL,
    "created_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "tweet_id" text NOT NULL,
    "discord_message_id" text,
    "discord_sent_date" text,
    "tweet_created_date" text,
    "tweet_content" text,
    "author_username" text,
    "author_name" text,
    "retweet_count" integer DEFAULT 0,
    "like_count" integer DEFAULT 0,
    "reply_count" integer DEFAULT 0,
    "quote_count" integer DEFAULT 0,
    "source_url" text,
    "retrieved_at" text
);

-- PRIMARY KEYS (from live database analysis)
-- Note: These would be added by ALTER TABLE statements in actual deployment

-- Composite Primary Keys:
-- account_balances: (account_id, currency_code, snapshot_date)
-- chart_metadata: (symbol, period, interval, theme)  
-- daily_prices: (symbol, date)
-- discord_processing_log: (message_id, channel)
-- positions: (symbol, account_id)
-- realtime_prices: (symbol, timestamp)
-- stock_metrics: (date, symbol)  -- NOTE: order is (date, symbol)

-- Single Primary Keys:
-- accounts: (id)
-- discord_market_clean: (message_id)
-- discord_messages: (message_id)
-- discord_trading_clean: (message_id)
-- orders: (brokerage_order_id)
-- processing_status: (message_id)
-- schema_migrations: (version)
-- symbols: (id)
-- twitter_data: (tweet_id)

-- Check constraints on orders table:
-- status: 'PENDING', 'EXECUTED', 'CANCELED', 'REJECTED', 'EXPIRED', 'FILLED', 'PARTIAL'
-- action: 'BUY', 'SELL', 'BUY_OPEN', 'SELL_CLOSE', 'BUY_TO_COVER', 'SELL_SHORT'