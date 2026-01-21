"""
Resilient async-friendly SQLAlchemy engine for PostgreSQL/Supabase connection.
Handles connection pooling, health checks, prepared statement optimization.
"""

import asyncio
import logging
import time
from functools import wraps
from pathlib import Path

from sqlalchemy import create_engine, event, text
from sqlalchemy.exc import DisconnectionError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.engine import CursorResult, Row
from typing import Any, Dict, List, Optional, Union, overload, Literal

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
            logger.info(
                "Creating synchronous SQLAlchemy engine for PostgreSQL database connection"
            )

            # Detect if using Supabase pooler
            is_pooler = ":6543" in database_url

            # PostgreSQL/Supabase configuration
            connect_args = {"connect_timeout": 10, "options": "-c timezone=utc"}

            # Force psycopg2 dialect (instead of psycopg3) for compatibility
            database_url_with_dialect = database_url.replace(
                "postgresql://", "postgresql+psycopg2://"
            )

            if is_pooler:
                logger.info(
                    "🔧 Detected Supabase pooler (port 6543) - using psycopg2 dialect"
                )

            _sync_engine = create_engine(
                database_url_with_dialect,
                pool_size=5,  # Number of connections to maintain in pool
                max_overflow=2,  # Additional connections beyond pool_size
                pool_pre_ping=True,  # Validate connections before use (recommended)
                pool_recycle=3600,  # Recycle connections after 1 hour
                pool_timeout=30,  # Timeout for getting connection from pool
                echo=getattr(settings(), "DEBUG", False),
                future=True,  # Use SQLAlchemy 2.0 style
                connect_args=connect_args,
            )

            # Add connection event listeners for better error handling
            @event.listens_for(_sync_engine, "connect")
            def set_connection_options(dbapi_connection, _connection_record):
                """Configure connection-specific options."""
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
                # Connection established (reduced logging to prevent spam)
                pass

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

            # Convert PostgreSQL sync URL to async URL with asyncpg driver
            async_url = database_url.replace("postgresql://", "postgresql+asyncpg://")

            logger.info(
                "Creating async SQLAlchemy engine for PostgreSQL database connection"
            )

            is_pooler = ":6543" in async_url

            # Async PostgreSQL configuration
            connect_args = {}

            if is_pooler:
                logger.info(
                    "🔧 Async engine: Detected Supabase pooler - using asyncpg dialect"
                )

            _async_engine = create_async_engine(
                async_url,
                pool_size=5,
                max_overflow=2,
                pool_pre_ping=True,
                pool_recycle=3600,
                echo=getattr(settings(), "DEBUG", False),
                future=True,
                connect_args=connect_args,
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


class transaction:
    """
    Context manager for executing multiple SQL statements in a single transaction.

    Use this when you need advisory locks to protect concurrent operations,
    or when multiple statements must be atomic (all succeed or all fail).

    Example:
        with transaction() as conn:
            conn.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": 123})
            conn.execute(text("DELETE FROM table WHERE id = :id"), {"id": 456})
            conn.execute(text("INSERT INTO table ..."), {...})
        # Lock released and transaction committed on exit

    The connection auto-commits on successful exit and rolls back on exception.
    Advisory locks (pg_advisory_xact_lock) are released when the transaction ends.
    """

    def __init__(self):
        self._conn = None
        self._engine = None

    def __enter__(self):
        self._engine = get_sync_engine()
        self._conn = self._engine.begin()
        return self._conn.__enter__()

    def __exit__(self, exc_type, exc_val, exc_tb):
        return self._conn.__exit__(exc_type, exc_val, exc_tb)


def save_parsed_ideas_atomic(
    message_id: str,
    ideas: list,
    status: str,
    prompt_version: str,
    error_reason: str = None,
) -> int:
    """
    CANONICAL atomic helper for saving parsed ideas with reparse safety.

    ALL code paths that write to discord_parsed_ideas MUST use this function
    to prevent the "separate transactions" bug.

    This function:
    1. Acquires advisory lock on message_id (prevents concurrent workers)
    2. Deletes ALL existing ideas for this message_id
    3. Inserts fresh ideas
    4. Updates parse_status on discord_messages
    5. Commits all operations in a SINGLE transaction

    Args:
        message_id: The message ID being processed
        ideas: List of idea dicts (each has message_id, idea_index, idea_text, etc.)
        status: Parse status (ok, error, noise, skipped)
        prompt_version: Version string for tracking schema changes
        error_reason: Error message if status='error'

    Returns:
        Number of ideas inserted

    Raises:
        Exception: If any database operation fails (entire transaction rolled back)
    """
    import json

    if not message_id:
        return 0

    # Convert message_id to a numeric lock key
    try:
        lock_key = int(message_id)
    except ValueError:
        lock_key = hash(message_id) & 0x7FFFFFFFFFFFFFFF

    inserted = 0

    with transaction() as conn:
        # Step 0: Acquire advisory lock (held until transaction ends)
        conn.execute(
            text("SELECT pg_advisory_xact_lock(:lock_key)"), {"lock_key": lock_key}
        )

        # Step 1: Delete existing ideas for this message
        conn.execute(
            text(
                "DELETE FROM discord_parsed_ideas WHERE message_id = CAST(:message_id AS text)"
            ),
            {"message_id": str(message_id)},
        )

        # Step 2: Insert fresh ideas (if any)
        for idea in ideas:
            insert_query = text(
                """
                INSERT INTO discord_parsed_ideas (
                    message_id, idea_index, soft_chunk_index, local_idea_index,
                    idea_text, idea_summary, context_summary,
                    primary_symbol, symbols, instrument, direction,
                    action, time_horizon, trigger_condition,
                    levels, option_type, strike, expiry, premium,
                    labels, label_scores, is_noise,
                    author_id, channel_id, model, prompt_version, confidence,
                    raw_json, source_created_at
                ) VALUES (
                    :message_id, :idea_index, :soft_chunk_index, :local_idea_index,
                    :idea_text, :idea_summary, :context_summary,
                    :primary_symbol, :symbols, :instrument, :direction,
                    :action, :time_horizon, :trigger_condition,
                    :levels, :option_type, :strike, :expiry, :premium,
                    :labels, :label_scores, :is_noise,
                    :author_id, :channel_id, :model, :prompt_version, :confidence,
                    :raw_json, :source_created_at
                )
            """
            )

            params = {
                "message_id": str(idea.get("message_id", message_id)),
                "idea_index": idea.get("idea_index", 0),
                "soft_chunk_index": idea.get("soft_chunk_index", 0),
                "local_idea_index": idea.get(
                    "local_idea_index", idea.get("idea_index", 0)
                ),
                "idea_text": idea.get("idea_text", ""),
                "idea_summary": idea.get("idea_summary"),
                "context_summary": idea.get("context_summary"),
                "primary_symbol": idea.get("primary_symbol"),
                "symbols": idea.get("symbols", []),
                "instrument": idea.get("instrument"),
                "direction": idea.get("direction"),
                "action": idea.get("action"),
                "time_horizon": idea.get("time_horizon"),
                "trigger_condition": idea.get("trigger_condition"),
                "levels": json.dumps(idea.get("levels", [])),
                "option_type": idea.get("option_type"),
                "strike": idea.get("strike"),
                "expiry": idea.get("expiry"),
                "premium": idea.get("premium"),
                "labels": idea.get("labels", []),
                "label_scores": json.dumps(idea.get("label_scores", {})),
                "is_noise": idea.get("is_noise", False),
                "author_id": idea.get("author_id"),
                "channel_id": idea.get("channel_id"),
                "model": idea.get("model", "unknown"),
                "prompt_version": idea.get("prompt_version", prompt_version),
                "confidence": idea.get("confidence"),
                "raw_json": json.dumps(idea.get("raw_json", {})),
                "source_created_at": idea.get("source_created_at"),
            }

            conn.execute(insert_query, params)
            inserted += 1

        # Step 3: Update message status (inside same transaction)
        conn.execute(
            text(
                """
                UPDATE discord_messages
                SET parse_status = :status,
                    prompt_version = :prompt_version,
                    error_reason = :error_reason
                WHERE message_id = CAST(:message_id AS text)
            """
            ),
            {
                "message_id": str(message_id),
                "status": status,
                "prompt_version": prompt_version,
                "error_reason": error_reason,
            },
        )

    # Transaction committed, lock released
    return inserted


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
                        logger.warning(
                            f"Database operation failed (attempt {attempt + 1}/{max_retries}): {e}"
                        )
                        time.sleep(delay * (2**attempt))  # Exponential backoff
                        # Only dispose engines on connection-specific errors, don't nullify
                        global _sync_engine, _async_engine
                        if _sync_engine and "connection" in str(e).lower():
                            try:
                                _sync_engine.dispose()  # Dispose connections, but keep engine
                                logger.debug(
                                    "Disposed sync engine connections for retry"
                                )
                            except Exception:
                                pass
                    else:
                        logger.error(
                            f"Database operation failed after {max_retries} attempts: {e}"
                        )
                        raise last_exception

            return None

        return wrapper

    return decorator


def ensure_tz_aware(dt):
    """
    Ensure datetime is timezone-aware for timestamptz fields.

    Args:
        dt: datetime object to validate

    Returns:
        datetime: The input datetime (validated as timezone-aware)

    Raises:
        ValueError: If datetime is naive (no timezone info)
    """
    import datetime

    if isinstance(dt, datetime.datetime) and dt.tzinfo is None:
        raise ValueError(
            f"Naive datetime {dt} not allowed for timestamptz fields. "
            "Use datetime.datetime.now(timezone.utc) or pd.to_datetime(utc=True)."
        )
    return dt


@retry_on_connection_error(max_retries=3, delay=1)
def _execute_query(query, params=None):
    """
    INTERNAL: Execute a query with automatic retry on connection errors.
    External callers should use execute_sql() instead.

    Args:
        query: SQL query string or SQLAlchemy text() object
        params: Query parameters (optional)

    Returns:
        Query result
    """
    engine = get_sync_engine()

    # Check if this is a statement that needs transaction commit (DDL + DML writes)
    query_str = str(query).upper().strip()
    is_ddl = any(query_str.startswith(ddl) for ddl in ["CREATE", "DROP", "ALTER"])
    is_dml_write = any(
        query_str.startswith(dml) for dml in ["INSERT", "UPDATE", "DELETE", "MERGE"]
    )

    if is_ddl or is_dml_write:
        # Use begin() for DDL statements and DML writes to ensure they are committed
        with engine.begin() as conn:
            if isinstance(query, str):
                query = text(query)

            if params:
                result = conn.execute(query, params)
            else:
                result = conn.execute(query)

            return result
    else:
        # Use regular connection for SELECT queries (read-only)
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
    Get the current PostgreSQL database size for monitoring.
    Returns size in human-readable format.
    """
    try:
        # PostgreSQL database size query
        with get_connection() as conn:
            result = conn.execute(
                text("SELECT pg_size_pretty(pg_database_size(current_database()))")
            )
            row = result.fetchone()
            return row[0] if row else "Unknown"
    except Exception as e:
        logger.error(f"Failed to get database size: {e}")
        return f"Error: {e}"


def get_table_sizes():
    """
    Get sizes of all PostgreSQL tables for monitoring.
    Returns dict of table_name -> size.
    """
    try:
        # PostgreSQL table sizes query
        query = text(
            """
            SELECT 
                tablename,
                pg_size_pretty(pg_total_relation_size(tablename::regclass)) as size,
                pg_total_relation_size(tablename::regclass) as size_bytes
            FROM pg_tables 
            WHERE schemaname = 'public'
            ORDER BY size_bytes DESC
        """
        )

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

        # Get PostgreSQL connection info
        with get_connection() as conn:
            # PostgreSQL info
            version_result = conn.execute(text("SELECT version()"))
            version_row = version_result.fetchone()
            version = (
                version_row[0].split()[0:2]
                if version_row
                else ["PostgreSQL", "(unknown)"]
            )

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
                "type": "postgresql",
            }
    except Exception as e:
        return {"status": "failed", "error": str(e)}


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


# ============================================================================
# LEGACY DATABASE.PY FUNCTIONS - CONSOLIDATED FOR BACKWARD COMPATIBILITY
# ============================================================================

# Constants for project structure
BASE_DIR = Path(__file__).resolve().parents[1]


def validate_timezone_aware(params):
    """
    Validate that datetime parameters are timezone-aware for timestamptz fields.

    Args:
        params: Dict or list of dicts containing parameters

    Raises:
        ValueError: If naive datetime found in parameters
    """
    import datetime

    def check_datetime_param(key, value):
        if isinstance(value, datetime.datetime) and value.tzinfo is None:
            raise ValueError(
                f"Parameter '{key}' contains naive datetime {value}. "
                "PostgreSQL timestamptz fields require timezone-aware datetimes. "
                "Use datetime.datetime.now(timezone.utc) or pd.to_datetime(utc=True)."
            )

    if isinstance(params, dict):
        for key, value in params.items():
            check_datetime_param(key, value)
    elif isinstance(params, list):
        for i, param_dict in enumerate(params):
            if isinstance(param_dict, dict):
                for key, value in param_dict.items():
                    check_datetime_param(f"[{i}].{key}", value)


@overload
def execute_sql(
    query: str,
    params: Optional[Union[Dict[str, Any], List[Dict[str, Any]]]] = None,
    fetch_results: Literal[True] = ...,
) -> List[Row[Any]]: ...


@overload
def execute_sql(
    query: str,
    params: Optional[Union[Dict[str, Any], List[Dict[str, Any]]]] = None,
    fetch_results: Literal[False] = ...,
) -> CursorResult[Any]: ...


@overload
def execute_sql(
    query: str,
    params: Optional[Union[Dict[str, Any], List[Dict[str, Any]]]] = None,
    fetch_results: bool = False,
) -> Union[List[Row[Any]], CursorResult[Any]]: ...


def execute_sql(
    query: str,
    params: Optional[Union[Dict[str, Any], List[Dict[str, Any]]]] = None,
    fetch_results: bool = False,
) -> Union[List[Row[Any]], CursorResult[Any]]:
    """
    Execute SQL query using PostgreSQL with enhanced type safety and timezone validation.

    Args:
        query: SQL query with named placeholders (:param_name)
        params: Dict or list of dicts for parameters. No tuples allowed.
        fetch_results: Whether to return query results

    Returns:
        Query results if fetch_results=True, otherwise execution result

    Raises:
        TypeError: If params aren't dict or list of dicts
        ValueError: If naive datetime found for timestamptz fields
        SQLAlchemyError: For database errors (after logging)
    """
    # Validate parameter types for SQLAlchemy 2.0 compatibility
    if params is not None:
        if not isinstance(params, (dict, list)):
            raise TypeError(
                f"params must be dict or list of dicts, got {type(params).__name__}. "
                "Use df.to_dict('records') for DataFrames."
            )
        if isinstance(params, list):
            if not all(isinstance(p, dict) for p in params):
                raise TypeError("All items in params list must be dictionaries")

        # Validate timezone-aware datetimes for timestamptz fields
        validate_timezone_aware(params)

    try:
        if isinstance(params, list):
            # Bulk operation using executemany
            engine = get_sync_engine()
            with engine.begin() as conn:
                result = conn.execute(text(query), params)
                if fetch_results:
                    return result.fetchall()
                return result
        else:
            # Single operation
            result = _execute_query(text(query), params)
            if fetch_results:
                return result.fetchall()
            return result
    except Exception as e:
        logger.error(f"Supabase query failed: {e}")
        raise  # Always re-raise for proper error surfacing


def df_to_records(df, utc_columns=None):
    """
    Convert DataFrame to list of dicts with proper UTC timestamp handling.

    Args:
        df: pandas DataFrame
        utc_columns: List of column names to convert to UTC timezone-aware timestamps

    Returns:
        List of dictionaries ready for bulk database operations
    """
    import pandas as pd

    if df.empty:
        return []

    # Convert timestamp columns to UTC timezone-aware
    df_processed = df.copy()
    if utc_columns:
        for col in utc_columns:
            if col in df_processed.columns:
                df_processed[col] = pd.to_datetime(df_processed[col], utc=True)

    # Convert to list of dicts for SQLAlchemy
    return df_processed.to_dict("records")


def check_database_tables():
    """Check if all required tables exist in the database.

    Returns:
        bool: True if all tables exist, False otherwise

    Note:
        Current schema has 19 tables as of migration 049 (Jan 2026).
        Legacy tables dropped: discord_processing_log, chart_metadata,
        discord_message_chunks, discord_idea_units, stock_mentions.
    """
    required_tables = {
        # SnapTrade/Brokerage (6 tables)
        "accounts",
        "account_balances",
        "positions",
        "orders",
        "symbols",
        "trade_history",
        # Market Data (3 tables)
        "realtime_prices",
        "daily_prices",
        "stock_metrics",
        # Discord/Social (4 tables)
        "discord_messages",
        "discord_market_clean",
        "discord_trading_clean",
        "discord_parsed_ideas",
        # Twitter (1 table)
        "twitter_data",
        # Event Contracts (2 tables)
        "event_contract_positions",
        "event_contract_trades",
        # Institutional (1 table)
        "institutional_holdings",
        # System (2 tables)
        "processing_status",
        "schema_migrations",
    }

    try:
        # Query existing tables
        result = execute_sql(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public'",
            fetch_results=True,
        )
        existing_tables = {row[0] for row in result} if result else set()

        missing_tables = required_tables - existing_tables
        if missing_tables:
            logger.info(f"Missing tables: {missing_tables}")
            return False

        logger.info(f"✅ All {len(required_tables)} required tables exist")
        return True

    except Exception as e:
        logger.error(f"Error checking database tables: {e}")
        return False


def initialize_database_smart():
    """Smart database initialization that only creates schema if tables don't exist."""
    try:
        # Check if tables already exist
        if check_database_tables():
            logger.info("📋 Database already initialized - skipping schema creation")
            return True

        logger.info("🔧 Tables missing - proceeding with schema initialization")
        return initialize_database()

    except Exception as e:
        logger.error(f"Error in smart database initialization: {e}")
        return False


def initialize_database():
    """Initialize the database with all required tables by executing the 000_baseline.sql schema and migrations."""
    # Use direct psycopg2 with explicit commits for PostgreSQL
    try:
        import psycopg2
        from psycopg2.extras import DictCursor

        database_url = get_database_url()

        # Load baseline schema first
        baseline_file = BASE_DIR / "schema" / "000_baseline.sql"
        if not baseline_file.exists():
            raise FileNotFoundError(f"Baseline schema file not found: {baseline_file}")

        # Find all migration files (NNN_*.sql) excluding archive
        schema_dir = BASE_DIR / "schema"
        migration_files = []
        for sql_file in schema_dir.glob("*.sql"):
            if (
                sql_file.name != "000_baseline.sql"
                and not sql_file.parent.name == "archive"
            ):
                # Extract number from filename (e.g., 014_security_fixes.sql -> 014)
                try:
                    file_num = int(sql_file.name[:3])
                    migration_files.append((file_num, sql_file))
                except ValueError:
                    logger.warning(
                        f"Skipping non-numbered schema file: {sql_file.name}"
                    )

        # Sort migrations by number
        migration_files.sort(key=lambda x: x[0])

        # Connect and execute all schema files
        conn = psycopg2.connect(database_url, cursor_factory=DictCursor)
        cur = conn.cursor()
        try:
            # Execute baseline schema first
            with open(baseline_file, "r", encoding="utf-8") as f:
                baseline_sql = f.read()
            logger.info(f"Executing baseline schema: {baseline_file.name}")
            cur.execute(baseline_sql)

            # Execute migrations in order
            for file_num, migration_file in migration_files:
                with open(migration_file, "r", encoding="utf-8") as f:
                    migration_sql = f.read()
                logger.info(f"Executing migration: {migration_file.name}")
                cur.execute(migration_sql)

            conn.commit()  # Explicit commit for DDL statements
            logger.info(
                f"Database initialized successfully with baseline + {len(migration_files)} migrations"
            )
            return True
        except Exception:
            conn.rollback()
            raise
        finally:
            cur.close()
            conn.close()

    except ImportError:
        logger.error(
            "psycopg2 not installed. Install with: pip install psycopg2-binary"
        )
        raise
    except Exception as e:
        logger.error(f"Failed to initialize PostgreSQL database: {e}")
        raise


def mark_message_processed(message_id: str, channel: str, processing_type: str):
    """Mark a message as processed for a specific type.

    This function is critical for the resumable processing pipeline:
    - Sets boolean flags (processed_for_cleaning or processed_for_twitter) in processing_status table
    - Raw messages in discord_messages are NEVER deleted, only marked as processed
    - Uses composite primary key (message_id, channel) for multi-channel support
    - ON CONFLICT safe: Can be called multiple times safely (idempotent)

    Processing Types:
    - "cleaning": Message has been cleaned and stored in discord_*_clean tables
    - "twitter": Message has been analyzed for Twitter links and data extracted

    Deduplication Guarantee:
    - Once marked, get_unprocessed_messages() will skip this message
    - Ensures each message is processed exactly once per processing type
    - Makes the pipeline resumable after interruptions

    Uses composite primary key (message_id, channel) to track processing
    status separately for each message-channel combination.

    Args:
        message_id: Discord message ID (globally unique)
        channel: Discord channel name
        processing_type: Either "cleaning" or "twitter"
    """
    try:
        if processing_type == "cleaning":
            column = "processed_for_cleaning"
        elif processing_type == "twitter":
            column = "processed_for_twitter"
        else:
            raise ValueError(f"Invalid processing type: {processing_type}")

        # PostgreSQL-only query with ON CONFLICT using composite key (message_id, channel)
        # This ensures idempotent operation - can be called multiple times safely
        query = f"""
        INSERT INTO processing_status (message_id, channel, {column}, updated_at)
        VALUES (:message_id, :channel, TRUE, CURRENT_TIMESTAMP)
        ON CONFLICT (message_id, channel) DO UPDATE SET
        {column} = TRUE,
        updated_at = CURRENT_TIMESTAMP
        """
        params = {"message_id": str(message_id), "channel": str(channel)}

        execute_sql(query, params)

    except Exception as e:
        logger.error(f"Error marking message as processed: {e}")
        raise


def get_unprocessed_messages(
    channel: str | None = None, processing_type: str = "cleaning"
):
    """Get messages that haven't been processed yet.

    This function is the core of the resumable processing pipeline:
    - Queries discord_messages LEFT JOIN processing_status
    - Returns only messages where the processing flag is NULL or FALSE
    - Ensures each message is processed exactly once per processing type

    How It Works:
    1. LEFT JOIN ensures we see all discord_messages
    2. Filter WHERE flag IS NULL (never processed) OR flag IS FALSE (failed)
    3. Messages with flag = TRUE are automatically excluded (already processed)

    This enables:
    - Resumable operations: After interruption, only unprocessed messages are returned
    - Safe re-runs: Already-processed messages are skipped automatically
    - No deletion needed: Raw messages remain in discord_messages forever

    Deduplication Guarantee:
    - Primary: message_id (globally unique Discord ID)
    - Secondary: Composite key (message_id, channel) in processing_status
    - Result: Each message processed exactly once per channel per type

    Checks processing_status table using composite key (message_id, channel)
    to determine which messages need processing for a specific channel.

    Args:
        channel: Discord channel name to filter by (optional - None returns all)
        processing_type: Either "cleaning" or "twitter"

    Returns:
        List of tuples: (message_id, author, content, channel, timestamp)
        Empty list if no unprocessed messages or on error
    """
    try:
        if processing_type == "cleaning":
            column = "processed_for_cleaning"
        elif processing_type == "twitter":
            column = "processed_for_twitter"
        else:
            raise ValueError(f"Invalid processing type: {processing_type}")

        # PostgreSQL-only query with proper composite key join
        # LEFT JOIN ensures we see messages even if not in processing_status yet
        # Filter WHERE flag IS NULL (never seen) OR FALSE (marked for reprocessing)
        query = f"""
        SELECT dm.message_id, dm.author, dm.content, dm.channel, dm.timestamp
        FROM discord_messages dm
        LEFT JOIN processing_status ps 
            ON dm.message_id = ps.message_id AND dm.channel = ps.channel
        WHERE (ps.{column} IS NULL OR ps.{column} IS FALSE)
        """

        params = {}

        if channel:
            query += " AND dm.channel = :channel"
            params["channel"] = channel

        query += " ORDER BY dm.timestamp"

        return execute_sql(query, params if params else None, fetch_results=True)

    except Exception as e:
        logger.error(f"Error getting unprocessed messages: {e}")
        return []
