#!/usr/bin/env python3
"""
Bootstrap automation for the LLM Portfolio Journal application.
Handles initialization, health checks, one-time pgloader migration, and startup processes.
"""

import logging
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class BootstrapManager:
    """Manages application bootstrap and initialization"""

    def __init__(self):
        # Fix: Go up to project root (scripts/ -> project/)
        self.project_root = Path(__file__).parent.parent
        self.scripts_dir = self.project_root / "scripts"
        self.src_dir = self.project_root / "src"
        self.requirements_file = self.project_root / "requirements.txt"
        self.migration_flag = self.project_root / ".migration_completed"

        # Module imports (will be loaded after dependencies)
        self.config_module = None
        self.db_module = None

    def install_dependencies(self, force=False):
        """Install Python dependencies from requirements.txt"""
        logger.info("📦 Installing dependencies...")

        if not self.requirements_file.exists():
            logger.error(f"❌ Requirements file not found: {self.requirements_file}")
            return False

        try:
            # Check if virtual environment is active
            venv_active = os.environ.get("VIRTUAL_ENV") is not None
            if not venv_active:
                logger.warning(
                    "⚠️ No virtual environment detected. Consider using a virtual environment."
                )

            # Install requirements
            cmd = [
                sys.executable,
                "-m",
                "pip",
                "install",
                "-r",
                str(self.requirements_file),
            ]
            if force:
                cmd.extend(["--force-reinstall", "--no-cache-dir"])

            result = subprocess.run(
                cmd, capture_output=True, text=True, cwd=self.project_root
            )

            if result.returncode == 0:
                logger.info("✅ Dependencies installed successfully")
                return True
            else:
                logger.error(f"❌ Failed to install dependencies: {result.stderr}")
                return False

        except Exception as e:
            logger.error(f"❌ Error installing dependencies: {e}")
            return False

    def load_modules(self):
        """Load project modules after dependencies are installed"""
        logger.info("📚 Loading project modules...")

        try:
            # Import modules using absolute imports
            from src import config, db

            self.config_module = config
            self.db_module = db

            logger.info("✅ Modules loaded successfully")
            return True

        except ImportError as e:
            logger.error(f"❌ Failed to import modules: {e}")
            return False

    def load_environment(self):
        """Load and validate environment variables"""
        logger.info("🔧 Loading environment configuration...")

        try:
            # Load environment using centralized config
            from src.config import get_database_url, settings

            # Test configuration loading
            config = settings()
            database_url = get_database_url()

            logger.info("✅ Environment loaded successfully")
            logger.info(
                f"Database URL configured: {'Yes' if config.DATABASE_URL or database_url else 'No'}"
            )
            logger.info(
                f"Supabase configured: {'Yes' if config.SUPABASE_URL else 'No'}"
            )

            return True

        except Exception as e:
            logger.error(f"❌ Environment loading failed: {e}")
            return False

    def test_database_connection(self):
        """Test database connectivity"""
        logger.info("🔗 Testing database connection...")

        try:
            connection_info = self.db_module.test_connection()
            if connection_info and connection_info.get("status") == "connected":
                logger.info("✅ Database connection successful")
                logger.info(f"Type: {connection_info.get('type', 'unknown')}")
                logger.info(f"Database: {connection_info.get('database', 'unknown')}")
                logger.info(f"User: {connection_info.get('user', 'unknown')}")
                logger.info(f"Size: {connection_info.get('database_size', 'unknown')}")
                return True
            else:
                error = (
                    connection_info.get("error", "Unknown error")
                    if connection_info
                    else "No response"
                )
                logger.error(f"❌ Database connection failed: {error}")
                return False

        except Exception as e:
            logger.error(f"❌ Database connection error: {e}")
            return False

    def check_migration_needed(self):
        """Check if SQLite to PostgreSQL migration is needed using pgloader"""
        logger.info("🔍 Checking migration status...")

        try:
            # Check if migration has already been completed
            if self.migration_flag.exists():
                logger.info("✅ Migration already completed (flag file exists)")
                return False

            from src.config import get_database_url

            database_url = get_database_url()

            # If using PostgreSQL, check if we need to migrate from SQLite
            if not database_url.startswith("sqlite"):
                # Check if SQLite database exists with data
                sqlite_path = (
                    self.project_root / "data" / "database" / "price_history.db"
                )
                if sqlite_path.exists():
                    sqlite_size = sqlite_path.stat().st_size
                    if sqlite_size > 1024:  # More than 1KB suggests real data
                        logger.info(
                            f"📊 SQLite database found with {sqlite_size} bytes - pgloader migration needed"
                        )
                        return True

            logger.info("✅ No migration needed")
            return False

        except Exception as e:
            logger.error(f"❌ Migration check failed: {e}")
            return False

    def run_migration(self):
        """Execute SQLite to PostgreSQL migration using pgloader"""
        logger.info("🚛 Starting database migration with pgloader...")

        try:
            # Check for pgloader installation
            try:
                result = subprocess.run(
                    ["pgloader", "--version"], capture_output=True, text=True
                )
                if result.returncode != 0:
                    logger.error(
                        "❌ pgloader not found. Please install pgloader first."
                    )
                    logger.info(
                        "Installation: apt-get install pgloader (Ubuntu) or brew install pgloader (macOS)"
                    )
                    return False
                logger.info(f"✅ pgloader found: {result.stdout.strip()}")
            except FileNotFoundError:
                logger.error(
                    "❌ pgloader not found in PATH. Please install pgloader first."
                )
                return False

            # Note: Legacy SQLite migration no longer supported
            # The system now requires PostgreSQL from the start
            # Migration script (migrate_sqlite.py) has been removed
            logger.warning("⚠️  SQLite → PostgreSQL migration is no longer supported.")
            logger.warning("   The system requires PostgreSQL/Supabase from the start.")
            logger.warning(
                "   Please configure DATABASE_URL in .env with PostgreSQL connection."
            )
            return False

        except Exception as e:
            logger.error(f"❌ Migration error: {e}")
            return False

    def schedule_data_updates(self):
        """Schedule periodic data collection"""
        logger.info("⏰ Setting up data collection schedule...")

        try:
            from src.config import settings

            config = settings()

            # Use a default update interval if not configured
            update_interval = getattr(
                config, "DATA_UPDATE_INTERVAL", 7200
            )  # 2 hours in seconds

            logger.info(
                f"📊 Data updates scheduled every {update_interval//3600} hours"
            )

            # You can implement actual scheduling here
            # For now, just log the intention
            logger.info("✅ Scheduling configured (manual implementation needed)")
            return True

        except Exception as e:
            logger.error(f"❌ Scheduling setup failed: {e}")
            return False

    def run_health_checks(self):
        """Run comprehensive health checks"""
        logger.info("🏥 Running health checks...")

        try:
            # Database health
            db_healthy = self.db_module.healthcheck()
            logger.info(
                f"Database health: {'✅ Healthy' if db_healthy else '❌ Unhealthy'}"
            )

            # Database size
            try:
                size = self.db_module.get_database_size()
                if size:
                    logger.info(f"Database size: {size}")
            except Exception:
                logger.warning("⚠️ Could not get database size")

            # Configuration health
            from src.config import settings

            config = settings()
            config_healthy = bool(
                config.DATABASE_URL and getattr(config, "SUPABASE_URL", None)
            )
            logger.info(
                f"Configuration: {'✅ Complete' if config_healthy else '⚠️ Missing keys'}"
            )

            return db_healthy and config_healthy

        except Exception as e:
            logger.error(f"❌ Health check failed: {e}")
            return False

    def cleanup(self):
        """Cleanup resources"""
        logger.info("🧹 Cleaning up...")

        try:
            if self.db_module:
                self.db_module.close_engines()
            logger.info("✅ Cleanup complete")
        except Exception as e:
            logger.warning(f"⚠️ Cleanup warning: {e}")

    def bootstrap(self):
        """Main bootstrap process"""
        start_time = datetime.now()
        logger.info("🚀 Starting LLM Portfolio Project bootstrap...")
        logger.info("=" * 60)

        try:
            # Step 1: Install dependencies
            if not self.install_dependencies():
                return False

            # Step 2: Load modules
            if not self.load_modules():
                return False

            # Step 3: Load environment
            if not self.load_environment():
                return False

            # Step 4: Test database
            if not self.test_database_connection():
                return False

            # Step 5: Check migration
            if self.check_migration_needed():
                if not self.run_migration():
                    return False

            # Step 6: Schedule updates
            if not self.schedule_data_updates():
                return False

            # Step 7: Final health checks
            if not self.run_health_checks():
                logger.warning("⚠️ Some health checks failed")

            # Success!
            duration = datetime.now() - start_time
            logger.info("=" * 60)
            logger.info(
                f"🎉 Bootstrap completed successfully in {duration.total_seconds():.1f}s"
            )
            logger.info("✅ System ready for operation")

            return True

        except KeyboardInterrupt:
            logger.info("❌ Bootstrap interrupted by user")
            return False
        except Exception as e:
            logger.error(f"❌ Bootstrap failed: {e}")
            return False
        finally:
            self.cleanup()


def main():
    """Main entry point"""
    try:
        bootstrap_manager = BootstrapManager()
        success = bootstrap_manager.bootstrap()
        sys.exit(0 if success else 1)
    except Exception as e:
        logger.error(f"❌ Critical error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
