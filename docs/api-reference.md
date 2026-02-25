# API Reference Documentation

## REST API (FastAPI)

The FastAPI application provides REST endpoints for the LLM Portfolio Journal frontend and integrations.

### Running the API Server

```bash
# Development (with auto-reload)
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

# Production (via Nginx reverse proxy)
uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 4
```

### Authentication

All endpoints (except `/health` and `/webhook/*`) require Bearer token authentication:

```
Authorization: Bearer <API_SECRET_KEY>
```

Set `API_SECRET_KEY` in your environment. In development, a default key is used if not set.

### Interactive Documentation

- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

---

## REST API Endpoints

### Health & Status

#### `GET /health`

Health check endpoint for monitoring and load balancers.

**Response:**

```json
{
  "status": "healthy",
  "timestamp": "2026-01-31T12:00:00Z",
  "database": "connected",
  "version": "1.0.0"
}
```

---

### Portfolio (`/portfolio`)

#### `GET /portfolio`

Get portfolio summary and all positions with current prices.

**Response Model:** `PortfolioResponse`

```json
{
  "summary": {
    "totalValue": 125000.0,
    "dayChange": 1250.0,
    "dayChangePercent": 1.01,
    "totalGainLoss": 15000.0,
    "totalGainLossPercent": 13.64,
    "cash": 5000.0,
    "buyingPower": 10000.0,
    "positionCount": 12
  },
  "positions": [
    {
      "symbol": "AAPL",
      "quantity": 100,
      "avgCost": 150.0,
      "currentPrice": 185.5,
      "marketValue": 18550.0,
      "dayChange": 125.0,
      "dayChangePercent": 0.68,
      "totalGainLoss": 3550.0,
      "totalGainLossPercent": 23.67,
      "portfolioWeight": 14.84
    }
  ],
  "lastUpdated": "2026-01-31T12:00:00Z"
}
```

#### `POST /portfolio/sync`

Trigger a SnapTrade sync to refresh portfolio data.

---

### Orders (`/orders`)

#### `GET /orders`

Get order history with optional filters.

**Query Parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `limit` | int | 50 | Number of orders (1-200) |
| `offset` | int | 0 | Pagination offset |
| `status` | string | null | Filter: `filled`, `pending`, `cancelled` |
| `ticker` | string | null | Filter by ticker symbol |
| `notified` | bool | null | Filter by Discord notification status |

**Response Model:** `OrdersResponse`

```json
{
  "orders": [
    {
      "id": "order-123",
      "symbol": "AAPL",
      "side": "buy",
      "type": "limit",
      "quantity": 100,
      "filledQuantity": 100,
      "price": 150.0,
      "filledPrice": 149.95,
      "status": "filled",
      "createdAt": "2026-01-30T10:00:00Z",
      "filledAt": "2026-01-30T10:05:00Z",
      "notified": true
    }
  ],
  "total": 156,
  "hasMore": true
}
```

#### `GET /portfolio/movers`

Get top portfolio gainers and losers by day change percentage.

**Query Parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `limit` | int | 10 | Number per side (1-50) |

**Response Model:** `MoversResponse`

```json
{
  "topGainers": [
    {
      "symbol": "AAPL",
      "currentPrice": 185.5,
      "previousClose": 182.0,
      "dayChange": 3.5,
      "dayChangePct": 1.92,
      "quantity": 100,
      "equity": 18550.0
    }
  ],
  "topLosers": [...],
  "source": "intraday"
}
```

**Price Cascade:** Databento → SnapTrade → yfinance → average cost fallback. `source` is `"intraday"` when day-change data available, `"unrealized"` when falling back to open P/L%.

---

### Ideas (`/ideas`)

#### `GET /ideas`

Paginated list of user ideas with filtering.

**Query Parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `symbol` | string | null | Filter by ticker (case-insensitive) |
| `tag` | string | null | Filter by tag (array contains) |
| `source` | string | null | Filter: `discord`, `manual`, `transcribe` |
| `status` | string | null | Filter: `draft`, `refined`, `archived` |
| `q` | string | null | Full-text content search (ILIKE) |
| `limit` | int | 50 | Page size (1-100) |
| `offset` | int | 0 | Pagination offset |

**Response Model:** `IdeasListResponse`

```json
{
  "ideas": [
    {
      "id": "a1b2c3d4-...",
      "symbol": "AAPL",
      "symbols": ["AAPL", "MSFT"],
      "content": "Buy AAPL on dip near 180 support",
      "source": "manual",
      "status": "draft",
      "tags": ["thesis", "entry"],
      "originMessageId": null,
      "contentHash": "abc123...",
      "createdAt": "2026-02-24T12:00:00+00:00",
      "updatedAt": "2026-02-24T12:00:00+00:00"
    }
  ],
  "total": 42,
  "hasMore": true
}
```

#### `POST /ideas`

Create a new idea. Content hash is auto-computed for same-day deduplication.

**Request Body:**

```json
{
  "content": "Buy AAPL on dip near 180 support",
  "symbol": "AAPL",
  "symbols": ["AAPL", "MSFT"],
  "tags": ["thesis", "entry"],
  "source": "manual"
}
```

**Response:** `201 Created` with the created `IdeaOut` object.

#### `PUT /ideas/{id}`

Partial update of an idea. Re-computes `contentHash` if content changes.

**Request Body:** (all fields optional, at least one required)

```json
{
  "content": "Updated thesis text",
  "status": "refined",
  "tags": ["thesis", "technical"]
}
```

**Response:** `200 OK` with the updated `IdeaOut` object. `404` if not found.

#### `DELETE /ideas/{id}`

Delete an idea.

**Response:** `204 No Content`. `404` if not found.

#### `POST /ideas/{id}/refine`

AI auto-refine an idea using OpenAI (gpt-4o-mini). Returns structured suggestions.

**Query Parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `apply` | bool | false | Auto-apply refinements to the idea |

**Response Model:** `RefineResponse`

```json
{
  "refinedContent": "Consider buying AAPL on a pullback to the $180 support level...",
  "extractedSymbols": ["AAPL"],
  "suggestedTags": ["thesis", "entry", "technical"],
  "changesSummary": "Added price level and improved clarity."
}
```

---

### Stocks (`/stocks`)

#### `GET /stocks/{ticker}`

Get stock profile with current price data.

**Path Parameters:**

- `ticker`: Stock ticker symbol (e.g., `AAPL`, `MSFT`)

**Response Model:** `StockProfileCurrent`

```json
{
  "symbol": "AAPL",
  "name": "Apple Inc.",
  "sector": null,
  "exchange": "NASDAQ",
  "currentPrice": 185.5,
  "previousClose": 184.25,
  "dayChange": 1.25,
  "dayChangePercent": 0.68,
  "volume": 52340000,
  "avgVolume": null,
  "marketCap": null,
  "high52Week": null,
  "low52Week": null
}
```

#### `GET /stocks/{ticker}/ideas`

Get trading ideas for a stock from Discord parsed messages.

**Query Parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `direction` | string | null | Filter: `bullish`, `bearish`, `neutral` |
| `limit` | int | 50 | Number of ideas (1-100) |

**Response Model:** `IdeasResponse`

```json
{
  "ideas": [
    {
      "id": 123,
      "messageId": "1234567890",
      "symbol": "AAPL",
      "direction": "bullish",
      "labels": ["entry_idea", "price_target"],
      "confidence": 0.85,
      "entryLevels": [{ "price": 180.0, "label": "support" }],
      "targetLevels": [{ "price": 200.0, "label": "PT1" }],
      "stopLevels": [{ "price": 170.0, "label": null }],
      "rawText": "AAPL looking good here...",
      "author": "trader123",
      "createdAt": "2026-01-30T15:30:00Z",
      "channelType": "trading"
    }
  ],
  "total": 25
}
```

#### `GET /stocks/{ticker}/ohlcv`

Get OHLCV chart data for a stock.

**Query Parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `period` | string | `1M` | Time period: `1W`, `1M`, `3M`, `6M`, `1Y`, `YTD` |

**Response Model:** `OHLCVSeries`

```json
{
  "symbol": "AAPL",
  "period": "1M",
  "bars": [
    {
      "date": "2026-01-02",
      "open": 180.0,
      "high": 182.5,
      "low": 179.25,
      "close": 181.75,
      "volume": 48000000
    }
  ],
  "orders": [
    {
      "date": "2026-01-15",
      "side": "buy",
      "price": 175.0,
      "quantity": 50
    }
  ]
}
```

#### `POST /stocks/{ticker}/chat`

Chat with AI about a stock using OpenAI.

**Request Body:**

```json
{
  "message": "What's the recent sentiment on this stock?",
  "context": "Optional additional context"
}
```

**Response Model:** `ChatResponse`

```json
{
  "response": "Recent sentiment on NVIDIA (NVDA) is mixed, with both bullish and bearish perspectives being expressed.\n\n1. **Bullish Sentiment**:\n   - There are calls to \"buy any NVIDIA dip,\" indicating a belief in the stock's long-term potential and resilience (qmy.y).\n   - Additionally, the sentiment conviction ranks NVIDIA positively, suggesting confidence in its performance moving forward (qmy.y).\n\n2. **Bearish Sentiment**:\n   - On the bearish side, there are concerns regarding the stock's current resistance levels. It has been noted that NVDA is at extreme resistance, and there may be a risk of exhaustion. This perspective suggests that selling now could be prudent, with a possibility to buy back at a lower price around $135 (qmy.y).\n\n3. **Neutral and Mixed Views**:\n   - A neutral technical analysis indicates that NVDA may not be ready to move upward until it stabilizes around $146 (qmy.y).\n   - There is also a mixed fundamental thesis, which suggests looking into competitors that could potentially replace NVIDIA or entice customers away (qmy.y).\n\nOverall, while there is optimism in the long-term outlook, caution is warranted due to current resistance levels and market dynamics.",
  "sources": ["Discord trading ideas", "Portfolio positions"]
}
```

---

### OpenBB Insights (`/stocks` — OpenBB endpoints)

> Powered by the [OpenBB Platform SDK](https://docs.openbb.co). Requires `FMP_API_KEY` for FMP-sourced data. SEC filings are free.

#### `GET /stocks/{ticker}/transcript`

Get earnings call transcripts for a stock.

**Query Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `year` | int | null | Filter by fiscal year |
| `quarter` | int | null | Filter by quarter (1-4) |

**Response Model:** `TranscriptResponse`

```json
{
  "symbol": "AAPL",
  "items": [
    {
      "date": "2026-01-30",
      "content": "Good afternoon. My name is Suhasini and I will be your...",
      "quarter": 1,
      "year": 2026,
      "symbol": "AAPL"
    }
  ]
}
```

#### `GET /stocks/{ticker}/management`

Get executive team for a stock.

**Response Model:** `ManagementResponse`

```json
{
  "symbol": "AAPL",
  "executives": [
    {
      "name": "Timothy D. Cook",
      "title": "Chief Executive Officer",
      "pay": 16425933,
      "currency": "USD",
      "gender": "male",
      "yearBorn": 1960,
      "titleSince": "2011-08-24"
    }
  ]
}
```

#### `GET /stocks/{ticker}/fundamentals`

Get key financial metrics for a stock.

**Response Model:** `FundamentalsResponse`

```json
{
  "symbol": "AAPL",
  "marketCap": 3450000000000,
  "peRatio": 32.5,
  "pegRatio": 2.1,
  "epsActual": 6.42,
  "debtToEquity": 1.87,
  "returnOnEquity": 1.47,
  "revenueGrowth": 0.05,
  "netMargin": 0.26,
  "operatingMargin": 0.31,
  "dividendYield": 0.005,
  "beta": 1.28,
  "priceToBook": 48.5,
  "currentRatio": 0.99,
  "freeCashFlowPerShare": 7.11
}
```

#### `GET /stocks/{ticker}/filings`

Get SEC filings for a stock. Uses the free SEC provider (no API key).

**Query Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `form_type` | string | null | Filter: `10-K`, `10-Q`, `8-K`, `4`, etc. |
| `limit` | int | 10 | Number of filings (1-50) |

**Response Headers:** `Cache-Control: public, max-age=3600, stale-while-revalidate=300`

**Response Model:** `FilingsResponse`

```json
{
  "symbol": "AAPL",
  "filings": [
    {
      "filingDate": "2026-01-28",
      "formType": "10-Q",
      "reportUrl": "https://www.sec.gov/Archives/edgar/...",
      "description": "Quarterly report for period ending 12/28/2025",
      "acceptedDate": "2026-01-28T16:04:00"
    }
  ]
}
```

#### `GET /stocks/{ticker}/news`

Get recent company news.

**Query Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `limit` | int | 10 | Number of articles (1-50) |

**Response Model:** `NewsResponse`

```json
{
  "symbol": "AAPL",
  "articles": [
    {
      "date": "2026-02-24T14:30:00",
      "title": "Apple Announces New AI Features at WWDC",
      "text": "Apple today unveiled a suite of new artificial intelligence...",
      "url": "https://example.com/article",
      "source": "Reuters",
      "images": ["https://example.com/image.jpg"]
    }
  ]
}
```

#### `GET /stocks/{ticker}/notes`

Get user notes for a stock. Stored in the `stock_notes` PostgreSQL table.

**Query Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `limit` | int | 50 | Number of notes (1-200) |

**Response Model:** `NotesResponse`

```json
{
  "symbol": "AAPL",
  "notes": [
    {
      "id": 1,
      "symbol": "AAPL",
      "content": "Strong earnings beat, watching for guidance revisions",
      "createdAt": "2026-02-20T10:30:00Z",
      "updatedAt": "2026-02-20T10:30:00Z"
    }
  ]
}
```

#### `POST /stocks/{ticker}/notes`

Create a new note for a stock.

**Request Body:**

```json
{
  "content": "Watching the 180 support level for re-entry"
}
```

**Response:** `201 Created` with the created `StockNote` object.

#### `DELETE /stocks/{ticker}/notes/{note_id}`

Delete a specific note.

**Response:** `204 No Content`

---

### Search (`/search`)

#### `GET /search`

Search for stocks/tickers by symbol or name. Uses a three-tier fallback chain:

1. **Local DB** — `symbols` table (instant)
2. **yfinance** — Yahoo Finance search
3. **OpenBB SEC** — `obb.equity.search()` with SEC provider (free, no API key)

**Query Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `q` | string | required | Search query (min 1 char) |
| `limit` | int | 10 | Maximum results (1-50) |

**Response Model:** `SearchResponse`

```json
{
  "results": [
    {
      "symbol": "AAPL",
      "name": "Apple Inc.",
      "sector": null,
      "type": "stock"
    },
    {
      "symbol": "SPY",
      "name": "SPDR S&P 500 ETF",
      "sector": null,
      "type": "etf"
    }
  ],
  "query": "app",
  "total": 2
}
```

---

### Watchlist (`/watchlist`)

#### `GET /watchlist`

Get current prices for watchlist tickers.

**Query Parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `tickers` | string | `""` | Comma-separated ticker symbols |

**Example:** `GET /watchlist?tickers=AAPL,MSFT,GOOGL`

**Response Model:** `WatchlistResponse`

```json
{
  "items": [
    {
      "symbol": "AAPL",
      "price": 185.5,
      "change": 1.25,
      "changePercent": 0.68,
      "volume": 0
    }
  ]
}
```

#### `POST /watchlist/validate`

Validate a ticker symbol exists in the database.

**Request Body:**

```json
{
  "ticker": "AAPL"
}
```

**Response Model:** `ValidationResponse`

```json
{
  "ticker": "AAPL",
  "valid": true,
  "message": "Valid symbol: Apple Inc."
}
```

---

### Webhooks (`/webhook`)

Webhook routes are protected by HMAC signature verification, NOT API key authentication.

#### `POST /webhook/snaptrade`

Handle incoming SnapTrade webhook events.

**Security:**

- HMAC-SHA256 signature verification using `SNAPTRADE_CLIENT_SECRET`
- Signature header: `X-SnapTrade-Signature` or `Signature`
- Replay protection via `eventTimestamp` (5-minute window)

**Supported Events:**
| Event | Description |
|-------|-------------|
| `ACCOUNT_HOLDINGS_UPDATED` | Holdings changed - triggers order refresh |
| `ACCOUNT_UPDATED` | Account sync triggered |
| `ORDER_PLACED` | New order placed |
| `ORDER_FILLED` | Order executed |
| `ORDER_CANCELLED` | Order cancelled |

**Request Body:**

```json
{
  "event": "ORDER_FILLED",
  "userId": "user-123",
  "accountId": "account-456",
  "eventTimestamp": "2026-01-31T12:00:00Z",
  "data": {}
}
```

**Response Model:** `WebhookResponse`

```json
{
  "status": "success",
  "event": "ORDER_FILLED",
  "processed": true,
  "message": null
}
```

---

### CORS Configuration

Allowed origins:

- `http://localhost:3000` (Local Next.js dev)
- `http://127.0.0.1:3000`
- `https://llm-portfolio-frontend.vercel.app` (Production Vercel)
- `https://llmportfolio.app` (Custom domain)

---

## Core Modules

### Data Collection

#### `src.price_service`

Centralized OHLCV data access layer using RDS PostgreSQL (Databento source).

**Key Functions:**

- `get_ohlcv(symbol, start, end)` → DataFrame: Get OHLCV data (mplfinance compatible)
- `get_latest_close(symbol)` → Optional[float]: Get most recent close price
- `get_previous_close(symbol, before_date)` → Optional[float]: Get close before date
- `get_ohlcv_range(symbol, start_date, end_date)` → DataFrame: Query date range

#### `src.databento_collector`

OHLCV daily bars from Databento Historical API with multi-storage backend.

**Key Functions:**

- `run_backfill(symbols, start_date, end_date)`: Backfill historical data
- `run_daily_update(symbols)`: Daily incremental update
- `save_to_rds(df)`: Persist to RDS PostgreSQL
- `save_to_s3(df)`: Archive to S3 as Parquet

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

### Message Processing

#### `src.message_cleaner`

Text processing and ticker extraction with sentiment analysis.

**Key Functions:**

- `extract_ticker_symbols(text)` → List[str]: Extract $TICKER symbols using regex
- `clean_text(text)` → str: Clean and normalize text content
- `calculate_sentiment(text)` → float: vaderSentiment analysis (-1.0 to 1.0)
- `process_messages_for_channel(messages, channel_type)` → DataFrame: Process message batch

**Regular Expressions:**

- `TICKER_PATTERN`: `r'\$[A-Z]{1,6}(?:\.[A-Z]+)?'` - Matches $AAPL, $BRK.B, etc.

#### `src.twitter_analysis`

Twitter/X integration with sentiment analysis.

**Key Functions:**

- `detect_twitter_links(text)` → List[str]: Extract Twitter/X URLs from text
- `extract_tweet_id(url)` → str: Get tweet ID from URL
- `analyze_sentiment(text)` → float: vaderSentiment analysis
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
- `SUPABASE_SERVICE_ROLE_KEY`: Secret key (sb*secret*…) for server-side access
- `SUPABASE_ANON_KEY`: Publishable key (sb*publishable*…) for client-side access
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

# OpenBB / Financial Modeling Prep (optional — SEC filings work without it)
FMP_API_KEY=your_fmp_api_key_here
```

### Database URLs

```ini
# PostgreSQL (Production)
DATABASE_URL=postgresql://user:password@localhost:5432/portfolio_db

# Supabase (Cloud)
DATABASE_URL=postgresql://user:password@db.supabase.co:5432/postgres
```
