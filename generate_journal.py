#!/usr/bin/env python
"""
Automated portfolio journal generator script.
Runs the data collection and journal generation process without manual notebook execution.

Usage:
    python generate_journal.py

This script will:
1. Update portfolio positions and orders
2. Fetch real-time price data for all holdings
3. Update historical price data
4. Generate a portfolio journal entry and save to file
"""

import os
import logging
import argparse
from pathlib import Path
from datetime import datetime

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Import project modules
from src.data_collector import update_all_data
from src.journal_generator import generate_portfolio_journal, BASE_DIR, RAW_DIR, PROCESSED_DIR

def main(force_update=False, output_dir=None):
    """Run the automated journal generation process
    
    Args:
        force_update: Force update of all data even if it was updated recently
        output_dir: Directory to save the journal (default: data/processed)
    """
    # Configure output directory
    output_dir = output_dir or PROCESSED_DIR
    
    # Create output directory if it doesn't exist
    output_dir.mkdir(parents=True, exist_ok=True)
    
    logger.info("🔄 Starting automated portfolio journal generation")
    
    # Check if data needs updating
    prices_csv = RAW_DIR / "prices.csv"
    positions_csv = RAW_DIR / "positions.csv"
    
    update_needed = force_update
    
    if not update_needed:
        # Check if prices were updated today
        if not prices_csv.exists() or not positions_csv.exists():
            update_needed = True
        else:
            # Check if files were updated today
            today = datetime.now().date()
            prices_last_modified = datetime.fromtimestamp(prices_csv.stat().st_mtime).date()
            positions_last_modified = datetime.fromtimestamp(positions_csv.stat().st_mtime).date()
            
            if prices_last_modified < today or positions_last_modified < today:
                update_needed = True
    
    # Update data if needed
    if update_needed:
        logger.info("🔄 Updating portfolio data")
        update_all_data()
    else:
        logger.info("✅ Using existing portfolio data from today")
    
    # Generate journal
    logger.info("🔄 Generating portfolio journal")
    journal_entry = generate_portfolio_journal(
        positions_path=positions_csv,
        discord_path=RAW_DIR / "discord_msgs.csv",
        prices_path=prices_csv,
        output_dir=output_dir
    )
    
    if journal_entry:
        logger.info("✅ Journal generation complete")
        return True
    else:
        logger.error("❌ Journal generation failed")
        return False

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate a portfolio journal automatically")
    parser.add_argument("--force", action="store_true", help="Force update of all data")
    parser.add_argument("--output", help="Directory to save the journal")
    
    args = parser.parse_args()
    
    output_dir = Path(args.output) if args.output else None
    
    main(force_update=args.force, output_dir=output_dir)