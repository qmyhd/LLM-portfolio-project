"""
Resilient async-friendly SQLAlchemy engine for PostgreSQL/Supabase connection.
Handles connection pooling, health checks, prepared statement optimization, and automatic fallback.
"""
import asyncio
import logging
import time
from functools import wraps

from sqlalchemy import create_engine, event, text
from sqlalchemy.exc import DisconnectionError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from src.config import get_database_url, settings

logger = logging.getLogger(__name__)

# Global engine instances
_sync_engine = None
_async_engine = None


def get_sync_engine():
    """
    Get or create the synchronous SQLAlchemy engine with connection pooling and resilience features.
    Automatically detects Supabase pooler and disables prepared statements for port 6543.
    """
    global _sync_engine
    
    if _sync_engine is None:
        try:
            database_url = get_database_url()
            logger.info("Creating synchronous SQLAlchemy engine for database connection")
            
            # Detect database type and configure accordingly
            is_sqlite = database_url.startswith("sqlite")
            is_pooler = ":6543" in database_url
            
            if is_sqlite:
                # SQLite configuration
                _sync_engine = create_engine(
                    database_url,
                    echo=getattr(settings(), 'DEBUG', False),
                    future=True,
                    connect_args={
                        "check_same_thread": False,  # Allow SQLite in threads
                        "timeout": 20
                    }
                )
            else:
                # PostgreSQL/Supabase configuration
                connect_args = {
                    "connect_timeout": 10,
                    "options": "-c timezone=utc"
                }
                
                # Auto-disable prepared statements for Supabase pooler (port 6543)
                if is_pooler:
                    connect_args["prepared_statement_cache_size"] = 0
                    logger.info("🔧 Detected Supabase pooler (port 6543) - disabled prepared statements")
                
                _sync_engine = create_engine(
                    database_url,
                    pool_size=5,                    # Number of connections to maintain in pool
                    max_overflow=2,                 # Additional connections beyond pool_size
                    pool_pre_ping=True,             # Validate connections before use (recommended)
                    pool_recycle=3600,              # Recycle connections after 1 hour
                    pool_timeout=30,                # Timeout for getting connection from pool
                    echo=getattr(settings(), 'DEBUG', False),
                    future=True,                    # Use SQLAlchemy 2.0 style
                    connect_args=connect_args
                )
            
            # Add connection event listeners for better error handling
            @event.listens_for(_sync_engine, "connect")
            def set_connection_options(dbapi_connection, connection_record):
                """Configure connection-specific options."""
                if not is_sqlite:
                    # PostgreSQL-specific optimizations
                    with dbapi_connection.cursor() as cursor:
                        cursor.execute("SET statement_timeout = '30s'")
                        cursor.execute("SET lock_timeout = '10s'")
                        if is_pooler:
                            cursor.execute("SET application_name = 'trading-bot-pooler'")
                        else:
                            cursor.execute("SET application_name = 'trading-bot-direct'")
            
            @event.listens_for(_sync_engine, "engine_connect")
            def receive_engine_connect(conn):
                logger.debug("New database connection established")
            
            logger.info("✅ Synchronous SQLAlchemy engine created successfully")
            
        except Exception as e:
            logger.error(f"Failed to create synchronous SQLAlchemy engine: {e}")
            raise
    
    return _sync_engine


async def get_async_engine() -> AsyncEngine:
    """
    Get or create the async SQLAlchemy engine for async operations.
    """
    global _async_engine
    
    if _async_engine is None:
        try:
            database_url = get_database_url()
            
            # Convert sync URL to async URL
            if database_url.startswith("sqlite"):
                async_url = database_url.replace("sqlite://", "sqlite+aiosqlite://")
            else:
                async_url = database_url.replace("postgresql://", "postgresql+asyncpg://")
            
            logger.info("Creating async SQLAlchemy engine for database connection")
            
            is_sqlite = async_url.startswith("sqlite")
            is_pooler = ":6543" in async_url
            
            if is_sqlite:
                # Async SQLite configuration
                _async_engine = create_async_engine(
                    async_url,
                    echo=getattr(settings(), 'DEBUG', False),
                    future=True
                )
            else:
                # Async PostgreSQL configuration
                connect_args = {}
                if is_pooler:
                    connect_args["prepared_statement_cache_size"] = 0
                    logger.info("🔧 Async engine: Detected Supabase pooler - disabled prepared statements")
                
                _async_engine = create_async_engine(
                    async_url,
                    pool_size=5,
                    max_overflow=2,
                    pool_pre_ping=True,
                    pool_recycle=3600,
                    echo=getattr(settings(), 'DEBUG', False),
                    future=True,
                    connect_args=connect_args
                )
            
            logger.info("✅ Async SQLAlchemy engine created successfully")
            
        except Exception as e:
            logger.error(f"Failed to create async SQLAlchemy engine: {e}")
            raise
    
    return _async_engine

def healthcheck():
    """
    Perform a health check on the database connection.
    Raises exception if connection fails.
    """
    try:
        engine = get_sync_engine()
        with engine.connect() as conn:
            result = conn.execute(text("SELECT 1 as health_check"))
            row = result.fetchone()
            if row and row[0] == 1:
                logger.debug("✅ Database health check passed")
                return True
            else:
                raise Exception("Health check query returned unexpected result")
    except Exception as e:
        logger.error(f"❌ Database health check failed: {e}")
        raise


async def async_healthcheck():
    """
    Perform an async health check on the database connection.
    """
    try:
        engine = await get_async_engine()
        async with engine.begin() as conn:
            result = await conn.execute(text("SELECT 1 as health_check"))
            row = result.fetchone()
            if row and row[0] == 1:
                logger.debug("✅ Async database health check passed")
                return True
            else:
                raise Exception("Health check query returned unexpected result")
    except Exception as e:
        logger.error(f"❌ Async database health check failed: {e}")
        raise


def get_connection():
    """
    Get a database connection from the sync engine.
    Returns a connection object that should be used in a context manager.
    """
    engine = get_sync_engine()
    return engine.connect()


# Legacy compatibility function
def get_engine():
    """Legacy compatibility function - use get_sync_engine() instead."""
    return get_sync_engine()

def retry_on_connection_error(max_retries=3, delay=1):
    """
    Decorator to retry database operations on connection errors.
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except (DisconnectionError, SQLAlchemyError) as e:
                    last_exception = e
                    if attempt < max_retries - 1:
                        logger.warning(f"Database operation failed (attempt {attempt + 1}/{max_retries}): {e}")
                        time.sleep(delay * (2 ** attempt))  # Exponential backoff
                        # Reset the global engines to force reconnection
                        global _sync_engine, _async_engine
                        if _sync_engine:
                            try:
                                _sync_engine.dispose()
                            except Exception:
                                pass
                            _sync_engine = None
                        if _async_engine:
                            try:
                                # Note: async engine disposal needs to be handled in async context
                                _async_engine = None  # Mark for recreation
                            except Exception:
                                pass
                    else:
                        logger.error(f"Database operation failed after {max_retries} attempts: {e}")
                        raise last_exception
            
            return None
        return wrapper
    return decorator


@retry_on_connection_error(max_retries=3, delay=1)
def execute_query(query, params=None):
    """
    Execute a query with automatic retry on connection errors.
    
    Args:
        query: SQL query string or SQLAlchemy text() object
        params: Query parameters (optional)
    
    Returns:
        Query result
    """
    with get_connection() as conn:
        if isinstance(query, str):
            query = text(query)
        
        if params:
            result = conn.execute(query, params)
        else:
            result = conn.execute(query)
        
        return result


def get_database_size():
    """
    Get the current database size for monitoring.
    Returns size in human-readable format.
    """
    try:
        database_url = get_database_url()
        if database_url.startswith("sqlite"):
            # SQLite - get file size
            from pathlib import Path
            if "///" in database_url:
                db_path = Path(database_url.split("///")[1])
                if db_path.exists():
                    size_bytes = db_path.stat().st_size
                    # Convert to human readable
                    for unit in ['B', 'KB', 'MB', 'GB']:
                        if size_bytes < 1024.0:
                            return f"{size_bytes:.1f} {unit}"
                        size_bytes /= 1024.0
                    return f"{size_bytes:.1f} TB"
                return "0 B"
            return "Unknown"
        else:
            # PostgreSQL
            with get_connection() as conn:
                result = conn.execute(text("SELECT pg_size_pretty(pg_database_size(current_database()))"))
                row = result.fetchone()
                return row[0] if row else "Unknown"
    except Exception as e:
        logger.error(f"Failed to get database size: {e}")
        return f"Error: {e}"


def get_table_sizes():
    """
    Get sizes of all tables for monitoring.
    Returns dict of table_name -> size.
    """
    try:
        database_url = get_database_url()
        if database_url.startswith("sqlite"):
            # SQLite - get table row counts
            with get_connection() as conn:
                tables_result = conn.execute(text("""
                    SELECT name FROM sqlite_master 
                    WHERE type='table' AND name NOT LIKE 'sqlite_%'
                """))
                tables = {}
                for row in tables_result.fetchall():
                    table_name = row[0]
                    count_result = conn.execute(text(f"SELECT COUNT(*) FROM `{table_name}`"))
                    count_row = count_result.fetchone()
                    count = count_row[0] if count_row else 0
                    tables[table_name] = f"{count} rows"
                return tables
        else:
            # PostgreSQL
            query = text("""
                SELECT 
                    tablename,
                    pg_size_pretty(pg_total_relation_size(tablename::regclass)) as size,
                    pg_total_relation_size(tablename::regclass) as size_bytes
                FROM pg_tables 
                WHERE schemaname = 'public'
                ORDER BY size_bytes DESC
            """)
            
            with get_connection() as conn:
                result = conn.execute(query)
                return {row[0]: row[1] for row in result.fetchall()}
    except Exception as e:
        logger.error(f"Failed to get table sizes: {e}")
        return {}


def test_connection():
    """
    Test the database connection and return detailed connection info.
    """
    try:
        # Test basic connection
        healthcheck()
        
        database_url = get_database_url()
        is_sqlite = database_url.startswith("sqlite")
        
        # Get connection info
        with get_connection() as conn:
            if is_sqlite:
                # SQLite info
                version_result = conn.execute(text("SELECT sqlite_version()"))
                version_row = version_result.fetchone()
                version = f"SQLite {version_row[0]}" if version_row else "SQLite (unknown)"
                
                db_path = database_url.split("///")[1] if "///" in database_url else "memory"
                
                return {
                    "status": "connected",
                    "version": version,
                    "database": db_path,
                    "user": "local",
                    "database_size": get_database_size(),
                    "type": "sqlite"
                }
            else:
                # PostgreSQL info
                version_result = conn.execute(text("SELECT version()"))
                version_row = version_result.fetchone()
                version = version_row[0].split()[0:2] if version_row else ["PostgreSQL", "(unknown)"]
                
                db_result = conn.execute(text("SELECT current_database()"))
                db_row = db_result.fetchone()
                database = db_row[0] if db_row else "unknown"
                
                user_result = conn.execute(text("SELECT current_user"))
                user_row = user_result.fetchone()
                user = user_row[0] if user_row else "unknown"
                
                return {
                    "status": "connected",
                    "version": version,
                    "database": database,
                    "user": user,
                    "database_size": get_database_size(),
                    "type": "postgresql"
                }
    except Exception as e:
        return {
            "status": "failed",
            "error": str(e)
        }


def close_engines():
    """
    Close both sync and async database engines and all connections.
    Should be called on application shutdown.
    """
    global _sync_engine, _async_engine
    
    # Close sync engine
    if _sync_engine:
        try:
            _sync_engine.dispose()
            logger.info("Sync database engine closed successfully")
        except Exception as e:
            logger.error(f"Error closing sync database engine: {e}")
        finally:
            _sync_engine = None
    
    # Close async engine
    if _async_engine:
        try:
            asyncio.create_task(_async_engine.dispose())
            logger.info("Async database engine closed successfully")
        except Exception as e:
            logger.error(f"Error closing async database engine: {e}")
        finally:
            _async_engine = None


# Legacy compatibility function
def close_engine():
    """Legacy compatibility function - use close_engines() instead."""
    close_engines()

if __name__ == "__main__":
    # Test database connection
    print("Testing database connection...")
    
    try:
        # Test configuration
        database_url = get_database_url()
        print(f"Database URL configured: {database_url[:50]}...")
        
        # Test connection
        connection_info = test_connection()
        print(f"Connection test result: {connection_info}")
        
        if connection_info["status"] == "connected":
            print("✅ Database connection successful!")
            print(f"Type: {connection_info.get('type', 'unknown')}")
            print(f"Database: {connection_info['database']}")
            print(f"User: {connection_info['user']}")
            print(f"Size: {connection_info['database_size']}")
            
            # Test table sizes
            table_sizes = get_table_sizes()
            if table_sizes:
                print(f"Tables found: {len(table_sizes)}")
                for table, size in list(table_sizes.items())[:5]:  # Show first 5 tables
                    print(f"  - {table}: {size}")
        else:
            print(f"❌ Database connection failed: {connection_info['error']}")
            
    except Exception as e:
        print(f"❌ Connection test error: {e}")
    finally:
        close_engines()
