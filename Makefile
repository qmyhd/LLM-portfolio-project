# LLM Portfolio Journal - Common post-migration:		## Validate post-migration state  
	$(PYTHON) scripts\validate_post_migration.py

gen-schemas:			## Generate src/expected_schemas.py from SSOT baseline
	$(PYTHON) scripts\schema_parser.py --output expected
	@echo "✅ Generated EXPECTED_SCHEMAS from 000_baseline.sql"

clean:					## Clean up temporary files and cacheslopment Tasks
# Works on PowerShell via 'make' command
# Usage: make init-db, make migrate, make size

PYTHON := python
SHELL := powershell.exe

.PHONY: help init-db migrate size clean lint test all

# Default target shows help
help:					## Show this help message
	@echo "Available commands:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-15s %s\n", $$1, $$2}'

init-db:				## Create database tables + enable RLS policies
	$(PYTHON) scripts\deploy_database.py

# ARCHIVED COMMANDS - Scripts moved or no longer exist
# bulk-import:			## Bulk import CSV data to PostgreSQL (recommended)
#	$(PYTHON) scripts\bulk_csv_import_fixed.py

# verify-migration:		## Verify migration success and show data status
#	$(PYTHON) scripts\verify_migration.py

# check-data:				## Check what data is available for migration
#	$(PYTHON) scripts\check_data_status.py

# size:					## Show PostgreSQL table counts and sizes
#	$(PYTHON) check_postgres_tables.py

verify-db:				## Verify database deployment and status
	$(PYTHON) scripts\verify_database.py

post-migration:			## Validate post-migration state  
	$(PYTHON) scripts\validate_post_migration.py

clean:					## Clean up temporary files and caches
	Remove-Item -Recurse -Force -ErrorAction SilentlyContinue __pycache__
	Remove-Item -Recurse -Force -ErrorAction SilentlyContinue .pytest_cache
	Remove-Item -Recurse -Force -ErrorAction SilentlyContinue src/__pycache__
	Remove-Item -Recurse -Force -ErrorAction SilentlyContinue scripts/__pycache__
	Remove-Item -Recurse -Force -ErrorAction SilentlyContinue tests/__pycache__
	Get-ChildItem -Recurse -Name "*.pyc" | Remove-Item -Force
	@echo "✅ Cleaned up temporary files"

lint:					## Run code linting and formatting
	$(PYTHON) -m flake8 src/ scripts/ tests/ --max-line-length=120 --ignore=E501,W503
	$(PYTHON) -m black src/ scripts/ tests/ --line-length=120 --check
	@echo "✅ Linting completed"

format:					## Format code with black
	$(PYTHON) -m black src/ scripts/ tests/ --line-length=120
	@echo "✅ Code formatted"

test:					## Run test suite
	$(PYTHON) -m pytest tests/ --maxfail=1 --disable-warnings -v

journal:				## Generate journal entry (auto-updates data)
	$(PYTHON) generate_journal.py --force

bot:					## Run Discord bot for real-time data collection
	$(PYTHON) -m src.bot.bot

install:				## Install dependencies
	$(PYTHON) -m pip install -r requirements.txt
	$(PYTHON) -m pip install -e .

setup:					## Complete development setup
	$(PYTHON) -m venv .venv
	.\.venv\Scripts\Activate.ps1
	$(PYTHON) -m pip install -r requirements.txt
	$(PYTHON) -m pip install -e .
	@echo "✅ Development environment ready"

all: clean lint test init-db		## Run complete validation pipeline
	@echo "🎉 All tasks completed successfully!"
