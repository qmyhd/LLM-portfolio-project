"""
Webhook API routes for SnapTrade integration.

Endpoints:
- POST /webhook/snaptrade - Handle SnapTrade webhook events
"""

import logging
import hmac
import hashlib
import os
from datetime import datetime, timezone
from typing import Optional, Any

from fastapi import APIRouter, HTTPException, Request, Header
from pydantic import BaseModel

from src.db import execute_sql

logger = logging.getLogger(__name__)
router = APIRouter()


class SnapTradeWebhookPayload(BaseModel):
    """SnapTrade webhook payload."""

    event: str
    userId: str
    userSecret: Optional[str] = None
    accountId: Optional[str] = None
    data: Optional[dict[str, Any]] = None


class WebhookResponse(BaseModel):
    """Webhook response."""

    status: str
    event: str
    processed: bool
    message: Optional[str] = None


def verify_webhook_signature(payload: bytes, signature: str, secret: str) -> bool:
    """
    Verify SnapTrade webhook signature.

    Args:
        payload: Raw request body
        signature: X-SnapTrade-Signature header
        secret: Webhook secret from SnapTrade

    Returns:
        True if signature is valid
    """
    if not signature or not secret:
        return False

    expected = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()

    return hmac.compare_digest(signature, expected)


@router.post("/snaptrade", response_model=WebhookResponse)
async def handle_snaptrade_webhook(
    request: Request,
    x_snaptrade_signature: Optional[str] = Header(None, alias="X-SnapTrade-Signature"),
):
    """
    Handle incoming SnapTrade webhook events.

    Supported events:
    - ACCOUNT_UPDATED: Account sync triggered
    - ORDER_PLACED: New order placed
    - ORDER_FILLED: Order executed
    - ORDER_CANCELLED: Order cancelled

    Args:
        request: Raw request with webhook payload
        x_snaptrade_signature: Webhook signature for verification

    Returns:
        Processing status
    """
    try:
        # Get raw body for signature verification
        raw_body = await request.body()

        # Verify signature if webhook secret is configured
        webhook_secret = os.getenv("SNAPTRADE_WEBHOOK_SECRET")
        if webhook_secret:
            if not x_snaptrade_signature:
                raise HTTPException(status_code=401, detail="Missing webhook signature")

            if not verify_webhook_signature(
                raw_body, x_snaptrade_signature, webhook_secret
            ):
                raise HTTPException(status_code=401, detail="Invalid webhook signature")

        # Parse payload
        payload = await request.json()
        event = payload.get("event", "UNKNOWN")
        user_id = payload.get("userId", "")
        account_id = payload.get("accountId")
        data = payload.get("data", {})

        logger.info(f"Received SnapTrade webhook: {event} for user {user_id}")

        # Handle different event types
        if event == "ACCOUNT_UPDATED":
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

            # Update order in database with filled status
            execute_sql(
                """
                UPDATE orders
                SET 
                    status = 'filled',
                    filled_price = :price,
                    filled_quantity = :quantity,
                    filled_at = :filled_at,
                    notified = false
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
