"""
Database initialization script for LLM Portfolio Journal.
Run this to set up all required tables for social and financial data.
"""

import logging
import os
import sys
from pathlib import Path

# Load environment variables first
from dotenv import load_dotenv
load_dotenv()

# Add src directory to path for imports
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))

def initialize_postgres_tables():
    """Initialize PostgreSQL tables using direct psycopg2 connection with explicit commits."""
    
    # Import here to ensure path is set up
    try:
        import psycopg2
        from psycopg2.extras import DictCursor
    except ImportError:
        raise ImportError("psycopg2 not installed. Install with: pip install psycopg2-binary")
    
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise ValueError("DATABASE_URL environment variable not set")
    
    # Define PostgreSQL table creation schema
    SCHEMA_SQL = """
    -- Discord and social media tables
    CREATE TABLE IF NOT EXISTS discord_messages (
        id SERIAL PRIMARY KEY,
        message_id TEXT UNIQUE NOT NULL,
        author TEXT NOT NULL,
        content TEXT NOT NULL,
        channel TEXT NOT NULL,
        timestamp TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS twitter_data (
        id SERIAL PRIMARY KEY,
        message_id TEXT NOT NULL,
        discord_date TEXT NOT NULL,
        tweet_date TEXT,
        content TEXT NOT NULL,
        stock_tags TEXT,
        author TEXT NOT NULL,
        channel TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS discord_general_clean (
        id SERIAL PRIMARY KEY,
        message_id TEXT UNIQUE NOT NULL,
        author TEXT NOT NULL,
        content TEXT NOT NULL,
        sentiment REAL,
        cleaned_content TEXT,
        timestamp TEXT NOT NULL,
        processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS discord_trading_clean (
        id SERIAL PRIMARY KEY,
        message_id TEXT UNIQUE NOT NULL,
        author TEXT NOT NULL,
        content TEXT NOT NULL,
        sentiment REAL,
        cleaned_content TEXT,
        stock_mentions TEXT,
        timestamp TEXT NOT NULL,
        processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS chart_metadata (
        id SERIAL PRIMARY KEY,
        symbol TEXT NOT NULL,
        period TEXT NOT NULL,
        interval TEXT NOT NULL,
        theme TEXT NOT NULL,
        file_path TEXT NOT NULL,
        trade_count INTEGER DEFAULT 0,
        min_trade_size REAL DEFAULT 0.0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS processing_status (
        id SERIAL PRIMARY KEY,
        message_id TEXT UNIQUE NOT NULL,
        channel TEXT NOT NULL,
        processed_for_cleaning BOOLEAN DEFAULT FALSE,
        processed_for_twitter BOOLEAN DEFAULT FALSE,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    -- Financial data tables
    CREATE TABLE IF NOT EXISTS daily_prices (
        id SERIAL PRIMARY KEY,
        symbol TEXT NOT NULL,
        date TEXT NOT NULL,
        open REAL,
        high REAL,
        low REAL,
        close REAL,
        volume INTEGER,
        dividends REAL,
        stock_splits REAL,
        UNIQUE(symbol, date)
    );

    CREATE TABLE IF NOT EXISTS realtime_prices (
        id SERIAL PRIMARY KEY,
        symbol TEXT NOT NULL,
        timestamp TEXT NOT NULL,
        price REAL,
        previous_close REAL,
        abs_change REAL,
        percent_change REAL,
        UNIQUE(symbol, timestamp)
    );

    CREATE TABLE IF NOT EXISTS stock_metrics (
        id SERIAL PRIMARY KEY,
        symbol TEXT NOT NULL,
        date TEXT NOT NULL,
        pe_ratio REAL,
        market_cap REAL,
        dividend_yield REAL,
        fifty_day_avg REAL,
        two_hundred_day_avg REAL,
        UNIQUE(symbol, date)
    );

    CREATE TABLE IF NOT EXISTS positions (
        id SERIAL PRIMARY KEY,
        symbol TEXT NOT NULL,
        quantity REAL,
        equity REAL,
        price REAL,
        average_buy_price REAL,
        type TEXT,
        currency TEXT,
        sync_timestamp TEXT NOT NULL,
        calculated_equity REAL,
        UNIQUE(symbol, sync_timestamp)
    );

    CREATE TABLE IF NOT EXISTS orders (
        brokerage_order_id TEXT,
        status TEXT,
        symbol TEXT,
        universal_symbol TEXT,
        quote_universal_symbol TEXT,
        quote_currency TEXT,
        option_symbol TEXT,
        action TEXT,
        total_quantity INTEGER,
        open_quantity INTEGER,
        canceled_quantity INTEGER,
        filled_quantity INTEGER,
        execution_price DECIMAL(18, 6),
        limit_price DECIMAL(18, 6),
        stop_price DECIMAL(18, 6),
        order_type TEXT,
        time_in_force TEXT,
        time_placed TIMESTAMP,
        time_updated TIMESTAMP,
        time_executed TIMESTAMP,
        expiry_date DATE,
        child_brokerage_order_ids TEXT,
        extracted_symbol TEXT
    );

    CREATE TABLE IF NOT EXISTS stock_charts (
        id SERIAL PRIMARY KEY,
        symbol TEXT NOT NULL,
        period TEXT NOT NULL,
        interval TEXT NOT NULL,
        theme TEXT NOT NULL,
        file_path TEXT NOT NULL,
        created_at TEXT NOT NULL,
        trade_count INTEGER DEFAULT 0,
        min_trade_size REAL DEFAULT 0.0,
        UNIQUE(symbol, period, interval, theme, created_at)
    );
    """
    
    # Connect and execute with explicit commit
    conn = psycopg2.connect(database_url, cursor_factory=DictCursor)
    cur = conn.cursor()
    try:
        cur.execute(SCHEMA_SQL)
        conn.commit()  # 🟢 Explicit commit for DDL statements
        print("✅ Tables created successfully")
        
        # Verify tables were created
        cur.execute("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public'
            ORDER BY table_name
        """)
        tables = [row[0] for row in cur.fetchall()]
        print(f"✅ Created {len(tables)} tables: {', '.join(tables)}")
        
        return True
        
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()

def main():
    """Initialize the database with all required tables."""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    
    logger = logging.getLogger(__name__)
    
    try:
        logger.info("Initializing database with all required tables...")
        initialize_postgres_tables()
        logger.info("Database initialization completed successfully!")
        
        # Print table creation summary
        print("\n✅ Database initialized successfully!")
        print("\nCreated tables:")
        print("📱 Social Media Data:")
        print("• discord_messages (raw message data)")
        print("• twitter_data (Twitter posts with stock tags)")
        print("• discord_general_clean (processed general channel data)")
        print("• discord_trading_clean (processed trading channel data)")
        print("• processing_status (tracks what's been processed)")
        print("\n📊 Financial Data:")
        print("• daily_prices (historical stock prices)")
        print("• realtime_prices (current market data)")
        print("• stock_metrics (P/E ratios, market cap, etc.)")
        print("• positions (portfolio holdings snapshots)")
        print("• orders (trade history)")
        print("• stock_charts (chart generation metadata)")
        print("\n🎨 Chart Data:")
        print("• chart_metadata (chart generation tracking)")
        
        print("\n📝 Next steps:")
        print("1. Enable Row-Level Security (RLS) in Supabase")
        print("2. Use Discord bot !history command to collect messages")
        print("3. Use !process [general|trading] to clean and process messages")
        print("4. Use !stats to see processing statistics")
        print("5. Run generate_journal.py to create portfolio summaries")
        
    except Exception as e:
        logger.error(f"Error initializing database: {e}")
        print(f"\n❌ Error: {e}")
        return 1
    
    return 0

def enable_row_level_security():
    """Enable Row-Level Security on all tables with permissive policies."""
    try:
        import psycopg2
        from psycopg2.extras import DictCursor
    except ImportError:
        raise ImportError("psycopg2 not installed. Install with: pip install psycopg2-binary")
    
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise ValueError("DATABASE_URL environment variable not set")
    
    # List of all tables that need RLS
    tables = [
        'discord_messages', 'twitter_data', 'discord_general_clean', 'discord_trading_clean',
        'chart_metadata', 'processing_status', 'daily_prices', 'realtime_prices', 
        'stock_metrics', 'positions', 'orders', 'stock_charts'
    ]
    
    # Public readable tables (subset)
    public_readable_tables = ['daily_prices', 'realtime_prices', 'stock_metrics', 'stock_charts']
    
    conn = psycopg2.connect(database_url, cursor_factory=DictCursor)
    cur = conn.cursor()
    
    try:
        policies_created = 0
        policies_skipped = 0
        
        # Get existing policies to avoid duplicates
        cur.execute("""
            SELECT policyname, tablename 
            FROM pg_policies 
            WHERE schemaname = 'public'
        """)
        existing_policies = {(row[0], row[1]) for row in cur.fetchall()}
        
        # Enable RLS on all tables
        for table in tables:
            try:
                cur.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
            except psycopg2.Error:
                pass  # RLS already enabled, ignore error
        
        # Create service role policies (check for existence first)
        for table in tables:
            policy_name = f"service_role_all_{table}"
            if (policy_name, table) in existing_policies:
                policies_skipped += 1
                continue
                
            cur.execute(f"""
                CREATE POLICY {policy_name} ON {table} 
                FOR ALL USING (auth.role() = 'service_role')
            """)
            policies_created += 1
        
        # Create public read-only policies for specific tables
        for table in public_readable_tables:
            policy_name = f"anon_select_{table}"
            if (policy_name, table) in existing_policies:
                policies_skipped += 1
                continue
                
            cur.execute(f"""
                CREATE POLICY {policy_name} ON {table} 
                FOR SELECT USING (true)
            """)
            policies_created += 1
        
        conn.commit()
        print(f"✅ Row-Level Security enabled: {policies_created} policies created, {policies_skipped} already existed")
        return True
        
    except Exception as e:
        conn.rollback()
        print(f"❌ RLS setup failed: {e}")
        return False
    finally:
        cur.close()
        conn.close()

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Initialize PostgreSQL database tables")
    parser.add_argument("--enable-rls", action="store_true", 
                       help="Also enable Row-Level Security policies")
    
    args = parser.parse_args()
    
    # Run main initialization
    result = main()
    
    # Optionally enable RLS
    if args.enable_rls and result == 0:
        print("\n🔒 Enabling Row-Level Security...")
        enable_row_level_security()
    
    exit(result)
