"""
Database initialization script for LLM Portfolio Journal.
Run this to set up all required tables for social and financial data.
"""

import logging
import sys
from pathlib import Path

# Add src directory to path for imports
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))

from database import initialize_database

def main():
    """Initialize the database with all required tables."""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    
    logger = logging.getLogger(__name__)
    
    try:
        logger.info("Initializing database with all required tables...")
        initialize_database()
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
        print("1. Use Discord bot !history command to collect messages")
        print("2. Use !process [general|trading] to clean and process messages")
        print("3. Use !stats to see processing statistics")
        print("4. Run generate_journal.py to create portfolio summaries")
        
    except Exception as e:
        logger.error(f"Error initializing database: {e}")
        print(f"\n❌ Error: {e}")
        return 1
    
    return 0

if __name__ == "__main__":
    exit(main())
