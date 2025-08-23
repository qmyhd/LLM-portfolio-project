"""
Database migration script for X/Twitter posts pipeline.
Creates the new schema and tables for storing X/Twitter data.
"""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def create_twitter_schema_postgres_sql():
    """Create PostgreSQL Twitter schema using execute_sql."""
    from src.database import execute_sql

    schema_sql = """
    -- Create schema if it doesn't exist
    CREATE SCHEMA IF NOT EXISTS twitter_data;
    
    -- Create x_posts_log table
    CREATE TABLE IF NOT EXISTS twitter_data.x_posts_log (
        tweet_id BIGINT PRIMARY KEY,
        content TEXT NOT NULL,
        author_username VARCHAR(50) NOT NULL,
        author_display_name VARCHAR(100) NOT NULL,
        created_at TIMESTAMPTZ NOT NULL,
        scraped_at TIMESTAMPTZ DEFAULT NOW(),
        tickers TEXT[] DEFAULT ARRAY[]::TEXT[],
        sentiment_score DECIMAL(3,2),
        sentiment_label VARCHAR(20),
        retweet_count INTEGER DEFAULT 0,
        like_count INTEGER DEFAULT 0,
        reply_count INTEGER DEFAULT 0,
        quote_count INTEGER DEFAULT 0,
        bookmark_count INTEGER DEFAULT 0,
        url TEXT NOT NULL,
        raw_data JSONB
    );
    
    -- Create indexes
    CREATE INDEX IF NOT EXISTS idx_x_posts_log_created_at ON twitter_data.x_posts_log (created_at);
    CREATE INDEX IF NOT EXISTS idx_x_posts_log_author ON twitter_data.x_posts_log (author_username);
    CREATE INDEX IF NOT EXISTS idx_x_posts_log_tickers ON twitter_data.x_posts_log USING GIN (tickers);
    CREATE INDEX IF NOT EXISTS idx_x_posts_log_sentiment ON twitter_data.x_posts_log (sentiment_label);
    """

    try:
        execute_sql(schema_sql)
        return True
    except Exception as e:
        print(f"PostgreSQL schema creation error: {e}")
        return False


def create_twitter_schema_postgres(connection):
    """Create PostgreSQL schema and tables for X/Twitter data."""
    try:
        with (
            connection.cursor() if hasattr(connection, "cursor") else connection.begin()
        ) as cursor:
            if hasattr(connection, "cursor"):
                # Direct database connection
                conn_cursor = cursor
            else:
                # SQLAlchemy connection
                conn_cursor = cursor.connection.cursor()

            # Create schema
            conn_cursor.execute("CREATE SCHEMA IF NOT EXISTS twitter_data;")

            # Create x_posts_log table
            conn_cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS twitter_data.x_posts_log (
                    tweet_id TEXT PRIMARY KEY,
                    tweet_time TIMESTAMPTZ NOT NULL,
                    discord_message_time TIMESTAMPTZ,
                    tweet_text TEXT NOT NULL,
                    tickers TEXT[] NOT NULL DEFAULT '{}',
                    author_id TEXT,
                    conversation_id TEXT,
                    inserted_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
            """
            )

            # Create indexes
            conn_cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS x_posts_log_time_idx 
                ON twitter_data.x_posts_log (tweet_time DESC);
            """
            )

            conn_cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS x_posts_log_tickers_gin 
                ON twitter_data.x_posts_log USING GIN (tickers);
            """
            )

            if hasattr(connection, "commit"):
                connection.commit()

            logger.info("PostgreSQL Twitter schema and tables created successfully")
            return True

    except Exception as e:
        logger.error(f"Error creating PostgreSQL Twitter schema: {e}")
        return False


def create_twitter_schema_sqlite(connection):
    """Create SQLite tables for X/Twitter data."""
    try:
        cursor = connection.cursor()

        # Create twitter_x_posts_log table
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS twitter_x_posts_log (
                tweet_id TEXT PRIMARY KEY,
                tweet_time TEXT NOT NULL,
                discord_message_time TEXT,
                tweet_text TEXT NOT NULL,
                tickers TEXT NOT NULL DEFAULT '[]',
                author_id TEXT,
                conversation_id TEXT,
                inserted_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
        """
        )

        # Create index
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS twitter_x_posts_log_time_idx 
            ON twitter_x_posts_log (tweet_time DESC);
        """
        )

        connection.commit()
        logger.info("SQLite Twitter tables created successfully")
        return True

    except Exception as e:
        logger.error(f"Error creating SQLite Twitter tables: {e}")
        return False


def initialize_twitter_schema():
    """Initialize Twitter schema for both PostgreSQL and SQLite."""
    import sys
    from pathlib import Path

    # Add parent directory to path for imports
    script_dir = Path(__file__).parent
    project_root = script_dir.parent
    sys.path.insert(0, str(project_root))

    try:
        from src.database import use_postgres, get_connection, execute_sql
    except ImportError as e:
        print(f"❌ Import error: {e}")
        print("Make sure you're running this from the project root directory")
        return False

    success = True

    # Try PostgreSQL first
    if use_postgres():
        try:
            print("Initializing PostgreSQL Twitter schema...")
            if not create_twitter_schema_postgres_sql():
                success = False
                print("❌ PostgreSQL Twitter schema creation failed")
            else:
                print("✅ PostgreSQL Twitter schema created successfully")
        except Exception as e:
            print(f"⚠️  PostgreSQL not available, falling back to SQLite: {e}")

    # Always ensure SQLite fallback exists
    try:
        print("Initializing SQLite Twitter schema...")
        with get_connection() as conn:
            if not create_twitter_schema_sqlite(conn):
                success = False
                logger.error("SQLite Twitter schema creation failed")
            else:
                print("✅ SQLite Twitter schema created successfully")
    except Exception as e:
        print(f"❌ SQLite Twitter schema creation failed: {e}")
        success = False

    return success


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    if initialize_twitter_schema():
        print("✅ Twitter schema initialized successfully")
    else:
        print("❌ Twitter schema initialization failed")
