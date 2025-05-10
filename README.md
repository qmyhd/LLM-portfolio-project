# LLM Portfolio Journal

A data-driven "portfolio journal" that pulls together your brokerage history, market data, and social sentiment, then uses LLMs to generate concise daily or weekly summaries of your trading activity and portfolio performance. The system uses a SQLite database for robust data storage and provides comprehensive insights through sentiment analysis.

---

## Table of Contents

1. [Features](#features)  
2. [Project Structure](#project-structure)  
3. [Installation](#installation)  
4. [Configuration](#configuration)  
5. [Usage](#usage)  
6. [Data Pipeline](#data-pipeline)  
7. [Discord Bot](#discord-bot)  
8. [Robinhood / SnapTrade Integration](#robinhood--snaptrade-integration)  
9. [Social Media Sources](#social-media-sources)  
10. [Journal Output Formats](#journal-output-formats)
11. [Testing](#testing)  
12. [Contributing](#contributing)  
13. [License](#license)  

---

## Features

- **Persistent SQLite database** for historical price data, metrics, positions, and orders
- **Automated ETL** of brokerage transactions (Robinhood via SnapTrade) and historical price data  
- **Discord ingestion**: fetch past messages + real-time streaming with ticker symbol detection
- **Social sentiment analysis**: Both from Discord messages and Twitter/X links shared in Discord
- **Real-time & historical market data**: Fetches current prices and stores historical data in SQLite
- **LLM summarization**: Portfolio changes, top gainers/losers, sentiment vs. fundamentals  
- **Smart symbol extraction**: Robust extraction of ticker symbols from text and nested API responses
- **Markdown journal output**: Rich formatted reports with tables of positions, gainers, losers, and sentiment
- **Dual output formats**: Plain text summary and detailed markdown report
- **Sentiment analysis**: TextBlob-powered sentiment scoring of Discord messages
- **Retry mechanism**: Robust API calls with exponential backoff for transient failures
- **Comprehensive logging**: Detailed logging throughout the application for debugging and monitoring

---

## Project Structure

```markdown
llm_portfolio_project/
├─ .env                 # API keys & credentials (git-ignored)
├─ setup.py             # Package definition
├─ requirements.txt     # Python dependencies
├─ generate_journal.py  # CLI entry point
├─ notebooks/           # Jupyter workflows
│  ├─ 01_generate_journal.ipynb  # Interactive journal generation
│  └─ 02_clean_discord.ipynb     # Discord data cleaning and preprocessing
├─ src/                 # Core modules
│  ├─ data_collector.py      # SnapTrade + price ETL, historical data storage
│  ├─ discord_logger_bot.py  # Discord fetcher & listener with Twitter integration
│  └─ journal_generator.py   # LLM prompt & rendering with markdown output
├─ data/
│  ├─ raw/               # CSV exports (discord_msgs.csv, orders.csv, positions.csv, prices.csv, x_posts_log.csv)
│  ├─ processed/         # Cleaned artifacts (discord_msgs_clean.parquet) and generated journals
│  └─ database/          # SQLite price_history.db with tables for prices, positions, orders, and metrics
└─ tests/               # Unit tests (test_core_functions.py)
```

---

## Installation

1. Clone your repo and enter the root folder (where `setup.py` lives):  
    ```bash
    git clone https://github.com/<USERNAME>/LLM-portfolio-project.git
    cd LLM-portfolio-project
    ```
2. Create & activate a virtual environment:
    ```bash
    python -m venv .venv
    source .venv/bin/activate    # macOS/Linux
    .venv\Scripts\Activate.ps1   # Windows PowerShell
    ```
3. Install dependencies & your package in editable mode:
    ```bash
    pip install -r requirements.txt
    pip install -e .
    ```

### Configuration

1. Copy .env.example to .env and fill in:
```ini
# Discord Bot credentials
DISCORD_BOT_TOKEN=your_discord_bot_token
LOG_CHANNEL_IDS=channel_id1,channel_id2

# Brokerage (SnapTrade/Robinhood) credentials
SNAPTRADE_CLIENT_ID=your_client_id
SNAPTRADE_CONSUMER_KEY=your_consumer_key
SNAPTRADE_USER_ID=your_user_id
SNAPTRADE_USER_SECRET=your_user_secret
ROBINHOOD_ACCOUNT_ID=your_account_id

# Social media API keys
TWITTER_API_KEY=your_twitter_key
TWITTER_API_SECRET_KEY=your_twitter_secret
TWITTER_ACCESS_TOKEN=your_twitter_token
TWITTER_ACCESS_TOKEN_SECRET=your_token_secret
TWITTER_BEARER_TOKEN=your_bearer_token

# LLM API keys
OPENAI_API_KEY=your_openai_key
# Alternative LLM API (optional)
GEMINI_API_KEY=your_gemini_key
```
2. Ensure your .gitignore excludes .env, raw data, caches, and DB files.

## Usage

Generate a journal entry (saves to data/processed/):
```bash
python generate_journal.py
```

Force update data even if already current:
```bash
python generate_journal.py --force
```

Specify custom output directory:
```bash
python generate_journal.py --output path/to/output
```

Run Discord logger to collect messages:
```bash
python -m src.discord_logger_bot
```

Inspect your portfolio positions:
```bash
python -c "from src.data_collector import get_account_positions; print(get_account_positions()[['symbol','quantity','price','equity']].head())"
```

## Data Pipeline

1. **Data Collection**
    - `data_collector.initialize_snaptrade()` → authenticates with SnapTrade API
    - `get_account_positions()` → pulls current holdings with robust symbol extraction
    - `get_recent_orders()` → fetches recent trade history
    - `fetch_realtime_prices()` → gets current market prices via yfinance
    - `fetch_historical_prices()` → stores historical price data in SQLite database
    - `fetch_stock_metrics()` → retrieves fundamental metrics like P/E ratio, market cap
    - All data is persisted in both CSV files and a SQLite database

2. **Discord Data Processing**
    - `discord_logger_bot.py` collects messages in real-time or via history command
    - Messages are stored with ticker detection and sentiment analysis
    - Integrated Twitter/X link detection extracts tweet data from shared links
    - `02_clean_discord.ipynb` standardizes timestamps, cleans data, adds features
    - Sentiment analysis using TextBlob provides numerical scoring of messages

3. **Journal Generation**
    - `journal_generator.create_enhanced_journal_prompt()` builds optimized prompt
    - LLM API call generates natural language summary
    - Dual output: plain text summary and detailed markdown report
    - Markdown output includes tables, position details, market movers, and sentiment analysis

## Discord Bot

Uses `discord.py` for bot implementation with the following features:

- Real-time message collection:
```python
@bot.event
async def on_message(message):
    # Process and log messages with ticker detection
```

- Historical message retrieval:
```python
@bot.command(name="history")
async def fetch_history(ctx, limit: int = 100):
    # Fetch and log past messages
```

- Robust ticker symbol detection using regex patterns
- Sentiment analysis with TextBlob
- Twitter/X link detection and metadata extraction
- CSV storage with detailed message attributes

## Robinhood / SnapTrade Integration

SnapTrade provides a secure API layer to access Robinhood data without directly storing credentials.

Key features:
- **Robust symbol extraction** from nested and complex API responses
- **Real-time equity calculation** and position valuation
- **Safe credential management** via environment variables
- **Order history retrieval** with detailed transaction data
- **Account balance and buying power calculation**
- **Persistent storage** in both CSV and SQLite database

The system has sophisticated logic to handle Robinhood's complex data structure and extract clean position data:
```python
{
  'symbol': 'AAPL',
  'quantity': 10.0,
  'equity': 1752.50,
  'price': 175.25,
  'average_buy_price': 150.75,
  'type': 'Stock',
  'currency': 'USD'
}
```

Order data is also robustly extracted with proper symbol identification:
```python
{
  'brokerage_order_id': '123456',
  'status': 'executed',
  'symbol': 'MSFT',
  'action': 'buy',
  'total_quantity': 5,
  'execution_price': 350.25,
  'extracted_symbol': 'MSFT'
}
```

## Social Media Sources

- **Twitter/X Integration**:
  - Detects shared Twitter/X links in Discord messages
  - Extracts tweet ID and fetches full tweet data via Twitter API
  - Captures engagement metrics (likes, retweets, replies)
  - Associates tweets with Discord messages for context
  - Stores in dedicated CSV file (`x_posts_log.csv`)
  - Includes comprehensive error handling for API failures

- **Discord as a source of market sentiment**:
  - Analyzes messages for ticker mentions and sentiment
  - Uses TextBlob for numerical sentiment scoring (-1.0 to 1.0)
  - Classifies sentiment as positive, negative, or neutral
  - Tracks most discussed tickers and sentiment trends
  - Provides context for price movements (sentiment-driven vs. fundamental)
  - Real-time logging of messages with sentiment and ticker detection

## Journal Output Formats

The system generates two complementary output formats:

1. **Plain Text Journal Entry**:
   - Concise (~120 words) natural language summary
   - Mentions portfolio value, top movers, and sentiment overview
   - Ideal for quick daily consumption
   - Saved as `journal_YYYY-MM-DD.txt`

2. **Rich Markdown Report**:
   - Comprehensive portfolio analysis with formatted tables
   - Sections include:
     - Summary text (same as plain text version)
     - Portfolio details with total equity
     - Top positions table (symbol, quantity, price, equity, change)
     - Today's gainers and losers tables
     - Discord activity summary with sentiment and ticker mentions
     - Market metrics including P/E ratios and moving averages
   - Saved as `journal_YYYY-MM-DD.md`

Example markdown output structure:
```markdown
# Portfolio Journal - 2025-05-01

## Summary
Brief summary of portfolio performance...

## Portfolio Details
### Overall Value
- Total Equity: $12,345.67
- Cash Balance: $1,234.56
- Buying Power: $2,469.12

### Top Positions
| Symbol | Quantity | Price | Equity | Change |
| ------ | -------: | ----: | -----: | -----: |
| AAPL   | 10.0     | $175.25 | $1,752.50 | +1.25% |
...

### Today's Movers
#### Gainers
| Symbol | Price | Change |
| ------ | ----: | -----: |
| MSFT   | $350.75 | +2.30% |
...

### Market Metrics
| Symbol | P/E Ratio | 50-Day Avg | 200-Day Avg |
| ------ | --------: | ---------: | ----------: |
| AAPL   | 28.5      | $172.30    | $165.75     |
...
```

## Testing

Run the unit tests in `tests/`:
```bash
pytest tests/
```

For faster testing with better output:
```bash
pytest --maxfail=1 --disable-warnings -v
```