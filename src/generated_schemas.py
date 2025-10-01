"""
Generated dataclass schemas from SSOT baseline SQL schema.
Auto-generated on September 30, 2025
Total tables: 16
"""
from dataclasses import dataclass
from datetime import datetime, date, time
from decimal import Decimal
from typing import Optional, List, Union, Dict, Any

# JSON type for proper JSONB mapping
JSON = Union[Dict[str, Any], List[Any]]


@dataclass
class AccountBalances:
    """Data model for account_balances table."""
    account_id: str
    currency_code: str
    snapshot_date: str
    buying_power: Optional[float]
    cash: Optional[float]
    currency_id: Optional[str]
    currency_name: Optional[str]
    sync_timestamp: str

@dataclass
class Accounts:
    """Data model for accounts table."""
    id: str
    brokerage_authorization: Optional[str]
    institution_name: Optional[str]
    last_successful_sync: Optional[str]
    name: Optional[str]
    number: Optional[str]
    portfolio_group: Optional[str]
    sync_timestamp: str
    total_equity: Optional[float]

@dataclass
class ChartMetadata:
    """Data model for chart_metadata table."""
    symbol: str
    period: str
    interval: str
    theme: str
    created_at: Optional[datetime]
    file_path: str
    min_trade_size: Optional[float]
    trade_count: Optional[int]

@dataclass
class DailyPrices:
    """Data model for daily_prices table."""
    symbol: str
    date: str
    close: Optional[float]
    dividends: Optional[float]
    high: Optional[float]
    low: Optional[float]
    open: Optional[float]
    stock_splits: Optional[float]
    volume: Optional[int]

@dataclass
class DiscordMarketClean:
    """Data model for discord_market_clean table."""
    message_id: str
    author: str
    cleaned_content: Optional[str]
    content: str
    processed_at: Optional[datetime]
    sentiment: Optional[float]
    timestamp: str

@dataclass
class DiscordMessages:
    """Data model for discord_messages table."""
    message_id: str
    author: str
    author_id: Optional[int]
    channel: str
    content: str
    created_at: Optional[datetime]
    is_reply: Optional[bool]
    mentions: Optional[str]
    num_chars: Optional[int]
    num_words: Optional[int]
    reply_to_id: Optional[int]
    sentiment_score: Optional[Decimal]
    tickers_detected: Optional[str]
    timestamp: str
    tweet_urls: Optional[str]
    user_id: Optional[str]

@dataclass
class DiscordProcessingLog:
    """Data model for discord_processing_log table."""
    message_id: str
    channel: str
    created_at: Optional[datetime]
    processed_date: str
    processed_file: Optional[str]

@dataclass
class DiscordTradingClean:
    """Data model for discord_trading_clean table."""
    message_id: str
    author: str
    cleaned_content: Optional[str]
    content: str
    processed_at: Optional[datetime]
    sentiment: Optional[float]
    stock_mentions: Optional[str]
    timestamp: str

@dataclass
class Orders:
    """Data model for orders table."""
    brokerage_order_id: str
    account_id: Optional[str]
    action: str
    canceled_quantity: Optional[Decimal]
    child_brokerage_order_ids: Optional[List[str]]
    created_at: Optional[datetime]
    diary: Optional[str]
    execution_price: Optional[Decimal]
    expiry_date: Optional[date]
    filled_quantity: Optional[Decimal]
    limit_price: Optional[Decimal]
    open_quantity: Optional[Decimal]
    option_expiry: Optional[date]
    option_right: Optional[str]
    option_strike: Optional[Decimal]
    option_ticker: Optional[str]
    order_type: Optional[str]
    parent_brokerage_order_id: Optional[str]
    quote_currency_code: Optional[str]
    state: Optional[str]
    status: str
    stop_price: Optional[Decimal]
    symbol: str
    sync_timestamp: Optional[str]
    time_executed: Optional[datetime]
    time_in_force: Optional[str]
    time_placed: Optional[datetime]
    time_updated: Optional[datetime]
    total_quantity: Optional[Decimal]
    updated_at: Optional[datetime]
    user_id: Optional[str]
    user_secret: Optional[str]

@dataclass
class Positions:
    """Data model for positions table."""
    symbol: str
    account_id: str
    asset_type: Optional[str]
    average_buy_price: Optional[float]
    created_at: Optional[datetime]
    currency: Optional[str]
    equity: Optional[float]
    exchange_code: Optional[str]
    exchange_name: Optional[str]
    figi_code: Optional[str]
    is_quotable: Optional[bool]
    is_tradable: Optional[bool]
    logo_url: Optional[str]
    mic_code: Optional[str]
    open_pnl: Optional[float]
    price: Optional[float]
    quantity: Optional[Decimal]
    symbol_description: Optional[str]
    symbol_id: Optional[str]
    sync_timestamp: Optional[str]

@dataclass
class ProcessingStatus:
    """Data model for processing_status table."""
    message_id: str
    channel: str
    processed_for_cleaning: Optional[bool]
    processed_for_twitter: Optional[bool]
    updated_at: Optional[datetime]

@dataclass
class RealtimePrices:
    """Data model for realtime_prices table."""
    symbol: str
    timestamp: str
    abs_change: Optional[float]
    percent_change: Optional[float]
    previous_close: Optional[float]
    price: Optional[float]

@dataclass
class SchemaMigrations:
    """Data model for schema_migrations table."""
    version: str
    applied_at: Optional[datetime]
    description: Optional[str]

@dataclass
class StockMetrics:
    """Data model for stock_metrics table."""
    date: str
    symbol: str
    dividend_yield: Optional[float]
    fifty_day_avg: Optional[float]
    market_cap: Optional[float]
    pe_ratio: Optional[float]
    two_hundred_day_avg: Optional[float]

@dataclass
class Symbols:
    """Data model for symbols table."""
    id: str
    asset_type: Optional[str]
    base_currency_code: Optional[str]
    created_at: Optional[datetime]
    description: Optional[str]
    exchange_code: Optional[str]
    exchange_mic: Optional[str]
    exchange_name: Optional[str]
    figi_code: Optional[str]
    is_quotable: Optional[bool]
    is_supported: Optional[bool]
    is_tradable: Optional[bool]
    logo_url: Optional[str]
    market_close_time: Optional[time]
    market_open_time: Optional[time]
    raw_symbol: Optional[str]
    ticker: Optional[str]
    timezone: Optional[str]
    type_code: Optional[str]
    updated_at: Optional[datetime]

@dataclass
class TwitterData:
    """Data model for twitter_data table."""
    tweet_id: str
    author: str
    author_name: Optional[str]
    author_username: Optional[str]
    channel: str
    content: str
    created_at: Optional[datetime]
    discord_date: str
    discord_message_id: Optional[str]
    discord_sent_date: Optional[str]
    like_count: Optional[int]
    message_id: str
    quote_count: Optional[int]
    reply_count: Optional[int]
    retrieved_at: Optional[str]
    retweet_count: Optional[int]
    source_url: Optional[str]
    stock_tags: Optional[str]
    tweet_content: Optional[str]
    tweet_created_date: Optional[str]
    tweet_date: Optional[str]
