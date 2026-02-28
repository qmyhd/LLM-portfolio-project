"""
SnapTrade Connection Management API routes.

Endpoints:
- GET /connections — List brokerage connections with status
- POST /connections/portal — Generate SnapTrade Connect redirect URL
"""

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.config import settings
from src.db import execute_sql
from src.retry_utils import snaptrade_retry

logger = logging.getLogger(__name__)
router = APIRouter()


class ConnectionInfo(BaseModel):
    accountId: str
    name: str | None = None
    institutionName: str | None = None
    connectionStatus: str = "connected"
    disabledAt: str | None = None
    errorMessage: str | None = None
    lastSync: str | None = None


class ConnectionsResponse(BaseModel):
    connections: list[ConnectionInfo]


class PortalUrlResponse(BaseModel):
    redirectUri: str


@router.get("", response_model=ConnectionsResponse)
async def list_connections():
    """List all brokerage connections with their status."""
    rows = execute_sql(
        """
        SELECT id, name, institution_name,
               COALESCE(connection_status, 'connected') as connection_status,
               connection_disabled_at, connection_error_message,
               last_successful_sync
        FROM accounts
        ORDER BY institution_name, name
        """,
        fetch_results=True,
    )
    connections = []
    for row in rows or []:
        rd = dict(row._mapping) if hasattr(row, "_mapping") else dict(row)
        connections.append(ConnectionInfo(
            accountId=rd["id"],
            name=rd.get("name"),
            institutionName=rd.get("institution_name"),
            connectionStatus=rd.get("connection_status", "connected"),
            disabledAt=str(rd["connection_disabled_at"]) if rd.get("connection_disabled_at") else None,
            errorMessage=rd.get("connection_error_message"),
            lastSync=str(rd["last_successful_sync"]) if rd.get("last_successful_sync") else None,
        ))
    return ConnectionsResponse(connections=connections)


@router.post("/portal", response_model=PortalUrlResponse)
async def generate_portal_url():
    """Generate a SnapTrade Connect redirect URL for linking a brokerage."""
    try:
        from snaptrade_client import SnapTrade
    except ImportError as e:
        raise HTTPException(status_code=500, detail="SnapTrade SDK not available") from e

    config = settings()
    if not config.SNAPTRADE_CLIENT_ID or not config.SNAPTRADE_CONSUMER_KEY:
        raise HTTPException(status_code=500, detail="SnapTrade credentials not configured")

    try:
        client = SnapTrade(
            client_id=config.SNAPTRADE_CLIENT_ID,
            consumer_key=config.SNAPTRADE_CONSUMER_KEY,
        )

        @snaptrade_retry(max_retries=2, delay=2.0)
        def _call():
            return client.authentication.login_snap_trade_user(
                user_id=config.SNAPTRADE_USER_ID,
                user_secret=config.SNAPTRADE_USER_SECRET,
            )

        response = _call()

        redirect_uri = _extract_redirect_uri(response)
        if not redirect_uri:
            raise HTTPException(status_code=502, detail="No redirect URI in SnapTrade response")

        return PortalUrlResponse(redirectUri=redirect_uri)

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to generate portal URL: %s", e)
        raise HTTPException(status_code=500, detail=str(e)) from e


def _extract_redirect_uri(response: Any) -> str | None:
    """Extract redirect URI from SnapTrade auth response."""
    # Try common response attributes
    for attr in ("parsed", "body", "data", "content"):
        val = getattr(response, attr, None)
        if isinstance(val, dict):
            uri = val.get("redirectURI") or val.get("loginLink")
            if uri:
                return uri
    return None
