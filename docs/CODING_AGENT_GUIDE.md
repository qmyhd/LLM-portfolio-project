# Coding Agent Guide

This guide is specifically designed to help AI coding agents understand and work effectively with the LLM Portfolio Journal codebase.

## 🚀 Quick Start for Coding Agents

### Repository Structure Overview
```
├── src/                          # Core application code
│   ├── 📊 Data Collection Layer
│   │   ├── data_collector.py     # yfinance integration & market data
│   │   ├── snaptrade_collector.py # SnapTrade API integration
│   │   ├── discord_data_manager.py # Discord message processing
│   │   └── twitter_analysis.py   # Twitter/X analysis
│   │
│   ├── 💾 Database Management
│   │   ├── database.py          # SQLite operations
│   │   ├── db.py               # PostgreSQL/SQLAlchemy operations
│   │   └── supabase_writers.py # Direct Supabase writes
│   │
│   ├── 🧠 Processing Engine
│   │   ├── message_cleaner.py   # Text processing & ticker extraction
│   │   ├── journal_generator.py # LLM integration & journal generation
│   │   ├── position_analysis.py # Position tracking & analytics
│   │   └── chart_enhancements.py # Enhanced charting
│   │
│   └── 🤖 Bot Infrastructure
│       └── bot/                 # Discord bot commands & events
```

## 🔧 Key Patterns & Conventions

### Database Operations
- **Primary**: `src.database.execute_sql()` - Universal database interface
- **SQLite**: Automatic fallback for local development
- **PostgreSQL**: Production database with connection pooling
- **Pattern**: All database functions return consistent formats

### Error Handling & Retries
- **Use**: `src.retry_utils.hardened_retry` for general operations
- **Use**: `src.retry_utils.database_retry` for database operations
- **Use**: `src.retry_utils.csv_processing_retry` for file processing
- **Pattern**: Decorators with exponential backoff and specific exception handling

### Configuration
- **Central config**: `src.config.settings()` - Pydantic-based configuration
- **Environment**: `.env` file for secrets (never commit!)
- **Pattern**: Type-safe configuration with automatic environment variable mapping

### Data Processing Pipeline
1. **Collection**: `data_collector.py` → market data
2. **Cleaning**: `message_cleaner.py` → text processing
3. **Analysis**: `position_analysis.py` → calculations
4. **Output**: `journal_generator.py` → LLM summaries

## 📝 Common Operations

### Adding New Data Sources
```python
# Follow this pattern:
from src.database import execute_sql
from src.retry_utils import hardened_retry

@hardened_retry(max_retries=3)
def fetch_new_data_source():
    # 1. Fetch data
    # 2. Validate/clean data
    # 3. Save to database using execute_sql()
    pass
```

### Database Schema Changes
1. Update `refresh_local_schema.py` with new DDL
2. Run `python refresh_local_schema.py --tables new_table`
3. Update relevant data models

### Adding Bot Commands
1. Create new file in `src/bot/commands/`
2. Follow pattern from existing commands
3. Register in `src/bot/commands/__init__.py`

## 🎯 Key Functions for Integration

### Data Collection
- `data_collector.update_all_data()` - Refresh all market data
- `snaptrade_collector.SnapTradeCollector().collect_all_data()` - Brokerage data
- `discord_data_manager.process_all_channels()` - Discord processing

### Data Querying
- `market_data.get_positions()` - Current positions
- `market_data.get_recent_trades()` - Trade history
- `database.execute_sql(query, params, fetch_results=True)` - Custom queries

### Text Processing
- `message_cleaner.extract_ticker_symbols(text)` - Find stock symbols
- `message_cleaner.calculate_sentiment(text)` - Sentiment analysis
- `message_cleaner.clean_text(text)` - Text normalization

### LLM Integration
- `journal_generator.generate_journal_entry(prompt)` - Create journal
- `journal_generator.create_enhanced_journal_prompt()` - Build prompts

## 🔍 Testing & Validation

### Quick Health Check
```bash
python test_integration.py  # Comprehensive integration tests
```

### Individual Module Testing
```bash
python -c "from src.database import execute_sql; print(execute_sql('SELECT COUNT(*) FROM positions', fetch_results=True))"
```

### Data Validation
```bash
python scripts/verify_schemas.py --verbose
```

## 📚 Architecture Patterns

### 1. **Modular Design**
- Each module has a single responsibility
- Clear interfaces between components
- Minimal coupling, high cohesion

### 2. **Error-First Design**
- All operations include comprehensive error handling
- Graceful degradation (SQLite fallback, etc.)
- Detailed logging for debugging

### 3. **Configuration-Driven**
- Environment-based configuration
- No hardcoded credentials or paths
- Easy testing/development setup

### 4. **Data-Centric**
- Database as single source of truth
- Consistent data models across modules
- Automated data cleaning and validation

## 🛠️ Development Workflow for Agents

### 1. Understanding the Current State
```python
# Check database schema
from src.database import execute_sql
tables = execute_sql("SELECT name FROM sqlite_master WHERE type='table'", fetch_results=True)

# Check configuration
from src.config import settings
config = settings()
```

### 2. Making Changes
- Always run `python test_integration.py` after changes
- Use existing patterns (retry decorators, error handling)
- Follow the modular structure

### 3. Adding Features
- Identify the appropriate module based on functionality
- Use the established patterns for database access
- Add comprehensive error handling
- Update documentation

## ⚠️ Important Notes

### Do NOT modify:
- Database connection logic in `database.py` and `db.py`
- Core retry mechanisms in `retry_utils.py`
- Configuration loading in `config.py`

### Always use:
- `execute_sql()` for database operations
- Retry decorators for external API calls
- Type hints for function signatures
- Comprehensive error handling

### Key Files to Understand:
- `src/database.py` - Database abstraction layer
- `src/config.py` - Configuration management
- `src/retry_utils.py` - Error handling patterns
- `src/data_collector.py` - Main data orchestration

## 🔗 Quick Reference

### Environment Setup
```bash
pip install -r requirements.txt
cp .env.example .env  # Edit with your API keys
```

### Common Commands
```bash
python generate_journal.py              # Generate journal
python -m src.bot.bot                   # Run Discord bot
python scripts/bootstrap.py             # Setup database
python migrate_with_cleaning.py --all   # Migrate data
```

This codebase is designed for maintainability, reliability, and ease of extension. Follow the established patterns and you'll be able to add features effectively!
