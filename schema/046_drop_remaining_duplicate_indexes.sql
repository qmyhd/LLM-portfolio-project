-- Migration 046: Drop remaining duplicate indexes
-- ================================================
-- These regular indexes are redundant because they duplicate their table's 
-- PRIMARY KEY index or UNIQUE constraint index on the same column.
--
-- Reference: Follow-up to migration 044, found via thorough audit

-- orders: idx_orders_brokerage_order_id duplicates orders_pkey
-- Both are btree on brokerage_order_id - the PK already provides this
DROP INDEX IF EXISTS idx_orders_brokerage_order_id;

-- symbols: idx_symbols_ticker duplicates symbols_ticker_unique
-- Both are btree on ticker - the unique constraint already provides this
DROP INDEX IF EXISTS idx_symbols_ticker;

-- twitter_data: idx_twitter_data_tweet_id duplicates twitter_data_pkey  
-- Both are btree on tweet_id - the PK already provides this
DROP INDEX IF EXISTS idx_twitter_data_tweet_id;

-- NOTE: discord_messages parse_status indexes are NOT duplicates:
-- - idx_discord_messages_parse_status: WHERE (parse_status = 'pending')
-- - idx_discord_messages_parse_errors: WHERE (parse_status = 'error')
-- These are PARTIAL indexes serving different query patterns.
