# LLM Portfolio Journal

A sophisticated data-driven portfolio journal that integrates brokerage data, market information, and social sentiment analysis to generate comprehensive trading insights using Large Language Models.

> **🤖 AI Coding Agents**: See [AGENTS.md](AGENTS.md) - the canonical guide for AI development  
> **🏗️ Architecture Details**: See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) - comprehensive system architecture  
> **📚 All Documentation**: See [docs/README.md](docs/README.md) - complete navigation hub

---

## ✨ Features

- **📊 Multi-Source Data Integration**: SnapTrade API, Discord bot, Twitter/X analysis, and real-time market data
- **💾 PostgreSQL Database Architecture**: Enterprise Supabase/PostgreSQL with advanced connection pooling and RLS policies
- **🤖 AI-Powered Insights**: Dual-engine LLM integration (Gemini/OpenAI) with custom prompt engineering
- **📈 Advanced Analytics**: FIFO position tracking, P/L calculations, and sophisticated charting capabilities
- **💬 Social Sentiment Analysis**: Real-time Discord message processing with ticker extraction and sentiment scoring
- **🔄 Automated ETL Pipeline**: Comprehensive data cleaning, validation, and transformation workflows
- **🛡️ Enterprise Reliability**: Retry mechanisms, error handling, and graceful degradation patterns
- **📱 Interactive Discord Bot**: Real-time commands for data processing, analytics, and chart generation

## 🚀 Quick Start

### Prerequisites
- Python 3.9+ with virtual environment
- **PostgreSQL/Supabase database** (required - SQLite support removed)
- Discord bot token (optional)
- API keys for SnapTrade, OpenAI/Gemini (optional)

### Installation
```bash
# 1. CRITICAL: Validate deployment readiness
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
# Generate journal with fresh data
python generate_journal.py --force

# Run Discord bot for real-time data
python -m src.bot.bot

# Run comprehensive tests
make test
```

## 📖 Documentation

### For Users
- **[Installation Guide](#installation)**: Complete setup instructions
- **[Usage Examples](#usage-examples)**: Common workflows and commands  
- **[Configuration](#configuration)**: Environment variables and settings
- **[API Reference](docs/API_REFERENCE.md)**: Detailed API documentation

### For Developers & AI Agents  
- **[AGENTS.md](AGENTS.md)** - **🎯 CANONICAL AI CONTRIBUTOR GUIDE**
  - Complete setup procedures with bootstrap automation
  - Essential code patterns and database architecture
  - Development workflows and testing strategies
  - Critical environment variables and dependencies

- **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)** - **🏗️ CANONICAL ARCHITECTURE REFERENCE**
  - System design and component relationships  
  - Data flow and processing pipelines
  - Database schema and migration patterns
  - Performance optimizations and monitoring

- **[docs/README.md](docs/README.md)** - **📚 COMPLETE DOCUMENTATION NAVIGATION**
  - Consolidated access to all project documentation
  - Quick reference guides and troubleshooting
  - Development and deployment workflows

---

## 🔧 Configuration

Copy the example environment file and configure your API keys:
```bash
cp .env.example .env
```

### Required Environment Variables
```ini
# Database (PostgreSQL/Supabase required)
DATABASE_URL=postgresql://postgres.[project]:[service-role-key]@[region].pooler.supabase.com:6543/postgres
DATABASE_DIRECT_URL=postgresql://postgres.[project]:[service-role-key]@[region].supabase.com:5432/postgres
SUPABASE_SERVICE_ROLE_KEY=sb_secret_your_service_role_key

# Alternative Supabase format
SUPABASE_URL=your_supabase_project_url
SUPABASE_ANON_KEY=your_supabase_anon_key

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

> **🔐 Security**: The `.env` file is git-ignored and never committed to version control.

## �️ Database Architecture

The system uses **PostgreSQL-only** architecture with Supabase integration:

### Connection Configuration
```ini
# Primary connection via Supabase Transaction Pooler (recommended)
DATABASE_URL=postgresql://postgres.[project]:[service-role-key]@[region].pooler.supabase.com:6543/postgres

# Alternative Supabase format
SUPABASE_URL=your_supabase_project_url
SUPABASE_ANON_KEY=your_supabase_anon_key
SUPABASE_SERVICE_ROLE_KEY=sb_secret_your_service_role_key
```

### 🚨 Critical: Service Role Key Required
Must use **`SUPABASE_SERVICE_ROLE_KEY`** (starts with `sb_secret_`) in connection string to bypass RLS policies for database operations.

### Production Architecture
- **PostgreSQL/Supabase**: Enterprise database with RLS policies and connection pooling
- **16 Tables**: Comprehensive schema for positions, orders, market data, and social sentiment
- **Automated Migration**: Schema versioning and migration system included

## 💡 Usage Examples

### Generate Trading Journal
```bash
# Basic journal generation
python generate_journal.py

# Force data refresh and generate journal
python generate_journal.py --force

# Custom output directory
python generate_journal.py --output custom/path
```

### Discord Bot Commands
```bash
# Start the Discord bot
python -m src.bot.bot

# Available commands in Discord:
!history [limit]              # Fetch message history
!chart SYMBOL [period]        # Generate charts
!twitter SYMBOL              # Twitter sentiment analysis
!stats                       # Channel statistics
```

### Interactive Development
Use Jupyter notebooks for exploration:
```bash
jupyter lab notebooks/01_generate_journal.ipynb
```

## 🧪 Testing & Validation

Run comprehensive tests:
```bash
# Full test suite
make test

# Database schema validation
python scripts/verify_database.py --mode comprehensive

# Integration tests
python test_integration.py

# System health check
python scripts/bootstrap.py  # Includes validation
```

---

## 📄 License

MIT License - see [LICENSE](LICENSE) file for details.