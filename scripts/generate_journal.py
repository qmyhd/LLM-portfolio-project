#!/usr/bin/env python
"""
Automated portfolio journal generator script.
Runs the data collection and journal generation process without manual notebook execution.

Usage:
    python generate_journal.py [options]

Options:
    --force     Force update of all data even if it was updated recently
    --output    Directory to save the journal (default: data/processed)

For more options, use the complete CLI interface:
    python -m src.journal_generator --help

This script will:
1. Update portfolio positions and orders if needed (use --force to always update)
2. Fetch real-time price data for all holdings
3. Update historical price data
4. Generate a portfolio journal entry and save to file

Note: This is a simple wrapper around src.journal_generator - all functionality has been migrated there.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.env_bootstrap import bootstrap_env  # noqa: E402

bootstrap_env()

# Import main function from journal_generator
from src.journal_generator import main  # noqa: E402

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate a portfolio journal automatically")
    parser.add_argument("--force", action="store_true", help="Force update of all data")
    parser.add_argument("--output", help="Directory to save the journal")
    
    args = parser.parse_args()
    
    output_dir = Path(args.output) if args.output else None
    
    # Call the main function from journal_generator
    main(force_update=args.force, output_dir=output_dir)
