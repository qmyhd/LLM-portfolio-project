#!/usr/bin/env python3
"""
LLM Portfolio Project - Environment Setup Script
===============================================

Minimal setup script for bootstrapping the LLM Portfolio Project in any environment.
Handles virtual environment creation, dependency installation, directory setup, 
and basic validation.

Usage:
    python setup.py                    # Full setup
    python setup.py --quick           # Skip validation checks
    python setup.py --dev             # Development mode (include test dependencies)
    python setup.py --check-only      # Only run health checks

Requirements:
    - Python 3.8+ 
    - pip
    - Internet connection for package downloads

This script will:
1. Create virtual environment (.venv)
2. Install all dependencies from requirements.txt
3. Create necessary data directories
4. Generate .env template
5. Initialize database structure
6. Run validation checks
"""

import argparse
import os
import subprocess
import sys
import platform
from pathlib import Path
from typing import List, Optional

# Color codes for terminal output
class Colors:
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BLUE = '\033[94m'
    BOLD = '\033[1m'
    END = '\033[0m'

def print_status(message: str, status: str = "INFO"):
    """Print colored status message."""
    color = {
        "INFO": Colors.BLUE,
        "SUCCESS": Colors.GREEN,
        "WARNING": Colors.YELLOW,
        "ERROR": Colors.RED
    }.get(status, Colors.BLUE)
    
    print(f"{color}[{status}]{Colors.END} {message}")

def run_command(command: List[str], cwd: Optional[Path] = None, check: bool = True) -> subprocess.CompletedProcess:
    """Run a command and return the result."""
    try:
        print_status(f"Running: {' '.join(command)}")
        result = subprocess.run(command, cwd=cwd, check=check, capture_output=True, text=True)
        if result.stdout:
            print(result.stdout.strip())
        return result
    except subprocess.CalledProcessError as e:
        print_status(f"Command failed: {e}", "ERROR")
        if e.stderr:
            print(e.stderr.strip())
        raise

class EnvironmentSetup:
    """Handles environment setup and validation."""
    
    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.venv_path = project_root / ".venv"
        self.data_dirs = [
            "data/raw",
            "data/processed", 
            "data/database",
            "charts",
            "logs"
        ]
        
    def check_python_version(self):
        """Verify Python version compatibility."""
        print_status("Checking Python version...")
        version = sys.version_info
        if version < (3, 8):
            raise RuntimeError(f"Python 3.8+ required, found {version.major}.{version.minor}")
        print_status(f"Python {version.major}.{version.minor}.{version.micro} ✓", "SUCCESS")
    
    def create_virtual_environment(self):
        """Create virtual environment if it doesn't exist."""
        if self.venv_path.exists():
            print_status("Virtual environment already exists", "WARNING")
            return
            
        print_status("Creating virtual environment...")
        run_command([sys.executable, "-m", "venv", str(self.venv_path)])
        print_status("Virtual environment created ✓", "SUCCESS")
    
    def get_python_executable(self) -> str:
        """Get the Python executable path in the virtual environment."""
        if platform.system() == "Windows":
            return str(self.venv_path / "Scripts" / "python.exe")
        else:
            return str(self.venv_path / "bin" / "python")
    
    def get_pip_executable(self) -> str:
        """Get the pip executable path in the virtual environment."""
        if platform.system() == "Windows":
            return str(self.venv_path / "Scripts" / "pip.exe")
        else:
            return str(self.venv_path / "bin" / "pip")
    
    def install_dependencies(self, dev_mode: bool = False):
        """Install project dependencies."""
        print_status("Installing dependencies...")
        
        pip_cmd = self.get_pip_executable()
        
        # Upgrade pip first
        run_command([pip_cmd, "install", "--upgrade", "pip"])
        
        # Install main dependencies
        requirements_file = self.project_root / "requirements.txt"
        if requirements_file.exists():
            run_command([pip_cmd, "install", "-r", str(requirements_file)])
        else:
            print_status("requirements.txt not found, installing minimal dependencies", "WARNING")
            # Install minimal required packages
            minimal_deps = [
                "pandas>=2.0.0",
                "yfinance>=0.2.0", 
                "python-dotenv>=1.0.0",
                "pydantic-settings>=2.0.0",
                "sqlalchemy>=2.0.0",
                "discord.py>=2.3.0"
            ]
            run_command([pip_cmd, "install"] + minimal_deps)
        
        # Install package in development mode
        if dev_mode:
            run_command([pip_cmd, "install", "-e", "."])
        
        print_status("Dependencies installed ✓", "SUCCESS")
    
    def create_directories(self):
        """Create necessary project directories."""
        print_status("Creating project directories...")
        
        for dir_path in self.data_dirs:
            full_path = self.project_root / dir_path
            full_path.mkdir(parents=True, exist_ok=True)
            print_status(f"Created: {dir_path}")
        
        print_status("Directories created ✓", "SUCCESS")
    
    def create_env_template(self):
        """Create .env template file if it doesn't exist."""
        env_file = self.project_root / ".env"
        env_example = self.project_root / ".env.example"
        
        if env_file.exists():
            print_status(".env file already exists", "WARNING")
            return
        
        print_status("Creating .env template...")
        
        env_template = """# LLM Portfolio Project Environment Variables
# Copy this file to .env and fill in your actual values

# Database Configuration
DATABASE_URL=""
SUPABASE_URL=""
SUPABASE_ANON_KEY=""
SUPABASE_SERVICE_ROLE_KEY=""

# SnapTrade API (Optional - for brokerage integration)
SNAPTRADE_CLIENT_ID=""
SNAPTRADE_CONSUMER_KEY=""
SNAPTRADE_USER_ID=""
SNAPTRADE_USER_SECRET=""
ROBINHOOD_ACCOUNT_ID=""

# LLM API Keys (At least one required)
GEMINI_API_KEY=""
OPENAI_API_KEY=""

# Discord Bot (Optional - for Discord integration)
DISCORD_BOT_TOKEN=""
DISCORD_CLIENT_ID=""
DISCORD_CLIENT_SECRET=""
LOG_CHANNEL_IDS=""

# Twitter API (Optional - for social sentiment analysis)
TWITTER_BEARER_TOKEN=""
TWITTER_API_KEY=""
TWITTER_API_SECRET=""
TWITTER_ACCESS_TOKEN=""
TWITTER_ACCESS_TOKEN_SECRET=""

# Application Settings
DEBUG=False
LOG_LEVEL=INFO
"""
        
        env_file.write_text(env_template)
        env_example.write_text(env_template)
        
        print_status(".env template created ✓", "SUCCESS")
        print_status("Please edit .env with your actual API keys and configuration", "WARNING")
    
    def initialize_database(self):
        """Initialize database structure."""
        print_status("Initializing database...")
        
        python_cmd = self.get_python_executable()
        
        # Try to run database initialization
        try:
            # Use the init script if it exists
            init_script = self.project_root / "scripts" / "init_database.py"
            if init_script.exists():
                run_command([python_cmd, str(init_script)], check=False)
            else:
                # Fallback: create basic SQLite database
                run_command([python_cmd, "-c", 
                    "from src.database import initialize_database; initialize_database()"], 
                    check=False)
        except Exception as e:
            print_status(f"Database initialization skipped: {e}", "WARNING")
        
        print_status("Database initialization completed", "SUCCESS")
    
    def run_health_checks(self):
        """Run basic health checks to verify setup."""
        print_status("Running health checks...")
        
        python_cmd = self.get_python_executable()
        
        # Test core imports
        test_imports = [
            "import src.config",
            "import src.database", 
            "import src.data_collector",
            "import src.journal_generator",
            "from src.config import settings; print('Config loaded successfully')"
        ]
        
        for test_import in test_imports:
            try:
                run_command([python_cmd, "-c", test_import])
                print_status(f"✓ {test_import.split(';')[0]}")
            except Exception as e:
                print_status(f"✗ {test_import.split(';')[0]} - {e}", "WARNING")
        
        print_status("Health checks completed ✓", "SUCCESS")
    
    def run_setup(self, quick: bool = False, dev_mode: bool = False, check_only: bool = False):
        """Run complete setup process."""
        print_status("=" * 50, "INFO")
        print_status("LLM Portfolio Project Setup", "INFO")
        print_status("=" * 50, "INFO")
        
        if check_only:
            self.run_health_checks()
            return
        
        try:
            self.check_python_version()
            self.create_virtual_environment()
            self.create_directories()
            self.install_dependencies(dev_mode)
            self.create_env_template()
            
            if not quick:
                self.initialize_database()
                self.run_health_checks()
            
            print_status("=" * 50, "SUCCESS")
            print_status("Setup completed successfully! 🎉", "SUCCESS")
            print_status("=" * 50, "SUCCESS")
            
            # Print next steps
            print_status("Next steps:", "INFO")
            print_status("1. Edit .env file with your API keys", "INFO")
            print_status("2. Activate virtual environment:", "INFO")
            if platform.system() == "Windows":
                print_status("   .venv\\Scripts\\Activate.ps1", "INFO")
            else:
                print_status("   source .venv/bin/activate", "INFO")
            print_status("3. Run: python generate_journal.py --help", "INFO")
            
        except Exception as e:
            print_status(f"Setup failed: {e}", "ERROR")
            sys.exit(1)

def main():
    """Main setup function."""
    parser = argparse.ArgumentParser(description="LLM Portfolio Project Setup")
    parser.add_argument("--quick", action="store_true", help="Skip validation checks")
    parser.add_argument("--dev", action="store_true", help="Development mode")
    parser.add_argument("--check-only", action="store_true", help="Only run health checks")
    
    args = parser.parse_args()
    
    project_root = Path(__file__).parent
    setup = EnvironmentSetup(project_root)
    
    setup.run_setup(
        quick=args.quick,
        dev_mode=args.dev,
        check_only=args.check_only
    )

if __name__ == "__main__":
    main()
