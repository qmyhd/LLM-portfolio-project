# Primary Keys Catalog & Natural Key Migration Status

## Overview

This catalog documents the primary key strategy for each table in the LLM Portfolio Journal database, tracking the migration from surrogate auto-increment IDs to meaningful natural keys as primary keys.

## 🎯 Natural Key Migration Strategy

The database has undergone a comprehensive migration from surrogate keys (auto-increment `id` columns) to natural keys (business-meaningful identifiers) as primary keys. This improves data integrity, query performance, and reduces redundant storage.

### Migration Timeline
- **Migrations 010 & 012**: Implemented natural key migration for most tables
- **Migration 008**: Standardized constraint naming (`_key` → `_unique`)
- **Current Status**: 13/16 tables successfully migrated to natural keys

## 📊 Complete Primary Key Catalog

### ✅ Natural Keys Successfully Implemented (13 tables)

#### 1. **discord_messages** 
- **Primary Key**: `message_id` (TEXT)
- **Migration Status**: ✅ Completed in migration 012
- **Natural Key Rationale**: Discord message ID is globally unique snowflake identifier
- **Business Logic**: Each Discord message has unique ID, no duplicates possible
- **Index Support**: `idx_discord_messages_message_id`

#### 2. **twitter_data**
- **Primary Key**: `tweet_id` (TEXT) 
- **Migration Status**: ✅ Completed in migration 012
- **Natural Key Rationale**: Twitter/X post IDs are globally unique
- **Business Logic**: Each tweet has unique identifier across platform
- **Index Support**: `idx_twitter_data_tweet_id`

#### 3. **discord_market_clean**
- **Primary Key**: `message_id` (TEXT)
- **Migration Status**: ✅ Completed in migration 012  
- **Natural Key Rationale**: References original Discord message
- **Business Logic**: One-to-one relationship with discord_messages
- **Unique Constraint**: `discord_market_clean_message_id_unique`

#### 4. **discord_trading_clean**
- **Primary Key**: `message_id` (TEXT)
- **Migration Status**: ✅ Completed in migration 012
- **Natural Key Rationale**: References original Discord message
- **Business Logic**: One-to-one relationship with discord_messages  
- **Unique Constraint**: `discord_trading_clean_message_id_unique`

#### 5. **processing_status**
- **Primary Key**: `message_id` (TEXT)
- **Migration Status**: ✅ Completed in migration 012
- **Natural Key Rationale**: Tracks processing state per message
- **Business Logic**: Each message has one processing status record
- **Unique Constraint**: `processing_status_message_id_unique`

#### 6. **daily_prices**
- **Primary Key**: `(symbol, date)` (Composite)
- **Migration Status**: ✅ Completed in migration 012
- **Natural Key Rationale**: Symbol + date uniquely identifies daily price record
- **Business Logic**: One price record per symbol per trading day
- **Unique Constraint**: `daily_prices_symbol_date_unique`

#### 7. **realtime_prices**
- **Primary Key**: `(symbol, timestamp)` (Composite)
- **Migration Status**: ✅ Completed in migration 012
- **Natural Key Rationale**: Symbol + timestamp uniquely identifies price point
- **Business Logic**: One price record per symbol per timestamp
- **Unique Constraint**: `realtime_prices_symbol_timestamp_unique`

#### 8. **stock_metrics**
- **Primary Key**: `(symbol, date)` (Composite)
- **Migration Status**: ✅ Completed in migration 012
- **Natural Key Rationale**: Symbol + date uniquely identifies metrics record
- **Business Logic**: One metrics record per symbol per date
- **Unique Constraint**: `stock_metrics_symbol_date_unique`

#### 9. **orders**
- **Primary Key**: `brokerage_order_id` (TEXT)
- **Migration Status**: ✅ Completed in migration 012
- **Natural Key Rationale**: SnapTrade brokerage order ID is globally unique
- **Business Logic**: Each order has unique identifier from brokerage
- **Unique Constraint**: `orders_brokerage_order_id_unique`

#### 10. **account_balances**
- **Primary Key**: `(account_id, currency_code, snapshot_date)` (Composite)
- **Migration Status**: ✅ Completed in migration 012
- **Natural Key Rationale**: Account + currency + date uniquely identifies balance
- **Business Logic**: One balance record per account per currency per snapshot
- **Unique Constraint**: `account_balances_account_id_currency_code_snapshot_date_unique`

#### 11. **chart_metadata**
- **Primary Key**: `(symbol, period, interval, theme)` (Composite)
- **Migration Status**: ✅ Completed in migration 012
- **Natural Key Rationale**: Chart configuration uniquely identifies metadata
- **Business Logic**: One metadata record per chart configuration
- **Unique Constraint**: `chart_metadata_symbol_period_interval_theme_unique`

#### 12. **discord_processing_log**
- **Primary Key**: `(message_id, channel)` (Composite)
- **Migration Status**: ✅ Completed in migration 012
- **Natural Key Rationale**: Message + channel uniquely identifies processing record
- **Business Logic**: One processing log per message per channel
- **Unique Constraint**: `discord_processing_log_message_id_channel_unique`

#### 13. **schema_migrations**
- **Primary Key**: `version` (TEXT)
- **Migration Status**: ✅ Natural key from inception
- **Natural Key Rationale**: Migration version strings are unique
- **Business Logic**: Each migration has unique version identifier
- **Design Pattern**: Standard Rails/Laravel-style migration tracking

### 🟡 Hybrid Approach - Awaiting Assessment (3 tables)

#### 14. **accounts**
- **Current Primary Key**: `id` (TEXT) - Surrogate key maintained
- **Migration Status**: ⚠️ Evaluation pending
- **Alternative Natural Key**: Could use account number or brokerage-specific ID
- **Current Rationale**: SnapTrade account IDs may not be stable across integrations
- **Business Logic**: Account creation needs auto-increment behavior for new accounts
- **Assessment Needed**: Review SnapTrade account ID stability and uniqueness

#### 15. **symbols**
- **Current Primary Key**: `id` (TEXT) - Surrogate key maintained  
- **Migration Status**: ⚠️ Evaluation pending
- **Alternative Natural Key**: `ticker` symbol (with unique constraint)
- **Current Rationale**: No single reliable natural key across all asset types
- **Business Logic**: Symbol metadata may need synthetic keys for complex securities
- **Unique Constraint**: `symbols_ticker_unique` (added in migration 006)
- **Assessment Needed**: Evaluate ticker symbol as primary key feasibility

#### 16. **stock_charts**
- **Current Primary Key**: `id` (SERIAL) - Surrogate key maintained
- **Migration Status**: ⚠️ Evaluation pending  
- **Alternative Natural Key**: Could use composite of symbol + generated_at
- **Current Rationale**: Auto-increment efficient for chart storage and retrieval
- **Business Logic**: Chart generation creates many records, synthetic PK may be optimal
- **Assessment Needed**: Review chart storage patterns and query requirements

## 🎯 Natural Key Success Metrics

### Migration Completion Rate: **81.25%** (13/16 tables)

#### ✅ Successfully Migrated:
- **Social Data**: 5/5 tables (100%)
  - discord_messages, twitter_data, discord_market_clean, discord_trading_clean, processing_status
- **Market Data**: 3/3 tables (100%)
  - daily_prices, realtime_prices, stock_metrics  
- **Trading Data**: 2/2 tables (100%)
  - orders, account_balances
- **System Data**: 3/3 tables (100%)
  - chart_metadata, discord_processing_log, schema_migrations

#### ⚠️ Pending Assessment:
- **Account Management**: 1/1 table (accounts)
- **Reference Data**: 1/1 table (symbols)
- **Generated Content**: 1/1 table (stock_charts)

## 🔧 Implementation Patterns

### Successful Natural Key Patterns:

1. **Unique External IDs**: Discord/Twitter message IDs, brokerage order IDs
2. **Composite Business Keys**: Symbol+date for time-series data
3. **Configuration Keys**: Multi-field combinations for settings/metadata
4. **Reference Keys**: Message IDs for derived/processed data

### Remaining Surrogate Key Justifications:

1. **accounts**: Account creation workflow may need auto-increment
2. **symbols**: Complex financial instruments may lack consistent natural keys
3. **stock_charts**: High-volume generation may benefit from synthetic keys

## 📈 Benefits Achieved

### Data Integrity Improvements:
- **Eliminated redundant ID columns** in 13 tables
- **Strengthened referential integrity** with meaningful foreign keys
- **Reduced storage overhead** by removing unnecessary auto-increment columns

### Query Performance Improvements:
- **More efficient joins** using business-meaningful keys
- **Better index utilization** on natural primary keys
- **Reduced query complexity** with direct business key references

### Development Experience Improvements:
- **Clearer data relationships** in application code
- **More intuitive database queries** for business logic
- **Reduced mapping complexity** between business objects and database records

## 🎯 Future Considerations

### Remaining Migration Candidates:

#### **accounts** table:
- **Option 1**: Use SnapTrade account ID as natural PK (if stable)
- **Option 2**: Create composite key with institution + account number
- **Option 3**: Maintain current surrogate key approach
- **Decision Factors**: SnapTrade integration stability, account lifecycle

#### **symbols** table:
- **Option 1**: Use ticker as natural PK (already has unique constraint)
- **Option 2**: Create composite key with ticker + exchange
- **Option 3**: Maintain current surrogate key for complex instruments
- **Decision Factors**: Asset type diversity, cross-exchange symbol conflicts

#### **stock_charts** table:  
- **Option 1**: Use composite (symbol, chart_type, time_period, generated_at)
- **Option 2**: Create hash-based natural key from chart configuration
- **Option 3**: Maintain current auto-increment for performance
- **Decision Factors**: Chart storage volume, lookup patterns, cleanup requirements

## 📋 Maintenance Recommendations

### Schema Consistency:
1. **Complete migration assessment** for remaining 3 tables
2. **Document final PK decisions** with business justification
3. **Update application code** to leverage natural key patterns
4. **Add foreign key constraints** where appropriate

### Monitoring:
1. **Track query performance** on natural key operations
2. **Monitor storage savings** from eliminated ID columns  
3. **Validate data integrity** with natural key constraints
4. **Review developer feedback** on natural key usability

### Documentation:
1. **Update API documentation** to reflect natural key usage
2. **Create developer guidelines** for natural key best practices
3. **Document migration lessons learned** for future projects
4. **Maintain this catalog** as schema evolves

---

## Summary

The natural key migration has been **highly successful**, achieving 81.25% completion with significant benefits to data integrity, query performance, and developer experience. The remaining 3 tables require careful assessment of business requirements vs. technical constraints to determine optimal primary key strategies.

The migration demonstrates a mature approach to database design, prioritizing business meaning and data relationships over traditional auto-increment patterns where appropriate.