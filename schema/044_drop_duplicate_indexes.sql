-- Migration 044: Drop duplicate indexes and constraints
-- ======================================================
-- These UNIQUE CONSTRAINTs are redundant because they duplicate their table's 
-- PRIMARY KEY constraint on the same column(s).
-- The PK already enforces uniqueness, so the extra UNIQUE constraint is wasteful.
--
-- Reference: Supabase Advisor flagged these as duplicate indexes

-- Step 1: Drop FK that depends on discord_messages_message_id_unique
-- (FK will be recreated to point to the PK index instead)
ALTER TABLE public.discord_parsed_ideas 
    DROP CONSTRAINT IF EXISTS fk_discord_parsed_ideas_message;

-- Step 2: Drop duplicate UNIQUE CONSTRAINTS that match PK constraints exactly
-- (These are constraints, not just indexes, so use ALTER TABLE DROP CONSTRAINT)

-- chart_metadata: _unique duplicates _pkey (same 4 columns)
ALTER TABLE public.chart_metadata 
    DROP CONSTRAINT IF EXISTS chart_metadata_symbol_period_interval_theme_unique;

-- discord_market_clean: _unique duplicates _pkey (message_id)
ALTER TABLE public.discord_market_clean 
    DROP CONSTRAINT IF EXISTS discord_market_clean_message_id_unique;

-- discord_messages: _unique duplicates _pkey (message_id)
ALTER TABLE public.discord_messages 
    DROP CONSTRAINT IF EXISTS discord_messages_message_id_unique;

-- discord_processing_log: _unique duplicates _pkey (message_id, channel)
ALTER TABLE public.discord_processing_log 
    DROP CONSTRAINT IF EXISTS discord_processing_log_message_id_channel_unique;

-- discord_trading_clean: _unique duplicates _pkey (message_id)
ALTER TABLE public.discord_trading_clean 
    DROP CONSTRAINT IF EXISTS discord_trading_clean_message_id_unique;

-- orders: _unique duplicates _pkey (brokerage_order_id)
ALTER TABLE public.orders 
    DROP CONSTRAINT IF EXISTS orders_brokerage_order_id_unique;

-- twitter_data: _unique duplicates _pkey (tweet_id)
ALTER TABLE public.twitter_data 
    DROP CONSTRAINT IF EXISTS twitter_data_tweet_id_unique;

-- Step 3: Recreate FK pointing to PK (which uses discord_messages_pkey)
ALTER TABLE public.discord_parsed_ideas 
    ADD CONSTRAINT fk_discord_parsed_ideas_message 
    FOREIGN KEY (message_id) REFERENCES public.discord_messages(message_id) 
    ON DELETE CASCADE;

-- Step 4: Drop duplicate regular INDEXES (not constraints)

-- discord_parsed_ideas: idx_discord_parsed_ideas_message_id duplicates idx_parsed_ideas_message
-- Both are btree indexes on message_id - keep the shorter name
DROP INDEX IF EXISTS idx_discord_parsed_ideas_message_id;

-- discord_parsed_ideas: idx_parsed_ideas_message_chunks duplicates unique constraint index
-- discord_parsed_ideas_message_chunk_idx_key is the unique constraint on same columns
DROP INDEX IF EXISTS idx_parsed_ideas_message_chunks;
