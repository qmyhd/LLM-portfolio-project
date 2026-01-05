# API Reference Documentation

## Core Modules

### Data Collection

#### `src.data_collector`

Primary market data collection module with yfinance integration and CSV handling.

**Key Functions:**
- `fetch_realtime_prices(symbols=None)` → DataFrame: Get current market prices
- `extract_symbol_from_data(data, fallback_key='symbol')` → str: Extract ticker from nested data
- `save_positions_to_csv(positions_data, csv_path)`: Save portfolio positions
- `save_orders_to_csv(orders_data, csv_path)`: Save order history

#### `src.snaptrade_collector`

**Class: `SnapTradeCollector`**

SnapTrade API integration with field extraction and database persistence.

**Constructor:**
```python
SnapTradeCollector(user_id: str = "default_user", enable_parquet: bool = False)
```

**Key Methods:**
- `get_accounts()` → DataFrame: Retrieve account information
- `get_balances()` → DataFrame: Get account balances and cash positions  
- `get_positions()` → DataFrame: Current portfolio positions
- `get_orders()` → DataFrame: Order history with execution details
- `get_all_data()` → Dict: Data collection from all endpoints
- `upsert_accounts_table(accounts_data)` → bool: Database persistence for accounts
- `upsert_balances_table(balances_data)` → bool: Database persistence for balances
- `upsert_positions_table(positions_data)` → bool: Database persistence for positions
- `upsert_orders_table(orders_data)` → bool: Database persistence for orders

**Field Extraction Functions:**
- `safely_extract_account_data(response)` → List[Dict]: Safe account data extraction
- `safely_extract_balance_data(response)` → List[Dict]: Safe balance data extraction  
- `safely_extract_position_data(response)` → List[Dict]: Safe position data extraction
- `safely_extract_order_data(response)` → List[Dict]: Safe order data extraction

#### `src.message_cleaner`

Discord message cleaning and processing.

**Key Functions:**
- `extract_ticker_symbols(text)` → List[str]: Extract $TICKER symbols from text
- `clean_messages(messages, channel_type="general")` → DataFrame: Clean message content with sentiment analysis
- `save_to_database(df, table_name, connection)` → bool: Save cleaned data to database
- `save_to_parquet(df, file_path)` → bool: Save cleaned data to Parquet format
- `process_messages_for_channel(messages, channel_name, channel_type)`: Complete processing pipeline

#### `src.channel_processor`

Production wrapper for Discord message processing.

**Key Functions:**
- `process_channel_data(channel_name, channel_type="general")` → Dict: Fetch → clean → write pipeline
- `parse_messages_with_llm(message_ids=None, limit=100)` → Dict: LLM parsing pipeline

### Database Management

#### `src.db`

PostgreSQL database engine with SQLAlchemy 2.0 and connection pooling.

**Key Functions:**
- `get_sync_engine()`: Get synchronous SQLAlchemy engine with pooling
- `get_async_engine()`: Get asynchronous SQLAlchemy engine  
- `get_connection()`: Get database connection from engine
- `execute_sql(query, params=None, fetch_results=False)`: Execute SQL with parameter binding
- `execute_query(query, params=None)`: Execute query with connection management
- `test_connection()` → Dict: Connection testing
- `healthcheck()` → bool: Database health verification
- `get_database_size()` → str: Database size information
- `get_table_info(table_name)` → List: Table schema information
- `table_exists(table_name)` → bool: Check if table exists

#### `src.market_data`

Portfolio and trade data queries.

**Key Functions:**
- `get_positions()` → DataFrame: All current portfolio positions from latest sync
- `get_position(symbol)` → DataFrame: Specific position for given symbol
- `get_recent_trades(limit=50)` → DataFrame: Recent trade history
- `get_trades_for_symbol(symbol, limit=100)` → DataFrame: Symbol-specific trades
- `get_portfolio_summary()` → Dict: Portfolio summary with total equity and top holdings

### Message Processing

#### `src.message_cleaner`

Text processing and ticker extraction with sentiment analysis.

**Key Functions:**
- `extract_ticker_symbols(text)` → List[str]: Extract $TICKER symbols using regex
- `clean_text(text)` → str: Clean and normalize text content
- `calculate_sentiment(text)` → float: TextBlob sentiment analysis (-1.0 to 1.0)
- `process_messages_for_channel(messages, channel_type)` → DataFrame: Process message batch

**Regular Expressions:**
- `TICKER_PATTERN`: `r'\$[A-Z]{1,6}(?:\.[A-Z]+)?'` - Matches $AAPL, $BRK.B, etc.

#### `src.twitter_analysis`

Twitter/X integration with sentiment analysis.

**Key Functions:**
- `detect_twitter_links(text)` → List[str]: Extract Twitter/X URLs from text
- `extract_tweet_id(url)` → str: Get tweet ID from URL
- `analyze_sentiment(text)` → float: TextBlob sentiment analysis
- `fetch_tweet_data(tweet_id, twitter_client=None)`: Retrieve tweet data via API
- `process_tweet_for_stocks(tweet_data)` → Dict: Extract stock mentions from tweets

### Journal Generation

#### `src.journal_generator`

LLM integration for journal generation with dual output formats.

**Key Functions:**
- `main(force_refresh=False, output_dir=None)`: Primary journal generation entry point
- `create_journal_prompt(portfolio_data, market_data, sentiment_data)` → str: Basic LLM prompt
- `create_enhanced_journal_prompt(...)` → str: Detailed LLM prompt with full context
- `format_holdings_as_json(holdings_df)` → str: Format portfolio data for LLM
- `format_prices_as_json(prices_df)` → str: Format market data for LLM
- `call_llm_api(prompt, max_tokens=200)` → str: LLM API integration with fallback
- `save_journal_outputs(text_summary, markdown_report, output_dir)`: Save dual formats

**LLM Integration:**
- Primary: Gemini API (free tier)
- Fallback: OpenAI API
- Output: Plain text summary + detailed markdown report

### Bot Infrastructure

#### `src.bot.bot`

Discord bot entry point with Twitter client integration.

**Key Functions:**
- `main()`: Bot startup with configuration loading
- `create_bot(command_prefix="!", twitter_client=None)`: Bot factory function

#### `src.bot.events`

Event handlers for Discord message processing.

**Key Functions:**
- `register_events(bot, twitter_client=None)`: Register event handlers
- Events handled: `on_ready`, `on_message` with channel filtering

#### `src.bot.commands.chart`

**Class: `FIFOPositionTracker`**

FIFO position tracking for P/L calculation.

**Methods:**
- `add_buy(shares, price, date)`: Add buy order to position queue
- `process_sell(shares_sold, sell_price, sell_date)` → float: Calculate realized P/L
- `get_current_position()` → Tuple: Get current position and average cost

**Chart Functions:**
- `create_chart(symbol, period="6mo", chart_type="candle")` → Tuple: Generate charts
- `query_trade_data(symbol, start_date, end_date)` → DataFrame: Get trade history
- `calculate_fifo_metrics(trades_df)` → Dict: FIFO P/L calculations
- `create_price_chart(...)` → str: Generate price charts with overlays

#### `src.bot.commands.process`

Channel data processing commands with statistics.

**Commands:**
- `!process [channel_type]`: Process current channel messages
- `!stats`: Show current channel statistics  
- `!globalstats`: Show global processing statistics

#### `src.bot.commands.twitter_cmd`

Twitter data analysis commands.

**Commands:**
- `!twitter [symbol]`: Show Twitter data for symbol or general stats
- `!tweets [symbol] [count]`: Get recent tweets with stock mentions
- `!twitter_stats [channel]`: Detailed Twitter statistics

### Configuration & Utilities

#### `src.config`

Configuration management with Pydantic validation.

**Class: `Settings`**

**Key Attributes:**
- `DATABASE_URL`: PostgreSQL connection string
- `SUPABASE_URL`, `SUPABASE_KEY`: Supabase configuration
- `DISCORD_BOT_TOKEN`: Discord bot authentication
- `TWITTER_BEARER_TOKEN`: Twitter API authentication  
- `OPENAI_API_KEY`, `GEMINI_API_KEY`: LLM service keys
- `LOG_CHANNEL_IDS`: Discord channels to monitor

**Functions:**
- `settings()` → Settings: Get validated configuration instance with automatic key mapping
- `get_database_url(use_direct: bool = False)` → str: Get database URL with Transaction Pooler (default) or Direct connection
- `get_migration_database_url()` → str: Get optimized database URL for migration operations (direct connection)

**New Supabase Environment Variables:**
- `DATABASE_URL`: Transaction Pooler connection (port 6543) 
- `DATABASE_DIRECT_URL`: Direct connection (port 5432, non-pooling)
- `SUPABASE_SERVICE_ROLE_KEY`: Secret key (sb_secret_…) for server-side access
- `SUPABASE_ANON_KEY`: Publishable key (sb_publishable_…) for client-side access  
- `JWT_PUBLIC_KEY`: Public key from ECC (P-256) for JWT verification
- `JWT_PRIVATE_KEY`: Private key for server-side token signing (optional)

**Legacy Key Support (backward compatibility):**
- `anon_public` → `SUPABASE_ANON_KEY`
- `service_role` → `SUPABASE_SERVICE_ROLE_KEY`  
- `JWT_Secret_Key` → `JWT_SECRET`

#### `src.retry_utils`

Retry decorator with exception handling.

**Decorator:**
```python
@hardened_retry(max_retries=3, delay=1, backoff_multiplier=2.0)
def risky_operation():
    pass
```

**Features:**
- Exponential backoff with jitter
- Non-retryable exception detection (ArgumentError, ParserError, etc.)
- Comprehensive logging of retry attempts

#### `src.logging_utils`

Database logging utilities with Twitter integration.

**Key Functions:**
- `log_message_to_database(message, twitter_client=None)`: Persist Discord messages
- `log_message_to_file(message, discord_csv, tweet_csv, twitter_client)`: CSV logging

### ETL Pipeline

#### `src.etl.clean_csv`

**Class: `CSVCleaner`**

CSV cleaning with data validation.

**Constructor:**
```python
CSVCleaner(table_name: str)
```

**Methods:**
- `clean_csv(csv_path, output_path=None)` → DataFrame: CSV cleaning
- `_clean_numeric_column(series, col_name)` → Series: Safe numeric conversion
- `_clean_orders_table(df)` → DataFrame: Orders-specific cleaning rules
- `_clean_discord_table(df)` → DataFrame: Discord messages cleaning
- `_clean_positions_table(df)` → DataFrame: Positions cleaning

**Validation:**
- `validate_cleaned_data(df, table_name)` → bool: Data quality validation
- `VALID_ACTIONS`: Set of valid order actions to prevent SQL errors
- `NUMERIC_COLUMNS`: Column type definitions by table
- `REQUIRED_COLUMNS`: Required field validation

### Advanced Analytics

#### `src.position_analysis`

Position tracking and analytics.

**Key Functions:**
- `analyze_position_history(symbol, start_date, end_date)` → Dict: Position analysis
- `get_current_position_size(symbol)` → float: Current position size
- `calculate_unrealized_pnl(symbol)` → float: Unrealized profit/loss
- `generate_position_report(symbol)` → str: Position report

#### `src.chart_enhancements`

Enhanced charting functionality with position overlays.

**Key Functions:**
- `create_enhanced_chart_with_position_analysis(...)` → Tuple: Enhanced charts
- `add_position_markers(chart, position_data)`: Add position entry/exit markers
- `calculate_technical_indicators(price_data)` → Dict: Technical analysis

## Error Handling Patterns

### Standard Error Response Format
```python
{
    "success": bool,
    "error": str,
    "data": Any,
    "timestamp": str
}
```

### Common Exception Types
- `SnapTradeError`: SnapTrade API specific errors
- `DatabaseError`: Database connection and query errors  
- `ValidationError`: Data validation failures
- `ConfigurationError`: Missing or invalid configuration

## Data Formats

### Portfolio Position Schema
```python
{
    "symbol": str,
    "quantity": float,
    "equity": float, 
    "price": float,
    "average_buy_price": float,
    "type": str,
    "currency": str,
    "sync_timestamp": str,
    "calculated_equity": float
}
```

### Order Schema
```python
{
    "id": str,
    "symbol": str,
    "action": str,  # buy, sell, etc.
    "quantity": float,
    "price": float,
    "execution_price": float,
    "status": str,
    "timestamp": str
}
```

### Discord Message Schema
```python
{
    "message_id": str,
    "author": str,
    "content": str,
    "channel": str,
    "timestamp": str,
    "tickers": List[str],
    "sentiment_score": float
}
```

## Configuration Examples

### Environment Variables (.env)
```ini
# Database Configuration
DATABASE_URL=postgresql://user:pass@host:port/db
SUPABASE_URL=https://xxx.supabase.co
SUPABASE_KEY=eyJ...

# Discord Bot
DISCORD_BOT_TOKEN=NzY...
LOG_CHANNEL_IDS=123456789,987654321

# Twitter API  
TWITTER_BEARER_TOKEN=AAAA...

# LLM Services
OPENAI_API_KEY=sk-...
GEMINI_API_KEY=AIza...
```

### Database URLs
```ini
# PostgreSQL (Production)
DATABASE_URL=postgresql://user:password@localhost:5432/portfolio_db

# Supabase (Cloud)
DATABASE_URL=postgresql://user:password@db.supabase.co:5432/postgres
```
