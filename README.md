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

- **🏗️ Robust Architecture**: Modular design with clear separation of concerns and comprehensive error handling
- **💾 Dual Database Support**: SQLite for local development, PostgreSQL/Supabase for production with automatic fallback
- **📊 Advanced Data Collection**: SnapTrade API integration, Discord bot, Twitter analysis, and real-time market data
- **🤖 Intelligent Processing**: LLM-powered journal generation with dual output formats (text + markdown)
- **📈 Sophisticated Analytics**: FIFO position tracking, P/L calculations, and enhanced charting capabilities
- **🔍 Smart Symbol Extraction**: Robust ticker symbol detection from text and nested API responses
- **💬 Social Sentiment Analysis**: Real-time Discord message processing with Twitter/X link analysis
- **⚡ Real-time & Historical Data**: Live price feeds with comprehensive historical data storage
- **🔄 Automated ETL Pipeline**: Comprehensive data cleaning, validation, and transformation
- **🛡️ Enterprise-grade Reliability**: Retry mechanisms, connection pooling, and graceful degradation
- **📱 Discord Bot Integration**: Interactive commands for data processing, analytics, and chart generation
- **🔐 Secure Configuration**: Environment-based secrets management with comprehensive validation
- **🧪 Comprehensive Testing**: Unit tests, integration tests, and validation scripts
- **📚 Extensive Documentation**: Detailed API reference, architecture docs, and user guides

---

## Project Structure

```
llm_portfolio_project/
├─ 📁 Configuration & Setup
│  ├─ .env                      # API keys & credentials (git-ignored)
│  ├─ .env.example              # Template for environment configuration
│  ├─ requirements.txt          # Python dependencies
│  ├─ pyproject.toml           # Package configuration
│  └─ Makefile                 # Development automation
│
├─ 🚀 Entry Points & Scripts
│  ├─ generate_journal.py       # CLI entry point for journal generation
│  ├─ validate_deployment.py    # Deployment validation script
│  ├─ migrate_with_cleaning.py  # Data migration with cleaning
│  └─ refresh_local_schema.py   # Schema synchronization utility
│
├─ 📓 Interactive Workflows
│  ├─ notebooks/
│  │  ├─ 01_generate_journal.ipynb     # Interactive journal generation
│  │  └─ 02_clean_discord.ipynb        # Discord data cleaning workflow
│
├─ 🏗️ Core Application
│  ├─ src/
│  │  ├─ 📊 Data Collection Layer
│  │  │  ├─ data_collector.py           # General market data & yfinance integration
│  │  │  ├─ snaptrade_collector.py      # SnapTrade API with enhanced field extraction
│  │  │  ├─ discord_data_manager.py     # Discord message processing & deduplication
│  │  │  └─ twitter_analysis.py         # Twitter/X sentiment analysis & URL extraction
│  │  │
│  │  ├─ 💾 Database Management
│  │  │  ├─ database.py                 # Unified SQLite/PostgreSQL abstraction
│  │  │  ├─ db.py                      # SQLAlchemy engine with connection pooling
│  │  │  ├─ supabase_writers.py        # Direct real-time Supabase writers
│  │  │  └─ market_data.py             # Consolidated portfolio & trade queries
│  │  │
│  │  ├─ 🤖 Bot Infrastructure
│  │  │  ├─ bot/
│  │  │  │  ├─ bot.py                  # Discord bot entry point
│  │  │  │  ├─ events.py               # Event handlers & message processing
│  │  │  │  └─ commands/               # Modular command structure
│  │  │  │     ├─ chart.py             # Advanced charting with FIFO tracking
│  │  │  │     ├─ history.py           # Message history with deduplication
│  │  │  │     ├─ process.py           # Channel processing & statistics
│  │  │  │     ├─ twitter_cmd.py       # Twitter data analysis commands
│  │  │  │     └─ eod.py               # End-of-day stock data
│  │  │
│  │  ├─ 🧠 Processing Engine
│  │  │  ├─ message_cleaner.py          # Text processing & ticker extraction
│  │  │  ├─ journal_generator.py        # LLM integration & dual output formats
│  │  │  ├─ position_analysis.py        # Advanced position tracking & analytics
│  │  │  └─ chart_enhancements.py       # Enhanced charting with position overlays
│  │  │
│  │  ├─ 🔧 Utilities & Configuration
│  │  │  ├─ config.py                   # Centralized configuration with Pydantic
│  │  │  ├─ retry_utils.py             # Hardened retry decorator with exception handling
│  │  │  ├─ logging_utils.py           # Database logging with Twitter integration
│  │  │  └─ channel_processor.py       # Channel-specific data processing
│  │  │
│  │  └─ 🔄 ETL Pipeline
│  │     └─ etl/
│  │        └─ clean_csv.py            # Robust CSV cleaning with validation
│
├─ 🛠️ Operational Tooling
│  ├─ scripts/
│  │  ├─ bootstrap.py               # Application bootstrap & dependency management
│  │  ├─ init_database.py           # Database initialization & schema creation
│  │  ├─ verify_schemas.py          # Comprehensive schema verification
│  │  ├─ migrate_sqlite.py          # SQLite → PostgreSQL migration
│  │  └─ init_twitter_schema.py     # Twitter-specific schema initialization
│
├─ 💾 Data Storage
│  ├─ data/
│  │  ├─ raw/                       # CSV exports & raw data files
│  │  ├─ processed/                 # Cleaned artifacts & generated journals
│  │  └─ database/                  # SQLite databases for local development
│
├─ 📊 Output & Visualization
│  └─ charts/                       # Generated charts & visualizations
│
├─ 🧪 Testing & Quality Assurance
│  ├─ tests/
│  │  ├─ test_core_functions.py     # Comprehensive unit tests
│  │  └─ test_safe_response_handling.py  # SnapTrade response handling tests
│  └─ test_integration.py           # Integration tests for cleanup verification
│
└─ 📚 Documentation
   └─ docs/
      ├─ README.md                  # Documentation overview
      ├─ ARCHITECTURE.md            # System architecture & design patterns
      ├─ API_REFERENCE.md           # Comprehensive API documentation
      ├─ SNAPTRADE_MIGRATION_COMPLETE.md    # SnapTrade migration notes
      └─ SNAPTRADE_RESPONSE_IMPROVEMENTS.md # API response improvements
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

1. Copy `.env.example` to `.env` and fill in your actual credentials:
```bash
cp .env.example .env
```

2. Edit `.env` with your actual API keys and credentials (never commit this file!):
```ini
# Discord Bot credentials
DISCORD_BOT_TOKEN=your_actual_discord_bot_token
LOG_CHANNEL_IDS=123456789,987654321

# Brokerage (SnapTrade/Robinhood) credentials  
SNAPTRADE_CLIENT_ID=your_actual_client_id
SNAPTRADE_CONSUMER_KEY=your_actual_consumer_key
SNAPTRADE_USER_ID=your_actual_user_id
SNAPTRADE_USER_SECRET=your_actual_user_secret
ROBINHOOD_ACCOUNT_ID=your_actual_account_id

# Social media API keys
TWITTER_API_KEY=your_actual_twitter_key
TWITTER_API_SECRET_KEY=your_actual_twitter_secret
TWITTER_ACCESS_TOKEN=your_actual_twitter_token
TWITTER_ACCESS_TOKEN_SECRET=your_actual_token_secret
TWITTER_BEARER_TOKEN=your_actual_bearer_token

# LLM API keys (Gemini is primary, OpenAI is fallback)
GEMINI_API_KEY=your_actual_gemini_key
OPENAI_API_KEY=your_actual_openai_key
```

3. **Security Note**: The `.env` file is automatically ignored by git and will never be pushed to GitHub.

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
python -m bot.bot
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
    - `bot/bot.py` runs the Discord bot, logging messages in real-time or via the history command
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

---

## 📚 Documentation

This project includes comprehensive documentation to help you understand, use, and extend the system:

### 📖 User Documentation
- **[Main README](README.md)** - This file: overview, installation, and basic usage
- **[Configuration Guide](#configuration)** - Detailed environment setup and API key configuration

### 🏗️ Technical Documentation
- **[Architecture Overview](docs/ARCHITECTURE.md)** - System design, data flow, and architectural patterns
- **[API Reference](docs/API_REFERENCE.md)** - Complete module, class, and function documentation
- **[Development Guide](docs/README.md)** - Development notes and migration history
- **[Coding Agent Guide](docs/CODING_AGENT_GUIDE.md)** - Comprehensive guide for AI coding agents working with this codebase

### 📋 Migration & Improvement Notes
- **[SnapTrade Migration](docs/SNAPTRADE_MIGRATION_COMPLETE.md)** - Complete migration from direct API access to safe response handling
- **[Response Improvements](docs/SNAPTRADE_RESPONSE_IMPROVEMENTS.md)** - Detailed SnapTrade API response handling improvements

### 🧪 Testing & Validation
- **Integration Tests** - `test_integration.py` for end-to-end validation
- **Unit Tests** - Comprehensive test suite in `tests/` directory
- **Validation Scripts** - `validate_deployment.py` for deployment readiness checks

---

## 🚀 Quick Start

### Development Setup

1. **Clone and Setup Environment**:
   ```bash
   git clone https://github.com/<USERNAME>/LLM-portfolio-project.git
   cd LLM-portfolio-project
   python -m venv .venv
   source .venv/bin/activate    # macOS/Linux
   .venv\Scripts\Activate.ps1   # Windows PowerShell
   ```

2. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt && pip install -e .
   ```

3. **Configure Environment**:
   ```bash
   cp .env.example .env
   # Edit .env with your API keys and configuration
   ```

4. **Initialize Database** (Optional - for advanced users):
   ```bash
   python scripts/init_database.py
   ```

5. **Run Integration Tests**:
   ```bash
   python test_integration.py
   ```

### Basic Usage

**Generate Journal**:
```bash
python generate_journal.py --force
```

**Run Discord Bot**:
```bash
python -m src.bot.bot
```

**Run Bootstrap Setup** (Comprehensive initialization):
```bash
python scripts/bootstrap.py
```

---

## 🔧 Advanced Usage

### Development Workflow

**Using Makefile** (if available):
```bash
make setup     # Complete development setup
make test      # Run test suite
make journal   # Generate journal
make bot       # Run Discord bot
make clean     # Clean temporary files
```

**Manual Development Commands**:
```bash
# Data collection and processing
python -c "from src.data_collector import fetch_realtime_prices; print(fetch_realtime_prices(['AAPL', 'MSFT']))"

# Discord message processing
python -c "from src.channel_processor import process_channel_data; print(process_channel_data('general'))"

# Database operations
python -c "from src.database import execute_sql; print(execute_sql('SELECT COUNT(*) FROM positions', fetch_results=True))"
```

### Database Management

**Schema Verification**:
```bash
python scripts/verify_schemas.py --verbose
```

**Data Migration**:
```bash
python migrate_with_cleaning.py --all
```

**Schema Refresh**:
```bash
python refresh_local_schema.py --tables orders,discord_messages
```

### Discord Bot Commands

Once the bot is running, use these commands in Discord:

- `!history [limit]` - Fetch message history with deduplication
- `!process [channel_type]` - Process current channel messages  
- `!stats` - Show channel statistics
- `!globalstats` - Show global processing statistics
- `!chart SYMBOL [period] [type]` - Generate advanced charts with position tracking
- `!twitter [SYMBOL]` - Show Twitter data and sentiment analysis
- `!tweets [SYMBOL] [count]` - Get recent tweets with stock mentions
- `!EOD` - Interactive end-of-day stock data lookup

---

## 🔍 Troubleshooting

### Common Issues

**Import Errors**:
- Ensure virtual environment is activated
- Run `pip install -r requirements.txt` to install dependencies
- Check Python version compatibility (3.8+)

**Database Connection Issues**:
- Verify `DATABASE_URL` in `.env` file
- For PostgreSQL: ensure database server is running
- For SQLite: check file permissions in `data/database/` directory

**API Authentication Errors**:
- Verify API keys in `.env` file match the `.env.example` format
- Check API key validity and rate limits
- Ensure Discord bot has proper permissions in target channels

**SnapTrade Integration Issues**:
- Verify SnapTrade consumer key and user credentials
- Check SnapTrade SDK installation: `pip install snaptrade-client`
- Review SnapTrade account authorization status

### Debug Mode

Enable verbose logging by setting environment variable:
```bash
export DEBUG=True  # Linux/macOS
set DEBUG=True     # Windows
```

### Getting Help

1. **Check Logs**: Review application logs for detailed error messages
2. **Run Validation**: Use `python validate_deployment.py` to check system health
3. **Integration Tests**: Run `python test_integration.py` to verify core functionality
4. **Documentation**: Refer to comprehensive docs in the `docs/` directory

---

SnapTrade provides a secure API layer to access Robinhood data without directly storing credentials.
If the SnapTrade Python SDK is unavailable (e.g., unsupported Python version), the
data collection functions will raise `ImportError` and the bot will continue without brokerage updates.

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
