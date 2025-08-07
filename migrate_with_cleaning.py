#!/usr/bin/env python3
"""
Migration Integration Script
============================

Wires together the CSV cleaner and bulk insert helper to safely migrate
orders and discord_messages data while preventing SQL injection from % characters.

This script follows the step-by-step approach:
1. Clean CSV data (strip spaces, validate actions, handle % characters)
2. Refresh local schema to match Supabase DDL  
3. Bulk insert using named placeholders (safe for % characters)

Key safety features:
- VALID_ACTIONS filtering prevents "Invalid action 'BBG...'" errors
- Named SQL placeholders (:col) are immune to % characters in data
- Hardened retry decorator prevents infinite loops on parsing errors
- Schema refresh ensures table compatibility

Usage:
    python migrate_with_cleaning.py --file data/raw/orders.csv --table orders
    python migrate_with_cleaning.py --file data/raw/discord_msgs.csv --table discord_messages
    python migrate_with_cleaning.py --all  # Process all data files
"""

import argparse
import logging
import sys
from pathlib import Path
from typing import List, Dict, Any, Optional

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent / "src"))

from src.etl.clean_csv import clean_csv_file
from src.db.bulk import BulkInserter, bulk_insert_csv
from src.retry_utils import hardened_retry, database_retry
from src.database import execute_sql, use_postgres
from src.config import settings

logger = logging.getLogger(__name__)


# Data file mapping
DATA_FILES = {
    'orders': 'data/raw/orders.csv',
    'discord_messages': 'data/raw/discord_msgs.csv',
    'positions': 'data/raw/positions.csv'
}

# Table column mappings for validation
TABLE_COLUMNS = {
    'orders': [
        'brokerage_order_id', 'status', 'symbol', 'extracted_symbol',
        'universal_symbol', 'option_symbol', 'action', 'total_quantity',
        'open_quantity', 'canceled_quantity', 'filled_quantity',
        'execution_price', 'limit_price', 'stop_price', 'time_in_force',
        'time_placed', 'time_updated', 'time_executed', 'diary',
        'child_brokerage_order_ids', 'parent_brokerage_order_id',
        'state', 'account_id', 'user_id', 'user_secret'
    ],
    'discord_messages': [
        'message_id', 'author', 'author_id', 'content', 'channel',
        'timestamp', 'tickers_detected', 'tweet_urls', 'is_reply',
        'reply_to_id', 'mentions', 'num_chars', 'num_words', 'sentiment_score'
    ]
}


@hardened_retry(max_retries=3, delay=1)
def refresh_table_schema(table_name: str) -> bool:
    """
    Refresh a single table schema using the schema refresh script.
    
    Args:
        table_name: Name of table to refresh
        
    Returns:
        True if successful, False otherwise
    """
    if use_postgres():
        logger.info(f"Using PostgreSQL - schema refresh not needed for {table_name}")
        return True
    
    logger.info(f"Refreshing schema for table: {table_name}")
    
    # Import and use the schema refresh logic
    try:
        from refresh_local_schema import refresh_table_schema as refresh_func
        return refresh_func(table_name, force=True)
    except ImportError:
        logger.error("Could not import schema refresh functionality")
        return False


@database_retry(max_retries=2, delay=1)
def verify_table_exists(table_name: str) -> bool:
    """
    Verify that a table exists and has the expected structure.
    
    Args:
        table_name: Name of table to verify
        
    Returns:
        True if table exists and looks correct
    """
    try:
        if use_postgres():
            # PostgreSQL check - simplified approach
            try:
                result = execute_sql("""
                    SELECT COUNT(*) FROM information_schema.tables 
                    WHERE table_name = %s
                """, (table_name,), fetch_results=True)
                
                # Try to access the result in different ways
                count = 0
                if hasattr(result, '__iter__'):
                    result_list = list(result)
                    if result_list and len(result_list) > 0:
                        count = result_list[0][0]
                elif isinstance(result, list) and result:
                    count = result[0][0]
                
                if count > 0:
                    logger.info(f"✅ Table {table_name} exists in PostgreSQL")
                    return True
            except Exception as e:
                logger.warning(f"PostgreSQL table check failed for {table_name}: {e}")
        else:
            # SQLite check
            result = execute_sql("""
                SELECT name FROM sqlite_master 
                WHERE type='table' AND name=?
            """, (table_name,), fetch_results=True)
            
            if result:
                logger.info(f"✅ Table {table_name} exists in SQLite")
                return True
        
        logger.warning(f"❌ Table {table_name} does not exist")
        return False
        
    except Exception as e:
        logger.error(f"Failed to verify table {table_name}: {e}")
        return False


@hardened_retry(max_retries=2, delay=1)
def process_data_file(file_path: str, table_name: str, max_rows: Optional[int] = None) -> bool:
    """
    Process a single data file: clean, validate, and insert.
    
    Args:
        file_path: Path to CSV file to process
        table_name: Target table name
        max_rows: Optional limit on number of rows to process
        
    Returns:
        True if successful, False otherwise
    """
    file_path_obj = Path(file_path)
    
    if not file_path_obj.exists():
        logger.error(f"Data file not found: {file_path_obj}")
        return False
    
    logger.info(f"Processing {file_path_obj} -> {table_name}")
    
    try:
        # Step 1: Clean the CSV data
        logger.info("Step 1: Cleaning CSV data...")
        cleaned_df = clean_csv_file(file_path_obj, table_name)
        
        if cleaned_df is None or cleaned_df.empty:
            logger.warning(f"No data to process from {file_path_obj}")
            return True  # Not an error, just empty
        
        # Limit rows if requested
        if max_rows and len(cleaned_df) > max_rows:
            logger.info(f"Limiting to first {max_rows} rows")
            cleaned_df = cleaned_df.head(max_rows)
        
        logger.info(f"Cleaned data: {len(cleaned_df)} rows, {len(cleaned_df.columns)} columns")
        
        # Step 2: Validate table schema
        logger.info("Step 2: Validating table schema...")
        if not verify_table_exists(table_name):
            logger.info(f"Table {table_name} doesn't exist, refreshing schema...")
            if not refresh_table_schema(table_name):
                logger.error(f"Failed to create table {table_name}")
                return False
        
        # Step 3: Use BulkInserter to safely insert data
        logger.info("Step 3: Bulk inserting records...")
        inserter = BulkInserter(batch_size=100)
        success = inserter.insert_dataframe(
            df=cleaned_df,
            table_name=table_name,
            if_exists='append'
        )
        
        if success:
            logger.info(f"✅ Successfully processed {len(cleaned_df)} records into {table_name}")
            return True
        else:
            logger.error(f"❌ Failed to insert records into {table_name}")
            return False
            
    except Exception as e:
        logger.error(f"Failed to process {file_path}: {e}")
        return False


def process_all_data_files(max_rows: Optional[int] = None) -> bool:
    """
    Process all configured data files.
    
    Args:
        max_rows: Optional limit on rows per file
        
    Returns:
        True if all files processed successfully
    """
    logger.info("Processing all data files...")
    
    success_count = 0
    total_count = len(DATA_FILES)
    
    for table_name, file_path in DATA_FILES.items():
        logger.info(f"\n--- Processing {table_name} from {file_path} ---")
        
        if process_data_file(file_path, table_name, max_rows):
            success_count += 1
            logger.info(f"✅ {table_name} processed successfully")
        else:
            logger.error(f"❌ Failed to process {table_name}")
    
    logger.info(f"\nProcessing complete: {success_count}/{total_count} files successful")
    return success_count == total_count


def validate_environment() -> bool:
    """
    Validate that the environment is ready for migration.
    
    Returns:
        True if environment is valid
    """
    logger.info("Validating environment...")
    
    # Check if data directory exists
    data_dir = Path("data/raw")
    if not data_dir.exists():
        logger.error(f"Data directory not found: {data_dir}")
        return False
    
    # Check for data files
    missing_files = []
    for table_name, file_path in DATA_FILES.items():
        if not Path(file_path).exists():
            missing_files.append(file_path)
    
    if missing_files:
        logger.warning(f"Missing data files: {missing_files}")
        logger.info("This is not necessarily an error - only process files that exist")
    
    # Check database connectivity
    try:
        result = execute_sql("SELECT 1", fetch_results=True)
        if result:
            logger.info("✅ Database connectivity verified")
            return True
        else:
            logger.error("❌ Database connectivity failed")
            return False
    except Exception as e:
        logger.error(f"❌ Database error: {e}")
        return False


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Migrate data with cleaning and safe insertion")
    parser.add_argument(
        '--file', 
        type=str, 
        help='Specific CSV file to process'
    )
    parser.add_argument(
        '--table', 
        type=str, 
        help='Target table name (required if --file is used)'
    )
    parser.add_argument(
        '--all', 
        action='store_true', 
        help='Process all configured data files'
    )
    parser.add_argument(
        '--max-rows', 
        type=int, 
        help='Maximum rows to process per file (for testing)'
    )
    parser.add_argument(
        '--dry-run', 
        action='store_true', 
        help='Validate and clean data but do not insert'
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
    
    logger.info("🚀 Starting migration with cleaning...")
    
    # Validate environment
    if not validate_environment():
        logger.error("❌ Environment validation failed")
        return 1
    
    config = settings()
    logger.info(f"Using {'PostgreSQL' if use_postgres() else 'SQLite'} backend")
    
    try:
        if args.dry_run:
            logger.info("🔍 DRY RUN MODE - No data will be inserted")
        
        if args.file and args.table:
            # Process single file
            logger.info(f"Processing single file: {args.file} -> {args.table}")
            
            if args.dry_run:
                # Just clean and validate
                from src.etl.clean_csv import clean_csv_file
                cleaned_df = clean_csv_file(Path(args.file), args.table)
                if cleaned_df is not None:
                    logger.info(f"✅ File would be cleaned: {len(cleaned_df)} rows")
                    return 0
                else:
                    logger.error("❌ File cleaning failed")
                    return 1
            else:
                success = process_data_file(args.file, args.table, args.max_rows)
                return 0 if success else 1
                
        elif args.all:
            # Process all files
            logger.info("Processing all data files...")
            
            if args.dry_run:
                logger.info("Would process all files:")
                for table, file_path in DATA_FILES.items():
                    if Path(file_path).exists():
                        logger.info(f"  ✅ {file_path} -> {table}")
                    else:
                        logger.info(f"  ❌ {file_path} (missing)")
                return 0
            else:
                success = process_all_data_files(args.max_rows)
                return 0 if success else 1
        else:
            # Show usage
            parser.print_help()
            print("\nExample usage:")
            print("  python migrate_with_cleaning.py --all")
            print("  python migrate_with_cleaning.py --file data/raw/orders.csv --table orders")
            print("  python migrate_with_cleaning.py --all --dry-run --max-rows 100")
            return 1
            
    except KeyboardInterrupt:
        logger.info("❌ Operation cancelled by user")
        return 1
    except Exception as e:
        logger.error(f"❌ Unexpected error: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
