import logging
import sqlite3
from pathlib import Path

# Use absolute imports
try:
    from src.config import settings
    from src.db import execute_query
    from src.db import get_connection as get_postgres_connection
    POSTGRES_AVAILABLE = True
except ImportError:
    try:
        # Fallback for when running from scripts
        from config import settings
        from db import execute_query
        from db import get_connection as get_postgres_connection
        POSTGRES_AVAILABLE = True
    except ImportError:
        settings = None
        POSTGRES_AVAILABLE = False
        logging.warning("PostgreSQL system not available, using SQLite fallback")

BASE_DIR = Path(__file__).resolve().parents[1]
DB_PATH = BASE_DIR / "data" / "database" / "price_history.db"

def use_postgres() -> bool:
    """Check if we should use PostgreSQL instead of SQLite"""
    if not POSTGRES_AVAILABLE or settings is None:
        return False
    
    try:
        config = settings()
        database_url = config.DATABASE_URL
        return bool(database_url and database_url.startswith("postgresql"))
    except Exception as e:
        logging.warning(f"Error checking PostgreSQL availability: {e}")
        return False

def get_connection(path: Path = DB_PATH):
    """
    Return a database connection. 
    Uses PostgreSQL if configured, otherwise falls back to SQLite.
    """
    if settings is None:
        # No configuration available, use SQLite
        path.parent.mkdir(parents=True, exist_ok=True)
        return sqlite3.connect(path)
    
    config = settings()
    database_url = config.DATABASE_URL
    
    if database_url and database_url.startswith("postgresql"):
        try:
            return get_postgres_connection()
        except Exception as e:
            logging.warning(f"PostgreSQL connection failed: {e}")
            # Check if SQLite fallback is allowed
            if not config.ALLOW_SQLITE_FALLBACK:
                raise RuntimeError("DATABASE_URL is configured but connection failed, and SQLite fallback is not allowed")
            logging.info("Falling back to SQLite")
    
    # SQLite fallback - only if explicitly allowed or no DATABASE_URL
    if not database_url or config.ALLOW_SQLITE_FALLBACK:
        path.parent.mkdir(parents=True, exist_ok=True)
        return sqlite3.connect(path)
    
    # If we get here, DATABASE_URL is configured but failed, and fallback not allowed
    raise RuntimeError("DATABASE_URL is required but connection failed")

def execute_sql(query: str, params=None, fetch_results=False):
    """
    Execute SQL query with support for both PostgreSQL and SQLite.
    """
    # Try PostgreSQL first if available
    if use_postgres():
        try:
            from sqlalchemy import text
            result = execute_query(text(query), params)
            if fetch_results:
                return result.fetchall()
            return result
        except Exception as e:
            logging.warning(f"PostgreSQL query failed: {e}")
            if settings is not None:
                config = settings()
                if not config.get("ALLOW_SQLITE_FALLBACK", False):
                    raise
            logging.info("Falling back to SQLite for query execution")
    
    # SQLite fallback
    sqlite_path = BASE_DIR / "data" / "database" / "price_history.db"
    sqlite_path.parent.mkdir(parents=True, exist_ok=True)
    
    with sqlite3.connect(sqlite_path) as conn:
        cursor = conn.cursor()
        if params:
            cursor.execute(query, params)
        else:
            cursor.execute(query)
        
        if fetch_results:
            return cursor.fetchall()
        
        conn.commit()
        return cursor

def initialize_database():
    """Initialize the database with all required tables (both social and financial data)."""
    if use_postgres():
        # Use direct psycopg2 with explicit commits for PostgreSQL (working approach)
        try:
            import psycopg2
            from psycopg2.extras import DictCursor
            from src.config import get_database_url
            
            database_url = get_database_url()
            
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
                logging.info("Database initialized successfully with all tables (social and financial data)")
                return True
            except Exception:
                conn.rollback()
                raise
            finally:
                cur.close()
                conn.close()
                
        except ImportError:
            logging.error("psycopg2 not installed. Install with: pip install psycopg2-binary")
            raise
        except Exception as e:
            logging.error(f"Failed to initialize PostgreSQL database: {e}")
            raise
    else:
        # SQLite fallback
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        
        # Define SQLite table creation queries
        tables = [
            """
            CREATE TABLE IF NOT EXISTS discord_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message_id TEXT UNIQUE NOT NULL,
                author TEXT NOT NULL,
                content TEXT NOT NULL,
                channel TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS twitter_data (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message_id TEXT NOT NULL,
                discord_date TEXT NOT NULL,
                tweet_date TEXT,
                content TEXT NOT NULL,
                stock_tags TEXT,
                author TEXT NOT NULL,
                channel TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS discord_general_clean (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message_id TEXT UNIQUE NOT NULL,
                author TEXT NOT NULL,
                content TEXT NOT NULL,
                sentiment REAL,
                cleaned_content TEXT,
                timestamp TEXT NOT NULL,
                processed_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS discord_trading_clean (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message_id TEXT UNIQUE NOT NULL,
                author TEXT NOT NULL,
                content TEXT NOT NULL,
                sentiment REAL,
                cleaned_content TEXT,
                stock_mentions TEXT,
                timestamp TEXT NOT NULL,
                processed_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS chart_metadata (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                period TEXT NOT NULL,
                interval TEXT NOT NULL,
                theme TEXT NOT NULL,
                file_path TEXT NOT NULL,
                trade_count INTEGER DEFAULT 0,
                min_trade_size REAL DEFAULT 0.0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS processing_status (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message_id TEXT UNIQUE NOT NULL,
                channel TEXT NOT NULL,
                processed_for_cleaning INTEGER DEFAULT 0,
                processed_for_twitter INTEGER DEFAULT 0,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS daily_prices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
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
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS realtime_prices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                price REAL,
                previous_close REAL,
                abs_change REAL,
                percent_change REAL,
                UNIQUE(symbol, timestamp)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS stock_metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                date TEXT NOT NULL,
                pe_ratio REAL,
                market_cap REAL,
                dividend_yield REAL,
                fifty_day_avg REAL,
                two_hundred_day_avg REAL,
                UNIQUE(symbol, date)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS positions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
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
            )
            """,
            """
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
                execution_price REAL,
                limit_price REAL,
                stop_price REAL,
                order_type TEXT,
                time_in_force TEXT,
                time_placed DATETIME,
                time_updated DATETIME,
                time_executed DATETIME,
                expiry_date DATE,
                child_brokerage_order_ids TEXT,
                extracted_symbol TEXT
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS stock_charts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                period TEXT NOT NULL,
                interval TEXT NOT NULL,
                theme TEXT NOT NULL,
                file_path TEXT NOT NULL,
                created_at TEXT NOT NULL,
                trade_count INTEGER DEFAULT 0,
                min_trade_size REAL DEFAULT 0.0,
                UNIQUE(symbol, period, interval, theme, created_at)
            )
            """
        ]
        
        try:
            for query in tables:
                execute_sql(query)
            logging.info("Database initialized successfully with all tables (social and financial data)")
        except Exception as e:
            logging.error(f"Failed to initialize SQLite database: {e}")
            raise

def mark_message_processed(message_id: str, channel: str, processing_type: str):
    """Mark a message as processed for a specific type."""
    try:
        if processing_type == "cleaning":
            column = "processed_for_cleaning"
        elif processing_type == "twitter":
            column = "processed_for_twitter"
        else:
            raise ValueError(f"Invalid processing type: {processing_type}")
        
        if use_postgres():
            query = f"""
            INSERT INTO processing_status (message_id, channel, {column}, updated_at)
            VALUES (%s, %s, TRUE, CURRENT_TIMESTAMP)
            ON CONFLICT (message_id) DO UPDATE SET
            {column} = TRUE,
            updated_at = CURRENT_TIMESTAMP
            """
            params = (message_id, channel)
        else:
            # SQLite uses INSERT OR REPLACE
            query = f"""
            INSERT OR REPLACE INTO processing_status 
            (message_id, channel, {column}, updated_at)
            VALUES (?, ?, 1, DATETIME('now'))
            """
            params = (message_id, channel)
        
        execute_sql(query, params)
        
    except Exception as e:
        logging.error(f"Error marking message as processed: {e}")

def get_unprocessed_messages(channel: str | None = None, processing_type: str = "cleaning"):
    """Get messages that haven't been processed yet."""
    try:
        if processing_type == "cleaning":
            column = "processed_for_cleaning"
        elif processing_type == "twitter":
            column = "processed_for_twitter"
        else:
            raise ValueError(f"Invalid processing type: {processing_type}")
        
        query = f"""
        SELECT dm.message_id, dm.author, dm.content, dm.channel, dm.timestamp
        FROM discord_messages dm
        LEFT JOIN processing_status ps ON dm.message_id = ps.message_id
        WHERE (ps.{column} IS NULL OR ps.{column} = %s)
        """
        
        params = []
        false_value = "FALSE" if use_postgres() else "0"
        params.append(false_value)
        
        if channel:
            query += " AND dm.channel = %s" if use_postgres() else " AND dm.channel = ?"
            params.append(channel)
        
        query += " ORDER BY dm.timestamp"
        
        # Handle parameter placeholders
        if not use_postgres():
            query = query.replace("%s", "?")
        
        return execute_sql(query, params if params else None, fetch_results=True)
        
    except Exception as e:
        logging.error(f"Error getting unprocessed messages: {e}")
        return []

if __name__ == "__main__":
    # Test database functionality
    print("Testing database functionality...")
    try:
        print(f"Using PostgreSQL: {use_postgres()}")
        initialize_database()
        print("✅ Database initialized successfully")
    except Exception as e:
        print(f"❌ Database test failed: {e}")
