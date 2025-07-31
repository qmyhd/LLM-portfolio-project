"""
One-time migration from SQLite to PostgreSQL (Supabase).
This script migrates data from the local SQLite database to Supabase PostgreSQL.
"""
import os
import sys
import sqlite3
import pandas as pd
import logging
from pathlib import Path
from datetime import datetime
from sqlalchemy import text

# Use absolute imports instead of sys.path manipulation
from src.config import settings
from src.db import get_sync_engine, test_connection

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class SQLiteToPostgresMigrator:
    """Handles migration from SQLite to PostgreSQL"""
    
    def __init__(self):
        config = settings()
        # Ensure path is resolved relative to project root
        sqlite_path = Path(config.SQLITE_PATH)
        if not sqlite_path.is_absolute():
            # Make it relative to the project root (parent of scripts directory)
            project_root = Path(__file__).resolve().parent.parent
            self.sqlite_path = project_root / sqlite_path
        else:
            self.sqlite_path = sqlite_path
        self.postgres_engine = None
        self.migration_log = []
        
    def validate_setup(self):
        """Validate that both source and destination are available"""
        logger.info("Validating migration setup...")
        
        # Check environment variables
        config = settings()
        required_vars = ['DATABASE_URL']
        missing_vars = []
        
        for var in required_vars:
            if not getattr(config, var, None):
                missing_vars.append(var)
        
        if missing_vars:
            raise ValueError(f"Missing environment variables: {missing_vars}")
        
        # Check SQLite database exists
        if not self.sqlite_path.exists():
            raise FileNotFoundError(f"SQLite database not found: {self.sqlite_path}")
        
        # Verify SQLite database is readable
        try:
            conn = sqlite3.connect(self.sqlite_path)
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' LIMIT 1")
            conn.close()
        except Exception as e:
            raise ValueError(f"SQLite database exists but is not readable: {e}")
        
        # Test PostgreSQL connection
        connection_info = test_connection()
        if connection_info["status"] != "connected":
            raise ConnectionError(f"PostgreSQL connection failed: {connection_info.get('error', 'Unknown error')}")
        
        logger.info("✅ Migration setup validation passed")
        return True
    
    def get_sqlite_tables(self):
        """Get list of tables from SQLite database"""
        try:
            conn = sqlite3.connect(self.sqlite_path)
            cursor = conn.cursor()
            
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [row[0] for row in cursor.fetchall()]
            
            conn.close()
            logger.info(f"Found {len(tables)} tables in SQLite: {tables}")
            return tables
        except Exception as e:
            logger.error(f"Failed to get SQLite tables: {e}")
            raise
    
    def check_postgres_tables(self):
        """Check which tables already exist in PostgreSQL"""
        try:
            query = text("""
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_schema = 'public'
            """)
            
            with get_sync_engine().connect() as conn:
                result = conn.execute(query)
                existing_tables = [row[0] for row in result.fetchall()]
            
            logger.info(f"Found {len(existing_tables)} existing tables in PostgreSQL: {existing_tables}")
            return existing_tables
        except Exception as e:
            logger.error(f"Failed to check PostgreSQL tables: {e}")
            return []
    
    def get_table_row_count(self, table_name, is_sqlite=True):
        """Get row count for a table"""
        try:
            if is_sqlite:
                conn = sqlite3.connect(self.sqlite_path)
                cursor = conn.cursor()
                cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
                count = cursor.fetchone()[0]
                conn.close()
            else:
                with get_sync_engine().connect() as conn:
                    result = conn.execute(text(f"SELECT COUNT(*) FROM {table_name}"))
                    row = result.fetchone()
                    count = row[0] if row else 0
            
            return count
        except Exception as e:
            logger.warning(f"Could not get row count for {table_name}: {e}")
            return 0
    
    def migrate_table(self, table_name, batch_size=1000):
        """Migrate a single table from SQLite to PostgreSQL"""
        logger.info(f"Migrating table: {table_name}")
        
        try:
            # Read data from SQLite
            sqlite_conn = sqlite3.connect(self.sqlite_path)
            df = pd.read_sql_query(f"SELECT * FROM {table_name}", sqlite_conn)
            sqlite_conn.close()
            
            if df.empty:
                logger.info(f"Table {table_name} is empty, skipping")
                self.migration_log.append({
                    "table": table_name,
                    "status": "skipped",
                    "reason": "empty",
                    "rows": 0
                })
                return True
            
            logger.info(f"Read {len(df)} rows from SQLite table {table_name}")
            
            # Handle data type conversions for PostgreSQL
            df = self.prepare_dataframe_for_postgres(df, table_name)
            
            # Write to PostgreSQL in batches
            engine = get_sync_engine()
            rows_written = 0
            
            for i in range(0, len(df), batch_size):
                batch = df.iloc[i:i + batch_size]
                batch.to_sql(
                    table_name,
                    engine,
                    if_exists='append',
                    index=False,
                    method='multi'  # Use multi-row INSERT for better performance
                )
                rows_written += len(batch)
                logger.info(f"Written {rows_written}/{len(df)} rows for {table_name}")
            
            logger.info(f"✅ Successfully migrated {table_name}: {rows_written} rows")
            self.migration_log.append({
                "table": table_name,
                "status": "success",
                "rows": rows_written,
                "timestamp": datetime.now().isoformat()
            })
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to migrate table {table_name}: {e}")
            self.migration_log.append({
                "table": table_name,
                "status": "failed",
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            })
            return False
    
    def prepare_dataframe_for_postgres(self, df, table_name):
        """Prepare DataFrame for PostgreSQL insertion"""
        # Handle common data type issues
        
        # Convert datetime columns
        datetime_columns = df.select_dtypes(include=['datetime64']).columns
        for col in datetime_columns:
            df[col] = pd.to_datetime(df[col], errors='coerce')
        
        # Handle JSON columns (convert dict/list to string)
        for col in df.columns:
            if df[col].dtype == 'object':
                # Check if column contains dict-like objects
                sample = df[col].dropna().head(5)
                if not sample.empty:
                    first_val = sample.iloc[0]
                    if isinstance(first_val, (dict, list)):
                        df[col] = df[col].astype(str)
        
        # Handle boolean columns
        boolean_columns = df.select_dtypes(include=['bool']).columns
        for col in boolean_columns:
            df[col] = df[col].astype(bool)
        
        # Replace NaN with None for PostgreSQL
        df = df.where(pd.notnull(df), None)
        
        logger.debug(f"Prepared DataFrame for {table_name}: {df.dtypes.to_dict()}")
        return df
    
    def run_migration(self, tables_to_migrate=None, skip_existing=True):
        """Run the complete migration process"""
        logger.info("Starting SQLite to PostgreSQL migration...")
        
        # Validate setup
        self.validate_setup()
        
        # Get list of tables
        sqlite_tables = self.get_sqlite_tables()
        postgres_tables = self.check_postgres_tables()
        
        if tables_to_migrate is None:
            tables_to_migrate = sqlite_tables
        
        # Filter out system tables and tables to skip
        system_tables = ['sqlite_sequence', 'sqlite_master']
        tables_to_migrate = [t for t in tables_to_migrate if t not in system_tables]
        
        if skip_existing:
            tables_to_migrate = [t for t in tables_to_migrate if t not in postgres_tables]
            if postgres_tables:
                logger.info(f"Skipping existing tables: {postgres_tables}")
        
        logger.info(f"Tables to migrate: {tables_to_migrate}")
        
        if not tables_to_migrate:
            logger.info("No tables to migrate")
            return True
        
        # Migrate each table
        successful_migrations = 0
        for table in tables_to_migrate:
            if self.migrate_table(table):
                successful_migrations += 1
        
        # Generate migration report
        self.generate_migration_report()
        
        success_rate = successful_migrations / len(tables_to_migrate) * 100
        logger.info(f"Migration completed: {successful_migrations}/{len(tables_to_migrate)} tables ({success_rate:.1f}%)")
        
        return successful_migrations == len(tables_to_migrate)
    
    def generate_migration_report(self):
        """Generate a detailed migration report"""
        logger.info("=== MIGRATION REPORT ===")
        
        successful = [log for log in self.migration_log if log["status"] == "success"]
        failed = [log for log in self.migration_log if log["status"] == "failed"]
        skipped = [log for log in self.migration_log if log["status"] == "skipped"]
        
        logger.info(f"Successful migrations: {len(successful)}")
        for migration in successful:
            logger.info(f"  ✅ {migration['table']}: {migration['rows']} rows")
        
        if failed:
            logger.error(f"Failed migrations: {len(failed)}")
            for migration in failed:
                logger.error(f"  ❌ {migration['table']}: {migration['error']}")
        
        if skipped:
            logger.info(f"Skipped migrations: {len(skipped)}")
            for migration in skipped:
                logger.info(f"  ⏭️ {migration['table']}: {migration['reason']}")
        
        total_rows = sum(m.get("rows", 0) for m in self.migration_log)
        logger.info(f"Total rows migrated: {total_rows}")

def main():
    """
    Main migration function with comprehensive error handling.
    
    Command line arguments:
        --tables: Specific tables to migrate (optional)
        --force: Overwrite existing tables (default: skip existing)
        --batch-size: Number of rows to insert per batch (default: 1000)
    """
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Migrate SQLite data to PostgreSQL",
        epilog="Example: python -m scripts.migrate_sqlite --tables positions orders --batch-size 500"
    )
    parser.add_argument("--tables", nargs="+", help="Specific tables to migrate")
    parser.add_argument("--force", action="store_true", help="Overwrite existing tables")
    parser.add_argument("--batch-size", type=int, default=1000, 
                       help="Batch size for inserts (default: 1000)")
    
    args = parser.parse_args()
    
    # Validate batch size
    if args.batch_size <= 0:
        logger.error("Batch size must be greater than 0")
        sys.exit(1)
    
    try:
        migrator = SQLiteToPostgresMigrator()
        
        success = migrator.run_migration(
            tables_to_migrate=args.tables,
            skip_existing=not args.force
        )
        
        if success:
            print("✅ Migration completed successfully!")
        else:
            print("❌ Migration completed with errors. Check logs for details.")
            sys.exit(1)
            
    except Exception as e:
        logger.error(f"Migration failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
