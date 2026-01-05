# LLM Portfolio Journal - Export Summary Report

> **Generated:** December 9, 2025  
> **Purpose:** Complete export of codebase documentation for AI coding advisors

---

## 📋 Cleanup Actions Completed

### Database Cleanup
- ✅ Dropped `orders_backup_019` table (264 KB)
- ✅ Dropped `positions_backup_019` table (72 KB)
- ✅ Applied migration: `drop_remaining_backup_tables`

### Directory Cleanup
- ✅ Removed empty `src/db_utils/` directory

### Documentation Updates
- ✅ Created `docs/AI_ADVISOR_GUIDE.md` - Complete technical reference
- ✅ Updated `docs/ARCHITECTURE.md` - Current 19-table schema
- ✅ Updated `docs/SCHEMA_REPORT.md` - Added row counts
- ✅ Updated `docs/CODEBASE_MAP.md` - Updated file listings

---

## 📊 Current System State

### Database (Supabase PostgreSQL)
- **19 active tables** with RLS enabled
- **Total data rows**: ~1,970 records across all tables
- **Key tables**: positions (178), orders (703), discord_messages (226), symbols (180)
- **Connection**: Port 6543 pooler with service_role key

### Source Code Structure
```
src/
├── Core Services (12 files)
│   ├── db.py              # Database engine
│   ├── config.py          # Settings
│   ├── data_collector.py  # Market data
│   ├── snaptrade_collector.py  # Brokerage ETL
│   ├── message_cleaner.py # Ticker extraction
│   ├── journal_generator.py # LLM integration
│   └── ...
├── bot/
│   ├── commands/ (8 command modules)
│   └── ui/ (4 UI components)
├── etl/
│   └── sec_13f_parser.py  # Standalone 13F tool
└── sports/
    └── arbitrage_calculator.py
```

### Scripts
- **Active**: 7 operational scripts
- **Testing**: 7 test files in `tests/`
- **Schema**: 16 migration files

---

## 🔗 Key Documentation Files

For AI coding advisors, provide these files:

1. **`docs/AI_ADVISOR_GUIDE.md`** - Complete technical reference with:
   - Database schema with row counts
   - File purposes and connections
   - Bot commands reference
   - Common operations patterns
   - Troubleshooting guide

2. **`docs/ARCHITECTURE.md`** - High-level system design

3. **`docs/SCHEMA_REPORT.md`** - Database schema details

4. **`docs/CODEBASE_MAP.md`** - Directory structure

5. **`AGENTS.md`** - Canonical AI contributor guide

---

## 🧪 Testing Bot Commands

### Prerequisites
1. Ensure `.env` has `DISCORD_BOT_TOKEN` configured
2. Bot must be invited to your Discord server with message content intent
3. Add channel IDs to `LOG_CHANNEL_IDS` in `.env`

### Start the Bot
```bash
python -m src.bot.bot
```

### Available Commands
| Command | Description |
|---------|-------------|
| `!portfolio` | Show all positions |
| `!portfolio winners` | Show profitable positions |
| `!portfolio losers` | Show losing positions |
| `!orders 10` | Show last 10 orders |
| `!movers` | Top gainers/losers |
| `!chart AAPL` | Generate AAPL chart |
| `!chart AAPL 3mo candle` | 3-month candlestick |
| `!history 100` | Fetch last 100 messages |
| `!process trading` | Process as trading channel |
| `!twitter AAPL` | Twitter sentiment |
| `!EOD` | End-of-day lookup |
| `!arb` | Sports arbitrage |
| `!help` | Interactive help menu |

### Verify Bot is Working
1. Check terminal for "Bot is ready" message
2. Type `!help` in Discord channel
3. Should see interactive dropdown menu

---

## 📝 Notes for AI Advisors

### Critical Patterns
- **Always** use `execute_sql()` with named placeholders (`:param`)
- **Always** use `pathlib.Path` for file paths
- **Always** regenerate `expected_schemas.py` after SQL changes
- **Never** modify `src/db.py` connection logic without review

### Common Issues
1. **Database errors**: Check service_role key in DATABASE_URL
2. **Schema mismatch**: Run `python scripts/verify_database.py`
3. **Bot not responding**: Verify channel is in LOG_CHANNEL_IDS
4. **Missing tickers**: Check `extract_ticker_symbols()` regex

### Architecture Principles
- PostgreSQL-only (no SQLite fallback)
- Modular command structure
- Retry decorators for external APIs
- Pydantic for configuration validation
