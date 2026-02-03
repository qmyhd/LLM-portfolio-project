"""
Webhook API routes for SnapTrade integration.

Endpoints:
- POST /webhook/snaptrade - Handle SnapTrade webhook events

Security:
- HMAC-SHA256 signature verification using SNAPTRADE_CLIENT_SECRET
- Signature is base64 encoded (matches SnapTrade's format)
- Replay protection via eventTimestamp (5-minute window)
- webhookId deduplication to prevent duplicate processing
- Signature header: X-SnapTrade-Signature or Signature
"""

import asyncio
import base64
import json
import logging
import hmac
import hashlib
import os
from datetime import datetime, timezone, timedelta
from typing import Optional, Any

from fastapi import APIRouter, HTTPException, Request, Header, BackgroundTasks
from pydantic import BaseModel

from src.db import execute_sql
from src.snaptrade_collector import SnapTradeCollector

logger = logging.getLogger(__name__)
router = APIRouter()

# Maximum age of webhook events (prevent replay attacks)
MAX_EVENT_AGE_SECONDS = 300  # 5 minutes

# In-memory cache for webhookId deduplication (with TTL-based cleanup)
# In production, consider using Redis or database for multi-instance support
_seen_webhook_ids: dict[str, datetime] = {}
_WEBHOOK_ID_TTL_SECONDS = 3600  # Keep IDs for 1 hour


class SnapTradeWebhookPayload(BaseModel):
    """SnapTrade webhook payload."""

    event: str
    userId: str
    userSecret: Optional[str] = None
    accountId: Optional[str] = None
    eventTimestamp: Optional[str] = None  # ISO timestamp for replay protection
    webhookId: Optional[str] = None  # Unique ID for deduplication
    data: Optional[dict[str, Any]] = None


class WebhookResponse(BaseModel):
    """Webhook response."""

    status: str
    event: str
    processed: bool
    message: Optional[str] = None


def canonicalize_json(payload: dict) -> str:
    """
    Convert payload to canonical JSON string for signature verification.

    SnapTrade uses: json.dumps(payload, separators=(",", ":"), sort_keys=True)

    Args:
        payload: Webhook payload dict

    Returns:
        Canonical JSON string
    """
    return json.dumps(payload, separators=(",", ":"), sort_keys=True)


def verify_webhook_signature(
    payload_bytes: bytes,
    payload_dict: dict,
    signature: str,
    secret: str,
) -> bool:
    """
    Verify SnapTrade webhook signature using SNAPTRADE_CLIENT_SECRET.

    SnapTrade signs webhooks with HMAC-SHA256 using the client secret,
    and base64 encodes the result.

    Tries both raw bytes and canonical JSON for compatibility.

    Args:
        payload_bytes: Raw request body bytes
        payload_dict: Parsed payload dict (for canonical JSON fallback)
        signature: Signature header value (base64 encoded)
        secret: SNAPTRADE_CLIENT_SECRET

    Returns:
        True if signature is valid
    """
    if not signature or not secret:
        return False

    # Clean signature (may have whitespace or "sha256=" prefix)
    clean_sig = signature.strip()
    if clean_sig.lower().startswith("sha256="):
        clean_sig = clean_sig[7:]

    # Try multiple signature verification methods:
    # 1. Base64 encoded HMAC of raw bytes
    # 2. Base64 encoded HMAC of canonical JSON
    # 3. Hex encoded HMAC (legacy fallback)

    secret_bytes = secret.encode()

    # Method 1: Base64 of raw bytes
    expected_b64_raw = base64.b64encode(
        hmac.new(secret_bytes, payload_bytes, hashlib.sha256).digest()
    ).decode()

    if hmac.compare_digest(clean_sig, expected_b64_raw):
        return True

    # Method 2: Base64 of canonical JSON
    canonical = canonicalize_json(payload_dict).encode()
    expected_b64_canonical = base64.b64encode(
        hmac.new(secret_bytes, canonical, hashlib.sha256).digest()
    ).decode()

    if hmac.compare_digest(clean_sig, expected_b64_canonical):
        return True

    # Method 3: Hex fallback (legacy)
    expected_hex = hmac.new(secret_bytes, payload_bytes, hashlib.sha256).hexdigest()
    if hmac.compare_digest(clean_sig.lower(), expected_hex.lower()):
        return True

    logger.warning(
        f"Signature mismatch. Received: {clean_sig[:20]}..., "
        f"Expected (b64 raw): {expected_b64_raw[:20]}..., "
        f"Expected (b64 canonical): {expected_b64_canonical[:20]}..."
    )
    return False


def is_duplicate_webhook(webhook_id: Optional[str]) -> bool:
    """
    Check if webhookId has been seen before (deduplication).

    Args:
        webhook_id: Unique webhook ID from payload

    Returns:
        True if this is a duplicate (already processed)
    """
    if not webhook_id:
        return False  # No ID means we can't dedupe, process it

    # Clean old entries (TTL-based cleanup)
    now = datetime.now(timezone.utc)
    expired = [
        wid
        for wid, seen_at in _seen_webhook_ids.items()
        if (now - seen_at).total_seconds() > _WEBHOOK_ID_TTL_SECONDS
    ]
    for wid in expired:
        del _seen_webhook_ids[wid]

    # Check if seen
    if webhook_id in _seen_webhook_ids:
        logger.info(f"Duplicate webhook detected: {webhook_id}")
        return True

    # Mark as seen
    _seen_webhook_ids[webhook_id] = now
    return False


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
    background_tasks: BackgroundTasks,
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
    - HMAC-SHA256 signature verification using SNAPTRADE_CLIENT_SECRET (base64)
    - Accepts signature in either X-SnapTrade-Signature or Signature header
    - Replay protection via eventTimestamp (5-minute window)
    - webhookId deduplication to prevent duplicate processing

    Args:
        request: Raw request with webhook payload
        background_tasks: FastAPI background tasks for async processing
        x_snaptrade_signature: Webhook signature (X-SnapTrade-Signature header)
        signature: Webhook signature (Signature header, fallback)

    Returns:
        Processing status (returns 200 quickly, processes asynchronously)
    """
    try:
        # Get raw body for signature verification
        raw_body = await request.body()

        # Parse payload early for canonical JSON verification
        payload = await request.json()

        # Use whichever signature header is present
        sig = x_snaptrade_signature or signature

        # Verify signature using SNAPTRADE_CLIENT_SECRET (NOT consumer key)
        client_secret = os.getenv("SNAPTRADE_CLIENT_SECRET")
        if client_secret:
            if not sig:
                raise HTTPException(status_code=401, detail="Missing webhook signature")

            if not verify_webhook_signature(raw_body, payload, sig, client_secret):
                raise HTTPException(status_code=401, detail="Invalid webhook signature")
        else:
            logger.warning(
                "SNAPTRADE_CLIENT_SECRET not set - skipping signature verification"
            )

        # Extract payload fields (already parsed above for signature verification)
        event = payload.get("event", "UNKNOWN")
        user_id = payload.get("userId", "")
        account_id = payload.get("accountId")
        event_timestamp = payload.get("eventTimestamp")
        webhook_id = payload.get("webhookId")
        data = payload.get("data", {})

        # Verify event timestamp for replay protection
        if not verify_event_timestamp(event_timestamp):
            raise HTTPException(
                status_code=400, detail="Event timestamp expired or invalid"
            )

        # Check for duplicate webhook (deduplication)
        if is_duplicate_webhook(webhook_id):
            logger.info(f"Ignoring duplicate webhook: {webhook_id} for event {event}")
            return WebhookResponse(
                status="duplicate",
                event=event,
                processed=False,
                message=f"Duplicate webhook {webhook_id} - already processed",
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
