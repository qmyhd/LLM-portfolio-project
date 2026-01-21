# LLM Portfolio Journal

A data-driven portfolio journal integrating brokerage data, market information, and social sentiment analysis to generate trading insights using Large Language Models.

**Documentation:**
- [AGENTS.md](AGENTS.md) - AI contributor guide
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) - System architecture
- [docs/README.md](docs/README.md) - Documentation hub

---

## Features

- Multi-source data integration: SnapTrade API, Discord bot, Twitter/X, market data
- PostgreSQL database with Supabase, connection pooling, and RLS policies
- Dual LLM engine (Gemini/OpenAI) with prompt engineering
- FIFO position tracking, P/L calculations, charting
- Discord message processing with ticker extraction and sentiment scoring
- Automated ETL pipeline with validation and transformation
- Retry mechanisms, error handling, graceful degradation
- Interactive Discord bot for data processing and analytics

## Quick Start

### Prerequisites
- Python 3.9+ with virtual environment
- PostgreSQL/Supabase database (required)
- Discord bot token (optional)
- API keys for SnapTrade, OpenAI/Gemini (optional)

### Installation
```bash
# 1. Validate deployment readiness
python tests/validate_deployment.py

# 2. Automated setup with health checks
python scripts/bootstrap.py

# 3. Configure environment
cp .env.example .env  # Add your API keys

# 4. Generate your first journal
python generate_journal.py --force
```

### Core Commands
```bash
python generate_journal.py --force   # Generate journal with fresh data
python -m src.bot.bot                # Run Discord bot
make test                            # Run tests
```

---

## Configuration

Copy the example environment file and configure your API keys:
```bash
cp .env.example .env
```

### Required Environment Variables
```ini
# Database (PostgreSQL/Supabase)
DATABASE_URL=postgresql://postgres.[project]:[service-role-key]@[region].pooler.supabase.com:6543/postgres
SUPABASE_SERVICE_ROLE_KEY=sb_secret_your_service_role_key

# LLM APIs (choose one)
GOOGLE_API_KEY=your_gemini_api_key      # Primary (free tier)
OPENAI_API_KEY=your_openai_key          # Fallback
```

### Optional Integrations
```ini
# Brokerage data (SnapTrade)
SNAPTRADE_CLIENT_ID=your_client_id
SNAPTRADE_CONSUMER_KEY=your_consumer_key

# Social media analysis
DISCORD_BOT_TOKEN=your_bot_token
TWITTER_BEARER_TOKEN=your_bearer_token
```

**Security**: The `.env` file is git-ignored and never committed.

---

## EC2 Environment Variables

For running the Databento OHLCV backfill on EC2, configure these variables:

```ini
# Databento API (required)
DATABENTO_API_KEY=db-your_databento_api_key

# RDS PostgreSQL (1-year rolling storage)
RDS_HOST=your-ohlcv-db.region.rds.amazonaws.com
RDS_PORT=5432
RDS_DB=postgres
RDS_USER=postgres
RDS_PASSWORD=your_rds_password

# S3 Archive (full historical Parquet)
S3_BUCKET_NAME=your-ohlcv-bucket
S3_RAW_DAILY_PREFIX=ohlcv/daily/

# AWS Credentials (if not using IAM role)
AWS_ACCESS_KEY_ID=your_access_key
AWS_SECRET_ACCESS_KEY=your_secret_key
AWS_REGION=us-east-1
```

EC2 backfill workflow:
```bash
ssh ec2-user@your-ec2-host
cd LLM-portfolio-project && git pull
python scripts/backfill_ohlcv.py --daily
```

---

## Database Architecture

PostgreSQL-only architecture with Supabase integration:

- **20 Tables**: Positions, orders, market data, NLP pipeline, social sentiment, OHLCV daily
- **RLS Policies**: Row-level security enabled on all tables
- **Service Role Key**: Must use `sb_secret_*` key in connection string to bypass RLS

### Connection Configuration
```ini
# Supabase Transaction Pooler (recommended)
DATABASE_URL=postgresql://postgres.[project]:[service-role-key]@[region].pooler.supabase.com:6543/postgres

# Direct connection
DATABASE_DIRECT_URL=postgresql://postgres.[project]:[service-role-key]@[region].supabase.com:5432/postgres
```

---

## Usage Examples

### Generate Trading Journal
```bash
python generate_journal.py                    # Basic generation
python generate_journal.py --force            # Force data refresh
python generate_journal.py --output custom/   # Custom output directory
```

### Discord Bot Commands
```bash
python -m src.bot.bot

# In Discord:
!history [limit]       # Fetch message history
!chart SYMBOL [period] # Generate charts
!twitter SYMBOL        # Twitter sentiment
!stats                 # Channel statistics
```

### OHLCV Backfill
```bash
python scripts/backfill_ohlcv.py --daily              # Last 5 days
python scripts/backfill_ohlcv.py --full               # Full historical
python scripts/backfill_ohlcv.py --start 2024-01-01   # Custom range
python scripts/backfill_ohlcv.py --prune              # Remove old data
```

---

## Testing

```bash
make test                                      # Full test suite
python scripts/verify_database.py --mode comprehensive  # Schema validation
python tests/test_integration.py               # Integration tests
python scripts/bootstrap.py                    # System health check
```

---

## License

MIT License - see [LICENSE](LICENSE) file for details.
