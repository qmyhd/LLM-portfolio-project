-- Migration 048: Drop unused indexes on deprecated/unused NLP tables
-- These tables are from the deprecated SetFit-based NLP pipeline
-- The new pipeline uses discord_parsed_ideas with message_id queries only
--
-- Performance impact: Reduces write overhead for INSERT/UPDATE operations
-- Space savings: ~100KB+ of index storage freed
-- Risk: LOW - these indexes have never been used according to pg_stat_user_indexes

-- =============================================================================
-- DROP INDEXES ON: discord_message_chunks (deprecated)
-- =============================================================================
DROP INDEX IF EXISTS idx_chunks_symbols_detected_gin;
DROP INDEX IF EXISTS idx_chunks_context_tickers_gin;
DROP INDEX IF EXISTS idx_chunks_gate_to_extraction;
DROP INDEX IF EXISTS idx_chunks_chunk_type;
DROP INDEX IF EXISTS idx_chunks_section_title_type;
DROP INDEX IF EXISTS idx_chunks_unclassified;
DROP INDEX IF EXISTS idx_chunks_labels;
DROP INDEX IF EXISTS idx_chunks_llm_tagged;
DROP INDEX IF EXISTS idx_chunks_labeled;
DROP INDEX IF EXISTS idx_chunks_gold_intents;

-- =============================================================================
-- DROP INDEXES ON: stock_mentions (deprecated)
-- =============================================================================
DROP INDEX IF EXISTS idx_stock_mentions_sentiment;
DROP INDEX IF EXISTS idx_stock_mentions_symbol;
DROP INDEX IF EXISTS idx_stock_mentions_message_id;
DROP INDEX IF EXISTS idx_stock_mentions_action;
DROP INDEX IF EXISTS idx_stock_mentions_created_at;
DROP INDEX IF EXISTS idx_stock_mentions_model_version;
DROP INDEX IF EXISTS idx_stock_mentions_mention_kind;
DROP INDEX IF EXISTS idx_stock_mentions_instrument;
DROP INDEX IF EXISTS idx_stock_mentions_side;
DROP INDEX IF EXISTS idx_stock_mentions_chunk;
DROP INDEX IF EXISTS idx_stock_mentions_levels_gin;
DROP INDEX IF EXISTS idx_stock_mentions_options_gin;

-- =============================================================================
-- DROP INDEXES ON: discord_idea_units (deprecated)
-- =============================================================================
DROP INDEX IF EXISTS idx_idea_units_subject_symbol;
DROP INDEX IF EXISTS idx_idea_units_subject_type;
DROP INDEX IF EXISTS idx_idea_units_idea_type;
DROP INDEX IF EXISTS idx_idea_units_unlabeled;
DROP INDEX IF EXISTS idx_idea_units_source;

-- =============================================================================
-- DROP INDEXES ON: discord_parsed_ideas (active but semantics unused)
-- Keep: unique constraint and FK index on message_id
-- =============================================================================
DROP INDEX IF EXISTS idx_parsed_ideas_primary_symbol;
DROP INDEX IF EXISTS idx_parsed_ideas_direction;
DROP INDEX IF EXISTS idx_parsed_ideas_action;
DROP INDEX IF EXISTS idx_parsed_ideas_time_horizon;
DROP INDEX IF EXISTS idx_parsed_ideas_instrument;
DROP INDEX IF EXISTS idx_parsed_ideas_labels;
DROP INDEX IF EXISTS idx_parsed_ideas_symbols;
DROP INDEX IF EXISTS idx_parsed_ideas_noise;
DROP INDEX IF EXISTS idx_parsed_ideas_parsed_at;
DROP INDEX IF EXISTS idx_parsed_ideas_source_created;
DROP INDEX IF EXISTS idx_parsed_ideas_options;

-- =============================================================================
-- DROP UNUSED INDEXES ON: Other tables
-- =============================================================================
-- discord_messages: Keep only essential indexes
DROP INDEX IF EXISTS idx_discord_messages_author_id;
DROP INDEX IF EXISTS idx_discord_messages_user_id;
DROP INDEX IF EXISTS idx_discord_messages_author;
DROP INDEX IF EXISTS idx_discord_messages_parse_errors;

-- orders: Drop option-specific indexes (no options data yet)
DROP INDEX IF EXISTS idx_orders_option_ticker;
DROP INDEX IF EXISTS idx_orders_option_expiry;
DROP INDEX IF EXISTS idx_orders_time_placed;
DROP INDEX IF EXISTS idx_orders_created_at;

-- trade_history: Table is empty, indexes unused
DROP INDEX IF EXISTS idx_trade_history_symbol;
DROP INDEX IF EXISTS idx_trade_history_account;
DROP INDEX IF EXISTS idx_trade_history_date;
DROP INDEX IF EXISTS idx_trade_history_type;

-- institutional_holdings: Table unused
DROP INDEX IF EXISTS idx_institutional_holdings_cusip;
DROP INDEX IF EXISTS idx_institutional_holdings_manager;
DROP INDEX IF EXISTS idx_institutional_holdings_ticker;

-- Various single-column indexes that duplicate PK coverage
DROP INDEX IF EXISTS idx_daily_prices_date;
DROP INDEX IF EXISTS idx_realtime_prices_timestamp;
DROP INDEX IF EXISTS idx_stock_metrics_date;
DROP INDEX IF EXISTS idx_discord_processing_log_processed_date;
DROP INDEX IF EXISTS idx_discord_processing_log_message_id;
DROP INDEX IF EXISTS idx_discord_processing_log_channel;
DROP INDEX IF EXISTS idx_discord_market_clean_timestamp;
DROP INDEX IF EXISTS idx_discord_trading_clean_stock_mentions;
DROP INDEX IF EXISTS idx_symbols_timezone;
DROP INDEX IF EXISTS idx_symbols_exchange_code;
DROP INDEX IF EXISTS idx_symbols_asset_type;
DROP INDEX IF EXISTS idx_twitter_data_has_media;
DROP INDEX IF EXISTS idx_twitter_data_discord_message_id;
DROP INDEX IF EXISTS idx_twitter_data_message_id;
DROP INDEX IF EXISTS idx_accounts_institution_name;
DROP INDEX IF EXISTS idx_account_balances_account_id;
DROP INDEX IF EXISTS idx_event_contract_trades_date;
DROP INDEX IF EXISTS idx_event_contract_trades_symbol;
DROP INDEX IF EXISTS idx_event_contract_positions_date;
DROP INDEX IF EXISTS idx_event_contract_positions_symbol;
