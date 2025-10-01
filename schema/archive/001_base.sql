-- 001_base.sql - Base Database Schema for LLM Portfolio Journal
-- Run this to initialize all tables for social and financial data
-- All DDL statements are idempotent using IF NOT EXISTS patterns

-- ==============================================
-- Social Media and Discord Tables
-- ==============================================

-- Primary discord messages table (raw data)
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'discord_messages' AND table_schema = 'public') THEN
        CREATE TABLE discord_messages (
            id SERIAL PRIMARY KEY,
            message_id TEXT UNIQUE NOT NULL,
            author TEXT NOT NULL,
            author_id TEXT,
            content TEXT NOT NULL,
            channel TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            tickers_detected TEXT,
            tweet_urls TEXT,
            is_reply BOOLEAN DEFAULT FALSE,
            reply_to_id TEXT,
            mentions TEXT,
            num_chars INTEGER,
            num_words INTEGER,
            sentiment_score REAL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        
        CREATE INDEX IF NOT EXISTS idx_discord_messages_message_id ON discord_messages(message_id);
        CREATE INDEX IF NOT EXISTS idx_discord_messages_channel ON discord_messages(channel);
        CREATE INDEX IF NOT EXISTS idx_discord_messages_timestamp ON discord_messages(timestamp);
        CREATE INDEX IF NOT EXISTS idx_discord_messages_author ON discord_messages(author);
    END IF;
END $$;

-- Twitter data table
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'twitter_data' AND table_schema = 'public') THEN
        CREATE TABLE twitter_data (
            id SERIAL PRIMARY KEY,
            tweet_id TEXT,
            discord_message_id TEXT,
            discord_sent_date TEXT,
            tweet_created_date TEXT,
            tweet_content TEXT,
            author_username TEXT,
            author_name TEXT,
            retweet_count INTEGER DEFAULT 0,
            like_count INTEGER DEFAULT 0,
            stock_tags TEXT,
            author TEXT NOT NULL,
            channel TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        
        CREATE INDEX IF NOT EXISTS idx_twitter_data_tweet_id ON twitter_data(tweet_id);
        CREATE INDEX IF NOT EXISTS idx_twitter_data_discord_message_id ON twitter_data(discord_message_id);
        CREATE INDEX IF NOT EXISTS idx_twitter_data_stock_tags ON twitter_data(stock_tags);
    END IF;
END $$;

-- Processed discord market messages (general channels)
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'discord_market_clean' AND table_schema = 'public') THEN
        CREATE TABLE discord_market_clean (
            id SERIAL PRIMARY KEY,
            message_id TEXT UNIQUE NOT NULL,
            author TEXT NOT NULL,
            content TEXT NOT NULL,
            sentiment REAL,
            cleaned_content TEXT,
            timestamp TEXT NOT NULL,
            processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        
        CREATE INDEX IF NOT EXISTS idx_discord_market_clean_message_id ON discord_market_clean(message_id);
        CREATE INDEX IF NOT EXISTS idx_discord_market_clean_timestamp ON discord_market_clean(timestamp);
        CREATE INDEX IF NOT EXISTS idx_discord_market_clean_sentiment ON discord_market_clean(sentiment);
    END IF;
END $$;

-- Processed discord trading messages (trading channels)
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'discord_trading_clean' AND table_schema = 'public') THEN
        CREATE TABLE discord_trading_clean (
            id SERIAL PRIMARY KEY,
            message_id TEXT UNIQUE NOT NULL,
            author TEXT NOT NULL,
            content TEXT NOT NULL,
            sentiment REAL,
            cleaned_content TEXT,
            stock_mentions TEXT,
            timestamp TEXT NOT NULL,
            processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        
        CREATE INDEX IF NOT EXISTS idx_discord_trading_clean_message_id ON discord_trading_clean(message_id);
        CREATE INDEX IF NOT EXISTS idx_discord_trading_clean_timestamp ON discord_trading_clean(timestamp);
        CREATE INDEX IF NOT EXISTS idx_discord_trading_clean_stock_mentions ON discord_trading_clean(stock_mentions);
        CREATE INDEX IF NOT EXISTS idx_discord_trading_clean_sentiment ON discord_trading_clean(sentiment);
    END IF;
END $$;

-- Processing status tracking table
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'processing_status' AND table_schema = 'public') THEN
        CREATE TABLE processing_status (
            id SERIAL PRIMARY KEY,
            message_id TEXT UNIQUE NOT NULL,
            channel TEXT NOT NULL,
            processed_for_cleaning BOOLEAN DEFAULT FALSE,
            processed_for_twitter BOOLEAN DEFAULT FALSE,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        
        CREATE INDEX IF NOT EXISTS idx_processing_status_message_id ON processing_status(message_id);
        CREATE INDEX IF NOT EXISTS idx_processing_status_channel ON processing_status(channel);
    END IF;
END $$;

-- ==============================================
-- Financial and Market Data Tables
-- ==============================================

-- Daily historical prices
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'daily_prices' AND table_schema = 'public') THEN
        CREATE TABLE daily_prices (
            id SERIAL PRIMARY KEY,
            symbol TEXT NOT NULL,
            date TEXT NOT NULL,
            open REAL,
            high REAL,
            low REAL,
            close REAL,
            volume INTEGER,
            dividends REAL,
            stock_splits REAL,
            UNIQUE(symbol, date)
        );
        
        CREATE INDEX IF NOT EXISTS idx_daily_prices_symbol ON daily_prices(symbol);
        CREATE INDEX IF NOT EXISTS idx_daily_prices_date ON daily_prices(date);
        CREATE INDEX IF NOT EXISTS idx_daily_prices_symbol_date ON daily_prices(symbol, date);
    END IF;
END $$;

-- Real-time price data
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'realtime_prices' AND table_schema = 'public') THEN
        CREATE TABLE realtime_prices (
            id SERIAL PRIMARY KEY,
            symbol TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            price REAL,
            previous_close REAL,
            abs_change REAL,
            percent_change REAL,
            UNIQUE(symbol, timestamp)
        );
        
        CREATE INDEX IF NOT EXISTS idx_realtime_prices_symbol ON realtime_prices(symbol);
        CREATE INDEX IF NOT EXISTS idx_realtime_prices_timestamp ON realtime_prices(timestamp);
    END IF;
END $$;

-- Stock metrics and fundamentals
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'stock_metrics' AND table_schema = 'public') THEN
        CREATE TABLE stock_metrics (
            id SERIAL PRIMARY KEY,
            symbol TEXT NOT NULL,
            date TEXT NOT NULL,
            pe_ratio REAL,
            market_cap REAL,
            dividend_yield REAL,
            fifty_day_avg REAL,
            two_hundred_day_avg REAL,
            UNIQUE(symbol, date)
        );
        
        CREATE INDEX IF NOT EXISTS idx_stock_metrics_symbol ON stock_metrics(symbol);
        CREATE INDEX IF NOT EXISTS idx_stock_metrics_date ON stock_metrics(date);
    END IF;
END $$;

-- Portfolio positions
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'positions' AND table_schema = 'public') THEN
        CREATE TABLE positions (
            id SERIAL PRIMARY KEY,
            account_id TEXT,
            symbol TEXT NOT NULL,
            symbol_description TEXT,
            quantity REAL,
            price REAL,
            equity REAL,
            average_buy_price REAL,
            open_pnl REAL,
            asset_type TEXT,
            currency TEXT DEFAULT 'USD',
            logo_url TEXT,
            sync_timestamp TEXT NOT NULL,
            calculated_equity REAL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(account_id, symbol, sync_timestamp)
        );
        
        CREATE INDEX IF NOT EXISTS idx_positions_symbol ON positions(symbol);
        CREATE INDEX IF NOT EXISTS idx_positions_sync_timestamp ON positions(sync_timestamp);
        CREATE INDEX IF NOT EXISTS idx_positions_account_id ON positions(account_id);
    END IF;
END $$;

-- Trade orders
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'orders' AND table_schema = 'public') THEN
        CREATE TABLE orders (
            id SERIAL PRIMARY KEY,
            account_id TEXT,
            brokerage_order_id TEXT,
            status TEXT,
            symbol TEXT,
            extracted_symbol TEXT,
            universal_symbol TEXT,
            quote_universal_symbol TEXT,
            quote_currency TEXT,
            option_symbol TEXT,
            action TEXT,
            total_quantity REAL,
            open_quantity REAL,
            canceled_quantity REAL,
            filled_quantity REAL,
            execution_price DECIMAL(18, 6),
            limit_price DECIMAL(18, 6),
            stop_price DECIMAL(18, 6),
            order_type TEXT,
            time_in_force TEXT,
            time_placed TIMESTAMP,
            time_updated TIMESTAMP,
            time_executed TIMESTAMP,
            expiry_date DATE,
            diary TEXT,
            child_brokerage_order_ids TEXT,
            parent_brokerage_order_id TEXT,
            state TEXT,
            option_ticker TEXT,
            option_expiry TEXT,
            option_strike REAL,
            option_right TEXT,
            user_id TEXT,
            user_secret TEXT,
            sync_timestamp TEXT DEFAULT (EXTRACT(EPOCH FROM CURRENT_TIMESTAMP)::TEXT),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(brokerage_order_id)
        );
        
        CREATE INDEX IF NOT EXISTS idx_orders_brokerage_order_id ON orders(brokerage_order_id);
        CREATE INDEX IF NOT EXISTS idx_orders_symbol ON orders(symbol);
        CREATE INDEX IF NOT EXISTS idx_orders_extracted_symbol ON orders(extracted_symbol);
        CREATE INDEX IF NOT EXISTS idx_orders_sync_timestamp ON orders(sync_timestamp);
        CREATE INDEX IF NOT EXISTS idx_orders_action ON orders(action);
        CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);
    END IF;
END $$;

-- ==============================================
-- SnapTrade and Account Data
-- ==============================================

-- Account information
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'accounts' AND table_schema = 'public') THEN
        CREATE TABLE accounts (
            id TEXT PRIMARY KEY,
            brokerage_authorization TEXT,
            portfolio_group TEXT,
            name TEXT,
            number TEXT,
            institution_name TEXT,
            last_successful_sync TEXT,
            total_equity REAL,
            sync_timestamp TEXT NOT NULL
        );
        
        CREATE INDEX IF NOT EXISTS idx_accounts_institution_name ON accounts(institution_name);
        CREATE INDEX IF NOT EXISTS idx_accounts_sync_timestamp ON accounts(sync_timestamp);
    END IF;
END $$;

-- Account balances
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'account_balances' AND table_schema = 'public') THEN
        CREATE TABLE account_balances (
            id SERIAL PRIMARY KEY,
            account_id TEXT NOT NULL,
            currency_code TEXT NOT NULL,
            currency_name TEXT,
            currency_id TEXT,
            cash REAL,
            buying_power REAL,
            snapshot_date TEXT NOT NULL,
            sync_timestamp TEXT NOT NULL,
            UNIQUE(account_id, currency_code, snapshot_date)
        );
        
        CREATE INDEX IF NOT EXISTS idx_account_balances_account_id ON account_balances(account_id);
        CREATE INDEX IF NOT EXISTS idx_account_balances_snapshot_date ON account_balances(snapshot_date);
    END IF;
END $$;

-- Symbol definitions and metadata
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'symbols' AND table_schema = 'public') THEN
        CREATE TABLE symbols (
            id TEXT PRIMARY KEY,
            ticker TEXT,
            description TEXT,
            asset_type TEXT,
            type_code TEXT,
            exchange_code TEXT,
            exchange_name TEXT,
            exchange_mic TEXT,
            figi_code TEXT,
            raw_symbol TEXT,
            logo_url TEXT,
            base_currency_code TEXT,
            is_supported BOOLEAN DEFAULT TRUE,
            is_quotable BOOLEAN DEFAULT TRUE,
            is_tradable BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        
        CREATE INDEX IF NOT EXISTS idx_symbols_ticker ON symbols(ticker);
        CREATE INDEX IF NOT EXISTS idx_symbols_exchange_code ON symbols(exchange_code);
        CREATE INDEX IF NOT EXISTS idx_symbols_asset_type ON symbols(asset_type);
    END IF;
END $$;

-- ==============================================
-- Chart and Visualization Data
-- ==============================================

-- Chart generation metadata
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'chart_metadata' AND table_schema = 'public') THEN
        CREATE TABLE chart_metadata (
            id SERIAL PRIMARY KEY,
            symbol TEXT NOT NULL,
            period TEXT NOT NULL,
            interval TEXT NOT NULL,
            theme TEXT NOT NULL,
            file_path TEXT NOT NULL,
            trade_count INTEGER DEFAULT 0,
            min_trade_size REAL DEFAULT 0.0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        
        CREATE INDEX IF NOT EXISTS idx_chart_metadata_symbol ON chart_metadata(symbol);
        CREATE INDEX IF NOT EXISTS idx_chart_metadata_created_at ON chart_metadata(created_at);
    END IF;
END $$;

-- Stock charts (legacy)
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'stock_charts' AND table_schema = 'public') THEN
        CREATE TABLE stock_charts (
            id SERIAL PRIMARY KEY,
            symbol TEXT NOT NULL,
            period TEXT NOT NULL,
            interval TEXT NOT NULL,
            theme TEXT NOT NULL,
            file_path TEXT NOT NULL,
            created_at TEXT NOT NULL,
            trade_count INTEGER DEFAULT 0,
            min_trade_size REAL DEFAULT 0.0,
            UNIQUE(symbol, period, interval, theme, created_at)
        );
        
        CREATE INDEX IF NOT EXISTS idx_stock_charts_symbol ON stock_charts(symbol);
        CREATE INDEX IF NOT EXISTS idx_stock_charts_created_at ON stock_charts(created_at);
    END IF;
END $$;

-- ==============================================
-- Discord Processing Legacy Tables
-- ==============================================

-- Discord processing log (for backward compatibility)
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'discord_processing_log' AND table_schema = 'public') THEN
        CREATE TABLE discord_processing_log (
            id SERIAL PRIMARY KEY,
            message_id TEXT NOT NULL,
            channel TEXT NOT NULL,
            processed_date TEXT NOT NULL,
            processed_file TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        
        CREATE INDEX IF NOT EXISTS idx_discord_processing_log_message_id ON discord_processing_log(message_id);
        CREATE INDEX IF NOT EXISTS idx_discord_processing_log_channel ON discord_processing_log(channel);
    END IF;
END $$;

-- ==============================================
-- Schema Metadata
-- ==============================================

-- Track schema version and migrations
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'schema_migrations' AND table_schema = 'public') THEN
        CREATE TABLE schema_migrations (
            version TEXT PRIMARY KEY,
            applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            description TEXT
        );
        
        -- Insert this schema version
        INSERT INTO schema_migrations (version, description) 
        VALUES ('001_base', 'Base schema with all tables') 
        ON CONFLICT (version) DO NOTHING;
    END IF;
END $$;