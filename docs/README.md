# Documentation

This directory contains detailed documentation for the LLM Portfolio Journal project.

## Development Documentation

- **[SnapTrade Migration Complete](SNAPTRADE_MIGRATION_COMPLETE.md)** - Complete migration summary from direct `.body` access to safe response handling
- **[SnapTrade Response Improvements](SNAPTRADE_RESPONSE_IMPROVEMENTS.md)** - Detailed improvements made to SnapTrade API response handling

## Project Overview

For general project information, installation, and usage instructions, see the main [README.md](../README.md) in the project root.

## Architecture Notes

The project follows a modular architecture with clear separation between:
- Data collection (`src/data_collector.py`, `src/snaptrade_collector.py`) 
- Bot functionality (`src/bot/`)
- Database operations (`src/database.py`, `src/db.py`, `src/supabase_writers.py`)
- Market data queries (`src/market_data.py`)
- Journal generation (`src/journal_generator.py`)
- Message processing (`src/message_cleaner.py`, `src/discord_data_manager.py`)

### Key Design Decisions

1. **Dual Database Support**: SQLite for local development, PostgreSQL/Supabase for production
2. **Safe API Response Handling**: All SnapTrade API calls use `safely_extract_response_data()` helper
3. **Comprehensive Error Handling**: Graceful degradation when external services are unavailable
4. **Modular Bot Design**: Commands are organized in separate files under `src/bot/commands/`
5. **Consolidated Data Access**: Portfolio and trade queries unified in `src/market_data.py`
6. **Advanced Analytics**: Position tracking with FIFO calculations and enhanced charting

## Development History

The SnapTrade integration underwent significant improvements to handle API response variations safely. See the migration documentation for details on how this was implemented.
