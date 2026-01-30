"""
Webhook API routes for SnapTrade integration.

Endpoints:
- POST /webhook/snaptrade - Handle SnapTrade webhook events

Security:
- HMAC-SHA256 signature verification using SNAPTRADE_CLIENT_SECRET
- Replay protection via eventTimestamp (5-minute window)
- Signature header: X-SnapTrade-Signature or Signature
"""

import asyncio
import logging
import hmac
import hashlib
import os
from datetime import datetime, timezone, timedelta
from typing import Optional, Any

from fastapi import APIRouter, HTTPException, Request, Header
from pydantic import BaseModel

from src.db import execute_sql
from src.snaptrade_collector import SnapTradeCollector

logger = logging.getLogger(__name__)
router = APIRouter()

# Maximum age of webhook events (prevent replay attacks)
MAX_EVENT_AGE_SECONDS = 300  # 5 minutes


class SnapTradeWebhookPayload(BaseModel):
    """SnapTrade webhook payload."""

    event: str
    userId: str
    userSecret: Optional[str] = None
    accountId: Optional[str] = None
    eventTimestamp: Optional[str] = None  # ISO timestamp for replay protection
    data: Optional[dict[str, Any]] = None


class WebhookResponse(BaseModel):
    """Webhook response."""

    status: str
    event: str
    processed: bool
    message: Optional[str] = None


def verify_webhook_signature(payload: bytes, signature: str, secret: str) -> bool:
    """
    Verify SnapTrade webhook signature using SNAPTRADE_CLIENT_SECRET.

    SnapTrade signs webhooks with HMAC-SHA256 using the client secret.

    Args:
        payload: Raw request body
        signature: Signature header value (X-SnapTrade-Signature or Signature)
        secret: SNAPTRADE_CLIENT_SECRET

    Returns:
        True if signature is valid
    """
    if not signature or not secret:
        return False

    expected = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()

    return hmac.compare_digest(signature.lower(), expected.lower())


def verify_event_timestamp(event_timestamp: Optional[str]) -> bool:
    """
    Verify webhook event is not a replay attack.

    Args:
        event_timestamp: ISO timestamp from webhook payload

    Returns:
        True if event is within acceptable time window
    """
    if not event_timestamp:
        # If no timestamp, allow but log warning
        logger.warning(
            "Webhook received without eventTimestamp - skipping replay check"
        )
        return True

    try:
        # Parse ISO timestamp
        event_time = datetime.fromisoformat(event_timestamp.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        age = (now - event_time).total_seconds()

        if age > MAX_EVENT_AGE_SECONDS:
            logger.warning(
                f"Webhook event too old: {age:.0f}s > {MAX_EVENT_AGE_SECONDS}s"
            )
            return False

        if age < -60:  # Allow 1 minute clock skew into the future
            logger.warning(f"Webhook event from future: {age:.0f}s")
            return False

        return True
    except Exception as e:
        logger.error(f"Failed to parse event timestamp: {e}")
        return False


@router.post("/snaptrade", response_model=WebhookResponse)
async def handle_snaptrade_webhook(
    request: Request,
    x_snaptrade_signature: Optional[str] = Header(None, alias="X-SnapTrade-Signature"),
    signature: Optional[str] = Header(None, alias="Signature"),
):
    """
    Handle incoming SnapTrade webhook events.

    Supported events:
    - ACCOUNT_HOLDINGS_UPDATED: Holdings changed - refresh orders
    - ACCOUNT_UPDATED: Account sync triggered
    - ORDER_PLACED: New order placed
    - ORDER_FILLED: Order executed
    - ORDER_CANCELLED: Order cancelled

    Security:
    - HMAC-SHA256 signature verification using SNAPTRADE_CLIENT_SECRET
    - Accepts signature in either X-SnapTrade-Signature or Signature header
    - Replay protection via eventTimestamp (5-minute window)

    Args:
        request: Raw request with webhook payload
        x_snaptrade_signature: Webhook signature (X-SnapTrade-Signature header)
        signature: Webhook signature (Signature header, fallback)

    Returns:
        Processing status
    """
    try:
        # Get raw body for signature verification
        raw_body = await request.body()

        # Use whichever signature header is present
        sig = x_snaptrade_signature or signature

        # Verify signature using SNAPTRADE_CLIENT_SECRET (NOT consumer key)
        client_secret = os.getenv("SNAPTRADE_CLIENT_SECRET")
        if client_secret:
            if not sig:
                raise HTTPException(status_code=401, detail="Missing webhook signature")

            if not verify_webhook_signature(raw_body, sig, client_secret):
                raise HTTPException(status_code=401, detail="Invalid webhook signature")
        else:
            logger.warning(
                "SNAPTRADE_CLIENT_SECRET not set - skipping signature verification"
            )

        # Parse payload
        payload = await request.json()
        event = payload.get("event", "UNKNOWN")
        user_id = payload.get("userId", "")
        account_id = payload.get("accountId")
        event_timestamp = payload.get("eventTimestamp")
        data = payload.get("data", {})

        # Verify event timestamp for replay protection
        if not verify_event_timestamp(event_timestamp):
            raise HTTPException(
                status_code=400, detail="Event timestamp expired or invalid"
            )

        logger.info(f"Received SnapTrade webhook: {event} for user {user_id}")

        # Handle different event types
        if event == "ACCOUNT_HOLDINGS_UPDATED":
            # Holdings changed - refresh orders from SnapTrade and reset notifications
            logger.info(f"Account {account_id} holdings updated - refreshing orders")

            try:
                # Trigger order refresh via SnapTrade collector
                collector = SnapTradeCollector()
                await asyncio.to_thread(collector.sync_orders)
                logger.info("Orders synced from SnapTrade")
            except Exception as e:
                logger.error(f"Failed to sync orders: {e}")

            # Reset notified_at for any newly filled orders so they get notified
            execute_sql(
                """
                UPDATE orders
                SET notified_at = NULL
                WHERE account_id = :account_id
                  AND status = 'filled'
                  AND notified_at IS NOT NULL
                  AND filled_at > NOW() - INTERVAL '1 hour'
                """,
                params={"account_id": account_id},
            )

            message = "Holdings updated, orders refreshed, notifications reset"

        elif event == "ACCOUNT_UPDATED":
            # Trigger account sync
            logger.info(f"Account {account_id} updated, triggering sync")
            # Could trigger async sync here
            message = "Account sync will be triggered"

        elif event == "ORDER_PLACED":
            # Log new order
            order_id = data.get("orderId")
            symbol = data.get("symbol")
            logger.info(f"New order placed: {order_id} for {symbol}")
            message = f"Order {order_id} logged"

        elif event == "ORDER_FILLED":
            # Order executed - mark for notification
            order_id = data.get("orderId")
            symbol = data.get("symbol")
            side = data.get("side")
            quantity = data.get("filledQuantity")
            price = data.get("filledPrice")

            logger.info(f"Order filled: {side} {quantity} {symbol} @ ${price}")

            # Update order in database with filled status, notified_at = NULL for pending notification
            execute_sql(
                """
                UPDATE orders
                SET
                    status = 'filled',
                    filled_price = :price,
                    filled_quantity = :quantity,
                    filled_at = :filled_at,
                    notified_at = NULL
                WHERE order_id = :order_id
                """,
                params={
                    "order_id": order_id,
                    "price": price,
                    "quantity": quantity,
                    "filled_at": datetime.now(timezone.utc).isoformat(),
                },
            )

            message = f"Order {order_id} marked as filled, pending notification"

        elif event == "ORDER_CANCELLED":
            order_id = data.get("orderId")
            logger.info(f"Order cancelled: {order_id}")

            execute_sql(
                "UPDATE orders SET status = 'cancelled' WHERE order_id = :order_id",
                params={"order_id": order_id},
            )

            message = f"Order {order_id} marked as cancelled"

        else:
            logger.warning(f"Unknown webhook event: {event}")
            message = f"Unknown event type: {event}"

        # Log webhook receipt
        execute_sql(
            """
            INSERT INTO processing_status (table_name, status, last_run)
            VALUES (:table_name, :status, :last_run)
            ON CONFLICT (table_name)
            DO UPDATE SET status = :status, last_run = :last_run
            """,
            params={
                "table_name": f"webhook_{event.lower()}",
                "status": "processed",
                "last_run": datetime.now(timezone.utc).isoformat(),
            },
        )

        return WebhookResponse(
            status="success",
            event=event,
            processed=True,
            message=message,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error processing webhook: {e}")
        return WebhookResponse(
            status="error",
            event=payload.get("event", "UNKNOWN") if "payload" in dir() else "UNKNOWN",
            processed=False,
            message=str(e),
        )
