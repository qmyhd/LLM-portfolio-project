# LLM Portfolio Journal - AI Coding Instructions

## Architecture Overview

This is a data-driven portfolio journal system with three core layers:
- **Data Collection**: SnapTrade API + Discord bot + Twitter API → CSV files + SQLite database
- **Processing**: Pandas ETL pipelines with ticker extraction and sentiment analysis
- **Output**: LLM-generated journal entries in plain text and markdown formats

Key data flow: `data_collector.py` → SQLite `price_history.db` + CSV files → `journal_generator.py` → LLM API → formatted journal outputs

## Quick Start Commands

```bash
# Setup environment
python -m venv .venv
.venv\Scripts\Activate.ps1  # Windows PowerShell
pip install -r requirements.txt && pip install -e .

# Generate journal (auto-updates data)
python generate_journal.py --force

# Run Discord bot for real-time data collection
python -m src.bot.bot

# Test API connections
python check_twitter_api.py
```

## Critical File Patterns

### Entry Points
- `generate_journal.py` - CLI wrapper, delegates to `src.journal_generator.main()`
- `src/bot/bot.py` - Discord bot entry point with Twitter integration
- `notebooks/01_generate_journal.ipynb` - Interactive development workflow

### Core Architecture
- `src/data_collector.py` - **Primary data ingestion**: SnapTrade positions/orders, yfinance prices, SQLite persistence
- `src/journal_generator.py` - **LLM orchestration**: prompt engineering, API calls, dual output formats (text + markdown)
- `src/database.py` - **Simple SQLite wrapper**: `get_connection()` returns connection to `data/database/price_history.db`
- `src/bot/` - **Modular Discord bot**: event handlers in `events.py`, commands in `commands/` subdirectory

### Data Conventions
- **Dual persistence**: CSV files in `data/raw/` + SQLite tables for historical data
- **Symbol extraction**: Robust regex patterns for `$TICKER` format, handles complex API responses
- **Sentiment scoring**: TextBlob integration with numerical values (-1.0 to 1.0)

## Development Workflows

### Testing
```bash
pytest tests/ --maxfail=1 --disable-warnings -v
```
Tests focus on ticker extraction logic and data formatting functions.

### Journal Generation
```bash
python generate_journal.py --force  # Force refresh all data
python generate_journal.py --output custom/path  # Custom output directory
```

### Discord Bot Development
```bash
python -m src.bot.bot  # Run bot (requires DISCORD_BOT_TOKEN in .env)
```

## Key Patterns & Conventions

### Error Handling
- **Graceful degradation**: SnapTrade import failures don't crash the system
- **Retry decorators**: `@retry_decorator(max_retries=3, delay=1)` for API calls in `journal_generator.py`
- **Optional dependencies**: Twitter client gracefully handles missing credentials

### Configuration Management
- **Environment-driven**: All secrets in `.env` (git-ignored), loaded via `python-dotenv`
- **Path objects**: Use `pathlib.Path` consistently, not string concatenation
- **Directory structure**: Auto-create `data/{raw,processed,database}/` directories

### Data Processing
- **Symbol extraction**: `extract_ticker_symbols()` function with regex `r'\$[A-Z]{1,6}(?:\.[A-Z]+)?'`
- **DataFrame conventions**: Standardized column names (`symbol`, `quantity`, `price`, `equity`)
- **Timestamp handling**: Use pandas datetime parsing with timezone awareness

### LLM Integration
- **Dual prompt functions**: `create_journal_prompt()` (basic) vs `create_enhanced_journal_prompt()` (detailed)
- **LLM fallback chain**: Gemini API (free tier) → OpenAI API → error handling
- **Token management**: Max 200 tokens for journal entries (~120 words)
- **Structured output**: JSON formatting functions for consistent LLM input format

### Discord Bot Structure
- **Command registration**: Each command file in `commands/` has `register(bot)` function
- **Event handling**: Centralized in `events.py` with Twitter client dependency injection
- **Message logging**: Real-time ticker detection and sentiment analysis via `on_message` handler
- **Channel filtering**: Only logs messages from channels in `LOG_CHANNEL_IDS` environment variable

### Symbol Extraction Pattern
- **Regex**: `r'\$[A-Z]{1,6}(?:\.[A-Z]+)?'` matches `$AAPL`, `$BRK.B`, handles 1-6 character symbols
- **SnapTrade parsing**: `extract_symbol_from_data()` walks nested dicts, handles "Unknown" symbols gracefully
- **Fallback hierarchy**: `raw_symbol` → `symbol` → `ticker` → short `id` values (no UUIDs)

## Integration Points

### External APIs
- **SnapTrade**: Optional dependency with graceful fallback if SDK unavailable
- **yfinance**: Primary price data source with retry logic
- **OpenAI/LangChain**: LLM providers for journal generation
- **Twitter API**: Tweet data extraction from Discord-shared links

### File Dependencies
- **CSV → DataFrame**: Raw data loading with pandas, handle missing files gracefully
- **SQLite schemas**: Historical price tables, positions, orders, metrics
- **Markdown templates**: Rich formatting with tables, sections, and summary text

When working with this codebase:
1. Always handle missing `.env` variables gracefully
2. Use `pathlib.Path` for file operations
3. Test ticker extraction with edge cases (numbers, special characters)
4. Maintain dual output formats (text summary + detailed markdown)
5. Follow the retry pattern for external API calls
