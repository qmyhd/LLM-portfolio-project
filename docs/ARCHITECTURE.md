# LLM Portfolio Journal - Architecture Documentation

## Overview

The LLM Portfolio Journal is a sophisticated data-driven application that integrates brokerage data, market information, and social sentiment analysis to generate comprehensive trading insights using Large Language Models.

## System Architecture

### Core Components

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Data Sources  │    │  Processing     │    │    Output       │
│                 │    │   Engine        │    │   Generation    │
├─────────────────┤    ├─────────────────┤    ├─────────────────┤
│ • SnapTrade API │───▶│ • Data Collector│───▶│ • Journal Gen   │
│ • Discord Bot   │    │ • Message Clean │    │ • Markdown      │
│ • Twitter API   │    │ • Sentiment     │    │ • Text Summary  │
│ • yfinance      │    │ • Database ETL  │    │ • Charts        │
└─────────────────┘    └─────────────────┘    └─────────────────┘
```

### Database Layer

**Dual Database Architecture:**
- **SQLite**: Local development and fallback storage
- **PostgreSQL/Supabase**: Production with real-time capabilities

**Key Tables:**
- `positions`: Current portfolio holdings with calculated equity
- `orders`: Trade history with execution details
- `discord_messages`: Social sentiment data with ticker extraction
- `twitter_data`: Tweet analysis with stock correlations
- `price_history`: Historical market data for analysis

### Module Structure

#### Data Collection (`src/`)
- **`data_collector.py`**: General market data collection, yfinance integration
- **`snaptrade_collector.py`**: SnapTrade API integration with enhanced field extraction
- **`discord_data_manager.py`**: Discord message processing and deduplication
- **`twitter_analysis.py`**: Twitter/X sentiment analysis and data extraction

#### Database Management (`src/`)
- **`database.py`**: Unified SQLite/PostgreSQL abstraction layer
- **`db.py`**: SQLAlchemy engine with connection pooling and health checks
- **`supabase_writers.py`**: Direct real-time writes to Supabase
- **`market_data.py`**: Consolidated portfolio and trade data queries

#### Bot Infrastructure (`src/bot/`)
- **`bot.py`**: Discord bot entry point with Twitter client integration
- **`events.py`**: Message event handlers and channel filtering
- **`commands/`**: Modular command structure:
  - `chart.py`: Advanced charting with FIFO position tracking
  - `history.py`: Message history fetching with deduplication
  - `process.py`: Channel data processing and statistics
  - `twitter_cmd.py`: Twitter data analysis commands
  - `eod.py`: End-of-day stock data queries

#### Processing Engine (`src/`)
- **`message_cleaner.py`**: Text processing and ticker symbol extraction
- **`journal_generator.py`**: LLM integration for journal generation
- **`position_analysis.py`**: Advanced position tracking and analytics
- **`chart_enhancements.py`**: Enhanced charting with position overlays

#### Utilities (`src/`)
- **`config.py`**: Centralized configuration management with Pydantic
- **`retry_utils.py`**: Hardened retry decorator with exception handling
- **`logging_utils.py`**: Database logging with Twitter integration

#### ETL Pipeline (`src/etl/`)
- **`clean_csv.py`**: Robust CSV cleaning with data validation and sanitization

### Operational Tooling (`scripts/`)
- **`bootstrap.py`**: Application bootstrap with dependency management
- **`init_database.py`**: Database initialization and schema creation
- **`verify_schemas.py`**: Comprehensive schema verification
- **`migrate_sqlite.py`**: SQLite to PostgreSQL migration utilities
- **`init_twitter_schema.py`**: Twitter-specific schema initialization

## Data Flow

### Primary Data Pipeline

```
1. Data Ingestion
   ├─ SnapTrade API → Positions/Orders/Accounts
   ├─ Discord Bot → Message Stream → Ticker Extraction
   ├─ Twitter API → Tweet Analysis → Sentiment Scoring
   └─ yfinance → Market Data → Price History

2. Data Processing
   ├─ CSV Cleaning → Data Validation → Error Handling
   ├─ Symbol Extraction → Ticker Normalization
   ├─ Sentiment Analysis → TextBlob Processing
   └─ Deduplication → Database Upserts

3. Data Storage
   ├─ SQLite (Local) → Immediate Storage
   ├─ PostgreSQL (Production) → Real-time Writes
   └─ CSV Backup → Raw Data Persistence

4. Analysis & Generation
   ├─ Portfolio Analysis → Position Tracking → P/L Calculation
   ├─ Sentiment Correlation → Market Data Integration
   ├─ LLM Processing → Prompt Engineering → Journal Generation
   └─ Chart Generation → Technical Analysis → Visualization
```

### Real-time Processing

- **Discord Event Stream**: Live message processing with ticker detection
- **Database Writes**: Immediate persistence with fallback mechanisms
- **Sentiment Analysis**: Real-time TextBlob processing
- **Deduplication**: Message ID tracking to prevent duplicates

## Key Design Patterns

### Error Handling Strategy
- **Graceful Degradation**: Services continue operating when dependencies fail
- **Retry Mechanisms**: Exponential backoff with circuit breaker patterns
- **Fallback Systems**: SQLite backup when PostgreSQL unavailable
- **Exception Filtering**: Non-retryable exceptions handled immediately

### Database Patterns
- **Dual Persistence**: CSV + Database for redundancy
- **Connection Pooling**: SQLAlchemy with health checks
- **Schema Migration**: Automated SQLite → PostgreSQL with pgloader
- **Prepared Statements**: Optimized for Supabase compatibility

### API Integration Patterns
- **Safe Response Handling**: Structured parsing with error recovery
- **Optional Dependencies**: Import failure handling for external services
- **Rate Limiting**: Respectful API usage with built-in delays
- **Authentication Management**: Secure credential handling via environment

### Data Processing Patterns
- **Modular ETL**: Separate extraction, transformation, and loading
- **Type Safety**: Comprehensive type checking and validation
- **Schema Enforcement**: Strict data validation before persistence
- **Performance Optimization**: Bulk operations and efficient queries

## Security Considerations

- **Credential Management**: Environment-based secrets with `.env` files
- **SQL Injection Prevention**: Parameterized queries and prepared statements
- **Data Sanitization**: Input validation and cleaning before storage
- **Access Control**: Database-level permissions and connection security

## Performance Optimizations

- **Connection Pooling**: Reusable database connections
- **Bulk Operations**: Batch processing for large datasets
- **Caching Strategies**: In-memory caching for frequently accessed data
- **Lazy Loading**: On-demand module imports and data loading

## Monitoring & Observability

- **Comprehensive Logging**: Structured logging throughout the application
- **Health Checks**: Database and service availability monitoring
- **Error Tracking**: Detailed exception logging and reporting
- **Performance Metrics**: Database size and query performance tracking

## Development Workflow

### Local Development
1. **Environment Setup**: Virtual environment with requirements.txt
2. **Database Initialization**: Local SQLite for development
3. **Configuration**: `.env` file with development credentials
4. **Testing**: Comprehensive unit and integration tests

### Production Deployment
1. **Bootstrap Process**: Automated dependency and database setup
2. **Migration**: SQLite → PostgreSQL data transfer
3. **Health Validation**: Comprehensive system health checks
4. **Monitoring**: Ongoing performance and error monitoring

## Extension Points

The architecture supports easy extension through:
- **Modular Commands**: New Discord bot commands via plugin pattern
- **Data Sources**: Additional APIs through standardized collector pattern
- **Processing Modules**: New analysis types via modular processing engine
- **Output Formats**: Additional journal formats through generator plugins

This architecture ensures scalability, maintainability, and robust operation across development and production environments.
