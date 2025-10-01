"""
Discord Processing Architecture Summary

This document outlines the consolidated Discord message processing system with
table renaming and architecture improvements.

DISCORD TABLE ARCHITECTURE:
- discord_market_clean (PRIMARY) - For all general market discussion messages
- discord_trading_clean (SECONDARY) - For trading-specific messages

PROCESSING FLOW:
1. Raw messages stored in: discord_messages
2. Processed through: message_cleaner.py (core logic)
3. Coordinated by: channel_processor.py (production wrapper)
4. Written to: discord_market_clean OR discord_trading_clean

FILE RESPONSIBILITIES:

src/message_cleaner.py (CORE CLEANING ENGINE):
- extract_ticker_symbols() - Parse $TICKER mentions
- clean_text() - Remove URLs, mentions, normalize content
- calculate_sentiment() - TextBlob sentiment analysis
- clean_messages() - Main processing pipeline
- save_to_parquet() - Parquet file output
- save_to_database() - Database table output
- process_messages_for_channel() - Complete processing pipeline

src/channel_processor.py (PRODUCTION COORDINATOR):
- process_channel_data() - Orchestrates message processing
- get_channel_stats() - Provides processing statistics
- Delegates ALL cleaning to message_cleaner.py
- Handles unprocessed message tracking

src/snaptrade_collector.py (SNAPTRADE API INTEGRATION):
- get_accounts() - SnapTrade account data
- get_balances() - Account balance information  
- get_positions() - Portfolio positions
- get_orders() - Trading order history
- SnapTrade client initialization and field extraction

TABLE USAGE MAPPING:
- discord_messages: Raw Discord messages (source)
- discord_market_clean: Processed general market messages (primary output)
- discord_trading_clean: Processed trading-specific messages (secondary output)
- twitter_data: Tweet analysis from Discord links
- positions: SnapTrade portfolio positions
- orders: SnapTrade trading orders
- accounts: SnapTrade account information
- account_balances: SnapTrade balance data
- symbols: SnapTrade symbol metadata
- daily_prices: Historical price data (yfinance)
- realtime_prices: Current price data (yfinance)  
- stock_metrics: Fundamental metrics (yfinance)
- processing_status: Message processing tracking
- chart_metadata: Chart generation metadata

WRITE HELPERS:
- message_cleaner.py provides save_to_parquet() and save_to_database()
- Both functions handle dual output (files + database)
- Automatic table selection based on channel_type parameter
- Built-in deduplication and error handling

CHANNEL TYPE MAPPING:
- channel_type="general" → discord_market_clean
- channel_type="trading" → discord_trading_clean

DATABASE RENAME REQUIRED:
Run scripts/rename_discord_table.sql in Supabase to rename:
discord_general_clean → discord_market_clean
"""
