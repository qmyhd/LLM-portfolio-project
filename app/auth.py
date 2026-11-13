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
import uuid
from collections import deque
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, Security, status
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from app.passwords import MAX_PASSWORD, normalize_username, verify_password
from src.db import execute_sql

logger = logging.getLogger(__name__)
router = APIRouter()

# HTTP Bearer scheme - expects "Authorization: Bearer <token>"
security = HTTPBearer(auto_error=False)


def get_environment() -> str:
    """
    Return the deployment environment, defaulting to "production".

    The default is deliberately production: a missing ENVIRONMENT variable
    must never relax security. Local work opts out explicitly, either with
    ENVIRONMENT=development or with DISABLE_AUTH=true in .env.
    """
    return (os.getenv("ENVIRONMENT") or "production").strip().lower()


def is_development() -> bool:
    """True only when ENVIRONMENT is explicitly set to development."""
    return get_environment() == "development"


def is_auth_disabled() -> bool:
    """
    Check if authentication is disabled for local development.

    Auth is disabled when:
    - DISABLE_AUTH=true (explicit), OR
    - ENVIRONMENT=development (explicit) AND API_SECRET_KEY is not set

    A production box that loses its key does NOT fall open: the startup
    check (`assert_auth_configured`) refuses to boot instead.

    Returns:
        True if auth should be skipped
    """
    # Explicit disable flag
    if os.getenv("DISABLE_AUTH", "").lower() in ("true", "1", "yes"):
        return True

    # Auto-disable only when development was explicitly requested
    has_key = bool(os.getenv("API_SECRET_KEY"))
    return is_development() and not has_key


def assert_auth_configured() -> None:
    """
    Fail closed at startup: refuse to run without an API key.

    Called from the FastAPI lifespan. Raises RuntimeError (which stops
    uvicorn) when auth is enabled but API_SECRET_KEY is missing, so a
    secrets-loading failure takes the API down instead of opening it up.
    """
    if is_auth_disabled():
        logger.warning(
            "API authentication is DISABLED (DISABLE_AUTH or development "
            "without a key). Never run this way on a public host."
        )
        return
    if not os.getenv("API_SECRET_KEY"):
        raise RuntimeError(
            "API_SECRET_KEY is not set and authentication is enabled "
            f"(ENVIRONMENT={get_environment()}). Refusing to start. Set the key, "
            "or set DISABLE_AUTH=true for local development only."
        )


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
        # Only an explicit development environment gets a default key
        if is_development():
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


class PasswordLoginRequest(BaseModel):
    username: str
    password: str


class MeOut(BaseModel):
    id: str
    role: str
    email: str
    fullName: str | None = None


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


def _check_auth_rate_limit(key: str) -> None:
    """Raise 429 when `key` (a client IP or a username key) exceeds
    AUTH_RATE_LIMIT requests/minute."""
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

        bucket = _rate_buckets.setdefault(key, deque())
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


def _row_dict(row) -> dict:
    return dict(row._mapping) if hasattr(row, "_mapping") else dict(row)


def _invalidate_role_cache(user_id: str) -> None:
    # Imported here: app.identity imports this module at load time. A failure
    # must never turn a committed sign-in into a 500; the cache expires anyway.
    try:
        from app.identity import invalidate_viewer

        invalidate_viewer(user_id)
    except Exception:
        logger.warning("Role cache invalidation failed", exc_info=True)


def _run_alert_in_background(name: str, send_name: str, *args) -> None:
    """Send a Discord alert on a daemon thread so a slow or failing call never
    delays or breaks the request. Nothing here can raise into the caller."""

    def _target() -> None:
        try:
            from src import approval_alert

            getattr(approval_alert, send_name)(*args)
        except Exception as exc:
            logger.warning("%s alert failed: %s", name, type(exc).__name__)

    try:
        threading.Thread(target=_target, name=f"alert-{name}", daemon=True).start()
    except Exception as exc:
        logger.warning("%s alert failed: %s", name, type(exc).__name__)


def _notify_new_pending(full_name: str | None, email: str) -> None:
    """Alert the owner that someone new is waiting for approval (background)."""
    _run_alert_in_background("approval", "send_approval_alert", full_name, email)


def _notify_lockout(username: str) -> None:
    """Alert the owner that a real account was just locked (background)."""
    _run_alert_in_background("lockout", "send_lockout_alert", username)


def _row_to_app_user(row) -> AppUserOut:
    rd = _row_dict(row)
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
    role on sign-in; everyone else keeps their existing role. A brand-new
    user starts as 'pending' until an owner approves them.
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

    # Promote to owner when the email is allowlisted; never demote an
    # existing role automatically (manual DB edit is the only demotion path).
    role_override = "owner" if email.lower() in _owner_emails() else None

    rows = execute_sql(
        """
        INSERT INTO app_users
            (provider, provider_user_id, email, full_name, avatar_url, role, last_seen_at)
        VALUES
            ('google', :provider_user_id, LOWER(:email), :full_name, :avatar_url,
             COALESCE(:role_override, 'pending'), NOW())
        ON CONFLICT (provider, provider_user_id) DO UPDATE SET
            email = EXCLUDED.email,
            full_name = EXCLUDED.full_name,
            avatar_url = EXCLUDED.avatar_url,
            role = COALESCE(:role_override, app_users.role),
            last_seen_at = NOW(),
            updated_at = NOW()
        RETURNING id, provider, provider_user_id, email, full_name, avatar_url,
                  role, created_at, updated_at, last_seen_at,
                  (xmax = 0) AS inserted
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
    user = _row_to_app_user(rows[0])
    inserted = bool(_row_dict(rows[0]).get("inserted"))

    if inserted or role_override:
        _invalidate_role_cache(user.id)
    if inserted and user.role == "pending":
        try:
            _notify_new_pending(user.fullName, user.email)
        except Exception:  # an alert must never block sign-in
            logger.warning("New-pending alert failed", exc_info=True)
    return user


# ---------------------------------------------------------------------------
# Username + password sign-in with lockout (5 failures lock for 15 minutes).
# State lives in app_users.failed_login_count / locked_until and every change
# is a single SQL statement, so concurrent failures can't both read the same
# count.
# ---------------------------------------------------------------------------

_LOGIN_LOOKUP_SQL = """
    SELECT id, password_hash,
           (locked_until IS NOT NULL AND locked_until > NOW()) AS is_locked
    FROM app_users
    WHERE provider = 'password' AND provider_user_id = :username
"""

# A lock that has expired restarts the count at 1. A live lock is never
# touched (the WHERE guard), so it is not extended and the count stays put.
_FAIL_SQL = """
    UPDATE app_users SET
        failed_login_count = CASE
            WHEN locked_until IS NOT NULL AND locked_until <= NOW() THEN 1
            ELSE failed_login_count + 1 END,
        locked_until = CASE
            WHEN (CASE WHEN locked_until IS NOT NULL AND locked_until <= NOW() THEN 1
                       ELSE failed_login_count + 1 END) >= 5
                THEN NOW() + INTERVAL '15 minutes'
            WHEN locked_until IS NOT NULL AND locked_until <= NOW() THEN NULL
            ELSE locked_until END
    WHERE id = CAST(:id AS uuid) AND (locked_until IS NULL OR locked_until <= NOW())
    RETURNING (locked_until IS NOT NULL AND locked_until > NOW()) AS is_locked
"""

_SUCCESS_SQL = """
    UPDATE app_users SET
        failed_login_count = 0,
        locked_until = NULL,
        last_seen_at = NOW(),
        updated_at = NOW()
    WHERE id = CAST(:id AS uuid) AND (locked_until IS NULL OR locked_until <= NOW())
    RETURNING id, provider, provider_user_id, email, full_name, avatar_url,
              role, created_at, updated_at, last_seen_at
"""

_WRONG_LOGIN = "Wrong username or password"
_LOCKED_LOGIN = "Too many attempts. Try again in 15 minutes"

# ---------------------------------------------------------------------------
# Shadow lock: names with no account are never written to the database, but
# they lock like a real account (5 failures -> 423 for 15 minutes) so the
# lockout can't be used to find out which usernames exist. In-process state,
# bounded like the rate-limit buckets.
# ---------------------------------------------------------------------------

_LOCK_FAILURES = 5
_LOCK_SECONDS = 15 * 60.0
_SHADOW_MAX_NAMES = 10_000
_shadow_locks: dict[str, dict] = {}  # key -> {"fails": [monotonic ts], "until": float}
_shadow_lock = threading.Lock()


def _shadow_key(raw_username: str) -> str:
    """Normalised username when valid, else trimmed lower-cased input cut to 64."""
    try:
        return normalize_username(raw_username)
    except ValueError:
        return (raw_username or "").strip().lower()[:64]


def _shadow_is_locked(key: str) -> bool:
    now = time.monotonic()
    with _shadow_lock:
        entry = _shadow_locks.get(key)
        return bool(entry and entry["until"] > now)


def _shadow_record_failure(key: str) -> bool:
    """Record a failure for an unknown name; True when the name is now locked."""
    now = time.monotonic()
    with _shadow_lock:
        if len(_shadow_locks) >= _SHADOW_MAX_NAMES:
            for name in [
                n
                for n, e in _shadow_locks.items()
                if e["until"] <= now and all(now - t > _LOCK_SECONDS for t in e["fails"])
            ]:
                del _shadow_locks[name]
            while len(_shadow_locks) >= _SHADOW_MAX_NAMES:  # still full: drop the oldest
                del _shadow_locks[next(iter(_shadow_locks))]

        entry = _shadow_locks.setdefault(key, {"fails": [], "until": 0.0})
        if entry["until"] > now:
            return True  # already locked: no change, no extension
        entry["fails"] = [t for t in entry["fails"] if now - t <= _LOCK_SECONDS]
        entry["fails"].append(now)
        if len(entry["fails"]) >= _LOCK_FAILURES:
            entry["until"] = now + _LOCK_SECONDS
            entry["fails"] = []
            return True
        return False


def _unknown_login(raw_username: str, password: str) -> HTTPException:
    """The response for a name with no usable account: one dummy verification,
    then 401, or 423 once the name's shadow lock is on."""
    verify_password(password, None)
    key = _shadow_key(raw_username)
    if _shadow_is_locked(key) or _shadow_record_failure(key):
        return HTTPException(status_code=status.HTTP_423_LOCKED, detail=_LOCKED_LOGIN)
    return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=_WRONG_LOGIN)


@router.post("/password", response_model=AppUserOut)
async def password_login(request: Request, body: PasswordLoginRequest):
    """
    Sign in with a username and password. Pending users sign in too (the
    frontend shows them the waiting page). Unknown, locked and wrong-password
    cases each do exactly one argon2 verification so timing doesn't reveal
    which one it was.
    """
    client_ip = request.client.host if request.client else "unknown"
    # Limit per username so one person hammering a name can't use up everyone
    # else's logins; fall back to the client IP when no username can be derived.
    try:
        username = normalize_username(body.username)
    except ValueError:
        username = None
    _check_auth_rate_limit(f"pw:{username}" if username else client_ip)

    if username is None:
        raise _unknown_login(body.username, body.password)

    rows = execute_sql(_LOGIN_LOOKUP_SQL, params={"username": username}, fetch_results=True)
    account = _row_dict(rows[0]) if rows else None
    stored_hash = account["password_hash"] if account else None

    if account is None or stored_hash is None:
        raise _unknown_login(username, body.password)

    # An over-long password can't be the real one: never verify a truncation.
    if len(body.password) > MAX_PASSWORD:
        verify_password(body.password[:MAX_PASSWORD], None)
        password_ok = False
    else:
        password_ok = verify_password(body.password, stored_hash)

    locked = HTTPException(status_code=status.HTTP_423_LOCKED, detail=_LOCKED_LOGIN)
    if account["is_locked"]:
        raise locked

    user_id = str(account["id"])
    if not password_ok:
        failed = execute_sql(_FAIL_SQL, params={"id": user_id}, fetch_results=True)
        # No row means a concurrent failure locked it since the lookup. The
        # attempt that trips the lock gets 423 too: the account is locked now.
        if not failed:
            raise locked
        if _row_dict(failed[0])["is_locked"]:
            _notify_lockout(username)  # this request tripped the lock
            raise locked
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=_WRONG_LOGIN)

    updated = execute_sql(_SUCCESS_SQL, params={"id": user_id}, fetch_results=True)
    if not updated:  # locked by a concurrent failure since the lookup
        raise locked
    return _row_to_app_user(updated[0])


async def auth_validation_error_handler(request: Request, exc: RequestValidationError):
    """422 for /auth/* without echoing any request input (it may hold a
    password). Every other path keeps FastAPI's default handler."""
    path = request.url.path
    if path == "/auth" or path.startswith("/auth/"):
        return JSONResponse(status_code=422, content={"detail": "Invalid request"})
    return await request_validation_exception_handler(request, exc)


@router.get("/me", response_model=MeOut)
async def auth_me(request: Request):
    """
    The role of the user named in X-App-User, read fresh (never cached) so the
    waiting page notices approval. Reveals nothing beyond that one user: a
    missing, malformed or unknown id is a plain 404.
    """
    not_found = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown user")
    raw = request.headers.get("X-App-User")
    if not raw:
        raise not_found
    try:
        user_id = str(uuid.UUID(raw.strip()))
    except ValueError:
        raise not_found from None

    rows = execute_sql(
        "SELECT id, role, email, full_name FROM app_users WHERE id = CAST(:id AS uuid)",
        params={"id": user_id},
        fetch_results=True,
    )
    if not rows:
        raise not_found
    rd = _row_dict(rows[0])
    return MeOut(
        id=str(rd["id"]), role=rd["role"], email=rd["email"], fullName=rd.get("full_name")
    )


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
