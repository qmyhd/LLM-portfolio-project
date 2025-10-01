--
-- PostgreSQL database dump
-- Single Source of Truth (SSOT) Baseline Schema
-- Generated from Supabase public schema
-- Excludes auth and storage schemas
--

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: public; Type: SCHEMA; Schema: -; Owner: -
--

-- *not* creating schema, since initdb creates it

--
-- Set default privileges
--

ALTER DEFAULT PRIVILEGES FOR ROLE "service_role" IN SCHEMA "public" GRANT ALL ON SEQUENCES TO "anon";
ALTER DEFAULT PRIVILEGES FOR ROLE "service_role" IN SCHEMA "public" GRANT ALL ON SEQUENCES TO "authenticated";
ALTER DEFAULT PRIVILEGES FOR ROLE "service_role" IN SCHEMA "public" GRANT ALL ON SEQUENCES TO "service_role";
ALTER DEFAULT PRIVILEGES FOR ROLE "service_role" IN SCHEMA "public" GRANT ALL ON TABLES TO "anon";
ALTER DEFAULT PRIVILEGES FOR ROLE "service_role" IN SCHEMA "public" GRANT ALL ON TABLES TO "authenticated";
ALTER DEFAULT PRIVILEGES FOR ROLE "service_role" IN SCHEMA "public" GRANT ALL ON TABLES TO "service_role";

--
-- Core SnapTrade Tables
--

--
-- Name: accounts; Type: TABLE; Schema: public; Owner: -
--

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

--
-- Name: account_balances; Type: TABLE; Schema: public; Owner: -
--

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

--
-- Name: positions; Type: TABLE; Schema: public; Owner: -
--

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
    "sync_timestamp" text DEFAULT CURRENT_TIMESTAMP,
    "created_at" timestamp with time zone DEFAULT CURRENT_TIMESTAMP
);

--
-- Name: orders; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE IF NOT EXISTS "public"."orders" (
    "brokerage_order_id" text NOT NULL,
    "account_id" text,
    "status" text NOT NULL,
    "action" text NOT NULL,
    "symbol" text NOT NULL,
    "total_quantity" numeric,
    "open_quantity" numeric DEFAULT 0,
    "canceled_quantity" numeric DEFAULT 0,
    "filled_quantity" numeric,
    "execution_price" numeric,
    "limit_price" numeric,
    "stop_price" numeric,
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
    "option_strike" numeric,
    "option_right" text,
    "diary" text,
    "parent_brokerage_order_id" text,
    "state" text,
    "user_secret" text,
    "sync_timestamp" text DEFAULT CURRENT_TIMESTAMP,
    "quote_currency_code" text,
    CONSTRAINT "orders_status_check" CHECK (("status" = ANY (ARRAY['PENDING'::text, 'EXECUTED'::text, 'CANCELED'::text, 'REJECTED'::text, 'EXPIRED'::text, 'FILLED'::text, 'PARTIAL'::text]))),
    CONSTRAINT "orders_action_check" CHECK (("action" = ANY (ARRAY['BUY'::text, 'SELL'::text, 'BUY_OPEN'::text, 'SELL_CLOSE'::text, 'BUY_TO_COVER'::text, 'SELL_SHORT'::text])))
);

--
-- Name: symbols; Type: TABLE; Schema: public; Owner: -
--

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

--
-- Market Data Tables
--

--
-- Name: daily_prices; Type: TABLE; Schema: public; Owner: -
--

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

--
-- Name: realtime_prices; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE IF NOT EXISTS "public"."realtime_prices" (
    "symbol" text NOT NULL,
    "timestamp" text NOT NULL,
    "price" real,
    "previous_close" real,
    "abs_change" real,
    "percent_change" real
);

--
-- Name: stock_metrics; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE IF NOT EXISTS "public"."stock_metrics" (
    "symbol" text NOT NULL,
    "date" text NOT NULL,
    "pe_ratio" real,
    "market_cap" real,
    "dividend_yield" real,
    "fifty_day_avg" real,
    "two_hundred_day_avg" real
);

--
-- Discord Integration Tables
--

--
-- Name: discord_messages; Type: TABLE; Schema: public; Owner: -
--

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
    "sentiment_score" numeric,
    "author_id" bigint,
    "is_reply" boolean DEFAULT false,
    "reply_to_id" bigint,
    "mentions" text
);

--
-- Name: discord_market_clean; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE IF NOT EXISTS "public"."discord_market_clean" (
    "message_id" text NOT NULL,
    "author" text NOT NULL,
    "content" text NOT NULL,
    "sentiment" real,
    "cleaned_content" text,
    "timestamp" text NOT NULL,
    "processed_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);

--
-- Name: discord_trading_clean; Type: TABLE; Schema: public; Owner: -
--

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

--
-- Name: discord_processing_log; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE IF NOT EXISTS "public"."discord_processing_log" (
    "message_id" text NOT NULL,
    "channel" text NOT NULL,
    "processed_date" text NOT NULL,
    "processed_file" text,
    "created_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);

--
-- Name: processing_status; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE IF NOT EXISTS "public"."processing_status" (
    "message_id" text NOT NULL,
    "channel" text NOT NULL,
    "processed_for_cleaning" boolean DEFAULT false,
    "processed_for_twitter" boolean DEFAULT false,
    "updated_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);

--
-- Twitter Integration Tables
--

--
-- Name: twitter_data; Type: TABLE; Schema: public; Owner: -
--

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

--
-- Chart and Analysis Tables
--

--
-- Name: chart_metadata; Type: TABLE; Schema: public; Owner: -
--

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

--
-- Schema Management Tables
--

--
-- Name: schema_migrations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE IF NOT EXISTS "public"."schema_migrations" (
    "version" text NOT NULL,
    "applied_at" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    "description" text
);

--
-- Primary Key Constraints
--

ALTER TABLE ONLY "public"."accounts"
    ADD CONSTRAINT "accounts_pkey" PRIMARY KEY ("id");

ALTER TABLE ONLY "public"."account_balances"
    ADD CONSTRAINT "account_balances_pkey" PRIMARY KEY ("account_id", "currency_code", "snapshot_date");

ALTER TABLE ONLY "public"."positions"
    ADD CONSTRAINT "positions_pkey" PRIMARY KEY ("symbol", "account_id");

ALTER TABLE ONLY "public"."orders"
    ADD CONSTRAINT "orders_pkey" PRIMARY KEY ("brokerage_order_id");

ALTER TABLE ONLY "public"."symbols"
    ADD CONSTRAINT "symbols_pkey" PRIMARY KEY ("id");

ALTER TABLE ONLY "public"."daily_prices"
    ADD CONSTRAINT "daily_prices_pkey" PRIMARY KEY ("symbol", "date");

ALTER TABLE ONLY "public"."realtime_prices"
    ADD CONSTRAINT "realtime_prices_pkey" PRIMARY KEY ("symbol", "timestamp");

ALTER TABLE ONLY "public"."stock_metrics"
    ADD CONSTRAINT "stock_metrics_pkey" PRIMARY KEY ("date", "symbol");

ALTER TABLE ONLY "public"."discord_messages"
    ADD CONSTRAINT "discord_messages_pkey" PRIMARY KEY ("message_id");

ALTER TABLE ONLY "public"."discord_market_clean"
    ADD CONSTRAINT "discord_market_clean_pkey" PRIMARY KEY ("message_id");

ALTER TABLE ONLY "public"."discord_trading_clean"
    ADD CONSTRAINT "discord_trading_clean_pkey" PRIMARY KEY ("message_id");

ALTER TABLE ONLY "public"."discord_processing_log"
    ADD CONSTRAINT "discord_processing_log_pkey" PRIMARY KEY ("message_id", "channel");

ALTER TABLE ONLY "public"."processing_status"
    ADD CONSTRAINT "processing_status_pkey" PRIMARY KEY ("message_id");

ALTER TABLE ONLY "public"."twitter_data"
    ADD CONSTRAINT "twitter_data_pkey" PRIMARY KEY ("tweet_id");

ALTER TABLE ONLY "public"."chart_metadata"
    ADD CONSTRAINT "chart_metadata_pkey" PRIMARY KEY ("symbol", "period", "interval", "theme");

ALTER TABLE ONLY "public"."schema_migrations"
    ADD CONSTRAINT "schema_migrations_pkey" PRIMARY KEY ("version");

--
-- Unique Constraints
--

ALTER TABLE ONLY "public"."symbols"
    ADD CONSTRAINT "symbols_ticker_key" UNIQUE ("ticker");

ALTER TABLE ONLY "public"."discord_messages"
    ADD CONSTRAINT "discord_messages_message_id_key" UNIQUE ("message_id");

ALTER TABLE ONLY "public"."discord_market_clean"
    ADD CONSTRAINT "discord_market_clean_message_id_key" UNIQUE ("message_id");

ALTER TABLE ONLY "public"."discord_trading_clean"
    ADD CONSTRAINT "discord_trading_clean_message_id_key" UNIQUE ("message_id");

ALTER TABLE ONLY "public"."processing_status"
    ADD CONSTRAINT "processing_status_message_id_key" UNIQUE ("message_id");

ALTER TABLE ONLY "public"."twitter_data"
    ADD CONSTRAINT "twitter_data_tweet_id_key" UNIQUE ("tweet_id");

ALTER TABLE ONLY "public"."orders"
    ADD CONSTRAINT "orders_brokerage_order_id_key" UNIQUE ("brokerage_order_id");

--
-- Row Level Security (RLS) Policies
--

ALTER TABLE "public"."discord_messages" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "public"."twitter_data" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "public"."discord_market_clean" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "public"."discord_trading_clean" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "public"."chart_metadata" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "public"."processing_status" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "public"."daily_prices" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "public"."realtime_prices" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "public"."stock_metrics" ENABLE ROW LEVEL SECURITY;
ALTER TABLE "public"."orders" ENABLE ROW LEVEL SECURITY;

--
-- Comments on Tables and Columns
--

COMMENT ON TABLE "public"."accounts" IS 'SnapTrade account information';
COMMENT ON TABLE "public"."account_balances" IS 'Account balance data using composite natural key (account_id, currency_code, snapshot_date)';
COMMENT ON TABLE "public"."positions" IS 'SnapTrade position data using composite natural key (account_id, symbol)';
COMMENT ON TABLE "public"."orders" IS 'Order data using brokerage_order_id as natural primary key';
COMMENT ON TABLE "public"."symbols" IS 'Symbol metadata and trading information';
COMMENT ON TABLE "public"."daily_prices" IS 'Daily price data using composite natural key (symbol, date)';
COMMENT ON TABLE "public"."realtime_prices" IS 'Real-time price data using composite natural key (symbol, timestamp)';
COMMENT ON TABLE "public"."stock_metrics" IS 'Stock metrics data using composite natural key (symbol, date)';
COMMENT ON TABLE "public"."discord_messages" IS 'Discord message data using message_id as natural primary key';
COMMENT ON TABLE "public"."discord_market_clean" IS 'Cleaned Discord market messages using message_id as natural primary key';
COMMENT ON TABLE "public"."discord_trading_clean" IS 'Cleaned Discord trading messages using message_id as natural primary key';
COMMENT ON TABLE "public"."discord_processing_log" IS 'Discord processing log using composite natural key (message_id, channel)';
COMMENT ON TABLE "public"."processing_status" IS 'Message processing status using message_id as natural primary key';
COMMENT ON TABLE "public"."twitter_data" IS 'Twitter data using tweet_id as natural primary key';
COMMENT ON TABLE "public"."chart_metadata" IS 'Chart metadata using composite natural key (symbol, period, interval, theme)';
COMMENT ON TABLE "public"."schema_migrations" IS 'Schema version tracking';

-- Column Comments
COMMENT ON COLUMN "public"."orders"."account_id" IS 'Account ID from SnapTrade - links to accounts table';
COMMENT ON COLUMN "public"."orders"."symbol" IS 'Canonical ticker symbol for the security (primary ticker field)';
COMMENT ON COLUMN "public"."orders"."time_placed" IS 'When the order was originally placed';
COMMENT ON COLUMN "public"."orders"."time_executed" IS 'When the order was executed (filled)';
COMMENT ON COLUMN "public"."orders"."child_brokerage_order_ids" IS 'Array of child order IDs stored as JSONB - enables complex order relationships';
COMMENT ON COLUMN "public"."orders"."updated_at" IS 'Timestamp when order record was last updated in database';
COMMENT ON COLUMN "public"."orders"."option_ticker" IS 'Underlying ticker for options (extracted from option_symbol)';
COMMENT ON COLUMN "public"."orders"."option_expiry" IS 'Option expiration date stored as DATE type - enables proper date calculations';
COMMENT ON COLUMN "public"."orders"."option_strike" IS 'Option strike price';
COMMENT ON COLUMN "public"."orders"."option_right" IS 'Option type: CALL or PUT';
COMMENT ON COLUMN "public"."orders"."diary" IS 'Trade diary notes and annotations';
COMMENT ON COLUMN "public"."orders"."parent_brokerage_order_id" IS 'Parent order ID for multi-leg strategies';
COMMENT ON COLUMN "public"."orders"."state" IS 'Order state for lifecycle tracking';
COMMENT ON COLUMN "public"."orders"."user_secret" IS 'Legacy user secret field for backwards compatibility';

COMMENT ON COLUMN "public"."discord_messages"."user_id" IS 'Additional user identifier for Discord message correlation';
COMMENT ON COLUMN "public"."discord_messages"."author_id" IS 'Discord user ID stored as BIGINT - snowflake format for efficient operations';
COMMENT ON COLUMN "public"."discord_messages"."reply_to_id" IS 'Discord message ID stored as BIGINT - snowflake format for efficient operations';

COMMENT ON COLUMN "public"."symbols"."timezone" IS 'Timezone for market hours of this symbol - enables proper time conversion';
COMMENT ON COLUMN "public"."symbols"."market_open_time" IS 'Market opening time for this symbol exchange - enables trading hours validation';
COMMENT ON COLUMN "public"."symbols"."market_close_time" IS 'Market closing time for this symbol exchange - enables trading hours validation';

COMMENT ON COLUMN "public"."twitter_data"."message_id" IS 'Discord message ID that contained this tweet link';
COMMENT ON COLUMN "public"."twitter_data"."discord_date" IS 'Timestamp when tweet was shared in Discord';
COMMENT ON COLUMN "public"."twitter_data"."tweet_date" IS 'Original date when tweet was posted on Twitter';
COMMENT ON COLUMN "public"."twitter_data"."content" IS 'Full tweet content text for analysis';
COMMENT ON COLUMN "public"."twitter_data"."tweet_id" IS 'Twitter/X post unique identifier';
COMMENT ON COLUMN "public"."twitter_data"."discord_message_id" IS 'Associated Discord message ID';
COMMENT ON COLUMN "public"."twitter_data"."discord_sent_date" IS 'When the tweet link was shared in Discord';
COMMENT ON COLUMN "public"."twitter_data"."tweet_created_date" IS 'Original tweet creation timestamp';
COMMENT ON COLUMN "public"."twitter_data"."tweet_content" IS 'Full tweet text content';
COMMENT ON COLUMN "public"."twitter_data"."author_username" IS 'Tweet author username (@handle)';
COMMENT ON COLUMN "public"."twitter_data"."author_name" IS 'Tweet author display name';
COMMENT ON COLUMN "public"."twitter_data"."retweet_count" IS 'Number of retweets/reposts';
COMMENT ON COLUMN "public"."twitter_data"."like_count" IS 'Number of likes/hearts';
COMMENT ON COLUMN "public"."twitter_data"."reply_count" IS 'Number of replies - engagement metric';
COMMENT ON COLUMN "public"."twitter_data"."quote_count" IS 'Number of quote tweets - engagement metric';
COMMENT ON COLUMN "public"."twitter_data"."source_url" IS 'Original Twitter URL for the tweet';
COMMENT ON COLUMN "public"."twitter_data"."retrieved_at" IS 'Timestamp when tweet data was retrieved from Twitter API';

--
-- PostgreSQL database dump complete
--