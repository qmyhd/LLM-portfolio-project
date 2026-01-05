"""
System Status Checker

Checks the health of the system by counting rows in key tables
and verifying recent data ingestion.
"""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.db import execute_sql
from src.config import settings


def check_status():
    print("🔍 Checking System Status...\n")

    # 1. Database Connection & Counts
    # Map tables to their timestamp columns for freshness check
    table_config = {
        "positions": "sync_timestamp",
        "orders": "sync_timestamp",
        "account_balances": "sync_timestamp",
        "discord_messages": "created_at",
        "discord_trading_clean": "processed_at",
        "discord_market_clean": "processed_at",
        "twitter_data": "created_at",
    }

    print(f"{'TABLE':<25} | {'COUNT':<10} | {'LATEST ENTRY'}")
    print("-" * 60)

    for table, date_col in table_config.items():
        try:
            # Get count
            count_res = execute_sql(f"SELECT COUNT(*) FROM {table}", fetch_results=True)
            count = count_res[0][0] if count_res else 0

            latest_res = execute_sql(
                f"SELECT {date_col} FROM {table} ORDER BY {date_col} DESC LIMIT 1",
                fetch_results=True,
            )
            latest = str(latest_res[0][0])[:19] if latest_res else "N/A"

            print(f"{table:<25} | {count:<10} | {latest}")

        except Exception as e:
            print(f"{table:<25} | {'ERROR':<10} | {str(e)[:20]}...")

    print("\n" + "-" * 60)

    # 2. Configuration Check
    config = settings()
    print(f"\n⚙️  Configuration:")
    print(f"• Database:   {'✅ Connected' if config.DATABASE_URL else '❌ Missing'}")
    print(
        f"• Discord:    {'✅ Configured' if config.DISCORD_BOT_TOKEN else '❌ Missing Token'}"
    )
    print(
        f"• SnapTrade:  {'✅ Configured' if config.SNAPTRADE_CLIENT_ID else '❌ Missing Creds'}"
    )
    print(f"• Channels:   {len(config.log_channel_ids_list)} monitored")
    print(f"• Sports:     {len(config.sports_channel_ids_list)} monitored")


if __name__ == "__main__":
    check_status()
