"""
Webhook API routes for SnapTrade integration.

Endpoints:
- POST /webhook/snaptrade - Handle SnapTrade webhook events

Security:
- HMAC SHA-256 signature verification via ``Signature`` header
  (key = SNAPTRADE_CLIENT_SECRET, input = raw request body)
- Replay protection via eventTimestamp (5-minute window)
- webhookId deduplication to prevent duplicate processing

SnapTrade event types handled:
- ACCOUNT_HOLDINGS_UPDATED — Holdings changed, refresh orders
- ACCOUNT_TRANSACTIONS_INITIAL_UPDATE — First transaction sync complete
- ACCOUNT_TRANSACTIONS_UPDATED — Incremental transaction update
- ACCOUNT_UPDATED — Account sync triggered
- ORDER_PLACED / ORDER_FILLED / ORDER_CANCELLED — Order lifecycle
- CONNECTION_CONNECTED — Brokerage connection established
- CONNECTION_DISCONNECTED — Brokerage connection lost
- CONNECTION_ERROR — Brokerage connection error
- CONNECTION_DELETED — Brokerage connection removed
"""

import base64
import hashlib
import hmac
import json
import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from pydantic import BaseModel

from src.config import settings
from src.db import execute_sql
from src.snaptrade_collector import SnapTradeCollector

logger = logging.getLogger(__name__)
router = APIRouter()

# Maximum age of webhook events (prevent replay attacks)
MAX_EVENT_AGE_SECONDS = 300  # 5 minutes

# In-memory cache for webhookId deduplication (with TTL-based cleanup)
_seen_webhook_ids: dict[str, datetime] = {}
_WEBHOOK_ID_TTL_SECONDS = 3600  # Keep IDs for 1 hour


class WebhookResponse(BaseModel):
    """Webhook response."""

    status: str
    event: str
    processed: bool
    message: str | None = None


def verify_webhook_signature(raw_body: bytes, signature_header: str | None) -> bool:
    """
    Verify SnapTrade webhook via HMAC SHA-256 Signature header.

    SnapTrade signs every webhook payload with the client secret.
    We recompute the HMAC and compare using constant-time comparison.

    Args:
        raw_body: The raw request body bytes (HMAC input).
        signature_header: The ``Signature`` header value from the request.

    Returns:
        True if the signature is valid.
    """
    if not signature_header:
        logger.warning("Webhook missing Signature header")
        return False

    secret = settings().SNAPTRADE_CLIENT_SECRET
    if not secret:
        logger.error("SNAPTRADE_CLIENT_SECRET not configured — cannot verify webhook")
        return False

    expected = base64.b64encode(
        hmac.new(secret.encode(), raw_body, hashlib.sha256).digest()
    ).decode()

    if hmac.compare_digest(signature_header.strip(), expected):
        return True

    logger.warning(
        "Webhook signature mismatch: got=%s... expected=%s...",
        signature_header[:12],
        expected[:12],
    )
    return False


def is_duplicate_webhook(webhook_id: str | None) -> bool:
    """
    Check if webhookId has been seen before (deduplication).

    Returns:
        True if this is a duplicate (already processed).
    """
    if not webhook_id:
        return False  # No ID means we can't dedupe, process it

    # Clean old entries (TTL-based cleanup)
    now = datetime.now(UTC)
    expired = [
        wid
        for wid, seen_at in _seen_webhook_ids.items()
        if (now - seen_at).total_seconds() > _WEBHOOK_ID_TTL_SECONDS
    ]
    for wid in expired:
        del _seen_webhook_ids[wid]

    if webhook_id in _seen_webhook_ids:
        logger.info("Duplicate webhook detected: %s", webhook_id)
        return True

    _seen_webhook_ids[webhook_id] = now
    return False


def verify_event_timestamp(event_timestamp: str | None) -> bool:
    """
    Verify webhook event is not a replay attack.

    Returns:
        True if event is within acceptable time window.
    """
    if not event_timestamp:
        logger.warning("Webhook without eventTimestamp — skipping replay check")
        return True

    try:
        event_time = datetime.fromisoformat(event_timestamp.replace("Z", "+00:00"))
        now = datetime.now(UTC)
        age = (now - event_time).total_seconds()

        if age > MAX_EVENT_AGE_SECONDS:
            logger.warning("Webhook event too old: %.0fs > %ds", age, MAX_EVENT_AGE_SECONDS)
            return False

        if age < -60:  # Allow 1 minute clock skew into the future
            logger.warning("Webhook event from future: %.0fs", age)
            return False

        return True
    except Exception as e:
        logger.error("Failed to parse event timestamp: %s", e)
        return False


@router.post("/snaptrade", response_model=WebhookResponse)
async def handle_snaptrade_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
):
    """
    Handle incoming SnapTrade webhook events.

    SnapTrade payload format (from docs):
    {
      "webhookId": "...",
      "clientId": "...",
      "eventTimestamp": "2022-05-31T12:39:47...",
      "userId": "...",
      "eventType": "ACCOUNT_HOLDINGS_UPDATED",
      "accountId": "...",
      "brokerageAuthorizationId": "..."
    }

    Security:
    - HMAC SHA-256 Signature header verification (SNAPTRADE_CLIENT_SECRET)
    - Replay protection via eventTimestamp (5-minute window)
    - webhookId deduplication
    """
    try:
        # Read raw body BEFORE parsing JSON (needed for HMAC)
        raw_body = await request.body()

        # --- Verify HMAC signature (required) ---
        signature = request.headers.get("Signature")
        if not verify_webhook_signature(raw_body, signature):
            raise HTTPException(status_code=401, detail="Invalid webhook signature")

        payload: dict[str, Any] = json.loads(raw_body)

        # --- Extract fields (SnapTrade uses eventType, not event) ---
        event_type = payload.get("eventType") or payload.get("event", "UNKNOWN")
        user_id = payload.get("userId", "")
        account_id = payload.get("accountId")
        event_timestamp = payload.get("eventTimestamp")
        webhook_id = payload.get("webhookId")

        # --- Replay protection ---
        if not verify_event_timestamp(event_timestamp):
            raise HTTPException(
                status_code=400, detail="Event timestamp expired or invalid"
            )

        # --- Deduplication ---
        if is_duplicate_webhook(webhook_id):
            logger.info("Ignoring duplicate webhook: %s for %s", webhook_id, event_type)
            return WebhookResponse(
                status="duplicate",
                event=event_type,
                processed=False,
                message=f"Duplicate webhook {webhook_id} — already processed",
            )

        logger.info("SnapTrade webhook: %s for user=%s account=%s", event_type, user_id, account_id)

        # --- Handle event types ---
        message = _handle_event(event_type, account_id, payload)

        # Log webhook receipt
        execute_sql(
            """
            INSERT INTO processing_status (table_name, status, last_run)
            VALUES (:table_name, :status, :last_run)
            ON CONFLICT (table_name)
            DO UPDATE SET status = :status, last_run = :last_run
            """,
            params={
                "table_name": f"webhook_{event_type.lower()}",
                "status": "processed",
                "last_run": datetime.now(UTC).isoformat(),
            },
        )

        return WebhookResponse(
            status="success",
            event=event_type,
            processed=True,
            message=message,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error processing webhook: %s", e)
        return WebhookResponse(
            status="error",
            event=payload.get("eventType", "UNKNOWN") if "payload" in dir() else "UNKNOWN",
            processed=False,
            message=str(e),
        )


def _handle_event(event_type: str, account_id: str | None, payload: dict) -> str:
    """Dispatch webhook event to the appropriate handler. Returns a message."""

    if event_type == "ACCOUNT_HOLDINGS_UPDATED":
        # Holdings changed — refresh orders and reset notifications
        logger.info("Account %s holdings updated — refreshing orders", account_id)
        try:
            collector = SnapTradeCollector()
            collector.write_to_database(
                collector.get_orders(account_id),
                "orders",
                ["brokerage_order_id"],
            )
            logger.info("Orders synced from SnapTrade")
        except Exception as e:
            logger.error("Failed to sync orders: %s", e)

        # Reset notified flag for newly filled orders
        execute_sql(
            """
            UPDATE orders
            SET notified = false
            WHERE account_id = :account_id
              AND status = 'FILLED'
              AND notified = true
              AND time_executed > NOW() - INTERVAL '1 hour'
            """,
            params={"account_id": account_id},
        )
        return "Holdings updated, orders refreshed, notifications reset"

    elif event_type in (
        "ACCOUNT_TRANSACTIONS_INITIAL_UPDATE",
        "ACCOUNT_TRANSACTIONS_UPDATED",
    ):
        # Transactions synced — trigger activity refresh
        logger.info(
            "Account %s transactions updated (%s)", account_id, event_type
        )
        try:
            collector = SnapTradeCollector()
            activities = collector.get_activities(account_id)
            if activities:
                collector.write_to_database(activities, "activities", ["id"])
                logger.info("Activities synced: %d records", len(activities))
        except Exception as e:
            logger.error("Failed to sync activities: %s", e)
        return f"Transactions updated ({event_type})"

    elif event_type == "ACCOUNT_UPDATED":
        logger.info("Account %s updated, triggering sync", account_id)
        return "Account sync will be triggered"

    elif event_type == "ORDER_PLACED":
        order_id = payload.get("data", {}).get("orderId")
        symbol = payload.get("data", {}).get("symbol")
        logger.info("New order placed: %s for %s", order_id, symbol)
        return f"Order {order_id} logged"

    elif event_type == "ORDER_FILLED":
        data = payload.get("data", {})
        order_id = data.get("orderId")
        symbol = data.get("symbol")
        side = data.get("side")
        quantity = data.get("filledQuantity")
        price = data.get("filledPrice")

        logger.info("Order filled: %s %s %s @ $%s", side, quantity, symbol, price)

        execute_sql(
            """
            UPDATE orders
            SET
                status = 'FILLED',
                execution_price = :price,
                filled_quantity = :quantity,
                time_executed = :time_executed,
                notified = false
            WHERE brokerage_order_id = :order_id
            """,
            params={
                "order_id": order_id,
                "price": price,
                "quantity": quantity,
                "time_executed": datetime.now(UTC).isoformat(),
            },
        )
        return f"Order {order_id} marked as filled, pending notification"

    elif event_type == "ORDER_CANCELLED":
        order_id = payload.get("data", {}).get("orderId")
        logger.info("Order cancelled: %s", order_id)
        execute_sql(
            "UPDATE orders SET status = 'CANCELED' WHERE brokerage_order_id = :order_id",
            params={"order_id": order_id},
        )
        return f"Order {order_id} marked as cancelled"

    # --- Connection lifecycle events ---

    elif event_type == "CONNECTION_CONNECTED":
        auth_id = payload.get("brokerageAuthorizationId")
        logger.info("Connection established: auth=%s", auth_id)
        if auth_id:
            execute_sql(
                """
                UPDATE accounts
                SET connection_status = 'connected',
                    connection_disabled_at = NULL,
                    connection_error_message = NULL
                WHERE brokerage_authorization = :auth_id
                   OR brokerage_authorization_id = :auth_id
                """,
                params={"auth_id": auth_id},
            )
        return f"Connection {auth_id} marked as connected"

    elif event_type == "CONNECTION_DISCONNECTED":
        auth_id = payload.get("brokerageAuthorizationId")
        logger.warning("Connection disconnected: auth=%s", auth_id)
        if auth_id:
            execute_sql(
                """
                UPDATE accounts
                SET connection_status = 'disconnected',
                    connection_disabled_at = :now
                WHERE brokerage_authorization = :auth_id
                   OR brokerage_authorization_id = :auth_id
                """,
                params={"auth_id": auth_id, "now": datetime.now(UTC).isoformat()},
            )
        return f"Connection {auth_id} marked as disconnected"

    elif event_type == "CONNECTION_ERROR":
        auth_id = payload.get("brokerageAuthorizationId")
        error_msg = payload.get("data", {}).get("errorMessage", "Unknown error")
        logger.error("Connection error: auth=%s error=%s", auth_id, error_msg)
        if auth_id:
            execute_sql(
                """
                UPDATE accounts
                SET connection_status = 'error',
                    connection_error_message = :error_msg,
                    connection_disabled_at = :now
                WHERE brokerage_authorization = :auth_id
                   OR brokerage_authorization_id = :auth_id
                """,
                params={
                    "auth_id": auth_id,
                    "error_msg": error_msg,
                    "now": datetime.now(UTC).isoformat(),
                },
            )
        return f"Connection {auth_id} error recorded"

    elif event_type == "CONNECTION_DELETED":
        auth_id = payload.get("brokerageAuthorizationId")
        logger.warning("Connection deleted: auth=%s", auth_id)
        if auth_id:
            execute_sql(
                """
                UPDATE accounts
                SET connection_status = 'deleted',
                    connection_disabled_at = :now
                WHERE brokerage_authorization = :auth_id
                   OR brokerage_authorization_id = :auth_id
                """,
                params={"auth_id": auth_id, "now": datetime.now(UTC).isoformat()},
            )
        return f"Connection {auth_id} marked as deleted"

    else:
        logger.warning("Unknown webhook event: %s", event_type)
        return f"Unknown event type: {event_type}"
