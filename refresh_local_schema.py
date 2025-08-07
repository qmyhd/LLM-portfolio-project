#!/usr/bin/env python3
"""
Local Schema Refresh Script
===========================

Drops and recreates local SQLite tables to match Supabase schema.
Essential for preventing schema mismatches during data migration.

This script ensures that local tables have the same structure as Supabase,
preventing insert failures due to missing columns or type mismatches.

Key tables updated:
- orders: Complete SnapTrade schema with all fields
- discord_messages: Full Discord message schema
- discord_general_clean: Processed general channel messages  
- discord_trading_clean: Processed trading channel messages

Usage:
    python refresh_local_schema.py [--tables orders,discord_messages]
"""

from typing import List, Optional
import argparse
import logging
import sys
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from src.database import execute_sql, get_connection, use_postgres
from src.config import settings

logger = logging.getLogger(__name__)


# Supabase-compatible DDL statements
SUPABASE_SCHEMA_DDL = {
    'orders': """
        DROP TABLE IF EXISTS orders;
        CREATE TABLE orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            brokerage_order_id TEXT,
            status TEXT,
            symbol TEXT,
            extracted_symbol TEXT,
            universal_symbol TEXT,
            option_symbol TEXT,
            action TEXT,
            total_quantity REAL,
            open_quantity REAL,
            canceled_quantity REAL,
            filled_quantity REAL,
            execution_price REAL,
            limit_price REAL,
            stop_price REAL,
            time_in_force TEXT,
            time_placed TEXT,
            time_updated TEXT,
            time_executed TEXT,
            diary TEXT,
            child_brokerage_order_ids TEXT,
            parent_brokerage_order_id TEXT,
            state TEXT,
            account_id TEXT,
            user_id TEXT,
            user_secret TEXT,
            sync_timestamp TEXT DEFAULT CURRENT_TIMESTAMP,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_orders_symbol ON orders(symbol);
        CREATE INDEX IF NOT EXISTS idx_orders_extracted_symbol ON orders(extracted_symbol);
        CREATE INDEX IF NOT EXISTS idx_orders_sync_timestamp ON orders(sync_timestamp);
        CREATE INDEX IF NOT EXISTS idx_orders_action ON orders(action);
        CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);
    """,
    
    'discord_messages': """
        DROP TABLE IF EXISTS discord_messages;
        CREATE TABLE discord_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message_id TEXT UNIQUE NOT NULL,
            author TEXT NOT NULL,
            author_id TEXT,
            content TEXT NOT NULL,
            channel TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            tickers_detected TEXT,
            tweet_urls TEXT,
            is_reply BOOLEAN DEFAULT 0,
            reply_to_id TEXT,
            mentions TEXT,
            num_chars INTEGER,
            num_words INTEGER,
            sentiment_score REAL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_discord_messages_message_id ON discord_messages(message_id);
        CREATE INDEX IF NOT EXISTS idx_discord_messages_channel ON discord_messages(channel);
        CREATE INDEX IF NOT EXISTS idx_discord_messages_timestamp ON discord_messages(timestamp);
        CREATE INDEX IF NOT EXISTS idx_discord_messages_author ON discord_messages(author);
    """,
    
    'discord_general_clean': """
        DROP TABLE IF EXISTS discord_general_clean;
        CREATE TABLE discord_general_clean (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message_id TEXT UNIQUE NOT NULL,
            author TEXT NOT NULL,
            content TEXT NOT NULL,
            sentiment REAL,
            cleaned_content TEXT,
            timestamp TEXT NOT NULL,
            processed_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_discord_general_clean_message_id ON discord_general_clean(message_id);
        CREATE INDEX IF NOT EXISTS idx_discord_general_clean_timestamp ON discord_general_clean(timestamp);
    """,
    
    'discord_trading_clean': """
        DROP TABLE IF EXISTS discord_trading_clean;
        CREATE TABLE discord_trading_clean (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message_id TEXT UNIQUE NOT NULL,
            author TEXT NOT NULL,
            content TEXT NOT NULL,
            sentiment REAL,
            cleaned_content TEXT,
            stock_mentions TEXT,
            timestamp TEXT NOT NULL,
            processed_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_discord_trading_clean_message_id ON discord_trading_clean(message_id);
        CREATE INDEX IF NOT EXISTS idx_discord_trading_clean_timestamp ON discord_trading_clean(timestamp);
        CREATE INDEX IF NOT EXISTS idx_discord_trading_clean_stock_mentions ON discord_trading_clean(stock_mentions);
    """,
    
    'positions': """
        DROP TABLE IF EXISTS positions;
        CREATE TABLE positions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            quantity REAL NOT NULL,
            equity REAL,
            price REAL,
            average_buy_price REAL,
            type TEXT,
            currency TEXT DEFAULT 'USD',
            sync_timestamp TEXT NOT NULL,
            calculated_equity REAL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_positions_symbol ON positions(symbol);
        CREATE INDEX IF NOT EXISTS idx_positions_sync_timestamp ON positions(sync_timestamp);
    """,
    
    'twitter_data': """
        DROP TABLE IF EXISTS twitter_data;
        CREATE TABLE twitter_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tweet_id TEXT,
            discord_message_id TEXT,
            discord_sent_date TEXT,
            tweet_created_date TEXT,
            tweet_content TEXT,
            author_username TEXT,
            author_name TEXT,
            retweet_count INTEGER DEFAULT 0,
            like_count INTEGER DEFAULT 0,
            reply_count INTEGER DEFAULT 0,
            quote_count INTEGER DEFAULT 0,
            stock_tags TEXT,
            source_url TEXT,
            retrieved_at TEXT,
            message_id TEXT,
            discord_date TEXT,
            tweet_date TEXT,
            content TEXT,
            author TEXT,
            channel TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_twitter_data_tweet_id ON twitter_data(tweet_id);
        CREATE INDEX IF NOT EXISTS idx_twitter_data_discord_message_id ON twitter_data(discord_message_id);
        CREATE INDEX IF NOT EXISTS idx_twitter_data_stock_tags ON twitter_data(stock_tags);
    """
}


def refresh_table_schema(table_name: str, force: bool = False) -> bool:
    """
    Refresh a single table schema to match Supabase.
    
    Args:
        table_name: Name of table to refresh
        force: If True, proceed without confirmation
        
    Returns:
        True if successful, False otherwise
    """
    if table_name not in SUPABASE_SCHEMA_DDL:
        logger.error(f"Unknown table: {table_name}")
        return False
    
    if use_postgres():
        logger.warning("Running against PostgreSQL - schema refresh not needed")
        return True
    
    if not force:
        response = input(f"⚠️  This will DROP and recreate table '{table_name}'. Continue? (y/N): ")
        if response.lower() != 'y':
            logger.info("Operation cancelled by user")
            return False
    
    logger.info(f"Refreshing schema for table: {table_name}")
    
    try:
        # Execute the DDL statements
        ddl_statements = SUPABASE_SCHEMA_DDL[table_name].strip().split(';')
        
        for statement in ddl_statements:
            statement = statement.strip()
            if statement:  # Skip empty statements
                logger.debug(f"Executing: {statement[:100]}...")
                execute_sql(statement)
        
        logger.info(f"✅ Successfully refreshed schema for {table_name}")
        return True
        
    except Exception as e:
        logger.error(f"❌ Failed to refresh schema for {table_name}: {e}")
        return False


def refresh_all_schemas(tables: Optional[List[str]] = None, force: bool = False) -> bool:
    """
    Refresh schemas for multiple tables.
    
    Args:
        tables: List of table names to refresh (default: all critical tables)
        force: If True, proceed without confirmation
        
    Returns:
        True if all successful, False if any failed
    """
    if tables is None:
        tables = ['orders', 'discord_messages', 'discord_general_clean', 'discord_trading_clean']
    
    logger.info(f"Refreshing schemas for {len(tables)} tables: {', '.join(tables)}")
    
    if not force:
        print("⚠️  This will DROP and recreate the following tables:")
        for table in tables:
            print(f"   - {table}")
        print("\n🚨 ALL DATA IN THESE TABLES WILL BE LOST!")
        response = input("\nContinue? (y/N): ")
        if response.lower() != 'y':
            logger.info("Operation cancelled by user")
            return False
    
    success_count = 0
    for table_name in tables:
        if refresh_table_schema(table_name, force=True):
            success_count += 1
        else:
            logger.error(f"Failed to refresh {table_name}")
    
    if success_count == len(tables):
        logger.info(f"✅ Successfully refreshed all {len(tables)} table schemas")
        return True
    else:
        logger.error(f"❌ Only {success_count}/{len(tables)} tables refreshed successfully")
        return False


def verify_schema(table_name: str) -> bool:
    """
    Verify that a table schema matches expectations.
    
    Args:
        table_name: Name of table to verify
        
    Returns:
        True if schema is correct, False otherwise
    """
    try:
        # Get table info
        if use_postgres():
            # PostgreSQL - check information_schema
            result = execute_sql("""
                SELECT column_name, data_type 
                FROM information_schema.columns 
                WHERE table_name = %s
                ORDER BY ordinal_position
            """, (table_name,), fetch_results=True)
        else:
            # SQLite - use PRAGMA
            result = execute_sql(f"PRAGMA table_info({table_name})", fetch_results=True)
        
        try:
            # Handle different result types safely
            if hasattr(result, 'fetchall') and callable(getattr(result, 'fetchall')):
                # It's a cursor, fetch all results
                result_list = result.fetchall()
            elif isinstance(result, list):
                # It's already a list
                result_list = result
            else:
                # Try to convert to list
                result_list = list(result)
        except Exception as e:
            logger.error(f"Failed to process result for {table_name}: {e}")
            return False
            
        if not result_list:
            logger.error(f"Table {table_name} does not exist")
            return False
            
        column_count = len(result_list)
        logger.info(f"Table {table_name} has {column_count} columns")
        
        # Log first few columns for verification
        try:
            if use_postgres():
                columns = [f"{row[0]}({row[1]})" for row in result_list[:5]]
            else:
                columns = [f"{row[1]}({row[2]})" for row in result_list[:5]]
            
            logger.info(f"First columns: {', '.join(columns)}")
        except (IndexError, TypeError) as e:
            logger.warning(f"Could not display column info for {table_name}: {e}")
        return True
        
    except Exception as e:
        logger.error(f"Failed to verify schema for {table_name}: {e}")
        return False


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Refresh local SQLite schemas to match Supabase")
    parser.add_argument(
        '--tables', 
        type=str, 
        help='Comma-separated list of tables to refresh (default: orders,discord_messages)'
    )
    parser.add_argument(
        '--force', 
        action='store_true', 
        help='Skip confirmation prompts'
    )
    parser.add_argument(
        '--verify-only', 
        action='store_true', 
        help='Only verify schemas, do not modify'
    )
    parser.add_argument(
        '--verbose', 
        action='store_true', 
        help='Enable verbose logging'
    )
    
    args = parser.parse_args()
    
    # Configure logging
    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    
    # Parse table list
    if args.tables:
        tables = [t.strip() for t in args.tables.split(',')]
    else:
        tables = ['orders', 'discord_messages', 'discord_general_clean', 'discord_trading_clean']
    
    # Verify environment
    config = settings()
    logger.info(f"Using {'PostgreSQL' if use_postgres() else 'SQLite'} backend")
    
    if use_postgres():
        logger.warning("Running against PostgreSQL - schema operations may not be needed")
    
    try:
        if args.verify_only:
            # Verify schemas only
            logger.info("Verifying table schemas...")
            all_good = True
            for table in tables:
                if not verify_schema(table):
                    all_good = False
            
            if all_good:
                logger.info("✅ All table schemas verified successfully")
                return 0
            else:
                logger.error("❌ Some table schemas have issues")
                return 1
        else:
            # Refresh schemas
            success = refresh_all_schemas(tables, args.force)
            
            if success:
                logger.info("🎉 Schema refresh completed successfully")
                
                # Verify the refreshed schemas
                logger.info("Verifying refreshed schemas...")
                for table in tables:
                    verify_schema(table)
                
                return 0
            else:
                logger.error("❌ Schema refresh failed")
                return 1
                
    except KeyboardInterrupt:
        logger.info("Operation cancelled by user")
        return 1
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
