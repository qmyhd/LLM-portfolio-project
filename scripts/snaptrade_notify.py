#!/usr/bin/env python3
"""
SnapTrade Discord Notification Script

Sends Discord notifications for filled orders that haven't been notified yet.
Designed to run periodically via cron or as part of the nightly pipeline.

Usage:
    python scripts/snaptrade_notify.py           # Process all unnotified orders
    python scripts/snaptrade_notify.py --dry-run # Preview without sending
    python scripts/snaptrade_notify.py --limit 5 # Process only 5 orders
"""

import argparse
import asyncio
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Optional

import discord
from discord import Embed, Color

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.db import execute_sql
from src.config import settings
from src.price_service import get_latest_close

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def get_unnotified_orders(limit: Optional[int] = None) -> list[dict]:
    """
    Fetch filled orders that haven't been notified yet.

    Uses notified = false pattern for pending notifications.

    Args:
        limit: Maximum number of orders to return

    Returns:
        List of order dictionaries
    """
    query = """
        SELECT 
            o.brokerage_order_id,
            o.symbol,
            o.action,
            o.order_type,
            o.filled_quantity,
            o.execution_price,
            o.time_executed,
            a.name as account_name
        FROM orders o
        LEFT JOIN accounts a ON o.account_id = a.id
        WHERE o.status = 'FILLED'
          AND o.notified = false
        ORDER BY o.time_executed ASC
    """

    if limit:
        query += f" LIMIT {limit}"

    return execute_sql(query, fetch_results=True) or []


def mark_order_notified(order_id: str) -> bool:
    """
    Mark an order as notified in the database by setting notified = true.

    Args:
        order_id: The brokerage order ID to mark

    Returns:
        True if successful
    """
    try:
        execute_sql(
            "UPDATE orders SET notified = true WHERE brokerage_order_id = :order_id",
            params={"order_id": order_id},
        )
        return True
    except Exception as e:
        logger.error(f"Failed to mark order {order_id} as notified: {e}")
        return False


def create_order_embed(order: dict) -> Embed:
    """
    Create a Discord embed for an order notification.

    Args:
        order: Order data dictionary

    Returns:
        Discord Embed object
    """
    symbol = order.get("symbol", "UNKNOWN")
    side = (order.get("action") or "").upper()
    quantity = order.get("filled_quantity", 0)
    price = order.get("execution_price", 0)
    filled_at = order.get("time_executed")
    account_name = order.get("account_name", "Unknown Account")

    # Calculate trade value
    trade_value = float(quantity) * float(price) if quantity and price else 0

    # Get current price for comparison
    current_price = get_latest_close(symbol)
    price_change = ""
    if current_price and price:
        diff = current_price - float(price)
        pct = (diff / float(price)) * 100 if float(price) > 0 else 0
        emoji = "📈" if diff > 0 else "📉" if diff < 0 else "➡️"
        price_change = f"\n{emoji} Current: ${current_price:.2f} ({pct:+.2f}%)"

    # Set color based on side
    if side == "BUY":
        color = Color.green()
        emoji = "🟢"
        action = "Bought"
    elif side == "SELL":
        color = Color.red()
        emoji = "🔴"
        action = "Sold"
    else:
        color = Color.blue()
        emoji = "🔵"
        action = "Traded"

    embed = Embed(
        title=f"{emoji} Order Filled: {symbol}",
        description=f"{action} **{quantity}** shares at **${price:.2f}**",
        color=color,
        timestamp=datetime.now(timezone.utc),
    )

    embed.add_field(name="Symbol", value=symbol, inline=True)
    embed.add_field(name="Side", value=side, inline=True)
    embed.add_field(name="Quantity", value=str(quantity), inline=True)
    embed.add_field(name="Fill Price", value=f"${float(price):.2f}", inline=True)
    embed.add_field(name="Trade Value", value=f"${trade_value:,.2f}", inline=True)
    embed.add_field(name="Account", value=account_name, inline=True)

    if filled_at:
        embed.add_field(name="Filled At", value=str(filled_at)[:19], inline=False)

    if price_change:
        embed.add_field(name="Price Update", value=price_change.strip(), inline=False)

    embed.set_footer(text="LLM Portfolio Journal • SnapTrade")

    return embed


async def send_discord_notification(webhook_url: str, embed: Embed) -> bool:
    """
    Send a Discord notification via webhook.

    Args:
        webhook_url: Discord webhook URL
        embed: The embed to send

    Returns:
        True if successful
    """
    try:
        async with discord.Webhook.from_url(
            webhook_url, adapter=discord.AsyncWebhookAdapter(discord.HTTPAdapter())
        ) as webhook:
            await webhook.send(embed=embed)
        return True
    except Exception as e:
        logger.error(f"Failed to send Discord notification: {e}")
        return False


async def send_notification_httpx(webhook_url: str, embed: Embed) -> bool:
    """
    Send Discord notification using httpx (fallback method).

    Args:
        webhook_url: Discord webhook URL
        embed: The embed to send

    Returns:
        True if successful
    """
    import httpx

    try:
        payload = {
            "embeds": [embed.to_dict()],
            "username": "LLM Portfolio Journal",
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(
                webhook_url,
                json=payload,
                headers={"Content-Type": "application/json"},
            )
            response.raise_for_status()

        return True
    except Exception as e:
        logger.error(f"Failed to send notification via httpx: {e}")
        return False


async def process_notifications(
    dry_run: bool = False,
    limit: Optional[int] = None,
) -> dict:
    """
    Process all unnotified orders and send Discord notifications.

    Args:
        dry_run: If True, preview without sending
        limit: Maximum number of orders to process

    Returns:
        Summary of processing results
    """
    webhook_url = os.getenv("DISCORD_WEBHOOK_URL")

    if not webhook_url and not dry_run:
        logger.error("DISCORD_WEBHOOK_URL not set in environment")
        return {"error": "Webhook URL not configured", "processed": 0, "failed": 0}

    orders = get_unnotified_orders(limit)

    if not orders:
        logger.info("No unnotified orders found")
        return {"processed": 0, "failed": 0, "skipped": 0}

    logger.info(f"Found {len(orders)} unnotified orders")

    processed = 0
    failed = 0

    for order in orders:
        order_id = order.get("order_id")
        symbol = order.get("symbol")

        logger.info(f"Processing order {order_id}: {symbol}")

        embed = create_order_embed(order)

        if dry_run:
            logger.info(f"[DRY RUN] Would send notification for {symbol}")
            logger.info(f"  Title: {embed.title}")
            logger.info(f"  Description: {embed.description}")
            processed += 1
            continue

        # Try to send notification
        try:
            success = await send_notification_httpx(webhook_url, embed)

            if success:
                mark_order_notified(order_id)
                processed += 1
                logger.info(f"Notification sent for {symbol}")
            else:
                failed += 1
                logger.error(f"Failed to send notification for {symbol}")

        except Exception as e:
            failed += 1
            logger.error(f"Error processing {order_id}: {e}")

        # Rate limit: wait between notifications
        await asyncio.sleep(1)

    return {
        "processed": processed,
        "failed": failed,
        "total": len(orders),
    }


def main():
    """Main entry point for the notification script."""
    parser = argparse.ArgumentParser(
        description="Send Discord notifications for filled orders"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview notifications without sending",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum number of orders to process",
    )

    args = parser.parse_args()

    logger.info("Starting SnapTrade notification processing")
    logger.info(f"Dry run: {args.dry_run}, Limit: {args.limit}")

    results = asyncio.run(
        process_notifications(
            dry_run=args.dry_run,
            limit=args.limit,
        )
    )

    logger.info(f"Processing complete: {results}")

    if results.get("error"):
        sys.exit(1)
    elif results.get("failed", 0) > 0:
        sys.exit(2)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()
