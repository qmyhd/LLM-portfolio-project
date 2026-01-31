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
from typing import Optional

from fastapi import HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

logger = logging.getLogger(__name__)

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
    credentials: Optional[HTTPAuthorizationCredentials] = Security(security),
) -> Optional[str]:
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
    credentials: Optional[HTTPAuthorizationCredentials] = Security(security),
) -> Optional[str]:
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
