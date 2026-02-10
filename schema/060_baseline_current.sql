-- =======================================================================
-- LLM Portfolio Journal - Full Schema Baseline
-- =======================================================================
-- Generated via pg_dump --schema-only from Supabase production database.
-- This file is executed ONLY on a completely empty database (fresh install).
-- Never edit this file once applied; create a new 06N_*.sql migration instead.
--
-- Prerequisites (Supabase provides these by default; listed for non-Supabase
-- environments):
--   CREATE EXTENSION IF NOT EXISTS uuid-ossp;
--   CREATE EXTENSION IF NOT EXISTS pgcrypto;
-- =======================================================================



-- Dumped from database version 17.4
-- Dumped by pg_dump version 17.7

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: public; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA IF NOT EXISTS public;


--
-- Name: drop_id_column_and_update_pk(text, text[]); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.drop_id_column_and_update_pk(table_name text, new_pk_columns text[]) RETURNS void
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'public'
    AS $$
DECLARE
    constraint_name TEXT;
BEGIN
    -- Get the primary key constraint name
    SELECT conname INTO constraint_name
    FROM pg_constraint
    WHERE conrelid = table_name::regclass AND contype = 'p';
    
    -- Drop the existing primary key
    IF constraint_name IS NOT NULL THEN
        EXECUTE format('ALTER TABLE %I DROP CONSTRAINT %I', table_name, constraint_name);
    END IF;
    
    -- Drop the id column if it exists
    BEGIN
        EXECUTE format('ALTER TABLE %I DROP COLUMN IF EXISTS id', table_name);
    EXCEPTION WHEN OTHERS THEN
        -- Column doesn't exist, continue
        NULL;
    END;
    
    -- Add the new primary key
    EXECUTE format('ALTER TABLE %I ADD PRIMARY KEY (%s)', 
                   table_name, 
                   array_to_string(array(SELECT quote_ident(unnest(new_pk_columns))), ', '));
END;
$$;


--
-- Name: update_ohlcv_daily_updated_at(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.update_ohlcv_daily_updated_at() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'public'
    AS $$
BEGIN NEW.updated_at = now(); RETURN NEW; END;
$$;


--
-- Name: update_orders_updated_at(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.update_orders_updated_at() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'public'
    AS $$
BEGIN NEW.updated_at = now(); RETURN NEW; END;
$$;


--
-- Name: update_updated_at_column(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.update_updated_at_column() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'public'
    AS $$
BEGIN NEW.updated_at = now(); RETURN NEW; END;
$$;


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: account_balances; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.account_balances (
    account_id text NOT NULL,
    currency_code text NOT NULL,
    currency_name text,
    currency_id text,
    cash real,
    buying_power real,
    snapshot_date date,
    sync_timestamp timestamp with time zone
);


--
-- Name: accounts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.accounts (
    id text NOT NULL,
    brokerage_authorization text,
    portfolio_group text,
    name text,
    number text,
    institution_name text,
    total_equity real,
    last_successful_sync timestamp with time zone,
    sync_timestamp timestamp with time zone
);


--
-- Name: activities; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.activities (
    id text NOT NULL,
    account_id text NOT NULL,
    activity_type text,
    trade_date timestamp with time zone,
    settlement_date timestamp with time zone,
    amount numeric,
    price numeric,
    units numeric,
    symbol text,
    description text,
    currency text DEFAULT 'USD'::text,
    fee numeric DEFAULT 0,
    fx_rate numeric,
    external_reference_id text,
    institution text,
    option_type text,
    sync_timestamp timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP
);


--
-- Name: discord_market_clean; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.discord_market_clean (
    message_id text NOT NULL,
    author text NOT NULL,
    content text NOT NULL,
    sentiment real,
    cleaned_content text,
    "timestamp" text NOT NULL,
    processed_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


--
-- Name: discord_messages; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.discord_messages (
    message_id text NOT NULL,
    author text NOT NULL,
    content text NOT NULL,
    channel text NOT NULL,
    "timestamp" text NOT NULL,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    user_id text DEFAULT 'default_user'::text,
    num_chars integer,
    num_words integer,
    tickers_detected text,
    tweet_urls text,
    sentiment_score numeric(5,4),
    author_id bigint,
    is_reply boolean DEFAULT false,
    reply_to_id bigint,
    mentions text,
    attachments text,
    prompt_version text,
    parse_status text DEFAULT 'pending'::text NOT NULL,
    error_reason text,
    is_bot boolean DEFAULT false,
    is_command boolean DEFAULT false,
    channel_type text,
    CONSTRAINT discord_messages_parse_status_chk CHECK ((parse_status = ANY (ARRAY['pending'::text, 'ok'::text, 'error'::text, 'skipped'::text, 'noise'::text])))
);


--
-- Name: discord_parsed_ideas; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.discord_parsed_ideas (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    message_id text NOT NULL,
    idea_index integer NOT NULL,
    idea_text text NOT NULL,
    idea_summary text,
    context_summary text,
    primary_symbol text,
    symbols text[] DEFAULT '{}'::text[],
    instrument text,
    direction text,
    action text,
    time_horizon text DEFAULT 'unknown'::text,
    trigger_condition text,
    levels jsonb DEFAULT '[]'::jsonb,
    option_type text,
    strike numeric,
    expiry date,
    premium numeric,
    labels text[] DEFAULT '{}'::text[],
    label_scores jsonb DEFAULT '{}'::jsonb,
    is_noise boolean DEFAULT false,
    author_id text,
    channel_id text,
    model text DEFAULT 'unknown'::text NOT NULL,
    prompt_version text DEFAULT 'unknown'::text NOT NULL,
    confidence numeric(4,3),
    parsed_at timestamp with time zone DEFAULT now(),
    raw_json jsonb,
    source_created_at timestamp with time zone,
    soft_chunk_index integer DEFAULT 0 NOT NULL,
    local_idea_index integer DEFAULT 0 NOT NULL,
    CONSTRAINT discord_parsed_ideas_action_check CHECK ((action = ANY (ARRAY['buy'::text, 'sell'::text, 'trim'::text, 'add'::text, 'watch'::text, 'hold'::text, 'short'::text, 'hedge'::text, 'none'::text]))),
    CONSTRAINT discord_parsed_ideas_direction_check CHECK ((direction = ANY (ARRAY['bullish'::text, 'bearish'::text, 'neutral'::text, 'mixed'::text]))),
    CONSTRAINT discord_parsed_ideas_instrument_check CHECK ((instrument = ANY (ARRAY['equity'::text, 'option'::text, 'crypto'::text, 'index'::text, 'sector'::text, 'event_contract'::text]))),
    CONSTRAINT discord_parsed_ideas_option_type_check CHECK ((option_type = ANY (ARRAY['call'::text, 'put'::text]))),
    CONSTRAINT discord_parsed_ideas_time_horizon_check CHECK ((time_horizon = ANY (ARRAY['scalp'::text, 'swing'::text, 'long_term'::text, 'unknown'::text])))
);


--
-- Name: discord_trading_clean; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.discord_trading_clean (
    message_id text NOT NULL,
    author text NOT NULL,
    content text NOT NULL,
    sentiment real,
    cleaned_content text,
    stock_mentions text,
    "timestamp" text NOT NULL,
    processed_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


--
-- Name: institutional_holdings; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.institutional_holdings (
    id integer NOT NULL,
    filing_date date,
    manager_cik character varying(10),
    manager_name character varying(255),
    cusip character varying(9) NOT NULL,
    ticker character varying(10),
    company_name character varying(255),
    value_usd bigint,
    shares bigint,
    share_type character varying(10),
    is_put boolean DEFAULT false,
    is_call boolean DEFAULT false,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: institutional_holdings_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.institutional_holdings_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: institutional_holdings_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.institutional_holdings_id_seq OWNED BY public.institutional_holdings.id;


--
-- Name: ohlcv_daily; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.ohlcv_daily (
    symbol text NOT NULL,
    date date NOT NULL,
    open numeric(18,6),
    high numeric(18,6),
    low numeric(18,6),
    close numeric(18,6),
    volume bigint,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    source text DEFAULT 'databento'::text
);


--
-- Name: orders; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.orders (
    brokerage_order_id text NOT NULL,
    account_id text,
    status text NOT NULL,
    action text NOT NULL,
    symbol text NOT NULL,
    total_quantity numeric(18,6),
    open_quantity numeric(18,6) DEFAULT 0,
    canceled_quantity numeric(18,6) DEFAULT 0,
    filled_quantity numeric(18,6),
    execution_price numeric(18,6),
    limit_price numeric(18,6),
    stop_price numeric(18,6),
    order_type text,
    time_in_force text,
    time_placed timestamp with time zone,
    time_updated timestamp with time zone,
    time_executed timestamp with time zone,
    expiry_date date,
    child_brokerage_order_ids jsonb,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    user_id text DEFAULT 'default_user'::text,
    option_ticker text,
    option_expiry date,
    option_strike numeric(10,2),
    option_right text,
    sync_timestamp timestamp with time zone,
    notified boolean DEFAULT false,
    CONSTRAINT valid_action CHECK ((action = ANY (ARRAY['BUY'::text, 'SELL'::text, 'BUY_OPEN'::text, 'SELL_CLOSE'::text, 'BUY_TO_COVER'::text, 'SELL_SHORT'::text]))),
    CONSTRAINT valid_status CHECK ((status = ANY (ARRAY['PENDING'::text, 'EXECUTED'::text, 'CANCELED'::text, 'REJECTED'::text, 'EXPIRED'::text, 'FILLED'::text, 'PARTIAL'::text])))
);


--
-- Name: positions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.positions (
    symbol text NOT NULL,
    symbol_id text,
    symbol_description text,
    quantity numeric(15,4),
    price numeric(12,4),
    equity numeric(15,4),
    average_buy_price numeric(12,4),
    open_pnl numeric(15,4),
    asset_type text,
    currency text,
    logo_url text,
    exchange_code text,
    exchange_name text,
    mic_code text,
    figi_code text,
    account_id text DEFAULT 'default_account'::text NOT NULL,
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    raw_symbol text,
    prev_price numeric(12,4),
    current_price numeric(12,4),
    price_updated_at timestamp with time zone,
    sync_timestamp timestamp with time zone
);


--
-- Name: processing_status; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.processing_status (
    message_id text NOT NULL,
    channel text NOT NULL,
    processed_for_cleaning boolean DEFAULT false,
    processed_for_twitter boolean DEFAULT false,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


--
-- Name: schema_migrations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.schema_migrations (
    version text NOT NULL,
    applied_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    description text
);


--
-- Name: stock_profile_current; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.stock_profile_current (
    ticker character varying(10) NOT NULL,
    last_updated timestamp with time zone DEFAULT now() NOT NULL,
    latest_close_price numeric(12,4),
    previous_close_price numeric(12,4),
    daily_change_pct numeric(8,4),
    return_1w_pct numeric(8,4),
    return_1m_pct numeric(8,4),
    return_3m_pct numeric(8,4),
    return_1y_pct numeric(8,4),
    volatility_30d numeric(8,4),
    volatility_90d numeric(8,4),
    year_high numeric(12,4),
    year_low numeric(12,4),
    avg_volume_30d bigint,
    current_position_qty numeric(12,4),
    current_position_value numeric(14,2),
    avg_buy_price numeric(12,4),
    unrealized_pnl numeric(14,2),
    unrealized_pnl_pct numeric(8,4),
    total_orders_count integer DEFAULT 0,
    buy_orders_count integer DEFAULT 0,
    sell_orders_count integer DEFAULT 0,
    avg_order_size numeric(12,4),
    first_trade_date date,
    last_trade_date date,
    total_mention_count integer DEFAULT 0,
    mention_count_30d integer DEFAULT 0,
    mention_count_7d integer DEFAULT 0,
    avg_sentiment_score numeric(5,4),
    bullish_mention_pct numeric(5,2),
    bearish_mention_pct numeric(5,2),
    neutral_mention_pct numeric(5,2),
    first_mentioned_at timestamp with time zone,
    last_mentioned_at timestamp with time zone,
    label_trade_execution_count integer DEFAULT 0,
    label_trade_plan_count integer DEFAULT 0,
    label_technical_analysis_count integer DEFAULT 0,
    label_options_count integer DEFAULT 0,
    label_catalyst_news_count integer DEFAULT 0,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: stock_profile_history; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.stock_profile_history (
    ticker character varying(10) NOT NULL,
    as_of_date date NOT NULL,
    close_price numeric(12,4),
    daily_change_pct numeric(8,4),
    return_1w_pct numeric(8,4),
    return_1m_pct numeric(8,4),
    return_3m_pct numeric(8,4),
    return_1y_pct numeric(8,4),
    volatility_30d numeric(8,4),
    volatility_90d numeric(8,4),
    year_high numeric(12,4),
    year_low numeric(12,4),
    avg_volume_30d bigint,
    position_qty numeric(12,4),
    position_value numeric(14,2),
    avg_buy_price numeric(12,4),
    unrealized_pnl numeric(14,2),
    unrealized_pnl_pct numeric(8,4),
    total_orders_count integer DEFAULT 0,
    total_mention_count integer DEFAULT 0,
    mention_count_30d integer DEFAULT 0,
    avg_sentiment_score numeric(5,4),
    bullish_mention_pct numeric(5,2),
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: symbol_aliases; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.symbol_aliases (
    id integer NOT NULL,
    ticker character varying(10) NOT NULL,
    alias character varying(50) NOT NULL,
    source character varying(20) DEFAULT 'manual'::character varying NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: symbol_aliases_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.symbol_aliases_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: symbol_aliases_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.symbol_aliases_id_seq OWNED BY public.symbol_aliases.id;


--
-- Name: symbols; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.symbols (
    id text NOT NULL,
    ticker text,
    description text,
    asset_type text,
    type_code text,
    exchange_code text,
    exchange_name text,
    exchange_mic text,
    figi_code text,
    raw_symbol text,
    logo_url text,
    base_currency_code text,
    is_supported boolean DEFAULT true,
    is_quotable boolean DEFAULT true,
    is_tradable boolean DEFAULT true,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    timezone text,
    market_open_time time without time zone,
    market_close_time time without time zone
);


--
-- Name: trade_history; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.trade_history (
    id integer NOT NULL,
    symbol text NOT NULL,
    account_id text DEFAULT 'default_account'::text NOT NULL,
    trade_type text NOT NULL,
    trade_date timestamp with time zone NOT NULL,
    quantity numeric NOT NULL,
    execution_price numeric NOT NULL,
    total_value numeric,
    cost_basis numeric,
    realized_pnl numeric,
    realized_pnl_pct numeric,
    position_qty_before numeric,
    position_qty_after numeric,
    holding_pct numeric,
    portfolio_weight numeric,
    brokerage_order_id text,
    source text DEFAULT 'snaptrade'::text,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: trade_history_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.trade_history_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: trade_history_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.trade_history_id_seq OWNED BY public.trade_history.id;


--
-- Name: twitter_data; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.twitter_data (
    message_id text NOT NULL,
    content text NOT NULL,
    stock_tags text,
    author text NOT NULL,
    channel text NOT NULL,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    tweet_id text NOT NULL,
    discord_message_id text,
    tweet_content text,
    author_username text,
    author_name text,
    retweet_count integer DEFAULT 0,
    like_count integer DEFAULT 0,
    reply_count integer DEFAULT 0,
    quote_count integer DEFAULT 0,
    source_url text,
    retrieved_at text,
    discord_date timestamp with time zone,
    tweet_date timestamp with time zone,
    discord_sent_date timestamp with time zone,
    tweet_created_date timestamp with time zone,
    media_urls jsonb DEFAULT '[]'::jsonb
);


--
-- Name: institutional_holdings id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.institutional_holdings ALTER COLUMN id SET DEFAULT nextval('public.institutional_holdings_id_seq'::regclass);


--
-- Name: symbol_aliases id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.symbol_aliases ALTER COLUMN id SET DEFAULT nextval('public.symbol_aliases_id_seq'::regclass);


--
-- Name: trade_history id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trade_history ALTER COLUMN id SET DEFAULT nextval('public.trade_history_id_seq'::regclass);


--
-- Name: accounts accounts_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.accounts
    ADD CONSTRAINT accounts_pkey PRIMARY KEY (id);


--
-- Name: activities activities_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.activities
    ADD CONSTRAINT activities_pkey PRIMARY KEY (id);


--
-- Name: discord_market_clean discord_market_clean_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.discord_market_clean
    ADD CONSTRAINT discord_market_clean_pkey PRIMARY KEY (message_id);


--
-- Name: discord_messages discord_messages_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.discord_messages
    ADD CONSTRAINT discord_messages_pkey PRIMARY KEY (message_id);


--
-- Name: discord_parsed_ideas discord_parsed_ideas_message_chunk_idx_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.discord_parsed_ideas
    ADD CONSTRAINT discord_parsed_ideas_message_chunk_idx_key UNIQUE (message_id, soft_chunk_index, local_idea_index);


--
-- Name: discord_parsed_ideas discord_parsed_ideas_message_id_idea_index_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.discord_parsed_ideas
    ADD CONSTRAINT discord_parsed_ideas_message_id_idea_index_key UNIQUE (message_id, idea_index);


--
-- Name: discord_parsed_ideas discord_parsed_ideas_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.discord_parsed_ideas
    ADD CONSTRAINT discord_parsed_ideas_pkey PRIMARY KEY (id);


--
-- Name: discord_trading_clean discord_trading_clean_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.discord_trading_clean
    ADD CONSTRAINT discord_trading_clean_pkey PRIMARY KEY (message_id);


--
-- Name: institutional_holdings institutional_holdings_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.institutional_holdings
    ADD CONSTRAINT institutional_holdings_pkey PRIMARY KEY (id);


--
-- Name: ohlcv_daily ohlcv_daily_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.ohlcv_daily
    ADD CONSTRAINT ohlcv_daily_pkey PRIMARY KEY (symbol, date);


--
-- Name: orders orders_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.orders
    ADD CONSTRAINT orders_pkey PRIMARY KEY (brokerage_order_id);


--
-- Name: positions positions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.positions
    ADD CONSTRAINT positions_pkey PRIMARY KEY (symbol, account_id);


--
-- Name: processing_status processing_status_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.processing_status
    ADD CONSTRAINT processing_status_pkey PRIMARY KEY (message_id, channel);


--
-- Name: schema_migrations schema_migrations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.schema_migrations
    ADD CONSTRAINT schema_migrations_pkey PRIMARY KEY (version);


--
-- Name: stock_profile_current stock_profile_current_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.stock_profile_current
    ADD CONSTRAINT stock_profile_current_pkey PRIMARY KEY (ticker);


--
-- Name: stock_profile_history stock_profile_history_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.stock_profile_history
    ADD CONSTRAINT stock_profile_history_pkey PRIMARY KEY (ticker, as_of_date);


--
-- Name: symbol_aliases symbol_aliases_alias_source_unique; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.symbol_aliases
    ADD CONSTRAINT symbol_aliases_alias_source_unique UNIQUE (alias, source);


--
-- Name: symbol_aliases symbol_aliases_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.symbol_aliases
    ADD CONSTRAINT symbol_aliases_pkey PRIMARY KEY (id);


--
-- Name: symbols symbols_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.symbols
    ADD CONSTRAINT symbols_pkey PRIMARY KEY (id);


--
-- Name: symbols symbols_ticker_unique; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.symbols
    ADD CONSTRAINT symbols_ticker_unique UNIQUE (ticker);


--
-- Name: trade_history trade_history_brokerage_order_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trade_history
    ADD CONSTRAINT trade_history_brokerage_order_id_key UNIQUE (brokerage_order_id);


--
-- Name: trade_history trade_history_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trade_history
    ADD CONSTRAINT trade_history_pkey PRIMARY KEY (id);


--
-- Name: twitter_data twitter_data_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.twitter_data
    ADD CONSTRAINT twitter_data_pkey PRIMARY KEY (tweet_id);


--
-- Name: idx_activities_account_trade_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_activities_account_trade_date ON public.activities USING btree (account_id, trade_date DESC);


--
-- Name: idx_activities_activity_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_activities_activity_type ON public.activities USING btree (activity_type);


--
-- Name: idx_activities_symbol; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_activities_symbol ON public.activities USING btree (symbol);


--
-- Name: idx_activities_trade_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_activities_trade_date ON public.activities USING btree (trade_date DESC);


--
-- Name: idx_discord_messages_channel; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_discord_messages_channel ON public.discord_messages USING btree (channel);


--
-- Name: idx_discord_messages_channel_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_discord_messages_channel_type ON public.discord_messages USING btree (channel_type) WHERE (channel_type IS NOT NULL);


--
-- Name: idx_discord_messages_parse_filter; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_discord_messages_parse_filter ON public.discord_messages USING btree (is_bot, is_command) WHERE ((is_bot = false) AND (is_command = false));


--
-- Name: idx_discord_messages_parse_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_discord_messages_parse_status ON public.discord_messages USING btree (parse_status) WHERE (parse_status = 'pending'::text);


--
-- Name: idx_discord_messages_timestamp; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_discord_messages_timestamp ON public.discord_messages USING btree ("timestamp");


--
-- Name: idx_discord_trading_clean_timestamp; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_discord_trading_clean_timestamp ON public.discord_trading_clean USING btree ("timestamp");


--
-- Name: idx_ohlcv_daily_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_ohlcv_daily_date ON public.ohlcv_daily USING btree (date DESC);


--
-- Name: idx_ohlcv_daily_symbol; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_ohlcv_daily_symbol ON public.ohlcv_daily USING btree (symbol);


--
-- Name: idx_ohlcv_daily_symbol_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_ohlcv_daily_symbol_date ON public.ohlcv_daily USING btree (symbol, date DESC);


--
-- Name: idx_orders_account_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_orders_account_id ON public.orders USING btree (account_id);


--
-- Name: idx_orders_action; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_orders_action ON public.orders USING btree (action);


--
-- Name: idx_orders_notified; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_orders_notified ON public.orders USING btree (notified, status) WHERE ((status = 'FILLED'::text) AND (notified = false));


--
-- Name: idx_orders_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_orders_status ON public.orders USING btree (status);


--
-- Name: idx_orders_symbol; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_orders_symbol ON public.orders USING btree (symbol);


--
-- Name: idx_orders_time_executed; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_orders_time_executed ON public.orders USING btree (time_executed);


--
-- Name: idx_orders_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_orders_user_id ON public.orders USING btree (user_id);


--
-- Name: idx_parsed_ideas_message; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_parsed_ideas_message ON public.discord_parsed_ideas USING btree (message_id);


--
-- Name: idx_stock_profile_current_mentions; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_stock_profile_current_mentions ON public.stock_profile_current USING btree (mention_count_30d DESC);


--
-- Name: idx_stock_profile_current_position; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_stock_profile_current_position ON public.stock_profile_current USING btree (current_position_qty DESC NULLS LAST);


--
-- Name: idx_stock_profile_current_updated; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_stock_profile_current_updated ON public.stock_profile_current USING btree (last_updated DESC);


--
-- Name: idx_stock_profile_history_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_stock_profile_history_date ON public.stock_profile_history USING btree (as_of_date DESC);


--
-- Name: idx_stock_profile_history_ticker; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_stock_profile_history_ticker ON public.stock_profile_history USING btree (ticker, as_of_date DESC);


--
-- Name: idx_symbol_aliases_alias; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_symbol_aliases_alias ON public.symbol_aliases USING btree (alias);


--
-- Name: idx_symbol_aliases_alias_lower; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_symbol_aliases_alias_lower ON public.symbol_aliases USING btree (lower((alias)::text));


--
-- Name: idx_symbol_aliases_source; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_symbol_aliases_source ON public.symbol_aliases USING btree (source);


--
-- Name: idx_symbol_aliases_ticker; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_symbol_aliases_ticker ON public.symbol_aliases USING btree (ticker);


--
-- Name: idx_twitter_data_discord_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_twitter_data_discord_date ON public.twitter_data USING btree (discord_date);


--
-- Name: ohlcv_daily trigger_ohlcv_daily_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trigger_ohlcv_daily_updated_at BEFORE UPDATE ON public.ohlcv_daily FOR EACH ROW EXECUTE FUNCTION public.update_ohlcv_daily_updated_at();


--
-- Name: orders update_orders_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER update_orders_updated_at BEFORE UPDATE ON public.orders FOR EACH ROW EXECUTE FUNCTION public.update_updated_at_column();


--
-- Name: ohlcv_daily Allow authenticated read access on ohlcv_daily; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY "Allow authenticated read access on ohlcv_daily" ON public.ohlcv_daily FOR SELECT TO authenticated USING (true);


--
-- Name: institutional_holdings Allow full access for service role; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY "Allow full access for service role" ON public.institutional_holdings TO service_role USING (true) WITH CHECK (true);


--
-- Name: institutional_holdings Allow read access for authenticated users; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY "Allow read access for authenticated users" ON public.institutional_holdings FOR SELECT TO authenticated USING (true);


--
-- Name: discord_parsed_ideas Allow service role full access; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY "Allow service role full access" ON public.discord_parsed_ideas TO service_role USING (true) WITH CHECK (true);


--
-- Name: ohlcv_daily Allow service role full access on ohlcv_daily; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY "Allow service role full access on ohlcv_daily" ON public.ohlcv_daily TO service_role USING (true) WITH CHECK (true);


--
-- Name: account_balances; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.account_balances ENABLE ROW LEVEL SECURITY;

--
-- Name: account_balances account_balances_anon_read; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY account_balances_anon_read ON public.account_balances FOR SELECT TO anon USING (true);


--
-- Name: account_balances account_balances_authenticated_read; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY account_balances_authenticated_read ON public.account_balances FOR SELECT TO authenticated USING (true);


--
-- Name: account_balances account_balances_service_role_all; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY account_balances_service_role_all ON public.account_balances TO service_role USING (true) WITH CHECK (true);


--
-- Name: accounts; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.accounts ENABLE ROW LEVEL SECURITY;

--
-- Name: accounts accounts_anon_read; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY accounts_anon_read ON public.accounts FOR SELECT TO anon USING (true);


--
-- Name: accounts accounts_authenticated_read; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY accounts_authenticated_read ON public.accounts FOR SELECT TO authenticated USING (true);


--
-- Name: accounts accounts_service_role_all; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY accounts_service_role_all ON public.accounts TO service_role USING (true) WITH CHECK (true);


--
-- Name: activities; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.activities ENABLE ROW LEVEL SECURITY;

--
-- Name: activities activities_anon_read; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY activities_anon_read ON public.activities FOR SELECT TO anon USING (true);


--
-- Name: activities activities_authenticated_read; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY activities_authenticated_read ON public.activities FOR SELECT TO authenticated USING (true);


--
-- Name: activities activities_service_role_all; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY activities_service_role_all ON public.activities TO service_role USING (true) WITH CHECK (true);


--
-- Name: discord_market_clean anon_read_discord_market_clean; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY anon_read_discord_market_clean ON public.discord_market_clean FOR SELECT TO anon USING (true);


--
-- Name: discord_messages anon_read_discord_messages; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY anon_read_discord_messages ON public.discord_messages FOR SELECT TO anon USING (true);


--
-- Name: discord_trading_clean anon_read_discord_trading_clean; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY anon_read_discord_trading_clean ON public.discord_trading_clean FOR SELECT TO anon USING (true);


--
-- Name: orders anon_read_orders; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY anon_read_orders ON public.orders FOR SELECT TO anon USING (true);


--
-- Name: processing_status anon_read_processing_status; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY anon_read_processing_status ON public.processing_status FOR SELECT TO anon USING (true);


--
-- Name: stock_profile_current anon_read_stock_profile_current; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY anon_read_stock_profile_current ON public.stock_profile_current FOR SELECT TO anon USING (true);


--
-- Name: stock_profile_history anon_read_stock_profile_history; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY anon_read_stock_profile_history ON public.stock_profile_history FOR SELECT TO anon USING (true);


--
-- Name: symbol_aliases anon_read_symbol_aliases; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY anon_read_symbol_aliases ON public.symbol_aliases FOR SELECT TO anon USING (true);


--
-- Name: twitter_data anon_read_twitter_data; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY anon_read_twitter_data ON public.twitter_data FOR SELECT TO anon USING (true);


--
-- Name: discord_market_clean authenticated_read_discord_market_clean; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY authenticated_read_discord_market_clean ON public.discord_market_clean FOR SELECT TO authenticated USING (true);


--
-- Name: discord_messages authenticated_read_discord_messages; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY authenticated_read_discord_messages ON public.discord_messages FOR SELECT TO authenticated USING (true);


--
-- Name: discord_trading_clean authenticated_read_discord_trading_clean; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY authenticated_read_discord_trading_clean ON public.discord_trading_clean FOR SELECT TO authenticated USING (true);


--
-- Name: orders authenticated_read_orders; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY authenticated_read_orders ON public.orders FOR SELECT TO authenticated USING (true);


--
-- Name: processing_status authenticated_read_processing_status; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY authenticated_read_processing_status ON public.processing_status FOR SELECT TO authenticated USING (true);


--
-- Name: stock_profile_current authenticated_read_stock_profile_current; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY authenticated_read_stock_profile_current ON public.stock_profile_current FOR SELECT TO authenticated USING (true);


--
-- Name: stock_profile_history authenticated_read_stock_profile_history; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY authenticated_read_stock_profile_history ON public.stock_profile_history FOR SELECT TO authenticated USING (true);


--
-- Name: symbol_aliases authenticated_read_symbol_aliases; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY authenticated_read_symbol_aliases ON public.symbol_aliases FOR SELECT TO authenticated USING (true);


--
-- Name: twitter_data authenticated_read_twitter_data; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY authenticated_read_twitter_data ON public.twitter_data FOR SELECT TO authenticated USING (true);


--
-- Name: discord_market_clean; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.discord_market_clean ENABLE ROW LEVEL SECURITY;

--
-- Name: discord_messages; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.discord_messages ENABLE ROW LEVEL SECURITY;

--
-- Name: discord_parsed_ideas; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.discord_parsed_ideas ENABLE ROW LEVEL SECURITY;

--
-- Name: discord_trading_clean; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.discord_trading_clean ENABLE ROW LEVEL SECURITY;

--
-- Name: institutional_holdings; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.institutional_holdings ENABLE ROW LEVEL SECURITY;

--
-- Name: ohlcv_daily; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.ohlcv_daily ENABLE ROW LEVEL SECURITY;

--
-- Name: orders; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.orders ENABLE ROW LEVEL SECURITY;

--
-- Name: orders orders_service_role_all; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY orders_service_role_all ON public.orders TO service_role USING (true) WITH CHECK (true);


--
-- Name: positions; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.positions ENABLE ROW LEVEL SECURITY;

--
-- Name: positions positions_anon_read; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY positions_anon_read ON public.positions FOR SELECT TO anon USING (true);


--
-- Name: positions positions_authenticated_read; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY positions_authenticated_read ON public.positions FOR SELECT TO authenticated USING (true);


--
-- Name: positions positions_service_role_all; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY positions_service_role_all ON public.positions TO service_role USING (true) WITH CHECK (true);


--
-- Name: processing_status; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.processing_status ENABLE ROW LEVEL SECURITY;

--
-- Name: schema_migrations; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.schema_migrations ENABLE ROW LEVEL SECURITY;

--
-- Name: schema_migrations schema_migrations_anon_read; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY schema_migrations_anon_read ON public.schema_migrations FOR SELECT TO anon USING (true);


--
-- Name: schema_migrations schema_migrations_authenticated_read; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY schema_migrations_authenticated_read ON public.schema_migrations FOR SELECT TO authenticated USING (true);


--
-- Name: schema_migrations schema_migrations_service_role_access; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY schema_migrations_service_role_access ON public.schema_migrations TO service_role USING (true) WITH CHECK (true);


--
-- Name: stock_profile_current service_role_all_stock_profile_current; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY service_role_all_stock_profile_current ON public.stock_profile_current TO service_role USING (true) WITH CHECK (true);


--
-- Name: stock_profile_history service_role_all_stock_profile_history; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY service_role_all_stock_profile_history ON public.stock_profile_history TO service_role USING (true) WITH CHECK (true);


--
-- Name: symbol_aliases service_role_all_symbol_aliases; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY service_role_all_symbol_aliases ON public.symbol_aliases TO service_role USING (true) WITH CHECK (true);


--
-- Name: stock_profile_current; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.stock_profile_current ENABLE ROW LEVEL SECURITY;

--
-- Name: stock_profile_history; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.stock_profile_history ENABLE ROW LEVEL SECURITY;

--
-- Name: symbol_aliases; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.symbol_aliases ENABLE ROW LEVEL SECURITY;

--
-- Name: symbols; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.symbols ENABLE ROW LEVEL SECURITY;

--
-- Name: symbols symbols_anon_read; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY symbols_anon_read ON public.symbols FOR SELECT TO anon USING (true);


--
-- Name: symbols symbols_authenticated_read; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY symbols_authenticated_read ON public.symbols FOR SELECT TO authenticated USING (true);


--
-- Name: symbols symbols_service_role_all; Type: POLICY; Schema: public; Owner: -
--

CREATE POLICY symbols_service_role_all ON public.symbols TO service_role USING (true) WITH CHECK (true);


--
-- Name: trade_history; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.trade_history ENABLE ROW LEVEL SECURITY;

--
-- Name: twitter_data; Type: ROW SECURITY; Schema: public; Owner: -
--

ALTER TABLE public.twitter_data ENABLE ROW LEVEL SECURITY;

--
-- PostgreSQL database dump complete
--

