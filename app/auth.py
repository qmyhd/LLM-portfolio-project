"""
API Key Authentication for FastAPI.

Provides a dependency that validates Bearer tokens against API_SECRET_KEY.
Applied to all routes except /health and /webhook/*.

Usage in routes:
    from app.auth import require_api_key

    @router.get("/protected", dependencies=[Depends(require_api_key)])
    async def protected_endpoint():
        return {"message": "Authenticated!"}
"""

import logging
import os
import threading
import time
from collections import deque
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

logger = logging.getLogger(__name__)
router = APIRouter()

# HTTP Bearer scheme - expects "Authorization: Bearer <token>"
security = HTTPBearer(auto_error=False)


def is_auth_disabled() -> bool:
    """
    Check if authentication is disabled for local development.

    Auth is disabled when:
    - DISABLE_AUTH=true (explicit), OR
    - ENVIRONMENT=development AND API_SECRET_KEY is not set

    Returns:
        True if auth should be skipped
    """
    # Explicit disable flag
    if os.getenv("DISABLE_AUTH", "").lower() in ("true", "1", "yes"):
        return True

    # Auto-disable in development if no key is configured
    env = os.getenv("ENVIRONMENT", "development")
    has_key = bool(os.getenv("API_SECRET_KEY"))

    return env == "development" and not has_key


def get_api_secret_key() -> str:
    """
    Get the API secret key from environment.

    Returns:
        The API secret key

    Raises:
        RuntimeError: If API_SECRET_KEY is not configured
    """
    key = os.getenv("API_SECRET_KEY")
    if not key:
        # In development, allow a default key for testing
        if os.getenv("ENVIRONMENT", "development") == "development":
            logger.warning("API_SECRET_KEY not set, using development default")
            return "dev-key-not-for-production"
        raise RuntimeError(
            "API_SECRET_KEY environment variable is required in production"
        )
    return key


async def require_api_key(
    credentials: HTTPAuthorizationCredentials | None = Security(security),
) -> str | None:
    """
    FastAPI dependency that validates API key authentication.

    Expects: Authorization: Bearer <API_SECRET_KEY>

    In development mode (DISABLE_AUTH=true or no API_SECRET_KEY set),
    authentication is skipped entirely.

    Args:
        credentials: The HTTP authorization credentials from the request

    Returns:
        The validated API key (for logging/auditing if needed), or None if auth disabled

    Raises:
        HTTPException: 401 if credentials are missing or invalid (production only)
    """
    # Skip auth in development mode
    if is_auth_disabled():
        logger.debug("Auth disabled - skipping authentication")
        return None

    if credentials is None:
        logger.warning("Request missing Authorization header")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if credentials.scheme.lower() != "bearer":
        logger.warning(f"Invalid auth scheme: {credentials.scheme}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication scheme. Use: Bearer <token>",
            headers={"WWW-Authenticate": "Bearer"},
        )

    expected_key = get_api_secret_key()

    # Use constant-time comparison to prevent timing attacks
    import hmac

    if not hmac.compare_digest(credentials.credentials, expected_key):
        logger.warning("Invalid API key attempted")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return credentials.credentials


# Optional: Dependency that only logs but doesn't block (for monitoring)
async def log_request(
    credentials: HTTPAuthorizationCredentials | None = Security(security),
) -> str | None:
    """
    Logs authentication status without blocking.
    Useful for transitioning to auth or debugging.
    """
    if credentials:
        logger.debug(f"Request with auth scheme: {credentials.scheme}")
        return credentials.credentials
    else:
        logger.debug("Request without auth")
        return None


class GoogleAuthRequest(BaseModel):
    """Frontend-provided Google sign-in payload."""

    idToken: str | None = None
    providerUserId: str | None = None
    email: str | None = None
    fullName: str | None = None
    avatarUrl: str | None = None


class AppUserOut(BaseModel):
    id: str
    provider: str
    providerUserId: str
    email: str
    fullName: str | None = None
    avatarUrl: str | None = None
    role: str
    createdAt: str
    updatedAt: str
    lastSeenAt: str


# ---------------------------------------------------------------------------
# Rate limiting — small in-process sliding window for the auth endpoint.
# The API runs as a single uvicorn process on EC2, so per-process state is the
# effective global state. Defense-in-depth on top of the API-key requirement.
# ---------------------------------------------------------------------------

AUTH_RATE_LIMIT = int(os.getenv("AUTH_RATE_LIMIT_PER_MINUTE", "20"))
_RATE_WINDOW_SECONDS = 60.0
_rate_buckets: dict[str, deque[float]] = {}
_rate_lock = threading.Lock()


def _check_auth_rate_limit(client_ip: str) -> None:
    """Raise 429 when `client_ip` exceeds AUTH_RATE_LIMIT requests/minute."""
    now = time.monotonic()
    with _rate_lock:
        # Opportunistic cleanup so the map can't grow unbounded under
        # spoofed-IP floods.
        if len(_rate_buckets) > 10_000:
            stale = [
                ip
                for ip, bucket in _rate_buckets.items()
                if not bucket or now - bucket[-1] > _RATE_WINDOW_SECONDS
            ]
            for ip in stale:
                del _rate_buckets[ip]

        bucket = _rate_buckets.setdefault(client_ip, deque())
        while bucket and now - bucket[0] > _RATE_WINDOW_SECONDS:
            bucket.popleft()
        if len(bucket) >= AUTH_RATE_LIMIT:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many authentication attempts; try again shortly",
            )
        bucket.append(now)


def _owner_emails() -> set[str]:
    """Emails granted the 'owner' role on sign-in (OWNER_EMAILS env)."""
    raw = os.getenv("OWNER_EMAILS", "")
    return {e.strip().lower() for e in raw.split(",") if e.strip()}


def _verify_google_id_token(id_token: str) -> dict:
    """Verify a Google ID token when GOOGLE_CLIENT_ID is configured."""
    client_id = os.getenv("GOOGLE_CLIENT_ID", "")
    if not client_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="GOOGLE_CLIENT_ID is required to verify Google ID tokens",
        )

    try:
        from google.auth.transport import requests as google_requests
        from google.oauth2 import id_token as google_id_token
    except ImportError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="google-auth is not installed on the API server",
        ) from exc

    try:
        return google_id_token.verify_oauth2_token(
            id_token,
            google_requests.Request(),
            client_id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Google ID token",
        ) from exc


def _row_to_app_user(row) -> AppUserOut:
    rd = dict(row._mapping) if hasattr(row, "_mapping") else dict(row)
    return AppUserOut(
        id=str(rd["id"]),
        provider=rd["provider"],
        providerUserId=rd["provider_user_id"],
        email=rd["email"],
        fullName=rd.get("full_name"),
        avatarUrl=rd.get("avatar_url"),
        role=rd["role"],
        createdAt=str(rd["created_at"]),
        updatedAt=str(rd["updated_at"]),
        lastSeenAt=str(rd["last_seen_at"]),
    )


@router.post("/google", response_model=AppUserOut)
async def google_auth(request: Request, body: GoogleAuthRequest):
    """
    Track a Google-authenticated app user.

    Preferred production flow: frontend sends `idToken`; API verifies it against
    GOOGLE_CLIENT_ID and upserts the user. Local/test flow can send the profile
    fields directly when auth is disabled.

    Users whose email is listed in OWNER_EMAILS are promoted to the 'owner'
    role on sign-in; everyone else keeps their existing role (default 'viewer').
    """
    client_ip = request.client.host if request.client else "unknown"
    _check_auth_rate_limit(client_ip)

    if body.idToken:
        payload = _verify_google_id_token(body.idToken)
        provider_user_id = str(payload.get("sub") or "")
        email = str(payload.get("email") or "")
        full_name = payload.get("name")
        avatar_url = payload.get("picture")
    elif is_auth_disabled():
        provider_user_id = body.providerUserId or ""
        email = str(body.email or "")
        full_name = body.fullName
        avatar_url = body.avatarUrl
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="idToken is required",
        )

    if not provider_user_id or not email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Google user id and email are required",
        )

    from src.db import execute_sql

    # Promote to owner when the email is allowlisted; never demote an
    # existing role automatically (manual DB edit is the only demotion path).
    role_override = "owner" if email.lower() in _owner_emails() else None

    rows = execute_sql(
        """
        INSERT INTO app_users
            (provider, provider_user_id, email, full_name, avatar_url, role, last_seen_at)
        VALUES
            ('google', :provider_user_id, LOWER(:email), :full_name, :avatar_url,
             COALESCE(:role_override, 'viewer'), NOW())
        ON CONFLICT (provider, provider_user_id) DO UPDATE SET
            email = EXCLUDED.email,
            full_name = EXCLUDED.full_name,
            avatar_url = EXCLUDED.avatar_url,
            role = COALESCE(:role_override, app_users.role),
            last_seen_at = NOW(),
            updated_at = NOW()
        RETURNING id, provider, provider_user_id, email, full_name, avatar_url,
                  role, created_at, updated_at, last_seen_at
        """,
        params={
            "provider_user_id": provider_user_id,
            "email": email,
            "full_name": full_name,
            "avatar_url": avatar_url,
            "role_override": role_override,
        },
        fetch_results=True,
    )
    if not rows:
        raise HTTPException(status_code=500, detail="Failed to track signed-in user")
    return _row_to_app_user(rows[0])


class AuthConfigStatus(BaseModel):
    googleClientIdConfigured: bool
    googleAuthLibInstalled: bool
    ownerEmailsCount: int
    authDisabled: bool
    appUsersCount: int | None = None


@router.get("/config", response_model=AuthConfigStatus)
async def auth_config_status():
    """
    Secrets-free health check for the Google sign-in flow, so config can be
    verified without SSH. Returns booleans/counts only — never any secret
    value. Requires the API key (the router carries require_api_key).
    """
    google_client_id_set = bool(os.getenv("GOOGLE_CLIENT_ID", "").strip())

    try:
        import google.oauth2.id_token  # noqa: F401

        lib_installed = True
    except ImportError:
        lib_installed = False

    app_users_count: int | None = None
    try:
        from src.db import execute_sql

        rows = execute_sql("SELECT COUNT(*) FROM app_users", fetch_results=True)
        if rows:
            app_users_count = int(rows[0][0])
    except Exception:  # table missing / DB issue — leave as None
        app_users_count = None

    return AuthConfigStatus(
        googleClientIdConfigured=google_client_id_set,
        googleAuthLibInstalled=lib_installed,
        ownerEmailsCount=len(_owner_emails()),
        authDisabled=is_auth_disabled(),
        appUsersCount=app_users_count,
    )
