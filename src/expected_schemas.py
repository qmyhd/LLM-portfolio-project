"""
Generated EXPECTED_SCHEMAS dictionary from SSOT baseline.
Auto-generated on September 30, 2025
This provides compatibility with verify_schemas.py and other validation scripts.
"""
from typing import Dict, Any, List

# Expected schema definitions for validation scripts
EXPECTED_SCHEMAS: Dict[str, Dict[str, Any]] = {
    "account_balances": {
        "required_fields": {
            "account_id": "text",
            "buying_power": "numeric",
            "cash": "numeric",
            "currency_code": "text",
            "currency_id": "text",
            "currency_name": "text",
            "snapshot_date": "date",
            "sync_timestamp": "timestamptz",
        },
        "primary_keys": ['currency_code', 'snapshot_date', 'account_id'],
        "description": "Auto-generated from account_balances table"
    },
    "accounts": {
        "required_fields": {
            "brokerage_authorization": "text",
            "id": "text",
            "institution_name": "text",
            "last_successful_sync": "timestamptz",
            "name": "text",
            "number": "text",
            "portfolio_group": "text",
            "sync_timestamp": "timestamptz",
            "total_equity": "numeric",
        },
        "primary_keys": ['id'],
        "description": "Auto-generated from accounts table"
    },
    "chart_metadata": {
        "required_fields": {
            "created_at": "timestamp",
            "file_path": "text",
            "interval": "text",
            "min_trade_size": "numeric",
            "period": "text",
            "symbol": "text",
            "theme": "text",
            "trade_count": "integer",
        },
        "primary_keys": ['symbol', 'period', 'interval', 'theme'],
        "description": "Auto-generated from chart_metadata table"
    },
    "daily_prices": {
        "required_fields": {
            "close": "numeric",
            "date": "date",
            "dividends": "numeric",
            "high": "numeric",
            "low": "numeric",
            "open": "numeric",
            "stock_splits": "numeric",
            "symbol": "text",
            "volume": "integer",
        },
        "primary_keys": ['date', 'symbol'],
        "description": "Auto-generated from daily_prices table"
    },
    "discord_market_clean": {
        "required_fields": {
            "author": "text",
            "cleaned_content": "text",
            "content": "text",
            "message_id": "text",
            "processed_at": "timestamp",
            "sentiment": "numeric",
            "timestamp": "text",
        },
        "primary_keys": ['message_id'],
        "description": "Auto-generated from discord_market_clean table"
    },
    "discord_messages": {
        "required_fields": {
            "author": "text",
            "author_id": "bigint",
            "channel": "text",
            "content": "text",
            "created_at": "timestamp",
            "is_reply": "boolean",
            "mentions": "text",
            "message_id": "text",
            "num_chars": "integer",
            "num_words": "integer",
            "reply_to_id": "bigint",
            "sentiment_score": "numeric",
            "tickers_detected": "text",
            "timestamp": "text",
            "tweet_urls": "text",
            "user_id": "text",
        },
        "primary_keys": ['message_id'],
        "description": "Auto-generated from discord_messages table"
    },
    "discord_processing_log": {
        "required_fields": {
            "channel": "text",
            "created_at": "timestamp",
            "message_id": "text",
            "processed_date": "date",
            "processed_file": "text",
        },
        "primary_keys": ['message_id', 'channel'],
        "description": "Auto-generated from discord_processing_log table"
    },
    "discord_trading_clean": {
        "required_fields": {
            "author": "text",
            "cleaned_content": "text",
            "content": "text",
            "message_id": "text",
            "processed_at": "timestamp",
            "sentiment": "numeric",
            "stock_mentions": "text",
            "timestamp": "text",
        },
        "primary_keys": ['message_id'],
        "description": "Auto-generated from discord_trading_clean table"
    },
    "orders": {
        "required_fields": {
            "account_id": "text",
            "action": "text",
            "brokerage_order_id": "text",
            "canceled_quantity": "numeric",
            "child_brokerage_order_ids": "json",
            "created_at": "timestamp",
            "diary": "text",
            "execution_price": "numeric",
            "expiry_date": "date",
            "filled_quantity": "numeric",
            "limit_price": "numeric",
            "open_quantity": "numeric",
            "option_expiry": "date",
            "option_right": "text",
            "option_strike": "numeric",
            "option_ticker": "text",
            "order_type": "text",
            "parent_brokerage_order_id": "text",
            "quote_currency_code": "text",
            "state": "text",
            "status": "text",
            "stop_price": "numeric",
            "symbol": "text",
            "sync_timestamp": "timestamptz",
            "time_executed": "timestamp",
            "time_in_force": "text",
            "time_placed": "timestamp",
            "time_updated": "timestamp",
            "total_quantity": "numeric",
            "updated_at": "timestamp",
            "user_id": "text",
            "user_secret": "text",
        },
        "primary_keys": ['brokerage_order_id'],
        "description": "Auto-generated from orders table"
    },
    "positions": {
        "required_fields": {
            "account_id": "text",
            "asset_type": "text",
            "average_buy_price": "numeric",
            "created_at": "timestamp",
            "currency": "text",
            "equity": "numeric",
            "exchange_code": "text",
            "exchange_name": "text",
            "figi_code": "text",
            "is_quotable": "boolean",
            "is_tradable": "boolean",
            "logo_url": "text",
            "mic_code": "text",
            "open_pnl": "numeric",
            "price": "numeric",
            "quantity": "numeric",
            "symbol": "text",
            "symbol_description": "text",
            "symbol_id": "text",
            "sync_timestamp": "timestamptz",
        },
        "primary_keys": ['symbol', 'account_id'],
        "description": "Auto-generated from positions table"
    },
    "processing_status": {
        "required_fields": {
            "channel": "text",
            "message_id": "text",
            "processed_for_cleaning": "boolean",
            "processed_for_twitter": "boolean",
            "updated_at": "timestamp",
        },
        "primary_keys": ['message_id'],
        "description": "Auto-generated from processing_status table"
    },
    "realtime_prices": {
        "required_fields": {
            "abs_change": "numeric",
            "percent_change": "numeric",
            "previous_close": "numeric",
            "price": "numeric",
            "symbol": "text",
            "timestamp": "timestamptz",
        },
        "primary_keys": ['timestamp', 'symbol'],
        "description": "Auto-generated from realtime_prices table"
    },
    "schema_migrations": {
        "required_fields": {
            "applied_at": "timestamp",
            "description": "text",
            "version": "text",
        },
        "primary_keys": ['version'],
        "description": "Auto-generated from schema_migrations table"
    },
    "stock_metrics": {
        "required_fields": {
            "date": "date",
            "dividend_yield": "numeric",
            "fifty_day_avg": "numeric",
            "market_cap": "numeric",
            "pe_ratio": "numeric",
            "symbol": "text",
            "two_hundred_day_avg": "numeric",
        },
        "primary_keys": ['date', 'symbol'],
        "description": "Auto-generated from stock_metrics table"
    },
    "symbols": {
        "required_fields": {
            "asset_type": "text",
            "base_currency_code": "text",
            "created_at": "timestamp",
            "description": "text",
            "exchange_code": "text",
            "exchange_mic": "text",
            "exchange_name": "text",
            "figi_code": "text",
            "id": "text",
            "is_quotable": "boolean",
            "is_supported": "boolean",
            "is_tradable": "boolean",
            "logo_url": "text",
            "market_close_time": "time",
            "market_open_time": "time",
            "raw_symbol": "text",
            "ticker": "text",
            "timezone": "text",
            "type_code": "text",
            "updated_at": "timestamp",
        },
        "primary_keys": ['id'],
        "description": "Auto-generated from symbols table"
    },
    "twitter_data": {
        "required_fields": {
            "author": "text",
            "author_name": "text",
            "author_username": "text",
            "channel": "text",
            "content": "text",
            "created_at": "timestamp",
            "discord_date": "timestamptz",
            "discord_message_id": "text",
            "discord_sent_date": "timestamptz",
            "like_count": "integer",
            "message_id": "text",
            "quote_count": "integer",
            "reply_count": "integer",
            "retrieved_at": "text",
            "retweet_count": "integer",
            "source_url": "text",
            "stock_tags": "text",
            "tweet_content": "text",
            "tweet_created_date": "timestamptz",
            "tweet_date": "timestamptz",
            "tweet_id": "text",
        },
        "primary_keys": ['tweet_id'],
        "description": "Auto-generated from twitter_data table"
    },
}

# Schema metadata for reference
SCHEMA_METADATA = {
    "generated_at": "2025-09-19",
    "source_files": ['000_baseline.sql', '015_primary_key_alignment.sql', '016_complete_rls_policies.sql', '017_timestamp_field_migration.sql', '018_cleanup_schema_drift.sql'],
    "table_count": 16,
    "total_columns": 184
}